import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { contractSchema, reviewSchema, assertShape, sourceCatalog, targetCatalog, budgetRule } from '../shared/protocol-schema.mjs';
import { validateContract, validateReview, parseSubmission } from '../shared/task-contract.mjs';
import * as old from '../baselines/0.7.0-protocol-20261013/shared/task-contract.mjs';
import { researchPrompt, reviewPrompt } from '../shared/research-tool.mjs';
import { initializeMethods, executeV07 } from '../server/optimization-v07.mjs';
import { taskFor } from '../server/agent-policy.mjs';
import { numericalCheck } from '../shared/result-contract.mjs';
import { trajectoryState, summarizeRuns } from '../server/research-metrics.mjs';
import { ExperimentService } from '../server/experiments.mjs';
import { resolveBudgetReply } from '../server/budget-relevance.mjs';
import { methodVersion } from '../shared/methods.mjs';

const model={format:'llm4orovo.lp.v1',name:'Fertilizer',sense:'minimize',variables:[{name:'C',type:'continuous',lower:0,upper:null},{name:'Y',type:'continuous',lower:0,upper:null}],objective:{C:2,Y:3},constraints:[{name:'nitrogen',terms:{C:1.5,Y:5},sense:'>=',rhs:5},{name:'vitamins',terms:{C:3,Y:1},sense:'>=',rhs:8}]};
const original={id:'source-1',role:'user',content:'C、Y 是非负实数，每千克成本分别为 2、3 美元。需求 1.5C+5Y≥5；3C+Y≥8。最小化成本，无其他费用或上限。批准预算固定在 [5,6] 美元，不能追加。'};
function contract(message=original,base=false){const sources=sourceCatalog([message]);const c={format:'llm4orovo.submission.v3',modelPurpose:base?'budget_threshold_base':'final_task',facts:[
  {id:'domain',kind:'domain_and_cost',sourceRefs:[sources[0].id],unit:'USD/kg',value:null,supersedes:[]},
  {id:'demand',kind:'restrictions',sourceRefs:[sources[1].id,sources[2].id],unit:'',value:null,supersedes:[]},
  {id:'goal',kind:'objective',sourceRefs:[sources[3].id],unit:'USD',value:null,supersedes:[]}
],bindings:[{factIds:['domain'],targetRefs:['variable:C','variable:Y','objective:C','objective:Y'],disposition:'encoded',reason:''},{factIds:['demand'],targetRefs:['constraint:nitrogen','constraint:vitamins'],disposition:'encoded',reason:''},{factIds:['goal'],targetRefs:['objective:$'],disposition:'encoded',reason:''}],gaps:[],budget:null};
if(base){c.facts.push({id:'budget',kind:'budget',sourceRefs:[sources[4].id],unit:'USD',value:{lower:5,upper:6},supersedes:[]});c.gaps.push({id:'budget-gap',factId:'budget',kind:'budget'});c.bindings.push({factIds:['budget'],targetRefs:['gap:budget-gap'],disposition:'deferred_to_budget_gate',reason:''});c.budget={factId:'budget',gapId:'budget-gap',lower:5,upper:6,unit:'USD',costTerms:{...model.objective},confirmedFixed:true,onlyCostCap:true,otherConditionsComplete:true};}return c;}
const submit=(c=contract(),m=model,action='solve',questions=[])=>({calls:[{name:'submit_optimization',arguments:{action,model_json:m?JSON.stringify(m):'',contract_json:JSON.stringify(c),message:'Fixture',questions}}],usage:{input:12,output:30}});
function review(c=contract(),status='no_issue_found',source=original){return {format:'llm4orovo.review.v3',status,diagnostics:status==='no_issue_found'?[]:[{code:'domain_check',factIds:['domain'],targetIds:['variable:C'],gapIds:[],sourceRefs:[sourceCatalog([source])[0].id],evidence:'Fixture semantic finding retained',repairable:true}],factIds:c.facts.map(f=>f.id),targetIds:targetCatalog(model).filter(x=>x.required).map(x=>x.id),gapIds:c.gaps.map(g=>g.id),budgetApplicability:c.budget?'supported':'not_applicable'};}
const reviewed=r=>({calls:[{name:'review_optimization',arguments:{review_json:JSON.stringify(r)}}],usage:{input:12,output:20}});
function setup({planner,base=false,correction=true,preset='full'}={}){
  const config={id:'deepseek',model:'fixture',language:'en',maxTokens:12000,modelingTokens:12000,protocolCorrection:correction};
  const task=taskFor({messages:[]},original,false),answer={content:'',provenance:{},automation:{task,usage:{}}};initializeMethods(answer.automation,config,'highs',preset);
  const values={C:70/27,Y:2/9},record={id:crypto.randomUUID(),model,values,objective:158/27,bound:158/27,status:'optimal',provenance:{solverInvoked:true},check:numericalCheck(model,values)};
  let requests=0,solves=0;const prompts=[];
  const options={config,messages:[original],problem:original.content,engine:'highs',seconds:30,answer,update(){},signal:new AbortController().signal,
    solver:{active:null,info:()=>({engines:{highs:{available:true}}}),start:()=>{solves++;return record;},get:()=>record,stop(){}},
    planner:async(conf,input)=>{requests++;prompts.push({conf,input});return planner?planner(requests,conf,input):conf.tool.name==='review_optimization'?reviewed(review(contract(original,base))):submit(contract(original,base));}};
  return {options,answer,prompts,requests:()=>requests,solves:()=>solves,run:()=>executeV07(options)};
}

