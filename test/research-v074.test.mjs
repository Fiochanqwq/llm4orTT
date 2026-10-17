import test from 'node:test';
import assert from 'node:assert/strict';
import { respondToQuestions, budgetIntent, questionsFromText } from '../server/experiment-environment.mjs';
import { scoreOriginalTask } from '../server/independent-scoring.mjs';
import { summarizeRuns } from '../server/research-metrics.mjs';
import { compileCompactContract,compileCompactReview,compactVersion,compactReviewVersion } from '../shared/compact-protocol.mjs';
import { executeOptimization } from '../server/optimization.mjs';
import { initializeMethods,validateReply } from '../server/optimization-v07.mjs';
import { taskFor } from '../server/agent-policy.mjs';
import { numericalCheck } from '../shared/result-contract.mjs';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { ExperimentService } from '../server/experiments.mjs';
import { analysisRow,ExportService } from '../server/exports.mjs';
import { readBatchConfig } from '../scripts/run-experiments.mjs';
const card={hidden_fixed_budget:340,unit:'USD',confirmedFixed:true};
test('same environment answers paraphrases without IDs, retains units, and handles multiple questions',()=>{
  for(const question of ['实际预算是多少？','请告诉我实际批准了多少钱？','What is your approved budget?','Is the fixed budget at least 330 USD?']){
    const result=respondToQuestions([{question}],card);assert.equal(result.status,'answered',question);assert.match(result.reply,/340 USD/);
  }
  const result=respondToQuestions([{question:'实际预算是多少？'},{question:'是否愿意追加预算？'}],card);
  assert.equal(result.status,'answered');assert.equal(result.decisions.length,2);
  assert.equal(questionsFromText('I need one fact. What is your approved budget?').length,1);
});
test('environment does not leak exact amounts for additional funding, vague fields, hypothetical or unasked facts',()=>{
  assert.doesNotMatch(respondToQuestions([{question:'能否增加预算？'}],card).reply,/340/);
  assert.equal(respondToQuestions([{field:'budget',question:'还有别的条件吗？'}],card).status,'awaiting_human');
  assert.equal(respondToQuestions([{question:'假设预算为 500，是否继续？'}],card).reply,null);
  assert.equal(respondToQuestions([],card).reply,null);
  assert.equal(respondToQuestions([{question:'预算区间是什么？'}],card).reply,null);
  assert.equal(respondToQuestions([{question:'实际预算是多少？'}],{hidden_fixed_budget:340}).status,'awaiting_human');
  assert.equal(budgetIntent('已批准且不可追加的预算是否至少为 330 USD？'),'amount');
});
const referenceModel={format:'llm4orovo.lp.v1',name:'two optima',sense:'minimize',variables:[{name:'x',type:'continuous',lower:0,upper:null},{name:'y',type:'continuous',lower:0,upper:null}],objective:{x:1,y:1},constraints:[{name:'demand',terms:{x:1,y:1},sense:'>=',rhs:3}]};
const reference={verified:true,provenance:'independently checked x+y >= 3',version:'fixture1',status:'optimal',model:referenceModel,objective:3};
function scoredRun(values,status='optimal',objective=3){return {status:'complete',conversation:{messages:[{role:'assistant',content:'final'}]},actions:[{type:'final',outcome:{status,values,objective}}]};}
test('independent score checks original requirements, not a submitted model or review; accepts alternate optima',()=>{
  assert.equal(scoreOriginalTask(scoredRun({x:3,y:0}),reference).verdict,'correct');
  assert.equal(scoreOriginalTask(scoredRun({x:0,y:3}),reference).verdict,'correct');
  assert.equal(scoreOriginalTask(scoredRun({x:0,y:0},'optimal',0),reference).verdict,'incorrect');
  assert.equal(scoreOriginalTask(scoredRun({x:0,y:3},'optimal',9),reference).verdict,'incorrect');
  assert.equal(scoreOriginalTask(scoredRun({a:3,b:0}),reference).verdict,'unknown');
  assert.equal(scoreOriginalTask(scoredRun({x:3,y:0}),null).verdict,'unknown');
});
test('infeasibility requires independent evidence and unfinished tasks cannot count as successful',()=>{
  const r=scoredRun(null,'infeasible',null);
  assert.equal(scoreOriginalTask(r,{verified:true,provenance:'review',status:'infeasible'}).verdict,'unknown');
  assert.equal(scoreOriginalTask(r,{verified:true,provenance:'review',status:'infeasible',certificate:'lower bound exceeds fixed cap'}).verdict,'correct');
  assert.equal(scoreOriginalTask({...r,status:'partial'},reference).taskSuccess,false);
  const summary=summarizeRuns([{preset:'generic',baseId:'a',status:'complete',score:{independent:{verdict:'correct'}}},{preset:'generic',baseId:'a',status:'failed'},{preset:'generic',baseId:'a',status:'complete',score:{independent:{verdict:'unknown'}}}]);
  assert.equal(summary.methods[0].attempted,3);assert.equal(summary.methods[0].meanBaseTaskSuccessLower,1/3);assert.equal(summary.methods[0].meanBaseTaskSuccessUpper,2/3);
});
test('malformed evaluation configuration and unclassified human replies stay unknown, not model failures',()=>{
  const run=scoredRun({x:3,y:0});assert.equal(scoreOriginalTask(run,{...reference,requiredDisclosures:'amount'}).verdict,'unknown');
  assert.equal(scoreOriginalTask({...run,events:[{state:'human_reply',content:'The actual budget is 4 USD'}]},{...reference,requiredDisclosures:['amount']}).verdict,'unknown');
});
const original={id:'origin',role:'user',content:'Choose nonnegative x and y with x+y at least 3, minimize x+y USD. Fixed budget is between 2 and 4 USD; no other costs or conditions.'};
const semantic=(budget=false)=>({format:compactVersion,requirements:[{statement:'Nonnegative variables, cost and demand',sources:['s1'],targets:[{kind:'variable',name:'x'},{kind:'variable',name:'y'},{kind:'objective'},{kind:'constraint',name:'demand'}]}],missing:[],budget:budget?{lower:2,upper:4,unit:'USD',sources:['s1','s2'],confirmedFixed:true,onlyCostCap:true,otherConditionsComplete:true}:null});
const action=(args)=>({calls:[{name:'submit_optimization',arguments:args}],usage:{input:10,output:10}});
const solve=(budget=false)=>action({action:'solve',model_json:JSON.stringify(referenceModel),message:'Candidate',questions:[],contract_json:JSON.stringify(semantic(budget))});
const review=(budget=false)=>({calls:[{name:'review_optimization',arguments:{review_json:JSON.stringify({format:compactReviewVersion,status:'no_issue_found',checks:{requirements:'checked',mathematics:'checked',amendments:'checked',budget:budget?'checked':'not_applicable'},diagnostics:[],budgetApplicability:budget?'supported':'not_applicable'})}}],usage:{input:10,output:10}});
function execution(preset,planner){
  const config={id:'openai',model:'injected',language:'en',maxTokens:16000,modelingTokens:16000,protocolCorrection:false};
  const task=taskFor({messages:[]},original,false),answer={content:'',provenance:{},automation:{task,usage:{}}};initializeMethods(answer.automation,config,'highs',preset);
  const saved=new Map();let calls=0;
  const solver={active:null,info:()=>({engines:{highs:{available:true}}}),get:id=>saved.get(id),stop:()=>{},start:({model})=>{const r={id:'run'+saved.size,engine:'highs',model,status:'optimal',values:{x:3,y:0},objective:3,bound:3,provenance:{solverInvoked:true},check:numericalCheck(model,{x:3,y:0})};saved.set(r.id,r);return r;}};
  const options={config,messages:[original],problem:original.content,engine:'highs',seconds:30,planner:async(...args)=>planner(++calls,...args),solver,signal:new AbortController().signal,answer,update:()=>{}};
  return {answer,options,run:()=>executeOptimization(options),calls:()=>calls};
}
test('compact nested budget generates all internal IDs; unknown handles and altered previous facts fail',()=>{
  const c=compileCompactContract(semantic(true),[original],referenceModel).contract;
  assert.equal(c.budget.gapId,c.gaps[0].id);assert.equal(c.wireFormat,compactVersion);
  const bad=semantic(true);bad.budget.sources=['gap:gap:budget'];assert.throws(()=>compileCompactContract(bad,[original],referenceModel),/UNKNOWN_REFERENCE/);
  const changed=semantic(true);changed.budget.previous='p2';changed.budget.upper=6;
  assert.throws(()=>compileCompactContract(changed,[original],referenceModel,{previous:c}),/CHANGED_PRIOR_FACT/);
});
test('review categories retain uncertainty without fabricated per-object coverage',()=>{
  const c=compileCompactContract(semantic(),[original],referenceModel).contract,r=JSON.parse(review().calls[0].arguments.review_json);
  const valid=compileCompactReview(r,c,[original],referenceModel);assert.equal(valid.status,'no_issue_found');assert.deepEqual(valid.factIds,[]);
  r.checks.requirements='not_checked';assert.equal(compileCompactReview(r,c,[original],referenceModel).status,'uncertain');
  r.status='mismatch';r.diagnostics=[{code:'sign',sources:['s1'],targets:[{kind:'constraint',name:'invented'}],evidence:'wrong direction',repairable:true}];assert.throws(()=>compileCompactReview(r,c,[original],referenceModel),/UNKNOWN_REFERENCE/);
});
test('current full route uses compact protocol and budget amount correction reuses checked solver evidence',async()=>{
  const f=execution('full',n=>n===1?solve(true):review(true));await f.run();const flow=f.answer.automation;
  assert.equal(flow.stage,'clarification');assert.equal(f.calls(),2);assert.equal(flow.task.solves,1);
  assert.ok(validateReply(flow.task,{taskId:flow.task.id,questionId:flow.questions[0].id,gapId:flow.questions[0].gapId,factVersion:flow.task.factVersion}));
  f.options.messages.push({id:'u2',role:'user',content:'4 EUR'});f.options.problem='4 EUR';await f.run();assert.equal(flow.decision.code,'budget_unit_conflict');
  f.options.messages.push({id:'u3',role:'user',content:'4 USD'});f.options.problem='4 USD';await f.run();assert.equal(flow.stage,'complete');assert.equal(f.calls(),2);assert.equal(flow.resultContract.evidenceReused,true);assert.match(f.answer.content,/actual budget 4 USD/);assert.doesNotMatch(f.answer.content,/throughout/);
});
test('generic uses the same solver but no research ledger or audit; model receives tool result and chooses final',async()=>{
  const stages=[];const f=execution('generic',(n,config,input)=>{
    stages.push(config.tool.name);const data=JSON.parse(input[0].content);
    if(n===1){assert.equal('contract_json' in config.tool.parameters.properties,false);return action({action:'solve',model_json:JSON.stringify(referenceModel),message:'Solve',questions:[]});}
    assert.equal(data.toolEvidence[0].objective,3);
    return action({action:'final',model_json:'',message:'The minimum cost is 3 USD.',questions:[],final:{status:'optimal',evidence:['r1'],values:{x:0,y:3},objective:3}});
  });await f.run();assert.equal(f.calls(),2);assert.equal(f.answer.automation.stage,'complete');assert.equal(f.answer.automation.methods.semanticReview,'not_run');assert.deepEqual(stages,['submit_optimization','submit_optimization']);assert.equal(f.answer.automation.publicOutcome.values.y,3);
});
test('generic may ask a threshold question after solving, then infer affordability without a system budget gate',async()=>{
  const f=execution('generic',n=>n===1?action({action:'solve',model_json:JSON.stringify(referenceModel),message:'Base cost',questions:[]}):n===2?action({action:'clarify',model_json:'',message:'Need actual budget',questions:[{question:'Is the fixed budget at least 3 USD?'}]}):action({action:'final',model_json:'',message:'With the actual budget 2 USD, a minimum cost of 3 USD is unaffordable.',questions:[],final:{status:'infeasible',evidence:['r1'],values:null,objective:null}}));
  await f.run();assert.equal(f.answer.automation.stage,'clarification');f.options.messages.push({id:'u2',role:'user',content:'The fixed budget is 2 USD.'});f.options.problem='The fixed budget is 2 USD.';await f.run();
  assert.equal(f.answer.automation.stage,'complete');assert.equal(f.answer.automation.publicOutcome.status,'infeasible');assert.equal(f.answer.automation.task.solves,1);assert.equal(f.answer.automation.methods.budgetRelevance,'not_run');assert.equal(f.calls(),3);
});
test('one new answer can resolve two compact gaps; same-age replacements cannot erase them',()=>{
  const initial={format:compactVersion,requirements:[],missing:[{description:'demand',sources:['s1'],question:'What is demand?',impact:'Required production'},{description:'capacity',sources:['s1'],question:'What is capacity?',impact:'Available production'}],budget:null};
  const previous=compileCompactContract(initial,[original],null).contract;
  const messages=[original,{id:'answer',role:'user',content:'Demand and capacity are both 5.'}];
  const raw={format:compactVersion,requirements:[{statement:'Demand and capacity now known',sources:['s3'],targets:[{kind:'conditions'}],replaces:['p1','p2']}],missing:[],budget:null};
  const resolved=compileCompactContract(raw,messages,null,{previous}).contract;assert.equal(resolved.facts.filter(f=>f.status==='superseded').length,2);
  raw.requirements[0].sources=['s1'];assert.throws(()=>compileCompactContract(raw,messages,null,{previous}),/INVALID_SUPERSESSION/);
});
test('explicit compact budget revisions require new sources and preserve old evidence',()=>{
  const previous=compileCompactContract(semantic(true),[original],referenceModel).contract;
  const raw=semantic(true);raw.budget={...raw.budget,lower:4,upper:5,sources:['s3'],replaces:['p2']};
  const messages=[original,{id:'revision',role:'user',content:'Correction: fixed budget is now between 4 and 5 USD.'}];
  const next=compileCompactContract(raw,messages,referenceModel,{previous}).contract;assert.equal(next.budget.lower,4);assert.equal(next.facts.find(f=>f.id===previous.budget.factId).status,'superseded');
  raw.budget.onlyCostCap=false;assert.throws(()=>compileCompactContract(raw,messages,referenceModel,{previous}),/FIELD_(VALUE|TYPE)/);
});
test('compact protocol correction repairs a source handle, uses the common limit and still runs semantic review',async()=>{
  const f=execution('full',(n)=>{if(n===3)return review();const p=solve();if(n===1){const c=JSON.parse(p.calls[0].arguments.contract_json);c.requirements[0].sources=['s999'];p.calls[0].arguments.contract_json=JSON.stringify(c);}return p;});
  f.answer.automation.methods.protocolCorrection=true;await f.run();assert.equal(f.calls(),3);assert.equal(f.answer.automation.task.protocolCorrections,1);assert.equal(f.answer.automation.methods.semanticReview,'executed');
});
test('generic cannot publish a fabricated tool reference or incorrect numeric final',async()=>{
  for(const final of [{status:'optimal',evidence:['r999'],values:{x:3,y:0},objective:3},{status:'optimal',evidence:['r1'],values:{x:0,y:0},objective:0}]){
    const f=execution('generic',n=>n===1?action({action:'solve',model_json:JSON.stringify(referenceModel),message:'Solve',questions:[]}):action({action:'final',model_json:'',message:'Bad result',questions:[],final}));await assert.rejects(f.run());assert.equal(f.answer.automation.task.calls,2);assert.equal(f.answer.automation.task.solves,1);
  }
});
test('turn-independent generic final retains actual evidence in a fresh answer object',async()=>{
  const f=execution('generic',n=>n===1?action({action:'solve',model_json:JSON.stringify(referenceModel),message:'Base',questions:[]}):n===2?action({action:'clarify',model_json:'',message:'Budget?',questions:[{question:'Actual budget?'}]}):action({action:'final',model_json:'',message:'Affordable',questions:[],final:{status:'optimal',evidence:['r1'],values:{x:3,y:0},objective:3}}));
  await f.run();const next={content:'',provenance:{},automation:{task:structuredClone(f.answer.automation.task),usage:{}}};initializeMethods(next.automation,f.options.config,'highs','generic');
  const u={id:'u2',role:'user',content:'Budget is 4 USD.'};await executeOptimization({...f.options,answer:next,messages:[original,u],problem:u.content});
  assert.equal(next.automation.stage,'complete');assert.equal(next.automation.runId,'run0');assert.equal(next.automation.resultContract.solverStatus,'optimal');assert.equal(next.provenance.solverRun.id,'run0');
});
test('batch environments treat generic/full/native questions alike and keep references outside method inputs',async()=>{
  const dir=path.resolve('qa','v074-env-'+crypto.randomUUID());let providerCalls=0;
  const service=new ExperimentService(dir,{store:{credentials:async()=>({id:'openai',model:'fixture',language:'en',maxTokens:16000,modelingTokens:16000,protocolCorrection:false})},solver:execution('generic',()=>{}).options.solver,
    planner:async(config,input)=>{providerCalls++;assert.ok(!JSON.stringify(input).includes('PRIVATE_REFERENCE_MARKER'));const d=JSON.parse(input[0].content);
      if(d.originalMessages.length>1)return action({action:'unsupported',model_json:'',message:'Fixture stops after receiving budget',questions:[],...(config.tool.parameters.properties.contract_json?{contract_json:JSON.stringify({format:compactVersion,requirements:[],missing:[],budget:null})}:{})});
      if(config.tool.parameters.properties.contract_json)return action({action:'clarify',model_json:'',message:'Need budget',questions:[],contract_json:JSON.stringify({format:compactVersion,requirements:[],missing:[{description:'budget',sources:['s1'],question:'What is the approved budget?',impact:'Feasibility'}],budget:null})});
      return action({action:'clarify',model_json:'',message:'Need budget',questions:[{question:'What is the approved budget?'}]});
    },generator:async function*(_c,input){providerCalls++;yield{text:input.length===1?'What is the approved budget?':'Budget received.'};}});
  const b=await service.create({cases:[{id:'case',prompt:'Minimize cost, budget unknown.',reference:{provenance:'PRIVATE_REFERENCE_MARKER'},privateCard:card}],presets:['generic','full','native_api'],requestCap:12,provider:'openai',language:'en',protocolCorrection:false});service.batches.get(b.id).rateIntervalMs=0;service.action(b.id,'start');while(service.working)await new Promise(r=>setTimeout(r,5));
  const runs=service.batches.get(b.id).runs.map(r=>service.run(r.id));const replies=runs.map(r=>r.events.find(e=>e.state==='controller_reply')?.content);assert.ok(replies.every(r=>r===replies[0]));assert.match(replies[0],/340 USD/);assert.equal(providerCalls,6);
  for(const r of runs){const blind=service.blindReview(r.id);assert.equal(blind.preset,undefined);assert.ok(!JSON.stringify(blind).includes('automation'));assert.ok(!JSON.stringify(r).includes('PRIVATE_REFERENCE_MARKER'));}
  const ex=new ExportService(dir,{data:{conversations:[]}},{get:()=>null},service),ticket=ex.create({batchIds:[b.id],format:'json'});for(const entry of ex.tickets.get(ticket.url.split('/').at(-1)).entries)assert.ok(!fs.readFileSync(entry.path,'utf8').includes('PRIVATE_REFERENCE_MARKER'));
});
test('CLI dry configuration calculates full cap without loading credentials; analysis preserves unknown usage',()=>{
  const dir=path.resolve('qa','v074-cli-'+crypto.randomUUID());fs.mkdirSync(dir,{recursive:true});const file=path.join(dir,'config.json');fs.writeFileSync(file,JSON.stringify({cases:[{id:'one',prompt:'Problem'}],presets:['generic','full'],repeats:3,requestCap:10}));
  const c=readBatchConfig(file);assert.equal(c.summary.maximumRequests,24);assert.equal(c.summary.budgetSufficient,false);assert.equal(c.summary.providerRequests,0);
  const r=analysisRow({id:'r',batchId:'b',caseId:'c',entry:'cli',preset:'full',repeat:2,status:'failed',events:[{id:'request',state:'failed',stage:'modeling'}],frozen:{methodVersion:'v4',apiKey:'SECRET'},score:{}});assert.equal(r.unknownUsageRequests,1);assert.equal(r.calls,1);assert.ok(!JSON.stringify(r).includes('SECRET'));
});

