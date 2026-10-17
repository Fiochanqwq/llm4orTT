import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {executeOptimization} from '../server/optimization.mjs';
import {initializeMethods} from '../server/optimization-v07.mjs';
import {taskFor} from '../server/agent-policy.mjs';
import {compileCompactContract,compileCompactReview,compactVersion,compactReviewVersion,readCompactObject,compactCorrectionHints} from '../shared/compact-protocol.mjs';
const fixtures=JSON.parse(fs.readFileSync(new URL('./fixtures/robustness-v076.json',import.meta.url))).cases;
const submission=args=>({calls:[{name:'submit_optimization',arguments:args}],usage:{input:1,output:1}});
const sample=fixtures.find(f=>f.caseId==='ga-08'&&f.preset==='full');
const argsOf=response=>typeof response.calls[0].arguments==='string'?JSON.parse(response.calls[0].arguments):structuredClone(response.calls[0].arguments);
function harness(fixture,planner,{correction=true,solver}={}){
  const config={id:'deepseek',model:'offline-fixture',language:'zh-CN',maxTokens:10000,modelingTokens:10000,protocolCorrection:correction};
  const answer={content:'',provenance:{},automation:{task:taskFor({messages:[]},fixture.messages[0],false),usage:{}}};
  initializeMethods(answer.automation,config,'highs',fixture.preset);
  let calls=0,solves=0;
  const options={config,messages:structuredClone(fixture.messages),problem:fixture.messages[0].content,engine:'highs',seconds:30,
    planner:async(...args)=>planner(calls++,...args),solver:solver??{info:()=>({engines:{highs:{available:true}}}),start:()=>{solves++;throw Error('Unexpected solver call');}},
    signal:new AbortController().signal,answer,update:()=>{}};
  return {answer,options,run:()=>executeOptimization(options),calls:()=>calls,solves:()=>solves};
}
for(const fixture of fixtures.filter(f=>['ga-02','ga-04','ga-08'].includes(f.caseId))){
  test(`saved ${fixture.caseId}/${fixture.preset} reaches clarification without losing original questions`,async()=>{
    const before=JSON.stringify(fixture),h=harness(fixture,n=>structuredClone(fixture.responses[n]));
    await h.run();
    assert.equal(h.answer.automation.stage,'clarification');assert.equal(h.solves(),0);
    assert.equal(h.calls(),fixture.preset==='generic'?2:1);
    assert.equal(h.answer.automation.questions.length,1);assert.equal(h.answer.automation.publicOutcome.complete,false);
    assert.equal(JSON.stringify(fixture),before,'normalization must not rewrite saved responses');
    assert.deepEqual(h.answer.automation.entities,[]);
    if(fixture.preset==='full')assert.deepEqual(h.answer.automation.contract.coverage.encodedTargets,[]);
  });
}
test('clarification ignores a supplied draft model without executing or dropping it from diagnostics',async()=>{
  const fixture=fixtures.find(f=>f.caseId==='ga-04'),response=structuredClone(fixture.responses[1]);
  const h=harness(fixture,()=>response);await h.run();
  assert.equal(h.answer.automation.stage,'clarification');assert.equal(h.solves(),0);
  assert.ok(h.answer.automation.normalizations.some(n=>n.rule==='unexecuted_clarification_model'&&n.model_json));
  assert.ok(h.answer.automation.pendingEntities.length);
});
test('conflicting envelope questions are still rejected instead of silently discarded',async()=>{
  const args=argsOf(sample.responses[1]);args.questions[0].question='Can the worker capacity be relaxed?';
  const h=harness(sample,()=>submission(args),{correction:false});await assert.rejects(h.run());
  assert.equal(h.answer.automation.failure.code,'CONFLICTING_QUESTIONS');assert.equal(h.solves(),0);
});
test('clarification does not bypass source validation for facts or pending entities',async()=>{
  for(const kind of ['fact','entity']){
    const args=argsOf(sample.responses[1]);
    if(kind==='fact'){const raw=JSON.parse(args.contract_json);raw.requirements[0].sources=['s999'];args.contract_json=raw;}
    else args.entities=[{variable:'x',label:'Worker',unit:'',sources:['s999']}];
    const h=harness(sample,()=>submission(args),{correction:false});await assert.rejects(h.run());
    assert.equal(h.answer.automation.failure.code,'UNKNOWN_REFERENCE');assert.equal(h.solves(),0);
  }
});
test('a missing root delimiter and omitted optional declarations recover without changing mathematics',()=>{
  const f=fixtures.find(f=>f.caseId==='ga-03'),args=argsOf(f.responses[0]),model=JSON.parse(args.model_json),before=JSON.stringify(model);
  const {contract}=compileCompactContract(args.contract_json,f.messages,model,{action:'solve'});
  assert.ok(contract.normalizations.some(n=>n.rule==='closed_contract_root'));
  assert.ok(contract.normalizations.some(n=>n.rule==='optional_contract_defaults'));
  assert.deepEqual(contract.gaps,[]);assert.equal(contract.budget,null);assert.equal(JSON.stringify(model),before);
});
test('narrow JSON recovery refuses broken strings, numbers, missing list delimiters and wrong brackets',()=>{
  for(const raw of ['{"requirements":[{"statement":"unfinished','{"requirements":[','{"requirements":[]]','{"requirements":[],"number":1e','{"requirements":[],']){
    assert.throws(()=>readCompactObject(raw,'$.contract_json',{closeRoot:true}),/INVALID_JSON/);
  }
});
test('clarify still needs explicit gaps; omitted missing cannot erase previous unanswered facts',async()=>{
  const args=argsOf(sample.responses[1]);args.contract_json={format:compactVersion,requirements:[]};args.questions=[];
  const h=harness(sample,()=>submission(args),{correction:false});await assert.rejects(h.run());
  assert.equal(h.answer.automation.failure.code,'CLARIFICATION_GAP_REQUIRED');
  const next=harness(sample,()=>structuredClone(sample.responses[1]),{correction:false});await next.run();
  next.options.messages.push({id:'followup',role:'user',content:'Please continue.'});next.options.problem='Please continue.';
  next.options.planner=async()=>submission({action:'solve',model_json:JSON.stringify(simpleModel),message:'Candidate',questions:[],contract_json:simpleContract});
  await assert.rejects(next.run());assert.equal(next.answer.automation.failure.code,'GAP_RESOLUTION_REQUIRED');assert.equal(next.solves(),0);
});
test('saved group-variable reference expands only to actual candidate variables',()=>{
  const f=fixtures.find(f=>f.caseId==='ga-07'),args=argsOf(f.responses[0]),model=JSON.parse(args.model_json);
  const {contract}=compileCompactContract(args.contract_json,f.messages,model,{action:'solve'});
  const n=contract.normalizations.find(n=>n.rule==='all_candidate_variables');assert.equal(n.targets.length,9);
  assert.deepEqual(n.targets,model.variables.map(v=>'variable:'+v.name));
});
test('coverage repair receives all uncovered targets, and incomplete mathematical bindings still fail',async()=>{
  const f=structuredClone(fixtures.find(f=>f.caseId==='ga-07'));let checked=false;
  const args=argsOf(f.responses[0]),raw=JSON.parse(args.contract_json);
  for(const r of raw.requirements)for(const t of r.targets)if(t.kind==='variable')t.name='ghost';
  args.contract_json=raw;f.responses[0]=submission(args);
  const h=harness(f,(n,config,input)=>{
    if(n===1){const d=JSON.parse(input[0].content).compactProtocol;assert.ok(d.invalidLocations.length);assert.equal(d.uncoveredTargets.filter(x=>x.startsWith('variable:')).length,9);assert.ok(d.locations.some(x=>x.kind==='objective'&&!x.name));checked=true;}
    return structuredClone(f.responses[n]);
  });
  await assert.rejects(h.run());assert.equal(checked,true);assert.equal(h.answer.automation.failure.code,'MODEL_COVERAGE');assert.equal(h.calls(),2);assert.equal(h.solves(),0);
});
const simpleModel={format:'llm4orovo.lp.v1',name:'one',sense:'minimize',variables:[{name:'x',type:'continuous',lower:0,upper:null}],objective:{x:1},constraints:[{name:'demand',terms:{x:1},sense:'>=',rhs:3}]};
const simpleContract={format:compactVersion,requirements:[{statement:'Nonnegative x >= 3, minimize x',sources:['s1'],targets:[{kind:'variable',name:'x'},{kind:'objective'},{kind:'constraint',name:'demand'}]}]};
const review={format:compactReviewVersion,status:'no_issue_found',checks:{requirements:'checked',mathematics:'checked',amendments:'not_applicable',budget:'not_applicable'},diagnostics:[],budgetApplicability:'not_applicable'};
test('object contract and review envelopes still pass semantic review before solver execution',async()=>{
  const fixture={preset:'full',messages:[{id:'u1',role:'user',content:'Nonnegative x >= 3, minimize x.'}]};let reviewed=false,solved=false;
  const solver={info:()=>({engines:{highs:{available:true}}}),get:()=>null,start:({model})=>{assert.equal(reviewed,true);solved=true;return {id:'offline-solver',model,status:'optimal',values:{x:3},objective:3,provenance:{solverInvoked:true}};}};
  const h=harness(fixture,(n,config)=>{if(n===0)return submission({action:'solve',model_json:JSON.stringify(simpleModel),message:'Candidate',questions:[],contract_json:simpleContract});assert.equal(config.tool.name,'review_optimization');reviewed=true;return {calls:[{name:'review_optimization',arguments:{review_json:review}}]};},{solver});
  await h.run();assert.equal(solved,true);assert.equal(h.answer.automation.methods.semanticReview,'executed');assert.equal(h.calls(),2);
});
test('solve cannot defer invalid mathematical references or unknown entities like clarification',async()=>{
  const fixture={preset:'full',messages:[{id:'u1',role:'user',content:'Nonnegative x >= 3, minimize x.'}]};
  for(const bad of ['reference','entity']){
    const c=structuredClone(simpleContract);if(bad==='reference')c.requirements[0].targets.push({kind:'variable',name:'ghost'});
    const h=harness(fixture,()=>submission({action:'solve',model_json:JSON.stringify(simpleModel),message:'Candidate',questions:[],contract_json:c,...(bad==='entity'?{entities:[{variable:'ghost',label:'Unknown',unit:'',sources:['s1']}]}:{})}),{correction:false});
    await assert.rejects(h.run());assert.equal(h.answer.automation.failure.code,bad==='reference'?'UNKNOWN_REFERENCE':'ENTITY_REFERENCE');assert.equal(h.solves(),0);
  }
});
test('object reviews do not lose mandatory diagnostics or manufacture certainty',()=>{
  const messages=[{id:'u1',role:'user',content:'Nonnegative x >= 3, minimize x.'}],c=compileCompactContract(simpleContract,messages,simpleModel).contract;
  assert.equal(compileCompactReview({...review,checks:{...review.checks,requirements:'not_checked'}},c,messages,simpleModel).status,'uncertain');
  const invalid={...review};delete invalid.diagnostics;assert.throws(()=>compileCompactReview(invalid,c,messages,simpleModel));
});
