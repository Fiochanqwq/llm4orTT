import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { decisionMetricsVersion, recordAction, decisionMetrics } from '../server/decision-metrics.mjs';
import { solverPython } from '../server/python-runtime.mjs';
import { analysisRow } from '../server/exports.mjs';
import { scoreRun } from '../server/experiments.mjs';

test('first decision preserves chronology even when repair follows clarification', () => {
  const task = { decisionMetricsVersion, calls:0, solves:0, clarifications:1 };
  recordAction(task,'clarify','missing_facts');
  recordAction(task,'repair','review','semantic');
  recordAction(task,'repair','audit','programmatic');
  recordAction(task,'repair','numeric','tool');
  recordAction(task,'deliver','final');
  const run={events:[],conversation:{messages:[{role:'assistant',automation:{task}}]}};
  for (const result of [decisionMetrics(task), analysisRow(run), scoreRun(run)]) {
    assert.equal(result.firstDecision,'clarify');
    assert.equal(result.semanticRepairs,1);
    assert.equal(result.programmaticRepairs,1);
    assert.equal(result.toolRepairs,1);
    assert.deepEqual(result.decisionEvents.map(e=>e.sequence),[1,2,3,4,5]);
  }
});
test('old records remain unknown instead of guessing from aggregate counts', () => {
  const result = decisionMetrics({semanticRepairs:4, programmaticRepairCount:1});
  assert.equal(result.firstDecision,null);
  assert.equal(result.semanticRepairs,null);
  assert.equal(decisionMetrics({ decisionMetricsVersion }).firstDecision,null);
});
test('runtime discovery handles embedded Windows, Windows venv and POSIX venv', t => {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'evidence-runtime-'));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  for(const file of ['runtime/python/Scripts/python.exe','runtime/python/bin/python3']) {
    fs.mkdirSync(path.dirname(path.join(root,file)),{recursive:true}); fs.writeFileSync(path.join(root,file),'');
  }
  assert.equal(solverPython(root,'win32'),path.join(root,'runtime/python/Scripts/python.exe'));
  assert.equal(solverPython(root,'linux'),path.join(root,'runtime/python/bin/python3'));
  fs.writeFileSync(path.join(root,'runtime/python/python.exe'),'');
  assert.equal(solverPython(root,'win32'),path.join(root,'runtime/python/python.exe'));
});
