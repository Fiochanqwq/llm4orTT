import test from 'node:test';
import assert from 'node:assert/strict';
import { executeOptimization } from '../server/optimization.mjs';
import { initializeMethods } from '../server/optimization-v07.mjs';
import { taskFor } from '../server/agent-policy.mjs';
import { decisionMetrics } from '../server/decision-metrics.mjs';
import { compactPlan, compactReviewed } from '../scripts/fixtures/compact-v074.mjs';
import { buildEvidenceCases, referenceOptimum } from '../scripts/fixtures/evidence-benchmark.mjs';

function fixture(audit, { programmaticEvidence, numericalError=false } = {}) {
  const c=buildEvidenceCases().find(c=>c.family==='production'), oracle=referenceOptimum(c.correctModel);
  const config={id:'openai',model:'fixture',maxTokens:12000,language:'zh-CN',protocolCorrection:false};
  const user={id:'u',role:'user',content:c.prompt},answer={content:'',provenance:{},automation:{usage:{},task:taskFor({messages:[]},user)}};
  initializeMethods(answer.automation,config,'highs','full');
  const controller=new AbortController(), inputs=[], saved=new Map();
  const solver={audit,info:()=>({engines:{highs:{available:true}}}),get:id=>saved.get(id),stop:()=>{},start:input=>{
    inputs.push(input);const r={id:'r'+inputs.length,status:'optimal',model:input.model,values:oracle.values,objective:oracle.objective+(numericalError?1:0),provenance:{solverInvoked:true},workerResponseValidated:true,programmaticEvidence};saved.set(r.id,r);return r;
  }};
  const run=()=>executeOptimization({config,messages:[user],problem:c.prompt,engine:'highs',seconds:10,solver,signal:controller.signal,answer,update:()=>{},planner:async(cfg,input)=>cfg.tool.name==='review_optimization'?compactReviewed({budget:false}):compactPlan(input[0].content,{model:c.correctModel,budget:false})});
  return {run,controller,answer,inputs};
}
test('audit exceptions, missing adapters, and invalid results fall back to the reviewed solver path', async()=>{
  for(const audit of [undefined,async()=>{throw Error('worker unavailable');},async()=>null,async()=>({diagnostic_error:'parse failure'})]) {
    const f=fixture(audit);await f.run();const flow=f.answer.automation;
    assert.equal(flow.stage,'complete');assert.equal(flow.review.status,'no_issue_found');
    assert.equal(flow.task.calls,2);assert.equal(flow.task.solves,1);assert.equal(flow.task.clarifications,0);
    assert.equal(flow.task.evidenceDisabled.code,'EVIDENCE_UNAVAILABLE');
    assert.equal(f.inputs[0].evidence,false);assert.equal(f.inputs[0].auxiliarySolveAllowance,0);
    assert.equal(decisionMetrics(flow.task).firstDecision,'deliver');
  }
});
test('postsolve diagnostic failure retains valid solver result and releases unused reservation',async()=>{
  const f=fixture(async()=>({prompt_audited:true}),{programmaticEvidence:{diagnostic_error:'postsolve failed',auxiliary_solves:0}});
  await f.run();assert.equal(f.answer.automation.stage,'complete');assert.equal(f.answer.automation.task.solves,1);
  assert.equal(f.answer.automation.task.evidenceDisabled.reason,'postsolve failed');
});
test('audit cancellation propagates and never starts a fallback solve',async()=>{
  const f=fixture(async()=>{f.controller.abort();throw Error('aborted worker');});
  await assert.rejects(f.run(),{name:'AbortError'});
  assert.equal(f.inputs.length,0);assert.equal(f.answer.automation.task.evidenceDisabled,undefined);
});
test('audit downgrade still rejects bad numerical results and never counts tool repair as semantic',async()=>{
  const f=fixture(async()=>{throw Error('audit failure');},{numericalError:true});
  await assert.rejects(f.run(),/数值复核失败/);
  const metrics=decisionMetrics(f.answer.automation.task);
  assert.equal(f.answer.automation.publicOutcome.complete,false);
  assert.equal(metrics.firstDecision,'repair');assert.equal(metrics.semanticRepairs,0);assert.equal(metrics.toolRepairs,1);
});
