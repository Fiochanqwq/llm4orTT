import test from 'node:test';
import assert from 'node:assert/strict';
import realFs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

// Execute the real transport with in-memory files, fake credentials, and a fake fetch.
// No provider request or persistent file is created by these tests.
const source = realFs.readFileSync('scripts/decision-contract-api.mjs', 'utf8').replace(/^import .*;\r?\n/gm, '');
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
async function run({failure=false, completion=60, started=false, modern=false, priorCost=.3, tamperPrior=false, badFloor=false}={}) {
  const root=process.cwd(), out=path.join(root,'实验','budget-test');
  const queue=Array.from({length:modern?240:600},(_,i)=>({id:`case_${i}`,maxTokens:3072,messages:[{role:'user',content:'test'}],json:true}));
  const prior=JSON.stringify({accounted_upper_CNY:priorCost,measured_usage_cost_CNY:priorCost,in_flight_reserved_CNY:0});
  const priorPath=path.join(root,'实验','previous-spend.json');
  const reports=[{path:priorPath,sha256:sha(prior)}];
  const modernBudget={total_CNY:15,stop_remaining_CNY:badFloor?null:3,max_model_calls:240,automatic_retries:0,prior_spend_reports:reports};
  const q=JSON.stringify(queue), prereg=JSON.stringify({estimate:{costs:{peak:{total_CNY:.9}}},
    ...(modern?{task:'T8',n:80,MDE:.15,arms:['verdict','point','point+anchor'],switching_rules:['Stop below the twenty-percent floor'],budget:modernBudget}:{})});
  const budget={total_CNY:6,stop_remaining_CNY:1.2,max_model_calls:600,model:'deepseek-flash',
    ...(modern?{...modernBudget,schema:'task-board-budget.v2'}:{}),
    prices:{peak:{hit:.04,miss:2,output:8},off_peak:{hit:.02,miss:1,output:4}},queue_sha256:sha(q),prereg_sha256:sha(prereg)};
  const files=new Map(), key=p=>path.resolve(p);
  files.set(key(path.join(out,'queue.json')),q);
  files.set(key(path.join(out,'budget.json')),JSON.stringify(budget));
  files.set(key(path.join(out,'prereg.json')),prereg);
  files.set(key(priorPath),tamperPrior?prior+' ':prior);
  files.set(key(path.join(out,'execution.log')),'预估调用数：600；预估费用：¥0.9。\n');
  files.set(key(path.join(root,'state/FYPPPPP/workspace/inverse-workspace.json')),'{}');
  if(started)files.set(key(path.join(out,'calls.jsonl')),JSON.stringify({event:'started',id:'case_0'})+'\n');
  const fs={mkdirSync(){},openSync(){return 1;},closeSync(){},unlinkSync(p){files.delete(key(p));},
    existsSync:p=>files.has(key(p)),readFileSync(p,encoding){const v=files.get(key(p));if(v===undefined)throw Error('Missing fake file '+p);return encoding?v:Buffer.from(v);},
    writeFileSync(p,data,options){if(options?.flag==='wx'&&files.has(key(p)))throw Error('Overwrite');files.set(key(p),String(data));},
    appendFileSync(p,data){files.set(key(p),(files.get(key(p))??'')+data);}};
  let calls=0;
  const fetch=async()=>{calls++;if(failure)throw Error('Simulated network failure');return {ok:true,status:200,text:async()=>JSON.stringify({id:'response',model:'deepseek-flash',choices:[{finish_reason:'stop',message:{content:'{}'}}],usage:{prompt_tokens:1,completion_tokens:completion,prompt_cache_hit_tokens:0}})};};
  class Store {async credentials(){return {apiKey:'synthetic-secret',model:'deepseek-flash',baseURL:'https://api.deepseek.com'};}}
  const fakeProcess={argv:['node','script','--out',out,'--queue',path.join(out,'queue.json'),'--budget',path.join(out,'budget.json'),'--concurrency','1'],env:{LOCALAPPDATA:path.join(root,'state')}};
  const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
  await new AsyncFunction('fs','path','crypto','Store','vault','process','console','fetch','fileURLToPath','Buffer','performance','AbortSignal',source.replaceAll('import.meta.url',"'file:///fake'"))(
    fs,path,crypto,Store,{},fakeProcess,{log(){},error(){}},fetch,()=>path.join(root,'scripts/decision-contract-api.mjs'),Buffer,performance,AbortSignal);
  return {calls,report:files.has(key(path.join(out,'budget-spend.json')))?JSON.parse(files.get(key(path.join(out,'budget-spend.json')))):null,exitCode:fakeProcess.exitCode};
}
test('all authorized cheap calls finish with exact measured usage',async()=>{
  const r=await run();assert.equal(r.calls,600);assert.equal(r.report.retries,0);assert.equal(r.report.unknown_charge_attempts,0);assert.ok(r.report.accounted_upper_CNY<1);assert.equal(r.report.in_flight_reserved_CNY,0);
});
test('maximum-output usage stops before consuming the twenty-percent floor',async()=>{
  const r=await run({completion:3072});assert.ok(r.calls>0&&r.calls<600);assert.equal(r.report.stop_reason,'20_percent_budget_floor');assert.ok(r.report.accounted_upper_CNY<=4.8);assert.ok(r.report.remaining_lower_CNY>=1.2-1e-10);
});
test('unknown-charge failures retain reservations and are never retried',async()=>{
  const r=await run({failure:true});assert.equal(r.calls,3);assert.equal(r.report.unknown_charge_attempts,3);assert.equal(r.report.measured_usage_cost_CNY,0);assert.ok(r.report.accounted_upper_CNY>0);assert.equal(r.report.stop_reason,'transport_failure_circuit_breaker');
});
test('an already attempted paid queue is rejected without a network request',async()=>{
  const r=await run({started:true});assert.equal(r.calls,0);assert.equal(r.exitCode,1);
});
test('T8 continuation carries forward prior spending under the approved board cap',async()=>{
  const r=await run({modern:true});assert.equal(r.calls,240);assert.equal(r.report.brought_forward_accounted_CNY,.3);
  assert.ok(r.report.current_run_accounted_CNY>0);assert.equal(r.report.total_budget_CNY,15);
  assert.ok(Math.abs(r.report.accounted_upper_CNY-r.report.current_run_accounted_CNY-.3)<1e-12);
});
test('a changed previous spending record is rejected before any request',async()=>{
  await assert.rejects(run({modern:true,tamperPrior:true}),/Prior spend report changed/);
});
test('new tasks cannot reset the spent budget or remove the twenty-percent floor',async()=>{
  await assert.rejects(run({modern:true,priorCost:11.5}),/Estimate exceeds available authorized budget/);
  await assert.rejects(run({modern:true,badFloor:true}),/Budget or task contract differs/);
});
