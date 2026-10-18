import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { methodPresets, frozenConfig, methodVersion } from '../shared/methods.mjs';
import { atomicJson, readValidated, StorageError } from './persistence.mjs';
import { UserInputError } from './user-error.mjs';
import { taskFor, taskMessages, agentLimits, reserveCall, stageTokens } from './agent-policy.mjs';
import { initializeMethods } from './optimization-v07.mjs';
import { executeOptimization, explanationMessages } from './optimization.mjs';
import { trajectoryState, summarizeRuns } from './research-metrics.mjs';
import { respondToQuestions, questionsFromText, environmentVersion } from './experiment-environment.mjs';
import { scoreOriginalTask, scorerVersion, publicOutcome } from './independent-scoring.mjs';
import { executionSnapshot } from './execution-snapshot.mjs';
import { decisionMetrics } from './decision-metrics.mjs';
export const digest = x => crypto.createHash('sha256').update(typeof x==='string'?x:JSON.stringify(x)).digest('hex');
const uuid=()=>crypto.randomUUID(), now=()=>new Date().toISOString();
const safeId=id=>typeof id==='string'&&/^[a-f0-9-]{36}$/.test(id);
const atomic = atomicJson;
const validBatch = b => b && typeof b === 'object' && safeId(b.id) && Array.isArray(b.runs) && Array.isArray(b.cases) && b.cases.every(c=>c && typeof c.id==='string' && typeof c.prompt==='string') && b.runs.every(r=>r && safeId(r.id) && typeof r.status==='string' && b.cases.some(c=>c.id===r.caseId)) && b.frozen && typeof b.frozen==='object';
export function parseCases(input, privateCards=[]) {
  if(typeof input==='string'){if(Buffer.byteLength(input)>1024*1024)throw Error('输入数据集过大');try{input=JSON.parse(input);}catch{input=input.trim().split(/\r?\n/).filter(Boolean).map(line=>JSON.parse(line));}}
    const rows=Array.isArray(input)?input:input?.cases;
  if(!Array.isArray(rows)||!rows.length||rows.length>1000||!Array.isArray(privateCards)||privateCards.length>1000)throw Error('输入需要 1–1000 条题目');
  const ids=new Set();
  return rows.map((row,i)=>{
    const id=String(row.id??row.question_id??i+1),prompt=row.prompt??row.publicPrompt??row.question;
    if(id.length>150||ids.has(id)||typeof prompt!=='string'||!prompt.trim()||prompt.length>24000)throw Error('输入题号或题目无效');ids.add(id);
    const card=privateCards.find(x=>String(x.id??x.question_id)===id)||row.privateCard||null;
    if(card&&JSON.stringify(card).length>24000)throw Error('输入事实卡过大');
    const privateReference=row.reference??row.privateReference??card?.reference??null;
    if(privateReference&&JSON.stringify(privateReference).length>250000)throw Error('参考资产过大');
    return {id,prompt,baseId:String(row.baseId??card?.source_id??id.replace(/-B\d+$/,'')),hash:digest(prompt),privateCard:card?structuredClone(card):null,privateReference};
  });
}
export function scoreRun(run, card, referenceAsset=null) {
  const last=run.conversation?.messages.findLast(m=>m.automation)?.automation;
  const result=last?.resultContract, outcome=publicOutcome(run), status=outcome.status;
  const asset=referenceAsset??card?.reference, reference=asset?.status??card?.expected_final_status??null;
  return {version:'0.7.5-score-2',independent:scoreOriginalTask(run,asset),referenceStatus:reference,originalTaskStatus:status,solverStatus:result?.solverStatus??last?.result?.status??null,observedStatus:status,statusAgreement:reference&&status?reference===status:null,
    originalTaskCorrect:null,semanticCorrect:null,displayFeasible:result?.displayValidation?.feasible??null,
    solverFeasible:result?.numericCheck?.feasible??last?.result?.check?.feasible??null,
    calls:last?.task.calls??run.events?.filter(e=>['reserved','sent','completed','failed','cancelled_unknown'].includes(e.state)).length??0,solves:last?.task.solves??0,clarifications:last?.task.clarifications??0,
    protocolCorrections:last?.task.protocolCorrections??0,...decisionMetrics(last?.task),
    executionStatus:run.status,semanticReviewStatus:last?.review?.status??'not_run',
    taskOutcome:['failed','cancelled','interrupted_unknown'].includes(run.status)?'failed':run.status!=='complete'?run.status:outcome.complete?'complete':'unknown',cost:null,requiresHumanReview:true};
}
// Controller has exclusive access to private cards. Return only an authorized answer.
export function controllerReply(flow,card) {
  if(flow.stage!=='clarification'||!card)return null;
  return respondToQuestions(flow.questions,card).reply;
}
export class ExperimentService {
  constructor(directory,{store,solver,planner,generator,runner=null}={}) {
    this.directory=path.join(directory,'experiments');fs.mkdirSync(this.directory,{recursive:true});
    this.store=store;this.solver=solver;this.planner=planner;this.generator=generator;this.runner=runner;this.batches=new Map();this.working=false;this.controller=null;
    this.storageError=null; this.skipped=[];
    for(const name of fs.readdirSync(this.directory).filter(x=>/^[a-f0-9-]{36}\.json$/.test(x))){
      let b;
      try { b=readValidated(path.join(this.directory,name),validBatch); } catch(error) { this.storageError=error; this.skipped.push(name); continue; }
      if(!b || b.id+'.json'!==name){this.skipped.push(name);continue;}
      this.batches.set(b.id,b);
      try {
        let changed=false;if(b.status==='running'){b.status='paused';changed=true;}
        for(const r of b.runs)if(r.status==='running'){
          r.status='interrupted_unknown';changed=true;const run=this.run(r.id);
          if(run){run.status='interrupted_unknown';for(const e of run.events||[])if(['reserved','sent'].includes(e.state))e.state='interrupted_unknown';for(const m of run.conversation?.messages||[])if(m.status==='streaming')m.status='interrupted';this.saveRun(run);}
        }
        if(changed)this.save(b);
      }catch(error){this.failStorage(error);}
    }

  }
  assertWritable(){if(this.storageError)throw this.storageError;}
  failStorage(error){this.storageError=error instanceof StorageError?error:new StorageError(error);this.controller?.abort();for(const b of this.batches.values())if(b.status==='running'){b.status='paused';b.storageError=this.storageError.message;for(const r of b.runs)if(r.status==='running')r.status='interrupted_unknown';}this.onStorageError?.(this.storageError);}
  save(b){this.assertWritable();b.updatedAt=now();b.sequence=(b.sequence||0)+1;try{atomic(path.join(this.directory,b.id+'.json'),b);}catch(error){this.failStorage(error);throw this.storageError;}}
  runPath(id){if(!safeId(id))throw Error('请求运行标识无效');return path.join(this.directory,'runs',id+'.json');}
  saveRun(run){this.assertWritable();try{fs.mkdirSync(path.join(this.directory,'runs'),{recursive:true});run.updatedAt=now();run.sequence=(run.sequence||0)+1;atomic(this.runPath(run.id),run);}catch(error){this.failStorage(error);throw this.storageError;}}
  run(id){const f=this.runPath(id);if(!fs.existsSync(f))return null;const run=readValidated(f,r=>r && r.id===id && r.conversation && Array.isArray(r.conversation.messages) && r.conversation.messages.every(m=>m && typeof m==='object') && (!r.events || (Array.isArray(r.events)&&r.events.every(e=>e && typeof e==='object'))));if(!run){if(!this.skipped.includes('runs/'+id+'.json'))this.skipped.push('runs/'+id+'.json');return null;}return run;}

