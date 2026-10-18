import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { numericalCheck,resultContract } from '../shared/result-contract.mjs';
import { exactCertificate } from '../shared/exact-certificate.mjs';
import { validateContract,targetKeys } from '../shared/task-contract.mjs';
import { budgetDecision } from '../server/budget-relevance.mjs';
import { executeV07,initializeMethods,validateReply } from '../server/optimization-v07.mjs';
import { agentLimits,taskFor } from '../server/agent-policy.mjs';
import { SolverService } from '../server/solver.mjs';
import { ExperimentService,parseCases,controllerReply } from '../server/experiments.mjs';
import { ExportService,conversationExport,readStoredZip } from '../server/exports.mjs';
import { Writable } from 'node:stream';
import { compactPlan } from '../scripts/fixtures/compact-v074.mjs';
const directory=()=>path.resolve('qa','research-'+crypto.randomUUID());
const model={format:'llm4orovo.lp.v1',name:'Fertilizer',sense:'minimize',variables:[{name:'C',type:'continuous',lower:0,upper:null},{name:'Y',type:'continuous',lower:0,upper:null}],objective:{C:2,Y:3},constraints:[{name:'nitrogen',terms:{C:1.5,Y:5},sense:'>=',rhs:5},{name:'vitamins',terms:{C:3,Y:1},sense:'>=',rhs:8}]};
const values={C:70/27,Y:2/9};
const record=()=>({id:'real-fixture',model,values,objective:158/27,bound:158/27,status:'optimal',provenance:{solverInvoked:true},check:numericalCheck(model,values)});
const message={id:'source-1',role:'user',content:'Minimize fertilizer cost, known coefficients, nonnegative real quantities. Fixed budget in [5,6].'};
function contract(base=false){return {format:'llm4orovo.submission.v2',modelPurpose:base?'budget_threshold_base':'final_task',facts:[{id:'f1',kind:'requirements',sourceMessageId:message.id,sourceSpan:message.content,entityRefs:[],unit:'USD',value:null,status:'active',supersedes:[]},...(base?[{id:'budget',kind:'budget',sourceMessageId:message.id,sourceSpan:'Fixed budget in [5,6].',entityRefs:[],unit:'USD',value:null,status:'unresolved',supersedes:[]}]:[])],bindings:[...['variable','objective','constraint'].map(targetKind=>({factIds:['f1'],targetKind,targetIds:targetKind==='constraint'?model.constraints.map(c=>c.name):['C','Y'],disposition:'encoded'})),...(base?[{factIds:['budget'],targetKind:'gap',targetIds:['g1'],disposition:'deferred_to_budget_gate'}]:[])],gaps:base?[{id:'g1',factId:'budget',kind:'budget',status:'open',questionId:null}]:[],budget:base?{factId:'budget',gapId:'g1',lower:5,upper:6,unit:'USD',costTerms:model.objective,confirmedFixed:true,onlyCostCap:true,otherConditionsComplete:true}:null};}
const plan=c=>({calls:[{name:'submit_optimization',arguments:{action:'solve',model_json:JSON.stringify(model),contract_json:JSON.stringify(c),message:'Model fixture',questions:[]}}],usage:{input:12,output:20},truncated:false});
function reviewed(c,status='no_issue_found'){return {calls:[{name:'review_optimization',arguments:{review_json:JSON.stringify({status,diagnostics:status==='mismatch'?[{code:'unit',factIds:['f1'],targetIds:['objective:C'],sourceMessageId:message.id,sourceSpan:'known coefficients',evidence:'Fixture anchored mismatch',repairable:true}]:[],factIds:c.facts.map(f=>f.id),targetIds:targetKeys(model),budgetApplicability:c.budget?'supported':'not_applicable'})}}],usage:{input:9,output:10}};}
// Preserve coverage of the frozen pre-evidence policy; evidence has dedicated real-worker tests.
async function setup({preset='no_evidence',base=false,planner,real=false,protocolCorrection=false}={}){
  const config={id:'openai',model:'mock',maxTokens:12000,modelingTokens:12000,language:'en',protocolCorrection},messages=[message],task=taskFor({messages:[]},message,false),answer={content:'',provenance:{},automation:{task,usage:{}}};initializeMethods(answer.automation,config,'highs',preset);
  const saved=new Map();const solver=real?new SolverService(directory()):{active:null,info:()=>({engines:{highs:{available:true}}}),start:()=>{const r=record();saved.set(r.id,r);return r;},get:id=>saved.get(id),stop:()=>{}};
  let calls=0;const options={config,messages,problem:message.content,engine:'highs',seconds:30,signal:new AbortController().signal,answer,update:()=>{},solver,planner:async(...args)=>{calls++;return planner?planner(calls,...args):calls%2===1?plan(contract(base)):reviewed(contract(base));}};
  return {options,answer,solver,calls:()=>calls,run:()=>executeV07(options)};
}
test('display rounding is checked, objective is independently recomputed, no fake invocation',()=>{
  assert.equal(numericalCheck(model,{C:2.593,Y:.222}).feasible,false);
  const r=resultContract(record());assert.equal(r.displayValidation.feasible,true);assert.equal(r.objectiveMatches,true);
  assert.equal(resultContract({...record(),objective:999}).objectiveMatches,false);
  assert.equal(resultContract({...record(),provenance:{solverInvoked:false}}).taskOutcome,'partial');
});
test('exact primal/dual certificate handles equality and interval boundaries',()=>{
  const r=record(),cert=exactCertificate(model,values);assert.equal(cert.objective,'158/27');assert.equal(cert.values.C,'70/27');
  assert.equal(budgetDecision(r,{lower:6,upper:7}).status,'all_feasible');assert.equal(budgetDecision(r,{lower:4,upper:5}).status,'all_infeasible');assert.equal(budgetDecision(r,{lower:5,upper:6}).status,'needs_clarification');
  const simple={...model,variables:[model.variables[0]],objective:{C:2},constraints:[{name:'min',terms:{C:1},sense:'>=',rhs:3}]},rr={...r,model:simple,values:{C:3},objective:6,bound:6,check:numericalCheck(simple,{C:3})};
  assert.equal(budgetDecision(rr,{lower:6,upper:7}).status,'all_feasible');assert.equal(budgetDecision(rr,{lower:5,upper:6}).status,'needs_clarification');
  assert.equal(exactCertificate({...simple,variables:[{...simple.variables[0],type:'integer'}]},{C:3}),null);
});
test('source anchors and two-way coverage reject unsupported omissions',()=>{
  assert.ok(validateContract(contract(),[message],model));let c=contract();c.facts[0].sourceSpan='invented';assert.throws(()=>validateContract(c,[message],model));c=contract();c.bindings.pop();assert.throws(()=>validateContract(c,[message],model));
  c=contract(true);c.budget.costTerms={C:3,Y:3};assert.throws(()=>validateContract(c,[message],model));assert.throws(()=>validateContract(contract(true),[message],model,{budgetEnabled:false}));
});
test('full method calls modeling and review once then delivers locally',async()=>{const f=await setup();await f.run();assert.equal(f.calls(),2);assert.equal(f.answer.automation.stage,'complete');assert.equal(f.answer.automation.resultContract.displayValidation.feasible,true);assert.equal(f.answer.automation.task.solves,1);assert.equal(f.answer.automation.task.clarifications,0);await f.run();assert.equal(f.calls(),2);assert.equal(f.answer.automation.decision.code,'no_new_information');});
test('one anchored repair + rereview use exactly four calls; remaining mismatch stops',async()=>{const f=await setup({planner:(n)=>n%2?plan(contract()):reviewed(contract(),'mismatch')});await f.run();assert.equal(f.calls(),4);assert.equal(f.answer.automation.task.solves,0);assert.equal(f.answer.automation.methods.repairStatus,'executed');assert.equal(f.answer.automation.decision.code,'semantic_unresolved');});
test('invalid tool submission consumes a request but no clarification; explicit retry preserves budget',async()=>{const f=await setup({planner:n=>n===1?{calls:[],text:'I solved it'}:n===2?plan(contract()):reviewed(contract())});await assert.rejects(f.run());assert.equal(f.answer.automation.task.calls,1);assert.equal(f.answer.automation.task.clarifications,0);f.options.retry=true;await f.run();assert.equal(f.calls(),3);assert.equal(f.answer.automation.resultContract.taskOutcome,'complete');});
test('budget answer reuses verified base evidence with zero additional calls or solves',async()=>{const f=await setup({base:true});await f.run();const flow=f.answer.automation;assert.equal(flow.stage,'clarification');assert.equal(flow.resultContract.taskOutcome,'awaiting_answer');assert.equal(flow.contract.gaps[0].status,'asked');const q=flow.questions[0];assert.ok(validateReply(flow.task,{taskId:flow.task.id,questionId:q.id,gapId:q.gapId,factVersion:flow.task.factVersion}));assert.throws(()=>validateReply(flow.task,{taskId:'old'}));f.options.problem='5';f.options.messages.push({id:'reply-1',role:'user',content:'5'});await f.run();assert.equal(flow.resultContract.budgetDecision,'all_infeasible');assert.equal(flow.resultContract.evidenceReused,true);assert.equal(f.calls(),2);assert.equal(flow.task.solves,1);});
test('actual bundled solver feeds the v0.7 delivery contract',async t=>{const f=await setup({real:true});t.after(()=>f.solver.close());await f.run();assert.equal(f.answer.automation.result.status,'optimal');assert.equal(f.answer.automation.resultContract.objectiveMatches,true);assert.equal(f.answer.automation.resultContract.displayValidation.feasible,true);});
test('existing 16 public questions import without private cards entering prompts',()=>{const publicCases=JSON.parse(fs.readFileSync('experiments/budget-boundary-20261011/questions.public.json','utf8')),cards=JSON.parse(fs.readFileSync('experiments/budget-boundary-20261011/answers.private.json','utf8'));const rows=parseCases(publicCases,cards);assert.equal(rows.length,16);assert.equal(rows[2].prompt,rows[3].prompt);assert.notEqual(rows[2].privateCard.hidden_fixed_budget,rows[3].privateCard.hidden_fixed_budget);assert.equal(controllerReply({stage:'clarification',questions:[{field:'unknown resource'}],task:{}},cards[2]),null);});
test('1000 mock trajectories persist independently; failures survive; no private data sent to runner',async()=>{
  const dir=directory();let count=0;const service=new ExperimentService(dir,{runner:async input=>{assert.ok(!JSON.stringify(input).includes('private_marker'));count++;if(count%100===0)throw Error('injected');return {status:'complete',mock:true};}});
  const b=await service.create({cases:[{id:'dev',prompt:'public-only',privateCard:{note:'private_marker'}}],presets:['legacy','delivery','structure','semantic','budget','audit','full','native_api'],repeats:100,requestCap:10});
  const b2=await service.create({cases:[{id:'dev2',prompt:'public-only'}],presets:['structure','full'],repeats:100,requestCap:10});
  service.action(b.id,'start');service.action(b2.id,'start');while(service.working)await new Promise(r=>setTimeout(r,10));if(service.storageError)throw service.storageError;assert.equal(count,1000);
  assert.equal(service.list().reduce((n,b)=>n+b.failed,0),10);assert.equal(fs.readdirSync(path.join(dir,'experiments/runs')).length,1000);
  const reopened=new ExperimentService(dir,{runner:async()=>{throw Error('must not rerun');}});assert.equal(reopened.list().reduce((n,b)=>n+b.completed,0),990);
  fs.writeFileSync(path.join(dir,'mock-report.json'),JSON.stringify({trajectories:count,completed:990,injectedFailures:10,providerCalls:0,purpose:'infrastructure_only'}));
});
test('streamed archive snapshot round-trips and rejects hash/path tampering',async()=>{
  const dir=directory(),service=new ExperimentService(dir,{runner:async()=>({status:'complete'})});const b=await service.create({cases:[{id:'one',prompt:'visible',privateCard:{hidden_fixed_budget:320}}]});service.action(b.id,'start');while(service.working)await new Promise(r=>setTimeout(r,5));
  const exports=new ExportService(dir,{data:{conversations:[]}},{get:()=>null},service);const result=exports.create({batchIds:[b.id],format:'json'});assert.equal(result.manifest.privateIncluded,false);
  const ticket=exports.tickets.get(result.url.split('/').at(-1));const bundle={format:'llm4orovo.bundle.v2',schemaVersion:2,entries:ticket.entries.map(e=>({name:e.name,data:JSON.parse(fs.readFileSync(e.path,'utf8'))}))};
  assert.ok(!JSON.stringify(bundle).includes('hidden_fixed_budget'));assert.equal(exports.import(bundle).status,'historical_only');const altered=structuredClone(bundle);altered.entries[1].data.title='tamper';assert.throws(()=>exports.import(altered));altered.entries[1].name='../outside';assert.throws(()=>exports.import(altered));
  const archive=exports.create({batchIds:[b.id],format:'zip'}),chunks=[];const output=new Writable({write(chunk,_encoding,callback){chunks.push(chunk);callback();}});output.writeHead=()=>{};const finished=new Promise(resolve=>output.on('finish',resolve));exports.download(archive.url.split('/').at(-1),output);await finished;assert.equal(exports.import(readStoredZip(Buffer.concat(chunks))).status,'historical_only');assert.throws(()=>readStoredZip(Buffer.from('bad archive')));
});
test('pause completes current mock trajectory; restart does not replay sent-unknown attempts',async()=>{
  const dir=directory();let release,entered;const ready=new Promise(r=>entered=r),gate=new Promise(r=>release=r);let count=0;
  const service=new ExperimentService(dir,{runner:async()=>{count++;entered();await gate;return {status:'complete'};}});const b=await service.create({cases:[{id:'one',prompt:'one'},{id:'two',prompt:'two'}]});service.action(b.id,'start');await ready;service.action(b.id,'pause');release();while(service.working)await new Promise(r=>setTimeout(r,5));assert.equal(count,1);assert.equal(service.batches.get(b.id).runs.filter(r=>r.status==='queued').length,1);
  const saved=service.batches.get(b.id),pending=saved.runs.find(r=>r.status==='queued');pending.status='running';saved.status='running';service.saveRun({id:pending.id,status:'running',events:[{state:'sent'}],conversation:{messages:[{status:'streaming'}]}});service.save(saved);
  const restored=new ExperimentService(dir,{runner:async()=>{throw Error('unwanted replay');}});assert.equal(restored.batches.get(b.id).status,'paused');assert.equal(restored.run(pending.id).status,'interrupted_unknown');assert.equal(restored.run(pending.id).events[0].state,'interrupted_unknown');restored.action(b.id,'resume');await restored.close();assert.equal(count,1);
});
test('experiment controller releases only authorized budget answer and preserves same trajectory',async()=>{
  const dir=directory(),saved=new Map();const solver={active:null,info:()=>({engines:{highs:{available:true}}}),start:()=>{const r=record();saved.set(r.id,r);return r;},get:id=>saved.get(id),stop:()=>{}};
  let requests=0;const service=new ExperimentService(dir,{store:{credentials:async()=>({id:'openai',model:'fixture',maxTokens:12000,modelingTokens:12000,language:'en',apiKey:'DO_NOT_SAVE_KEY'})},solver,
    planner:async(_config,input)=>{requests++;assert.ok(!JSON.stringify(input).includes('private_marker'));return compactPlan(input[0].content);},generator:async function*(){throw Error('unneeded explanation');}});
  const b=await service.create({cases:[{id:'B3',prompt:message.content,privateCard:{hidden_fixed_budget:5,unit:'USD',note:'private_marker'}}],presets:['budget'],provider:'openai',language:'en'});service.action(b.id,'start');while(service.working)await new Promise(r=>setTimeout(r,5));const meta=service.batches.get(b.id).runs[0],run=service.run(meta.id);
  assert.equal(meta.status,'complete');assert.equal(requests,1);assert.equal(run.conversation.messages.length,4);assert.match(run.conversation.messages[2].content,/5 USD/);assert.equal(run.conversation.messages[3].automation.resultContract.budgetDecision,'all_infeasible');assert.ok(!JSON.stringify(run).includes('DO_NOT_SAVE_KEY'));
});