test('v3 source catalog supports multiple exact spans and immutable message offsets',()=>{
  const sources=sourceCatalog([original]);assert.equal(sources.length,5);
  for(const s of sources)assert.equal(original.content.slice(s.start,s.end),s.text);
  const c=validateContract(contract(),[original],model);assert.equal(c.facts[1].sourceEvidence.length,2);assert.match(c.facts[1].sourceSpan,/3C\+Y/);
  const bad=contract();bad.facts[0].sourceRefs[0]='source:other:0:10';assert.throws(()=>validateContract(bad,[original],model),e=>e.issue.layer==='source'&&e.issue.path==='$.facts[0].sourceRefs');
});
test('shared schemas reject unknown fields including inherited property names and invalid intervals',()=>{
  const c=contract();assertShape(c,contractSchema);c.constructor='bad';assert.throws(()=>assertShape(c,contractSchema),/FIELD_UNKNOWN/);
  const interval=contract(original,true);interval.facts.at(-1).value={lower:7,upper:6};assert.throws(()=>validateContract(interval,[original],model),/FACT_VALUE/);
  const r=review();assertShape(r,reviewSchema);r.extra=true;assert.throws(()=>validateReview(r,contract(),[original],model),/FIELD_UNKNOWN/);
});
test('not-applicable cannot supply mathematical coverage or conceal a dangling gap',()=>{
  const c=contract();c.bindings[0].disposition='not_applicable';c.bindings[0].reason='No limitations';assert.throws(()=>validateContract(c,[original],model),/APPLICABILITY_REASON/);
  const d=contract();d.bindings[0].targetRefs=['method:conditions'];d.bindings[0].disposition='not_applicable';d.bindings[0].reason='No extra fees';assert.throws(()=>validateContract(d,[original],model),/MODEL_COVERAGE/);
  const e=contract();e.bindings.push({factIds:['domain'],targetRefs:['gap:missing'],disposition:'pending_clarification',reason:''});assert.throws(()=>validateContract(e,[original],model),/UNKNOWN_REFERENCE/);
});
test('valid no-extra-fee fact has an explicit applicability reason separate from coverage',()=>{
  const c=contract();c.facts.push({...c.facts[2],id:'no-fees',kind:'completeness'});c.bindings.push({factIds:['no-fees'],targetRefs:['method:conditions'],disposition:'not_applicable',reason:'The source explicitly excludes additional fees.'});assert.ok(validateContract(c,[original],model));
});
test('model cannot assign gap execution states; old v2 cannot bypass the gate',()=>{
  const c=contract(original,true);c.gaps[0].status='resolved';assert.throws(()=>validateContract(c,[original],model),/FIELD_UNKNOWN/);
  const dir='experiments/protocol-regression-20261013/original/runs';const r=JSON.parse(fs.readFileSync(dir+'/e2200fea-a967-4a0f-b7df-57a028a38d26.json','utf8'));const args=old.parseSubmission(r.events[0].response,'deepseek','submit_optimization').value,d=JSON.parse(args.contract_json);d.gaps[0].status='resolved';assert.throws(()=>validateContract(d,r.conversation.messages,JSON.parse(args.model_json)),/UNVERIFIED_GAP_STATE/);
});
test('review distinguishes objective direction, coefficients and gaps; unknown aliases are not silently dropped',()=>{
  const c=validateContract(contract(original,true),[original],model),r=review(contract(original,true));assert.equal(validateReview(r,c,[original],model).status,'no_issue_found');
  r.targetIds.push('objective:total_cost');assert.throws(()=>validateReview(r,c,[original],model),/UNKNOWN_REFERENCE/);
  const missing=review(contract(original,true));missing.targetIds=missing.targetIds.filter(x=>x!=='objective:$');assert.equal(validateReview(missing,c,[original],model).status,'uncertain');
  const omit=review(contract(original,true));omit.gapIds=[];assert.equal(validateReview(omit,c,[original],model).coverageIncomplete,true);
});
test('both prompts share the exact unknown-budget rule, source and review schemas',()=>{
  assert.ok(researchPrompt('en',true).includes(budgetRule));assert.ok(reviewPrompt('en').includes(budgetRule));assert.ok(researchPrompt('en',true).includes(JSON.stringify(contractSchema)));assert.ok(reviewPrompt('en').includes(JSON.stringify(reviewSchema)));
  for(const mutate of [c=>c.budget.onlyCostCap=false,c=>c.budget.costTerms.C=5,c=>c.gaps.push({id:'fees',factId:'goal',kind:'unknown_fee'}),c=>c.budget.unit='']){const c=contract(original,true);mutate(c);assert.throws(()=>validateContract(c,[original],model));}
});
test('full v3 flow passes generated catalogs, reviews once and solves once',async()=>{
  const f=setup();await f.run();assert.equal(f.requests(),2);assert.equal(f.solves(),1);assert.equal(f.answer.automation.stage,'complete');assert.equal(f.answer.automation.task.protocolCorrections||0,0);
  assert.equal(JSON.parse(f.prompts[0].input[0].content).sourceCatalog.length,5);assert.ok(JSON.parse(f.prompts[1].input[0].content).targetCatalog.some(t=>t.id==='objective:$'));
});
test('one source correction consumes one request, preserves mathematics and is followed by review',async()=>{
  const broken=contract();broken.facts[1].sourceRefs=['fiction'];const f=setup({planner:n=>n===1?submit(broken):n===2?submit():reviewed(review())});await f.run();assert.equal(f.requests(),3);assert.equal(f.solves(),1);assert.equal(f.answer.automation.task.protocolCorrections,1);assert.equal(f.answer.automation.task.clarifications,0);assert.equal(f.answer.automation.protocolIssues[0].path,'$.facts[1].sourceRefs');assert.equal(f.prompts[1].conf.tool.name,'submit_optimization');assert.equal(f.answer.automation.failure,undefined);
});
test('correction off stops with detailed error; request failures never trigger protocol correction',async()=>{
  const c=contract();c.facts[0].sourceRefs=['bad'];const f=setup({correction:false,planner:()=>submit(c)});await assert.rejects(f.run());assert.equal(f.requests(),1);assert.equal(f.solves(),0);assert.equal(f.answer.automation.protocolError.layer,'source');
  const g=setup({planner:()=>{throw Object.assign(Error('connection unavailable'),{status:503});}});await assert.rejects(g.run());assert.equal(g.requests(),1);assert.equal(g.answer.automation.failure.layer,'transport');
});
test('two invalid responses stop; correction and review never exceed the global call cap',async()=>{
  const c=contract();c.facts[0].sourceRefs=['bad'];const f=setup({planner:()=>submit(c)});await assert.rejects(f.run());assert.equal(f.requests(),2);assert.equal(f.solves(),0);
  const g=setup({planner:()=>submit(c)});g.answer.automation.task.calls=2;await assert.rejects(g.run());assert.equal(g.requests(),1);assert.equal(g.answer.automation.task.calls,3);assert.equal(g.answer.automation.task.protocolCorrections||0,0);
});
test('protocol correction cannot change a valid model or erase an adverse review',async()=>{
  const c=contract();c.facts[0].sourceRefs=['bad'];const f=setup({planner:n=>n===1?submit(c):submit(contract(),{...model,objective:{C:1,Y:3}})});await assert.rejects(f.run());assert.equal(f.answer.automation.protocolError.code,'CORRECTION_CHANGED_MODEL');assert.equal(f.solves(),0);
  const bad=review(contract(),'uncertain');bad.targetIds.push('objective:total_cost');const g=setup({planner:n=>n===1?submit():n===2?reviewed(bad):reviewed(review())});await assert.rejects(g.run());assert.equal(g.answer.automation.protocolError.code,'CORRECTION_CHANGED_FINDING');assert.equal(g.solves(),0);
});
test('reference correction retains substantive uncertainty and produces an incomplete trajectory',async()=>{
  const bad=review(contract(),'uncertain');bad.targetIds.push('objective:total_cost');const f=setup({planner:n=>n===1?submit():n===2?reviewed(bad):reviewed(review(contract(),'uncertain'))});await f.run();assert.equal(f.requests(),3);assert.equal(f.solves(),0);assert.equal(f.answer.automation.stage,'paused');assert.equal(trajectoryState({conversation:{messages:[f.answer]}}),'partial');
});
test('v3 clarification uses explicit gap IDs rather than array order',async()=>{
  const c=contract();c.modelPurpose='final_task';c.bindings=c.facts.map(f=>({factIds:[f.id],targetRefs:['method:conditions'],disposition:'not_applicable',reason:'Known facts retained pending formulation'}));c.gaps=[{id:'g1',factId:'domain',kind:'quantity'},{id:'g2',factId:'demand',kind:'demand'}];c.bindings.push({factIds:['domain'],targetRefs:['gap:g1'],disposition:'pending_clarification',reason:''},{factIds:['demand'],targetRefs:['gap:g2'],disposition:'pending_clarification',reason:''});
  const qs=[{gapId:'g2',field:'Demand',question:'Demand?',impact:'Defines constraint'},{gapId:'g1',field:'Quantity',question:'Quantity?',impact:'Defines bound'}];const f=setup({planner:()=>submit(c,null,'clarify',qs)});await f.run();assert.deepEqual(f.answer.automation.questions.map(q=>q.gapId),['g2','g1']);assert.equal(f.solves(),0);assert.equal(f.answer.automation.taskOutcome,'awaiting_answer');
});
test('missing gap cannot disappear on a follow-up without an anchored replacement fact',async()=>{
  const f=setup({correction:false});f.answer.automation.task.contract={...contract(),gaps:[{id:'old-gap',factId:'domain',kind:'quantity',status:'asked',questionId:'q1'}]};await assert.rejects(f.run(),/GAP_RESOLUTION_REQUIRED/);assert.equal(f.solves(),0);
});
test('budget evidence resolution records provenance and reuses no calls',async()=>{
  const f=setup({base:true});await f.run();assert.equal(f.answer.automation.stage,'clarification');f.options.messages.push({id:'reply',role:'user',content:'5'});f.options.problem='5';await f.run();assert.equal(f.requests(),2);assert.equal(f.solves(),1);assert.equal(f.answer.automation.contract.gaps[0].resolution.kind,'budget_reply');assert.equal(f.answer.automation.contract.gaps[0].resolution.sourceMessageId,'reply');
});
test('stale sources require fresh modeling and review before any mathematical evidence reuse',async()=>{
  const f=setup({base:true,correction:false});await f.run();f.options.messages=[{...original,content:original.content+' New fact.'},{id:'reply',role:'user',content:'5'}];f.options.problem='5';await f.run();assert.equal(f.requests(),4);assert.equal(f.answer.automation.resultContract.reuseReason,'same_mathematics_after_current_validation');assert.equal(f.answer.automation.stage,'clarification');
});
test('explicit budget currency must agree with the frozen unit before any numerical comparison',()=>{
  const pending={budget:{lower:5,upper:6,unit:'USD'}};
  for(const reply of ['预算为5元','预算为5人民币','budget: 5 CNY','budget: 5 RMB'])assert.equal(resolveBudgetReply(pending,reply).status,'unit_conflict',reply);
  for(const reply of ['5','预算为5美元','budget: 5 USD'])assert.deepEqual(resolveBudgetReply(pending,reply),{status:'amount',value:5});
  assert.equal(resolveBudgetReply({budget:{lower:5,upper:6,unit:'CNY'}},'预算为5美元').status,'unit_conflict');
  assert.deepEqual(resolveBudgetReply({budget:{lower:5,upper:6,unit:'人民币'}},'预算为5元'),{status:'amount',value:5});
  assert.equal(resolveBudgetReply({budget:{lower:5,upper:6,unit:'CAD'}},'budget: 5 dollars').status,'unit_conflict');
});
test('currency conflict pauses budget reuse without model calls and keeps the pending evidence',async()=>{
  const f=setup({base:true});await f.run();
  f.options.messages.push({id:'wrong-currency',role:'user',content:'预算为5元'});f.options.problem='预算为5元';await f.run();
  assert.equal(f.answer.automation.stage,'paused');assert.equal(f.answer.automation.decision.code,'budget_unit_conflict');assert.notEqual(f.answer.automation.resultContract.evidenceReused,true);assert.ok(f.answer.automation.task.pendingBudget);assert.equal(f.requests(),2);assert.equal(f.solves(),1);
});
test('attempt-level statistics retain failed and unfinished tasks and expose unknown grades',()=>{
  const runs=[{status:'complete',manualVerdict:'correct'},{status:'failed'},{status:'complete'},{status:'partial'},{status:'queued'},{status:'cancelled'}].map((r,i)=>({...r,id:String(i),preset:'full',baseId:'base'}));
  const s=summarizeRuns(runs).methods[0];assert.equal(s.attempted,4);assert.equal(s.failed,1);assert.equal(s.unscored,3);assert.equal(s.meanBaseTaskSuccessLower,.25);assert.equal(s.meanBaseTaskSuccessUpper,.5);assert.equal(s.meanBaseCorrectRate,1);
});
test('workbench persists partial state and blocks a positive label for unfinished task',async()=>{
  const dir=path.resolve('qa','protocol-partial-'+crypto.randomUUID());const service=new ExperimentService(dir,{runner:async()=>({status:'running',conversation:{messages:[{role:'assistant',automation:{stage:'paused',taskOutcome:'partial',task:{calls:2,solves:0,clarifications:0}}}]}})});
  const b=await service.create({cases:[{id:'a',prompt:'x'}],protocolCorrection:false});service.action(b.id,'start');while(service.working)await new Promise(r=>setTimeout(r,5));const run=service.batches.get(b.id).runs[0];assert.equal(run.status,'partial');assert.equal(run.score.taskOutcome,'partial');assert.throws(()=>service.evaluate(b.id,run.id,{verdict:'correct',note:'not allowed'}));assert.equal(service.summary(b.id).methods[0].attempted,1);assert.equal(service.view(b.id).frozen.protocolCorrection,false);await service.close();
});
test('old frozen tasks do not silently adopt a different protocol',()=>{
  const f=setup();f.answer.automation.task.frozen.methodVersion='0.7.0-research-1';assert.throws(()=>initializeMethods(f.answer.automation,f.options.config,'highs','full'),/旧协议/);
});
test('failed correction is reserved before dispatch and cannot be automatically repeated',async()=>{
  const broken=contract();broken.facts[0].sourceRefs=['bad'];const f=setup({planner:n=>{if(n===2)throw Error('connection lost during correction');return submit(broken);}});
  await assert.rejects(f.run());assert.equal(f.requests(),2);assert.equal(f.answer.automation.task.protocolCorrections,1);f.options.retry=true;await assert.rejects(f.run());assert.equal(f.requests(),3);assert.equal(f.answer.automation.task.protocolCorrections,1);
});
test('truncated provider responses never trigger an automatic paid correction',async()=>{
  const f=setup({planner:()=>({...submit(),truncated:true})});await assert.rejects(f.run());assert.equal(f.requests(),1);assert.equal(f.answer.automation.task.protocolCorrections||0,0);assert.equal(f.answer.automation.protocolError.code,'INCOMPLETE_SUBMISSION');
});
test('completed archives are not rewritten on restart; reruns get the current frozen protocol',async()=>{
  const dir=path.resolve('qa','protocol-archive-'+crypto.randomUUID()),service=new ExperimentService(dir,{runner:async()=>({status:'complete',mock:true})});
  const b=await service.create({cases:[{id:'x',prompt:'x'}],protocolCorrection:false});service.action(b.id,'start');while(service.working)await new Promise(r=>setTimeout(r,5));
  const file=path.join(dir,'experiments',b.id+'.json'),before=fs.readFileSync(file,'utf8');const reopened=new ExperimentService(dir,{runner:async()=>({status:'complete',mock:true})});assert.equal(fs.readFileSync(file,'utf8'),before);
  const stored=reopened.batches.get(b.id);stored.methodVersion='0.7.0-research-1';stored.frozen.methodVersion='0.7.0-research-1';delete stored.frozen.protocolCorrection;const next=await reopened.rerun(b.id,[stored.runs[0].id]);assert.equal(next.frozen.methodVersion,methodVersion);assert.equal(next.parentMethodVersion,'0.7.0-research-1');assert.equal(next.frozen.protocolCorrection,false);await service.close();await reopened.close();
});
test('recorded real responses reproduce all 11 historical failures without a provider or solver',()=>{
  const root='experiments/protocol-regression-20261013',manifest=JSON.parse(fs.readFileSync(root+'/manifest.json','utf8'));const hashes=()=>manifest.records.map(r=>crypto.createHash('sha256').update(fs.readFileSync(path.join(root,r.path))).digest('hex'));
  assert.deepEqual(hashes(),manifest.records.map(r=>r.sha256));const rows=[];
  for(const item of manifest.records.filter(r=>r.path.includes('/runs/'))){const r=JSON.parse(fs.readFileSync(path.join(root,item.path),'utf8')),messages=r.conversation.messages.filter(m=>m.role==='user');const a=old.parseSubmission(r.events[0].response,'deepseek','submit_optimization').value,m=JSON.parse(a.model_json),c=JSON.parse(a.contract_json);const row={id:r.id,caseId:r.caseId,historicalStatus:r.status};
    try{old.validateContract(c,messages,m);if(r.events[1]?.response)old.validateReview(JSON.parse(old.parseSubmission(r.events[1].response,'deepseek','review_optimization').value.review_json),c,messages,m);row.old='accepted';}catch(e){row.old=e.message;}
    try{const next=validateContract(c,messages,m);if(r.events[1]?.response){const checked=validateReview(JSON.parse(parseSubmission(r.events[1].response,'deepseek','review_optimization').value.review_json),next,messages,m);row.newReview=checked.status;row.normalizations=checked.normalizations;}row.new='accepted_protocol_only';}catch(e){row.new='requires_correction';row.issue=e.issue||{code:e.message};}
    rows.push(row);
  }
  const count=s=>rows.filter(r=>r.old===s).length;assert.equal(count('Unknown review coverage reference'),7);assert.equal(count('Invalid fact or original source reference'),3);assert.equal(count('Unknown model target'),1);assert.equal(count('accepted'),5);assert.deepEqual(hashes(),manifest.records.map(r=>r.sha256));
  fs.mkdirSync('qa',{recursive:true});fs.writeFileSync('qa/v071-recorded-replay.json',JSON.stringify({kind:'protocol_replay_not_new_model_experiment',providerCalls:0,solverCalls:0,oldFailures:11,rows},null,2));
});
