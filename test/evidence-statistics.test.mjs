import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { analyzeControlledEvidence, exactMcNemar, holm } from '../scripts/lib/evidence-statistics.mjs';
import { controlledReport } from '../scripts/analyze-controlled-evidence.mjs';
import { buildEvidenceCases } from '../scripts/fixtures/evidence-benchmark.mjs';
import { checkPublishedEvidence } from '../scripts/check-published-evidence.mjs';
import { executionSnapshot } from '../server/execution-snapshot.mjs';
import { sha256 } from '../scripts/lib/evidence-statistics.mjs';

const source=new URL('../docs/evidence/controlled/',import.meta.url);
const text=fs.readFileSync(new URL('controlled-results.jsonl',source),'utf8');
const protocol=JSON.parse(fs.readFileSync(new URL('protocol.json',source),'utf8'));
protocol.caseManifest=buildEvidenceCases().map(c=>({caseId:c.id,baseId:c.baseId,expectedDecision:c.expectedDecision}));
const serialize=rows=>rows.map(row=>JSON.stringify(row)).join('\n')+'\n';
const close=(actual,expected)=>assert.ok(Math.abs(actual-expected)<1e-12,`${actual} != ${expected}`);

test('exact McNemar handles concordance, balanced and unequal discordances without overflow',()=>{
  close(exactMcNemar(0,0),1);
  close(exactMcNemar(4,0),0.125);
  close(exactMcNemar(0,8),0.0078125);
  close(exactMcNemar(3,3),1);
  close(exactMcNemar(1,5),0.21875); // 2*(C(6,0)+C(6,1))/2^6
  close(exactMcNemar(1000,1000),1);
  assert.throws(()=>exactMcNemar(-1,2));
  assert.throws(()=>exactMcNemar(0.5,2));
});

test('Holm controls the full four-test family and preserves original ordering',()=>{
  assert.deepEqual(holm([0.125,0.0078125,0.125,0.0078125]),[0.25,0.03125,0.25,0.03125]);
  assert.deepEqual(holm([1,0.01,0.04]),[1,0.03,0.08]);
  assert.throws(()=>holm([NaN]));
});

test('committed synthetic pairs use 12 base units and keep the nonsignificant primary result',()=>{
  const result=analyzeControlledEvidence(text,protocol);
  assert.equal(result.rows,72); assert.equal(result.baseUnits,12);
  for(const row of result.comparisons){
    const delivery=row.outcome==='correctDelivery';
    assert.deepEqual(row.table,delivery?[[4,4],[0,4]]:[[0,8],[0,4]]);
    close(row.p,delivery?0.125:0.0078125);
    close(row.pHolm,delivery?0.25:0.03125);
    assert.equal(row.significant,!delivery);
  }
});

test('missing, duplicate and mismatched variants cannot silently become paired successes',()=>{
  const rows=JSON.parse('['+text.trim().split('\n').join(',')+']');
  assert.throws(()=>analyzeControlledEvidence(serialize(rows.slice(1)),protocol),/Incomplete/);
  assert.throws(()=>analyzeControlledEvidence(serialize([...rows,rows[0]]),protocol),/duplicate/);
  const wrong=structuredClone(rows);wrong[0].caseId='unmatched-case';
  assert.throws(()=>analyzeControlledEvidence(serialize(wrong),protocol),/Unmatched/);
  const missingBase=rows.filter(r=>r.baseId!==rows[0].baseId);
  assert.throws(()=>analyzeControlledEvidence(serialize(missingBase),protocol),/Incomplete/);
});

test('old actions, fabricated metrics, unfinished runs and invalid outcomes fail closed',()=>{
  const mutate=fn=>{const rows=text.trim().split('\n').map(JSON.parse);fn(rows[0]);return serialize(rows);};
  for(const fn of [
    row=>delete row.decisionMetricsVersion,
    row=>delete row.decisionEvents,
    row=>row.decisionEvents[0].sequence=2,
    row=>row.semanticRepairs=100,
    row=>row.correctFirstDecision=!row.correctFirstDecision,
    row=>row.correctDelivery='true',
    row=>row.status='failed',
    row=>row.status='partial',
    row=>row.providerCalls=1,
    row=>row.calls=100,
    row=>row.decisionEvents[0].calls=100
  ]) assert.throws(()=>analyzeControlledEvidence(mutate(fn),protocol));
});