test('public exports redact private evaluation evidence in both batch indexes and run records',()=>{
  const dir=path.resolve('qa','v074-export-'+crypto.randomUUID()),batchId=crypto.randomUUID(),runId=crypto.randomUUID();
  const privateRef={...reference,provenance:'PRIVATE_PROVENANCE',status:'infeasible',certificate:'PRIVATE_BUDGET_CERTIFICATE'};
  const run={...scoredRun(null,'infeasible',null),id:runId,batchId,caseId:'one',events:[]};run.score={independent:scoreOriginalTask(run,privateRef)};
  const batch={id:batchId,sequence:1,runs:[{id:runId,caseId:'one',status:'complete',score:run.score}],cases:[{id:'one',prompt:'Public prompt',privateReference:privateRef,privateCard:card}]};
  const ex=new ExportService(dir,{data:{conversations:[]}},{get:()=>null},{batches:new Map([[batchId,batch]]),run:()=>run});
  for(const includePrivate of [false,true]){
    const ticket=ex.create({batchIds:[batchId],includePrivate});
    const texts=ex.tickets.get(ticket.url.split('/').at(-1)).entries.filter(e=>!e.name.startsWith('manifest')).map(e=>fs.readFileSync(e.path,'utf8'));
    assert.ok(texts.every(t=>t.includes('PRIVATE_BUDGET_CERTIFICATE')===includePrivate));assert.ok(texts.every(t=>t.includes('PRIVATE_PROVENANCE')===includePrivate));
  }
  const summary=JSON.stringify(analysisRow(run));assert.ok(!summary.includes('PRIVATE_'));assert.ok(summary.includes('INDEPENDENT_STATUS_REFERENCE'));
});

