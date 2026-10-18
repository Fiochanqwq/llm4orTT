import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {executeOptimization} from '../server/optimization.mjs';
import {initializeMethods} from '../server/optimization-v07.mjs';
import {taskFor} from '../server/agent-policy.mjs';
import {SolverService} from '../server/solver.mjs';
import {compactCatalog,compileCompactContract,compactReviewVersion} from '../shared/compact-protocol.mjs';
import {resultContract,resultText,objectiveUnitFromContract} from '../shared/result-contract.mjs';
const f=JSON.parse(fs.readFileSync(new URL('./fixtures/clarification-v077.json',import.meta.url)));
const argsOf=r=>typeof r.calls?.[0]?.arguments==='string'?JSON.parse(r.calls[0].arguments):structuredClone(r.calls?.[0]?.arguments??JSON.parse(r.text));
const contractOf=a=>typeof a.contract_json==='string'?JSON.parse(a.contract_json):structuredClone(a.contract_json);
const initialArgs=argsOf(f.responses[0]);
const initial=()=>compileCompactContract(initialArgs.contract_json,f.messages.slice(0,1),null,{action:'clarify',candidateId:'original'}).contract;
const parsed=argsOf(f.responses[2]),math=JSON.parse(parsed.model_json);
function replacement(handle,{fresh=true}={}){
  const args=structuredClone(parsed),raw=contractOf(args);
  for(const r of raw.requirements)if(r.replaces?.length){r.replaces=[handle];if(!fresh)r.sources=r.sources.filter(s=>s!=='s14');}
  args.contract_json=raw;return args;
}
const response=args=>({calls:[{name:'submit_optimization',arguments:args}],usage:{input:1,output:1}});
const reviewed=()=>({calls:[{name:'review_optimization',arguments:{review_json:{format:compactReviewVersion,status:'no_issue_found',checks:{requirements:'checked',mathematics:'checked',amendments:'checked',budget:'not_applicable'},diagnostics:[],budgetApplicability:'not_applicable'}}}],usage:{input:1,output:1}});
async function exercise(planner,{solver,correction=true,markAnswered=false}={}){
  const config={id:'deepseek',model:'offline-fixture',language:'zh-CN',maxTokens:10000,modelingTokens:10000,protocolCorrection:correction};let calls=0,solves=0;
  const options={config,engine:'highs',seconds:15,planner:async(...args)=>planner(calls++,...args),solver:solver??{info:()=>({engines:{highs:{available:true}}}),start:()=>{solves++;throw Error('Unexpected solver');}},signal:new AbortController().signal,update:()=>{}};
  let answer={content:'',provenance:{},automation:{task:taskFor({messages:[]},f.messages[0],false),usage:{}}};initializeMethods(answer.automation,config,'highs','full');
  await executeOptimization({...options,answer,messages:f.messages.slice(0,1),problem:f.messages[0].content});assert.equal(answer.automation.stage,'clarification');
  const previous=structuredClone(answer.automation.task);
  if(markAnswered)previous.questions.forEach(q=>q.status='answered');
  answer={content:'',provenance:{},automation:{task:previous,usage:{}}};initializeMethods(answer.automation,config,'highs','full');
  let error;try{await executeOptimization({...options,answer,messages:f.messages,problem:f.messages[1].content});}catch(e){error=e;}
  return {answer,error,calls,solves};
}
test('pending-gap catalog exposes legal fact handles and genuinely newer source candidates',()=>{
  const before=initial(),catalog=compactCatalog(f.messages,before),gap=catalog.pendingGaps[0];
  assert.equal(gap.previousFact,'p6');assert.equal(gap.description,'B 对任务2的资格状态未确定');assert.deepEqual(gap.newUserSources,['s14']);
  assert.equal(catalog.previousFacts[5].statement,gap.description);assert.ok(!JSON.stringify(catalog).includes(before.gaps[0].id));
  assert.deepEqual(compactCatalog(f.messages.slice(0,1),before).pendingGaps[0].newUserSources,[]);
  const shifted=structuredClone(before);shifted.facts.unshift({...shifted.facts[0],id:'another-active-fact'});
  assert.equal(compactCatalog(f.messages,shifted).pendingGaps[0].previousFact,'p7');
  const result=compileCompactContract(replacement('p7').contract_json,f.messages,math,{previous:shifted,action:'solve'}).contract;
  assert.ok(result.facts.find(x=>x.id===before.gaps[0].factId&&x.status==='superseded'));
});
test('legal p6 replacement requires new source evidence; gap IDs and unknown handles stay invalid',()=>{
  const previous=initial();const c=compileCompactContract(replacement('p6').contract_json,f.messages,math,{previous,action:'solve'}).contract;
  assert.equal(c.gaps.length,0);assert.equal(c.facts.find(x=>x.id===previous.gaps[0].factId).status,'superseded');
  for(const h of ['c1r1-g1',previous.gaps[0].id,previous.gaps[0].factId,'p999','s14'])assert.throws(()=>compileCompactContract(replacement(h).contract_json,f.messages,math,{previous,action:'solve'}),/UNKNOWN_REFERENCE/);
  assert.throws(()=>compileCompactContract(replacement('p6',{fresh:false}).contract_json,f.messages,math,{previous,action:'solve'}),/INVALID_SUPERSESSION/);
});
test('original bad correction still fails rather than accepting internal IDs as aliases',async()=>{
  const h=await exercise(n=>structuredClone(f.responses[n]));
  assert.equal(h.answer.automation.failure.code,'UNKNOWN_REFERENCE');assert.equal(h.calls,3);assert.equal(h.solves,0);
  const missing=h.answer.automation.protocolIssues.find(x=>x.code==='GAP_RESOLUTION_REQUIRED');
  assert.equal(JSON.parse(missing.received).previousFact,'p6');assert.ok(!missing.received.includes('c1r1-g1'));
});
test('unresolved gaps remain rejected even when the UI question was marked answered',async()=>{
  const h=await exercise(n=>structuredClone(f.responses[n]),{correction:false,markAnswered:true});
  assert.equal(h.answer.automation.failure.code,'GAP_RESOLUTION_REQUIRED');assert.equal(h.calls,2);assert.equal(h.solves,0);
});
test('saved two-turn trajectory completes using explicit correction, semantic review and real HiGHS within four calls',async t=>{
  const solver=new SolverService(path.resolve('qa','clarification-v077-'+Date.now()));t.after(()=>solver.close());
  let seen;const before=JSON.stringify(f);
  const h=await exercise((n,config,input)=>{
    if(n<2)return structuredClone(f.responses[n]);
    if(n===2){
      seen=JSON.parse(input[0].content);const gap=seen.context.pendingGaps[0];
      assert.equal(JSON.parse(seen.issue.received).previousFact,gap.previousFact);
      assert.deepEqual(seen.compactProtocol.pendingGaps,seen.context.pendingGaps);
      assert.deepEqual(gap.newUserSources,['s14']);assert.ok(!input[0].content.includes('c1r1-g1'));
      return response(replacement(gap.previousFact));
    }
    assert.equal(config.tool.name,'review_optimization');return reviewed();
  },{solver});
  assert.ifError(h.error);assert.equal(h.answer.automation.stage,'complete',JSON.stringify(h.answer.automation.programmaticEvidence));assert.equal(h.answer.automation.task.protocolCorrections,1);
  assert.equal(h.calls,4);assert.equal(h.answer.automation.task.solves,1);assert.equal(h.answer.automation.publicOutcome.objective,15);
  assert.equal(h.answer.automation.methods.semanticReview,'executed');assert.equal(h.answer.automation.resultContract.solverInvoked,true);
  assert.ok(h.answer.automation.gapResolutions[0].sourceMessageId===f.messages[1].id);
  assert.equal(JSON.stringify(f),before);assert.match(h.answer.content,/15 元/);
});
test('objective display removes tiny float tails while keeping raw values and explicit approximation',()=>{
  const value=143.99999999999997,model={variables:[{name:'x',type:'continuous',lower:0,upper:null}],objective:{x:1},constraints:[]};
  const result=resultContract({id:'round',model,values:{x:value},objective:value,status:'optimal',provenance:{solverInvoked:true}},{objectiveUnit:'元'});
  assert.equal(result.objective,value);assert.equal(result.objectiveRecomputed,value);assert.equal(result.displayObjective,144);assert.equal(result.displayObjectiveApproximate,true);
  assert.match(resultText(result),/≈ 144 元/);assert.match(resultText(result),/原始求解值/);
  const large=resultContract({model,values:{x:123456789.12345678},objective:123456789.12345678,status:'optimal',provenance:{solverInvoked:true}});
  assert.equal(large.displayObjective,large.objectiveRecomputed,'do not round materially different values');
});
test('objective unit uses only unique source-grounded objective facts; absent or conflicting units stay unknown',()=>{
  const fact=(id,unit,sourceSpan)=>({id,unit,sourceSpan,status:'active'}),bind=id=>({factIds:[id],targetRefs:['objective:$'],disposition:'encoded'});
  assert.equal(objectiveUnitFromContract({facts:[fact('f','元','费用（元）')],bindings:[bind('f')]}),'元');
  assert.equal(objectiveUnitFromContract({facts:[fact('f','USD','费用（元）')],bindings:[bind('f')]}),null);
  assert.equal(objectiveUnitFromContract({facts:[fact('f','元','元'),fact('g','USD','USD')],bindings:[bind('f'),bind('g')]}),null);
});
test('infeasible delivery explains only checkable submitted-model conflicts',()=>{
  const model={variables:[{name:'A',type:'integer',lower:0,upper:1},{name:'B',type:'integer',lower:0,upper:1}],objective:{A:1},constraints:[{name:'afternoon',terms:{A:1,B:1},sense:'>=',rhs:3}]};
  const r=resultContract({model,status:'infeasible',provenance:{solverInvoked:true}}),text=resultText(r);
  assert.match(text,/afternoon/);assert.match(text,/\[0, 2\]/);assert.match(text,/>= 3/);assert.match(text,/当前模型/);
  const opaque=resultContract({model:{...model,constraints:[]},status:'infeasible',provenance:{solverInvoked:true}});
  assert.equal(opaque.conflictEvidence,null);assert.match(resultText(opaque),/未提取到具体冲突证据/);
});