  blindReview(id){const run=this.run(id);if(!run)return null;return {id:run.id,status:run.status,blind:true,publicPrompt:run.publicPrompt,environmentFailure:run.environmentFailure,
    conversation:{id:run.conversation.id,messages:run.conversation.messages.map(({id,role,content,status})=>({id,role,content,status}))}};}
  list(){return [...this.batches.values()].map(b=>({id:b.id,title:b.title,status:b.status,createdAt:b.createdAt,updatedAt:b.updatedAt,total:b.runs.length,completed:b.runs.filter(r=>r.status==='complete').length,failed:b.runs.filter(r=>['failed','interrupted_unknown'].includes(r.status)).length,partial:b.runs.filter(r=>['partial','unsupported'].includes(r.status)).length,awaiting:b.runs.filter(r=>r.status==='awaiting_human').length,requestCount:b.requestCount,requestCap:b.requestCap}));}
  view(id,offset=0){const b=this.batches.get(id);if(!b)return null;return {...b,counts:Object.fromEntries([...new Set(b.runs.map(r=>r.status))].map(s=>[s,b.runs.filter(r=>r.status===s).length])),cases:b.cases.map(({privateCard,privateReference,...c})=>({...c,hasPrivateCard:!!privateCard,hasReference:!!privateReference})),runs:b.runs.slice(offset,offset+100),offset,total:b.runs.length};}
  async create(data) {
    this.assertWritable();
    const cases=parseCases(data.cases,data.privateCards||[]),presets=data.presets||['full'],repeats=data.repeats??1;
    if(!Array.isArray(presets)||!presets.length||presets.length>9||new Set(presets).size!==presets.length||presets.some(p=>!Object.hasOwn(methodPresets,p)&&p!=='native_api')||!Number.isInteger(repeats)||repeats<1||repeats>100||cases.length*presets.length*repeats>10000)throw Error('输入实验规模或方法无效');
    const requestCap=data.requestCap??100,seed=data.scheduleSeed??1;
    if(!Number.isInteger(requestCap)||requestCap<1||requestCap>40000||!Number.isInteger(seed))throw Error('请求额度或排程种子无效');
    const config=this.runner?{id:'mock',model:'injected-test-runner',language:'zh-CN'}:await this.store.credentials(data.provider);
    config.language=data.language==='en'?'en':'zh-CN';
    if(data.protocolCorrection!==undefined&&typeof data.protocolCorrection!=='boolean')throw Error('协议纠正开关无效');
    config.protocolCorrection=data.protocolCorrection!==false;
    config.unattended=data.unattended!==false;
    const engine=data.engine||'highs';if(!['highs','gurobi'].includes(engine))throw Error('请选择有效求解器');
    const b={id:uuid(),title:String(data.title||'Research batch').slice(0,150),createdAt:now(),status:'draft',cases,
      datasetHash:digest(cases.map(c=>({id:c.id,hash:c.hash}))),privateCardHash:digest(cases.map(c=>c.privateCard)),frozen:frozenConfig(config,engine,null),methodVersion,methodSnapshot:Object.fromEntries(presets.map(p=>[p,methodPresets[p]||{label:'Native API, no tools'}])),configHash:digest(frozenConfig(config,engine,null)),limits:agentLimits,
      environmentVersion,scorerVersion,sourceSnapshot:executionSnapshot(),entry:data.entry==='cli'?'cli':'workbench',referenceHash:digest(cases.map(c=>c.privateReference)),estimatedMaximumRequests:cases.length*presets.length*repeats*agentLimits.calls,
      scheduleSeed:seed,modelSeed:null,requestCap,requestCount:0,retries:0,concurrency:1,rateIntervalMs:1000,timeoutMs:300000,unattended:data.unattended!==false,runs:[],source:this.runner?'injected_test_runner':'provider_api'};
    for(const c of cases)for(const preset of presets)for(let repeat=0;repeat<repeats;repeat++)b.runs.push({id:uuid(),caseId:c.id,baseId:c.baseId,preset,repeat,status:'queued'});
    let state=seed>>>0;for(let i=b.runs.length-1;i>0;i--){state=(Math.imul(state,1664525)+1013904223)>>>0;const j=state%(i+1);[b.runs[i],b.runs[j]]=[b.runs[j],b.runs[i]];}
    this.batches.set(b.id,b);this.save(b);return this.view(b.id);
  }
  action(id,action){this.assertWritable();const b=this.batches.get(id);if(!b)throw Error('请求实验不存在');
    if(['start','resume'].includes(action)&&b.methodVersion!==methodVersion)throw new UserInputError('EXPERIMENT_VERSION_CHANGED','当前实现与冻结版本不同，请新建实验');
    if(['start','resume'].includes(action)&&(b.environmentVersion!==environmentVersion||b.scorerVersion!==scorerVersion||b.sourceSnapshot?.sha256!==executionSnapshot().sha256))throw new UserInputError('EXPERIMENT_SOURCE_CHANGED','源码、环境或评分器与冻结清单不同，请新建实验；历史记录保留');
    if(action==='start'&&!this.runner&&b.requestCap<b.estimatedMaximumRequests)throw new UserInputError('EXPERIMENT_REQUEST_CAP',`本批最多需要 ${b.estimatedMaximumRequests} 次请求额度，当前仅 ${b.requestCap} 次。请新建足够额度的清单，或明确拆分配对子批。`);
    if(action==='start'||action==='resume'){if(b.status==='cancelled')throw Error('请求已取消，需创建新批次');b.status='running';}
    else if(action==='pause')b.status='paused';
    else if(action==='cancel'){b.status='cancelled';for(const r of b.runs)if(r.status==='queued')r.status='cancelled';if(this.activeBatch===id)this.controller?.abort();}
    else throw Error('请求操作无效');this.save(b);if(b.status==='running')void this.pump().catch(error=>this.failStorage(error));return this.view(id);
  }
  async rerun(id,runIds){const source=this.batches.get(id);if(!source||!Array.isArray(runIds)||!runIds.length||runIds.length>1000||runIds.some(id=>!source.runs.some(r=>r.id===id)))throw Error('请选择要重跑的历史记录');const selected=source.runs.filter(r=>runIds.includes(r.id));
    const created=await this.create({title:source.title+' · rerun',cases:source.cases.filter(c=>selected.some(r=>r.caseId===c.id)),presets:[...new Set(selected.map(r=>r.preset))],repeats:1,requestCap:source.requestCap,scheduleSeed:source.scheduleSeed,provider:source.frozen.provider,engine:source.frozen.engine,language:source.frozen.language});
    const b=this.batches.get(created.id),current=b.frozen;b.frozen={...structuredClone(source.frozen),methodVersion,protocolVersion:current.protocolVersion,protocolCorrection:source.frozen.protocolCorrection===true};b.configHash=digest(b.frozen);b.parentMethodVersion=source.methodVersion;b.parentBatchId=id;b.runs=b.runs.filter(r=>selected.some(s=>s.caseId===r.caseId&&s.preset===r.preset));b.estimatedMaximumRequests=b.runs.length*agentLimits.calls;for(const r of b.runs)r.parentRunIds=selected.filter(s=>s.caseId===r.caseId&&s.preset===r.preset).map(s=>s.id);this.save(b);return this.view(b.id);
  }
  async pump(){this.assertWritable();if(this.working)return;this.working=true;
    try {while(true){const b=[...this.batches.values()].find(x=>x.status==='running'&&x.runs.some(r=>r.status==='queued'));if(!b)break;
      const meta=b.runs.find(r=>r.status==='queued'),c=b.cases.find(x=>x.id===meta.caseId);this.activeBatch=b.id;
      meta.status='running';meta.attempted=true;this.save(b);let run=this.run(meta.id)||{...meta,batchId:b.id,entry:b.entry,environmentVersion:b.environmentVersion,sourceSnapshot:b.sourceSnapshot,createdAt:now(),status:'running',caseHash:c.hash,publicPrompt:c.prompt,frozen:{...b.frozen,preset:meta.preset},attemptId:uuid(),conversation:{id:uuid(),messages:[]},events:[]};run.status='running';
      this.saveRun(run);this.controller=new AbortController();this.deadline=Date.now()+b.timeoutMs;this.timer=setTimeout(()=>this.controller?.abort(),b.timeoutMs);
      try {
        if(this.runner)run={...run,...await this.runner({run:structuredClone(run),prompt:c.prompt,signal:this.controller.signal})};
        else await this.trajectory(b,run,c,this.controller.signal);
        if(run.status==='running')run.status=trajectoryState(run);run.score=scoreRun(run,c.privateCard,c.privateReference);
      }catch(error){run.status=this.controller.signal.aborted?'cancelled':'failed';const last=run.conversation.messages.at(-1);run.failure=last?.automation?.failure||{layer:'transport',code:'EXECUTION_FAILED',stage:last?.automation?.stage||'request',path:'$',httpStatus:Number(error.status)||null};run.error={message:error.message.slice(0,1500),httpStatus:Number(error.status)||null,name:error.name};if(last?.role==='assistant'){last.status=run.status==='cancelled'?'stopped':'error';if(last.automation){last.automation.stage=last.status;last.automation.taskOutcome='failed';}}run.score=scoreRun(run,c.privateCard,c.privateReference);if([401,402,403,429].includes(Number(error.status))||Number(error.status)>=500)b.status='paused';}
      finally {clearTimeout(this.timer);run.completedAt=now();this.saveRun(run);meta.status=run.status;meta.score=run.score;meta.failure=run.failure;meta.updatedAt=run.updatedAt;this.save(b);this.controller=null;}
      if(!b.runs.some(r=>r.status==='queued')&&b.status==='running'){b.status=b.runs.some(r=>r.status==='awaiting_human')?'awaiting_human':'complete';this.save(b);}
    }}catch(error){this.failStorage(error);}finally{clearTimeout(this.timer);this.controller=null;this.working=false;this.activeBatch=null;}
  }
  async trajectory(b,run,c,signal){
    const credentials=await this.store.credentials(b.frozen.provider),config={...credentials,...b.frozen,id:b.frozen.provider};
    const conversation=run.conversation;let message=run.humanReply||c.prompt;delete run.humanReply;
    const request=async(call,evidence={})=>{
      if(b.status==='paused'){const remaining=Math.max(1,this.deadline-Date.now());clearTimeout(this.timer);run.waitingForResume=true;this.saveRun(run);while(b.status==='paused'){signal.throwIfAborted();await new Promise(r=>setTimeout(r,50));}delete run.waitingForResume;this.deadline=Date.now()+remaining;this.timer=setTimeout(()=>this.controller?.abort(),remaining);}
      if(b.requestCount>=b.requestCap){b.status='paused';this.save(b);const flow=run.conversation.messages.at(-1)?.automation;if(flow)flow.failure={layer:'budget',code:'BATCH_REQUEST_LIMIT',stage:flow.stage,path:'$.requestCap'};throw Error('批次请求额度已用尽，任务未完成。');}signal.throwIfAborted();b.requestCount++;this.save(b);
      const entry={id:uuid(),state:'reserved',createdAt:now(),...evidence};run.events.push(entry);this.saveRun(run);
      const wait=Math.max(0,(this.lastRequestAt||0)+b.rateIntervalMs-Date.now());if(wait)await new Promise(r=>setTimeout(r,wait));signal.throwIfAborted();entry.state='sent';this.lastRequestAt=Date.now();this.saveRun(run);
      try{const value=await call();entry.state='completed';entry.completedAt=now();entry.response=value??null;this.saveRun(run);return value;}catch(error){entry.state=signal.aborted?'cancelled_unknown':'failed';entry.httpStatus=Number(error.status)||null;this.saveRun(run);throw error;}
    };
    for(let turn=0;turn<3;turn++){
      const user={id:uuid(),role:'user',content:message,createdAt:now(),status:'complete'};conversation.messages.push(user);
      const answer={id:uuid(),role:'assistant',content:'',status:'streaming',createdAt:now(),provider:config.id,model:config.model,provenance:{source:'llm'},usage:{input:null,output:null}};
      if(run.preset!=='native_api'){
        answer.automation={stage:'modeling',engine:b.frozen.engine,seconds:30,usage:{},limits:agentLimits,task:taskFor(conversation,user,false)};
        initializeMethods(answer.automation,config,b.frozen.engine,run.preset);
      }
      const messages=answer.automation?taskMessages(conversation,answer.automation.task):conversation.messages.filter(m=>m.role==='user'||m.status==='complete').map(({role,content})=>({role,content}));
      conversation.messages.push(answer);const update=()=>this.saveRun(run);update();
      let record=null;
      if(answer.automation)record=await executeOptimization({config,messages,problem:message,engine:b.frozen.engine,seconds:30,planner:(...args)=>request(()=>this.planner(...args),{stage:answer.automation.stage,input:args[1],prompt:args[0].stagePrompt??null,promptHash:args[0].stagePrompt?digest(args[0].stagePrompt):null}),solver:this.solver,signal,answer,update});
      if(!answer.automation||record){const input=record?explanationMessages(messages,record):messages;
        if(!answer.automation&&(run.nativeCalls||0)>=agentLimits.calls){run.status='partial';run.failure={layer:'budget',code:'TASK_REQUEST_LIMIT'};return;}
        if(!answer.automation)run.nativeCalls=(run.nativeCalls||0)+1;
        if(!answer.automation||reserveCall(answer,input,config.language))await request(async()=>{for await(const chunk of this.generator({...config,maxTokens:record?stageTokens(config,'interpretation'):config.maxTokens},input,signal)){if(chunk.text)answer.content+=chunk.text;if(chunk.usage)Object.assign(answer.usage,chunk.usage);if(chunk.warning)answer.warning=chunk.warning;if(chunk.rawUsage)answer.rawUsage=chunk.rawUsage;if(chunk.requestMetadata)answer.requestMetadata=chunk.requestMetadata;update();}return {text:answer.content,usage:answer.usage,rawUsage:answer.rawUsage??null,requestMetadata:answer.requestMetadata??null,warning:answer.warning??null};},{input,stage:record?'interpretation':'native_api'});
      }
      if(answer.warning){answer.status='interrupted';run.status='partial';run.failure={layer:'transport',code:'OUTPUT_TRUNCATED',stage:record?'interpretation':'native_api'};update();return;}
      answer.status='complete';if(answer.automation?.stage==='interpreting')answer.automation.stage='complete';update();
      const questions=answer.automation?.stage==='clarification'?answer.automation.questions:!answer.automation?questionsFromText(answer.content):[];
      if(questions.length){
        run.environmentTurns=(run.environmentTurns||0)+1;
        if(run.environmentTurns>agentLimits.clarifications){run.status='partial';run.failure={layer:'budget',code:'CLARIFICATION_LIMIT'};return;}
        const response=respondToQuestions(questions,c.privateCard,{language:config.language});
        run.events.push({id:uuid(),state:'environment_decision',...response,createdAt:now()});
        if(response.status!=='answered'){
          if(response.reply){conversation.messages.push({id:uuid(),role:'user',content:response.reply,status:'complete',createdAt:now()});run.events.push({id:uuid(),state:'controller_reply',content:response.reply,factHash:response.factHash,createdAt:now()});}
          run.status=b.unattended?'partial':'awaiting_human';run.environmentFailure={code:b.unattended?'UNATTENDED_CLARIFICATION_RECORDED':'UNSUPPORTED_OR_AMBIGUOUS_QUESTION',questions:response.unanswered};return;
        }
        run.events.push({id:uuid(),state:'controller_reply',content:response.reply,questionIds:questions.map(q=>q.id).filter(Boolean),factHash:response.factHash,createdAt:now()});message=response.reply;continue;
      }
      return;
    }
    run.status=b.unattended?'partial':'awaiting_human';
  }
  answer(batchId,runId,message){const b=this.batches.get(batchId),meta=b?.runs.find(r=>r.id===runId),run=meta&&this.run(runId);if(!run||meta.status!=='awaiting_human'||typeof message!=='string'||!message.trim()||message.length>24000)throw Error('输入答复或运行状态无效');run.humanReply=message.trim();(run.events||=[]).push({id:uuid(),state:'human_reply',content:message.trim(),createdAt:now(),reviewMode:'human_answer_presentation_not_verified'});delete run.environmentFailure;run.status='queued';this.saveRun(run);meta.status='queued';this.save(b);return {ok:true};}
  evaluate(batchId,runId,value){const b=this.batches.get(batchId),meta=b?.runs.find(r=>r.id===runId),run=meta&&this.run(runId);if(!run||!['correct','incorrect','uncertain'].includes(value.verdict)||typeof value.note!=='string'||!value.note.trim()||value.note.length>4000)throw Error('输入评分无效');if(value.verdict==='correct'&&run.status!=='complete')throw Error('任务未完成，不能标为完整正确；请记录未完成原因或待复核。');run.manualEvaluations||=[];run.manualEvaluations.push({id:uuid(),version:'manual-2',verdict:value.verdict,note:value.note,at:now()});run.manualVerdict=value.verdict;this.saveRun(run);meta.manualVerdict=value.verdict;this.save(b);return run;}
  summary(batchId){const b=this.batches.get(batchId);return b?{...summarizeRuns(b.runs),methodVersion:b.methodVersion,configHash:b.configHash,protocolCorrection:b.frozen.protocolCorrection??false}:null;}
  async close(){this.controller?.abort();while(this.working)await new Promise(r=>setTimeout(r,20));}
}


