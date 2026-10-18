// Rebuild verification from executed checks and fresh synthetic trajectories.
// Raw workspaces stay ignored; only the explicitly selected synthetic summary is publishable.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { runBenchmark } from './run-evidence-benchmark.mjs';
import { executionSnapshot } from '../server/execution-snapshot.mjs';
import { decisionMetrics, decisionMetricsVersion } from '../server/decision-metrics.mjs';

const root=fileURLToPath(new URL('../',import.meta.url));
process.chdir(root);
const directory=path.resolve(process.argv[2]||'qa/evidence-verification');
const publishIndex=process.argv.indexOf('--publish');
const publishDirectory=publishIndex>=0?path.resolve(process.argv[publishIndex+1]):null;
if(fs.existsSync(path.join(directory,'verification.json')))throw Error('Use a fresh verification directory to preserve previous evidence');
fs.mkdirSync(directory,{recursive:true});
const sha=data=>crypto.createHash('sha256').update(data).digest('hex');
const report={schema:'llm4orovo.verification.v2',kind:'controlled_fault_injection_not_live_llm',generatedAt:new Date().toISOString(),
  node:process.version,platform:process.platform,decisionMetricsVersion,sourceSnapshot:executionSnapshot(),checks:[],passed:false};
function check(name,args) {
  const log=path.join(directory,name+'.log'),fd=fs.openSync(log,'w');
  let result;
  try { result=spawnSync(process.execPath,args,{cwd:root,stdio:['ignore',fd,fd],windowsHide:true,timeout:240000}); }
  finally { fs.closeSync(fd); }
  const output=fs.readFileSync(log,'utf8');
  const counts=Object.fromEntries(['tests','pass','fail','cancelled','skipped'].map(key=>[key,Number(output.match(new RegExp('^# '+key+' (\\d+)','m'))?.[1]??0)]));
  report.checks.push({name,command:['node',...args],exitCode:result.status,signal:result.signal,log:path.basename(log),sha256:sha(output),...(args.includes('--test')?counts:{})});
  console.log(`${name}: ${result.status===0?'passed':'FAILED'}`);
  assert.equal(result.status,0,result.error?.message||output.slice(-5000));
  if(args.includes('--test')){assert.ok(counts.tests>0);assert.equal(counts.fail+counts.cancelled+counts.skipped,0);}
}
try {
  const pkg=JSON.parse(fs.readFileSync('package.json','utf8'));
  check('test-ci',['--test','--test-reporter=tap','--test-timeout=60000',...pkg.scripts['test:ci'].replace('node --test ','').split(' ')]);
  check('test-evidence',['--test','--test-reporter=tap','--test-timeout=60000','test/evidence.test.mjs']);
  // Invoke the same build tools directly: node --run corrupts non-ASCII cwd on some Windows builds.
  check('typecheck',['node_modules/typescript/bin/tsc','--noEmit']);
  check('build',['node_modules/vite/bin/vite.js','build']);
  const {rows}=await runBenchmark(directory);
  const batch=JSON.parse(fs.readFileSync(path.join(directory,'batch.json'),'utf8'));
  assert.equal(batch.status,'complete');
  assert.equal(rows.length,batch.cases.length*Object.keys(batch.methodSnapshot).length);
  assert.ok(rows.every(r=>!['failed','queued','running','awaiting_human'].includes(r.status)));
  assert.deepEqual(batch.sourceSnapshot,report.sourceSnapshot);
  assert.deepEqual(executionSnapshot(),report.sourceSnapshot);
  for(const [file,hash] of Object.entries(JSON.parse(fs.readFileSync(path.join(directory,'driver-source-hashes.json'),'utf8'))))assert.equal(sha(fs.readFileSync(file,'utf8')),hash);
  const bundle=JSON.parse(fs.readFileSync(path.join(directory,'export-bundle.json'),'utf8'));
  const manifest=bundle.entries.find(e=>e.name==='manifest.json').data;
  assert.equal(manifest.complete,true);assert.deepEqual(manifest.missingReferences,[]);
  assert.equal(manifest.files.length,bundle.entries.length-1);
  for(const item of manifest.files){
    const data=JSON.stringify(bundle.entries.find(e=>e.name===item.name).data,null,2);
    assert.equal(sha(data),item.sha256);assert.equal(Buffer.byteLength(data),item.bytes);
  }
  for(const row of rows){
    const run=bundle.entries.find(e=>e.name===`runs/${row.runId}.json`).data;
    const task=run.conversation.messages.findLast(m=>m.automation).automation.task;
    const metrics=decisionMetrics(task);
    assert.equal(row.decisionMetricsVersion,decisionMetricsVersion);
    for(const key of ['firstDecision','semanticRepairs','programmaticRepairs','toolRepairs'])assert.equal(row[key],metrics[key]);
    assert.ok(row.firstDecision);assert.equal(row.providerCalls,0);
    for(const key of ['calls','solves','clarifications'])assert.ok(row[key]<=batch.limits[key]);
  }
  const compact=rows.map(r=>Object.fromEntries(['caseId','baseId','preset','status','expectedDecision','firstDecision','correctFirstDecision','correctDelivery','silentErrorDelivery','calls','solves','clarifications','semanticRepairs','programmaticRepairs','toolRepairs','providerCalls','decisionMetricsVersion','decisionEvents'].map(k=>[k,r[k]])));
  const serialized=compact.map(r=>JSON.stringify(r)).join('\n')+'\n';
  fs.writeFileSync(path.join(directory,'controlled-results.jsonl'),serialized);
  report.execution={runs:rows.length,failed:0,awaitingHuman:0,providerCalls:0,sourceAndDriverHashesVerified:true,exportHashesVerified:true,allTaskBudgetsRespected:true,
    resultsFile:'controlled-results.jsonl',resultsSha256:sha(serialized)};
  report.passed=true;
} catch(error) { report.error=error.message;process.exitCode=1;console.error(error); }
finally { fs.writeFileSync(path.join(directory,'verification.json'),JSON.stringify(report,null,2)+'\n'); }
if(publishDirectory&&report.passed){
  fs.mkdirSync(publishDirectory,{recursive:true});
  for(const file of ['verification.json','controlled-results.jsonl','protocol.json','driver-source-hashes.json'])fs.copyFileSync(path.join(directory,file),path.join(publishDirectory,file));
}
