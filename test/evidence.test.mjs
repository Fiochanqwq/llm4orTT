import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { solverPython } from '../server/python-runtime.mjs';
import { decisionMetrics } from '../server/decision-metrics.mjs';
import { SolverService } from '../server/solver.mjs';
import { queuedSolve } from '../server/solver-queue.mjs';
import { evidenceDecision } from '../server/evidence-routing.mjs';
import { executeOptimization } from '../server/optimization.mjs';
import { initializeMethods } from '../server/optimization-v07.mjs';
import { taskFor,agentLimits } from '../server/agent-policy.mjs';
import { ExperimentService } from '../server/experiments.mjs';
import { compactPlan,compactReviewed } from '../scripts/fixtures/compact-v074.mjs';
import { buildEvidenceCases,referenceOptimum } from '../scripts/fixtures/evidence-benchmark.mjs';
const cases=buildEvidenceCases(),directory=()=>path.resolve('qa','evidence-'+crypto.randomUUID());
const service=new SolverService(directory());
const solve=(model,extra={})=>queuedSolve(service,{model,engine:'highs',seconds:10,...extra},new AbortController().signal,()=>{});

test('actual Pyomo extraction catches wrong direction, integer omission and public unit conversion',async()=>{
  for(const family of ['sense','integer','units','omission']){
    const c=cases.find(c=>c.family===family),bad=await service.audit(c.candidateModel,c.prompt),good=await service.audit(c.correctModel,c.prompt);
    const d=evidenceDecision(bad,{limits:agentLimits});assert.equal(d.action,'repair',JSON.stringify(bad));
    assert.equal(evidenceDecision(good,{limits:agentLimits}).action,'continue',JSON.stringify(good));
    assert.equal(good.source,'pyomo_standard_repn');assert.equal(good.variable_count,2);assert.equal(good.auxiliary_solves,0);
  }
});
test('elastic infeasibility diagnosis solves once, retains original model, names violated rows',async()=>{
  const c=cases.find(c=>c.family==='conflict'),before=JSON.stringify(c.correctModel);
  const r=await solve(c.correctModel,{problem:c.prompt,auxiliarySolveAllowance:1});
  assert.equal(r.status,'infeasible');assert.equal(r.programmaticEvidence.auxiliary_solves,1);
  assert.ok(r.programmaticEvidence.infeasible_conflict_constraints.length>0);
  assert.ok(r.programmaticEvidence.infeasible_conflict_constraints.every(c=>c.slack>1e-5&&c.expression.name===c.name));
  assert.equal(JSON.stringify(c.correctModel),before);
  const no=await solve(c.correctModel,{problem:c.prompt,auxiliarySolveAllowance:0});assert.equal(no.programmaticEvidence.auxiliary_solves,0);
});
test('two-sided RHS perturbation honors budget, sense and actual numerical monotonicity',async()=>{
  const c=cases.find(c=>c.family==='production'),r=await solve(c.correctModel,{problem:c.prompt,auxiliarySolveAllowance:2,perturb:true});
  assert.equal(r.status,'optimal');assert.equal(r.programmaticEvidence.auxiliary_solves,2);
  assert.equal(r.programmaticEvidence.probes.length,2);assert.equal(r.programmaticEvidence.monotonicity_violated,false);
  const limited=await solve(c.correctModel,{problem:c.prompt,auxiliarySolveAllowance:1,perturb:true});
  assert.equal(limited.programmaticEvidence.auxiliary_solves,0);assert.match(limited.programmaticEvidence.probe_status,/budget/);
});
test('scaling, zero optimum and unsupported large artificial cap are visible',async()=>{
  const c=cases.find(c=>c.family==='production'),m=structuredClone(c.correctModel);m.constraints[0].terms.y=.00001;
  assert.equal((await service.audit(m,c.prompt)).has_scaling_issue,true);
  const zero=cases.find(c=>c.family==='zero_missing_demand');assert.equal((await solve(zero.correctModel,{problem:zero.prompt})).programmaticEvidence.is_trivial_solution,true);
  const cap=structuredClone(cases.find(c=>c.family==='unbounded').correctModel);cap.variables[0].upper=1e6;
  assert.equal((await solve(cap,{problem:'最大化 3x，x 非负。'})).programmaticEvidence.hit_artificial_bound,true);
  assert.equal((await solve(cap,{problem:'最大化 3x，x 非负，业务上限为 1000000。'})).programmaticEvidence.hit_artificial_bound,false);
});
test('mixed named domains are checked without imposing integrality on continuous variables',async()=>{
  const c=cases.find(c=>c.family==='production'),e=await service.audit(c.correctModel,'最大化 7x+4y。x 为整数，y 为非负连续量。机器 2x+y<=8，人工 x+3y<=12。');
  assert.equal(e.integrality_mismatch,true);assert.deepEqual(e.integrality_mismatch_variables,['x']);
});
test('real full trajectory repairs internally, clears evidence, respects limits and agrees with independent enumeration',async()=>{
  const c=cases.find(c=>c.family==='integer'),config={id:'openai',model:'fixture',maxTokens:12000,language:'zh-CN',protocolCorrection:false};
  const user={id:'u',role:'user',content:c.prompt},answer={content:'',provenance:{},automation:{usage:{},task:taskFor({messages:[]},user)}};
  initializeMethods(answer.automation,config,'highs','full');let repairs=0;
  await executeOptimization({config,messages:[user],problem:c.prompt,engine:'highs',seconds:10,solver:service,signal:new AbortController().signal,answer,update:()=>{},planner:async(cfg,input)=>{
    if(cfg.tool.name==='review_optimization')return compactReviewed({budget:false});
    if(answer.automation.stage==='repairing')repairs++;
    return compactPlan(input[0].content,{model:repairs?c.correctModel:c.candidateModel,budget:false});
  }});
  const f=answer.automation;assert.equal(f.stage,'complete',JSON.stringify(f.evidenceDecisions));assert.equal(repairs,1);assert.equal(f.task.calls,3);assert.equal(f.task.solves,1);assert.equal(f.task.clarifications,0);
  const metrics=decisionMetrics(f.task);assert.equal(metrics.firstDecision,'repair');assert.equal(metrics.semanticRepairs,0);assert.equal(metrics.programmaticRepairs,1);
  assert.equal(f.publicOutcome.objective,referenceOptimum(c.correctModel).objective);
});
test('unattended actual experiment trajectory records unanswered questions and settles without human wait',async()=>{
  const c=cases.find(c=>c.family==='unbounded'),config={id:'openai',model:'fixture',maxTokens:12000,language:'zh-CN',protocolCorrection:false};
  const exp=new ExperimentService(directory(),{store:{credentials:async()=>config},solver:service,
    planner:async(cfg,input)=>cfg.tool.name==='review_optimization'?compactReviewed({budget:false}):compactPlan(input[0].content,{model:c.correctModel,budget:false}),generator:async function*(){throw Error('Unexpected interpretation call');}});
  const created=await exp.create({cases:[c],presets:['full'],requestCap:4}),batch=exp.batches.get(created.id);batch.rateIntervalMs=0;exp.action(batch.id,'start');
  while(exp.working)await new Promise(r=>setTimeout(r,25));
  assert.equal(batch.status,'complete');const r=exp.run(batch.runs[0].id);assert.equal(r.status,'partial');assert.equal(r.environmentFailure.code,'UNATTENDED_CLARIFICATION_RECORDED');
  assert.equal(r.conversation.messages.at(-1).automation.task.clarifications,1);await exp.close();
});
test('validated worker errors release unused diagnostic reservation and permit one internal retry',async()=>{
  const c=cases.find(c=>c.family==='production'),config={id:'openai',model:'fixture',maxTokens:12000,language:'zh-CN',protocolCorrection:false};
  const user={id:'u',role:'user',content:c.prompt},answer={content:'',provenance:{},automation:{usage:{},task:taskFor({messages:[]},user)}};
  initializeMethods(answer.automation,config,'highs','full');
  let starts=0;const failed={id:'injected-worker-error',status:'error',error:'Injected solver runtime failure',workerResponseValidated:true,model:c.correctModel,provenance:{solverInvoked:true}};
  const adapter={info:()=>service.info(),audit:(...args)=>service.audit(...args),get:id=>id===failed.id?failed:service.get(id),stop:id=>service.stop(id),start:input=>++starts===1?failed:service.start(input),get active(){return service.active;}};
  await executeOptimization({config,messages:[user],problem:c.prompt,engine:'highs',seconds:10,solver:adapter,signal:new AbortController().signal,answer,update:()=>{},planner:async(cfg,input)=>cfg.tool.name==='review_optimization'?compactReviewed({budget:false}):compactPlan(input[0].content,{model:c.correctModel,budget:false})});
  assert.equal(answer.automation.stage,'complete');assert.equal(answer.automation.task.calls,4);assert.equal(answer.automation.task.solves,2);assert.equal(answer.automation.task.clarifications,0);
  const metrics=decisionMetrics(answer.automation.task);assert.equal(metrics.firstDecision,'repair');assert.equal(metrics.toolRepairs,1);assert.equal(metrics.semanticRepairs,0);assert.equal(metrics.programmaticRepairs,0);
});
test('monotonicity violation signal is exercised using a deliberately inconsistent diagnostic solver',()=>{
  const result=spawnSync(solverPython(),['-X','utf8','-B',path.resolve('test/evidence-python-test.py')],{encoding:'utf8',windowsHide:true});assert.equal(result.status,0,result.error?.message||result.stderr||result.stdout);
});