test('both variants must succeed: one failed variant changes its entire paired unit',()=>{
  const rows=text.trim().split('\n').map(JSON.parse);
  const row=rows.find(r=>r.preset==='full'&&r.baseId.startsWith('A-'));
  row.correctDelivery=false;
  const result=analyzeControlledEvidence(serialize(rows),protocol);
  for(const r of result.comparisons.filter(r=>r.outcome==='correctDelivery')){
    assert.equal(r.improved,3);close(r.p,0.25);
  }
});

test('generated reports bind to exact input bytes and reject tampering or stale data',t=>{
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'evidence-statistics-'));
  t.after(()=>fs.rmSync(directory,{recursive:true,force:true}));
  fs.writeFileSync(path.join(directory,'controlled-results.jsonl'),text);
  fs.writeFileSync(path.join(directory,'protocol.json'),JSON.stringify(protocol,null,2));
  const initial=controlledReport(directory);
  assert.deepEqual(controlledReport(directory,{check:true}),initial);
  const report=fs.readFileSync(path.join(directory,'report.md'),'utf8');
  assert.match(report,/主指标 correctDelivery：structure：不显著/);
  assert.match(report,/0\.03125/);
  fs.appendFileSync(path.join(directory,'report.md'),'tampered');
  assert.throws(()=>controlledReport(directory,{check:true}),/Stale or modified/);
  controlledReport(directory);
  fs.appendFileSync(path.join(directory,'controlled-results.jsonl'),'\n');
  assert.throws(()=>controlledReport(directory,{check:true}),/Stale or modified/);
});

test('verification refuses malformed publish arguments and any existing output directory',t=>{
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'evidence-existing-'));
  t.after(()=>fs.rmSync(directory,{recursive:true,force:true}));
  for(const args of [[directory],[directory,'--publish'],['--publish',directory]]){
    const run=spawnSync(process.execPath,['scripts/verify-evidence.mjs',...args],{encoding:'utf8',windowsHide:true,timeout:15000});
    assert.equal(run.status,1,run.stderr);
    assert.match(run.stderr,/Usage:|fresh verification directory/);
  }
  assert.deepEqual(fs.readdirSync(directory),[]);
});

test('publication gate rejects failed checks and stale source or driver manifests',t=>{
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'evidence-publication-'));
  t.after(()=>fs.rmSync(directory,{recursive:true,force:true}));
  fs.writeFileSync(path.join(directory,'controlled-results.jsonl'),text);
  fs.writeFileSync(path.join(directory,'protocol.json'),JSON.stringify(protocol));
  const statistics=controlledReport(directory);
  const names=['scripts/verify-evidence.mjs','scripts/analyze-controlled-evidence.mjs','scripts/check-published-evidence.mjs','scripts/lib/evidence-statistics.mjs','test/evidence-statistics.test.mjs','.github/workflows/ci.yml','.gitattributes'];
  const drivers=Object.fromEntries(names.map(name=>[name,sha256(fs.readFileSync(name))]));
  fs.writeFileSync(path.join(directory,'driver-source-hashes.json'),JSON.stringify(drivers));
  // Synthetic manifest for gate unit tests only; never published as execution evidence.
  const fixture={passed:true,kind:protocol.kind,sourceSnapshot:executionSnapshot(),statistics,
    execution:{runs:72,failed:0,providerCalls:0,resultsSha256:statistics.sourceSha256},
    checks:['test-ci','test-evidence','test-evidence-coverage','typecheck','build'].map(name=>({name,exitCode:0,tests:1,pass:1,fail:0,cancelled:0,skipped:0}))};
  const write=v=>fs.writeFileSync(path.join(directory,'verification.json'),JSON.stringify(v));
  write(fixture);assert.equal(checkPublishedEvidence(directory).passed,true);
  for(const mutate of [v=>v.passed=false,v=>v.checks[0].exitCode=1,v=>v.checks[0].skipped=1,v=>v.checks.pop(),v=>v.execution.resultsSha256='bad',v=>v.statistics.files['report.md']='bad',v=>v.sourceSnapshot.sha256='bad']){
    const copy=structuredClone(fixture);mutate(copy);write(copy);assert.throws(()=>checkPublishedEvidence(directory));
  }
  write(fixture);drivers[names[0]]='bad';
  fs.writeFileSync(path.join(directory,'driver-source-hashes.json'),JSON.stringify(drivers));
  assert.throws(()=>checkPublishedEvidence(directory),/outdated driver/);
});