test('compact semantic repair remains anchored, includes entity evidence, and uses exactly four calls',async()=>{
  const f=execution('full',(n,config,input)=>{
    if(n%2===1){const p=solve();if(n===1){const wrong=structuredClone(referenceModel);wrong.constraints[0].sense='<=';p.calls[0].arguments.model_json=JSON.stringify(wrong);}p.calls[0].arguments.entities=[{variable:'x',label:'x',unit:'',sources:['s1']}];return p;}
    assert.equal(JSON.parse(input[0].content).entities[0].variable,'x');const p=review();
    if(n===2){const r=JSON.parse(p.calls[0].arguments.review_json);r.status='mismatch';r.diagnostics=[{code:'fixture_sign',sources:['s1'],targets:[{kind:'constraint',name:'demand'}],evidence:'Original says at least 3, but candidate encodes at most 3; replace <= with >=.',repairable:true}];p.calls[0].arguments.review_json=JSON.stringify(r);}
    return p;
  });await f.run();assert.equal(f.calls(),4);assert.equal(f.answer.automation.methods.repairStatus,'executed');assert.equal(f.answer.automation.task.reviews.length,2);assert.equal(f.answer.automation.task.solves,1);assert.equal(f.answer.automation.stage,'complete');
});

test('budget method runs without a semantic reviewer and rejects missing special-case premises',async()=>{
  const f=execution('budget',()=>solve(true));await f.run();assert.equal(f.calls(),1);assert.equal(f.answer.automation.stage,'clarification');assert.equal(f.answer.automation.methods.semanticReview,'not_run');assert.equal(f.answer.automation.methods.budgetRelevance,'executed');
  for(const flag of ['confirmedFixed','onlyCostCap','otherConditionsComplete']){const bad=semantic(true);bad.budget[flag]=false;assert.throws(()=>compileCompactContract(bad,[original],referenceModel),/FIELD_(VALUE|TYPE)/);}
});


