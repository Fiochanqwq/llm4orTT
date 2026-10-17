import test from 'node:test';
import packageInfo from '../package.json' with { type: 'json' };
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { respondToQuestions } from '../server/experiment-environment.mjs';
import { scoreRun, ExperimentService } from '../server/experiments.mjs';
import { publicOutcome } from '../server/independent-scoring.mjs';
import { analysisRow, ExportService } from '../server/exports.mjs';
import { summarizeRuns, trajectoryState } from '../server/research-metrics.mjs';
import { budgetDecision } from '../server/budget-relevance.mjs';
import { numericalCheck, resultText } from '../shared/result-contract.mjs';
import { executeOptimization } from '../server/optimization.mjs';
import { initializeMethods } from '../server/optimization-v07.mjs';
import { taskFor, agentLimits } from '../server/agent-policy.mjs';
import { compactVersion, compactReviewVersion } from '../shared/compact-protocol.mjs';
const card={hidden_fixed_budget:2,unit:'USD',confirmedFixed:true};
const model={format:'llm4orovo.lp.v1',name:'base',sense:'minimize',variables:[{name:'x',type:'continuous',lower:0,upper:null}],objective:{x:1},constraints:[{name:'demand',terms:{x:1},sense:'>=',rhs:3}]};
const reference={version:'independent-algebra',verified:true,provenance:'x >= 3; cost x; cap 2',status:'infeasible',certificate:'x >= 3 > 2'};
const specification=JSON.parse(fs.readFileSync(new URL('../experiments/mainline-preparation-20261013/acceptance-cases.json',import.meta.url),'utf8'));
for(const c of specification.environment)test(c.id+' budget disclosure policy',()=>{
  const questions=c.questions?.map(question=>({question}))??[{question:c.question,field:c.field}];
  const r=respondToQuestions(questions,card),amount=r.decisions.filter(d=>d.disclosed&&d.factKind==='amount');
  assert.equal(amount.length,['A04','A05','A10'].includes(c.id)?1:0);
  if(['A01','A02','A03','A07','A08','A11'].includes(c.id))assert.equal(r.reply,null);
  if(c.id==='A06')assert.match(r.reply,/不能追加/);
  if(c.id==='A10'){assert.equal(r.status,'awaiting_human');assert.deepEqual(r.unanswered,['最低所需预算是多少？']);}
  if(c.id==='A11'){const pub=respondToQuestions(questions,{...card,publicBudgetRange:{lower:1,upper:4}});assert.equal(pub.reply,'[1, 4] USD');}
});
test('required costs, counterfactuals, negations and combined intents do not authorize private amounts',()=>{
  assert.equal(respondToQuestions([{question:'已批准预算'}],card).reply,null);
  for(const question of ['已批准且不可追加的预算是否至少为 158/27 USD？可回答是/否，或填写实际预算。','Is the fixed approved budget at least 158/27 USD? Answer yes/no or enter the actual amount.'])assert.match(respondToQuestions([{question}],card).reply,/2 USD/);
  for(const question of ['最少经费是多少？','需要多少拨款才能完成？','How much funding is needed?','What budget would satisfy demand?','Suppose the actual budget is 3, is that enough?','如果实际预算为3，是否够用？','不要告诉我实际预算是多少','Do not tell me the actual budget','实际预算是多少以及最低所需预算是多少？','预算差多少才能完成任务？','How much budget must be spent to deliver this plan?','What budget will this plan consume?','预算将消耗多少？','How much is the budget shortfall?'])assert.equal(respondToQuestions([{question}],card).reply,null,question);
  for(const question of ['实际预算是多少？','请告诉我实际批准了多少钱？','Is the approved budget at least 3 USD?','What is your approved budget?','请确认目前实际可动用的资金总额。','实际预算不超过3 USD，对吗？'])assert.match(respondToQuestions([{question}],card).reply,/2 USD/,question);
});
function scored({status='infeasible',solverStatus='optimal',execution='complete',stage='complete',values=null,objective=null,final=true}={}){
  return {id:crypto.randomUUID(),batchId:crypto.randomUUID(),caseId:'counterexample',baseId:'base',preset:'generic',status:execution,events:[],conversation:{messages:[{role:'assistant',content:'Final answer',automation:{stage,task:{calls:3,solves:1,clarifications:1},resultContract:{solverStatus,taskOutcome:'complete'},...(final?{publicOutcome:{status,values,objective,complete:true,source:'model_final_action'}}:{})}}]}};
}
test('B01 original infeasibility and base optimal survive scoring, summary and exports separately',()=>{
  const run=scored();run.score=scoreRun(run,card,reference);
  assert.equal(run.score.observedStatus,'infeasible');assert.equal(run.score.originalTaskStatus,'infeasible');assert.equal(run.score.solverStatus,'optimal');assert.equal(run.score.statusAgreement,true);assert.equal(run.score.independent.verdict,'correct');
  assert.equal(summarizeRuns([run]).methods[0].correct,1);assert.deepEqual(analysisRow(run).score.originalTaskStatus,'infeasible');
  const dir=path.resolve('qa','graduation-export-'+crypto.randomUUID()),batch={id:run.batchId,runs:[run],cases:[]};
  const ex=new ExportService(dir,{data:{conversations:[]}},{get:()=>null},{batches:new Map([[batch.id,batch]]),run:()=>run});
  const before=JSON.stringify(run);const ticket=ex.create({batchIds:[batch.id],format:'json'}),entries=ex.tickets.get(ticket.url.split('/').at(-1)).entries;
  const stored=JSON.parse(fs.readFileSync(entries.find(e=>e.name.startsWith('runs/')).path,'utf8'));
  assert.equal(stored.score.solverStatus,'optimal');assert.equal(stored.score.statusAgreement,true);assert.equal(JSON.stringify(run),before);
});
test('B02/B03/B06 status agreement never substitutes for independent correctness',()=>{
  const ref={...reference,status:'optimal',model,objective:3};
  for(const [x,expected] of [[3,'correct'],[0,'incorrect']]){
    const s=scoreRun(scored({status:'optimal',values:{x},objective:x}),{...card,expected_final_status:'optimal'},ref);
    assert.equal(s.statusAgreement,true);assert.equal(s.independent.verdict,expected);
  }
  assert.equal(scoreRun(scored({solverStatus:'infeasible'}),card,reference).independent.verdict,'correct');
});
test('B04/B05 missing finals, partial and stale delivered results never become success',()=>{
  for(const changes of [{execution:'partial'},{stage:'paused'},{final:false},{stage:'clarification'},{execution:'cancelled'}]){
    const run=scored(changes),score=scoreRun(run,card,reference);assert.equal(score.originalTaskStatus,null);assert.equal(score.statusAgreement,null);assert.equal(score.independent.verdict,'unknown');assert.notEqual(score.independent.taskSuccess,true);
  }
  const stale=scored({stage:'paused'});assert.equal(trajectoryState(stale),'partial');assert.equal(publicOutcome(stale).complete,false);
});
function harness(preset,{status='optimal',budget=false,finalStatus='infeasible',clarify=true}={}){
  const original={id:'original',role:'user',content:'Choose nonnegative x >= 3, minimize cost x USD. Fixed budget is between 2 and 4 USD, no other costs or conditions.'};
  const config={id:'openai',model:'INJECTED',language:'en',maxTokens:4096,modelingTokens:2048,protocolCorrection:false};
  const answer={role:'assistant',content:'',provenance:{},automation:{task:taskFor({messages:[]},original,false),usage:{}}};initializeMethods(answer.automation,config,'highs',preset);
  const saved=new Map();let calls=0;const seen=[];
  const record={id:'solver-record',engine:'highs',model,status,values:status==='optimal'?{x:3}:null,objective:status==='optimal'?3:null,bound:status==='optimal'?3:null,provenance:{solverInvoked:true}};record.check=numericalCheck(model,record.values);
  const solver={info:()=>({engines:{highs:{available:true}}}),get:id=>saved.get(id),start:()=>{saved.set(record.id,record);return record;},stop:()=>{}};
  const action=args=>({calls:[{name:'submit_optimization',arguments:args}],usage:{input:10,output:10}});
  const planner=async(c,input)=>{calls++;seen.push({maxTokens:c.maxTokens,tool:c.tool.name});
    if(c.tool.name==='review_optimization')return {calls:[{name:c.tool.name,arguments:{review_json:JSON.stringify({format:compactReviewVersion,status:'no_issue_found',checks:{requirements:'checked',mathematics:'checked',amendments:'checked',budget:budget?'checked':'not_applicable'},diagnostics:[],budgetApplicability:budget?'supported':'not_applicable'})}}]};
    if(calls===1)return action({action:'solve',model_json:JSON.stringify(model),message:'Compute base model',questions:[],...(preset==='full'?{contract_json:JSON.stringify({format:compactVersion,requirements:[{statement:'x >= 3, minimize x',sources:['s1'],targets:[{kind:'variable',name:'x'},{kind:'objective'},{kind:'constraint',name:'demand'}]}],missing:[],budget:budget?{lower:2,upper:4,unit:'USD',sources:['s1'],confirmedFixed:true,onlyCostCap:true,otherConditionsComplete:true}:null})}:{})});
    const data=JSON.parse(input[0].content);
    if(clarify&&data.originalMessages.length===1)return action({action:'clarify',model_json:'',message:'Need actual budget',questions:[{question:'What is the approved budget?'}]});
    return action({action:'final',model_json:'',message:'Final original-task answer',questions:[],final:{status:finalStatus,evidence:['r1'],values:finalStatus==='optimal'?{x:3}:null,objective:finalStatus==='optimal'?3:null}});
  };
  const options={config,messages:[original],problem:original.content,engine:'highs',seconds:30,planner,solver,signal:new AbortController().signal,answer,update:()=>{}};
  return {answer,options,seen,calls:()=>calls,run:()=>executeOptimization(options)};
}
test('generic/full get the same factual reply and limits; actual final status matches independent scoring',async()=>{
  const replies=[];
  for(const preset of ['generic','full']){
    const h=harness(preset,{budget:true});await h.run();const flow=h.answer.automation;
    assert.equal(flow.stage,'clarification');assert.equal(flow.publicOutcome.complete,false);
    const reply=respondToQuestions(flow.questions,card,{language:'en'});assert.equal(reply.status,'answered');replies.push(reply.reply);
    h.options.messages.push({id:'answer',role:'user',content:reply.reply});h.options.problem=reply.reply;await h.run();
    assert.equal(flow.stage,'complete');assert.equal(flow.publicOutcome.status,'infeasible');assert.equal(flow.resultContract.solverStatus,'optimal');
    const run={status:'complete',conversation:{messages:[h.answer]}};assert.equal(scoreRun(run,card,reference).statusAgreement,true);
    assert.ok(h.calls()<=agentLimits.calls);assert.ok(h.seen.every(c=>c.maxTokens===2048));assert.equal(flow.task.solves,1);
  }
  assert.equal(replies[0],replies[1]);
});
test('base infeasible ends full budget reasoning; base unbounded leaves budget conclusion unknown',async()=>{
  for(const status of ['infeasible','unbounded','time_limit']){
    const h=harness('full',{status,budget:true});await h.run();const flow=h.answer.automation;
    assert.equal(flow.stage,status==='infeasible'?'complete':'paused');assert.equal(flow.publicOutcome.status,status==='infeasible'?'infeasible':null);
    assert.equal(flow.task.clarifications,0);assert.equal(h.calls(),2);
    if(status==='infeasible')assert.doesNotMatch(h.answer.content,/budget is insufficient/i);
  }
});
test('generic reports actual unbounded evidence and rejects unsupported unbounded claim',async()=>{
  const h=harness('generic',{status:'unbounded',finalStatus:'unbounded',clarify:false});await h.run();assert.equal(h.answer.automation.publicOutcome.status,'unbounded');
  const wrong=harness('generic',{finalStatus:'unbounded',clarify:false});await assert.rejects(wrong.run());assert.equal(wrong.answer.automation.publicOutcome.complete,false);
});
test('budget evidence ignores stale check fields, invalid intervals and nonterminal bounds',()=>{
  const r={model:{...model,variables:[...model.variables,{name:'y',type:'continuous',lower:0,upper:null},{name:'z',type:'continuous',lower:0,upper:null}]},status:'time_limit',provenance:{solverInvoked:true},values:{x:0,y:0,z:0},check:{feasible:true,objective:0},bound:null};
  assert.equal(budgetDecision(r,{lower:2,upper:4}).status,'uncertain');assert.equal(budgetDecision(r,{lower:4,upper:2}).status,'uncertain');
  assert.equal(budgetDecision({...r,status:'unbounded',bound:100},{lower:2,upper:4}).status,'uncertain');
  assert.match(resultText({modelPurpose:'budget_threshold_base',budgetDecision:'all_feasible',solverStatus:'optimal',semanticReviewStatus:'no_issue_found'}),/不能自动证明/);
});
test('drafts make zero requests and source/environment/scoring drift blocks start',async()=>{
  let calls=0;const dir=path.resolve('qa','graduation-freeze-'+crypto.randomUUID());
  const service=new ExperimentService(dir,{runner:async()=>{calls++;return {status:'partial'};}});
  const created=await service.create({cases:[{id:'one',prompt:'example'}],presets:['generic','full'],requestCap:8});assert.equal(calls,0);
  const b=service.batches.get(created.id);assert.equal(b.sourceSnapshot.appVersion,packageInfo.version);
  const original=b.sourceSnapshot.sha256;b.sourceSnapshot.sha256='altered';assert.throws(()=>service.action(b.id,'start'),/冻结/);b.sourceSnapshot.sha256=original;
  b.environmentVersion='old';assert.throws(()=>service.action(b.id,'resume'),/冻结/);assert.equal(calls,0);await service.close();
});
