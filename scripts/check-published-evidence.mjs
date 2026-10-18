import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { controlledReport } from './analyze-controlled-evidence.mjs';
import { sha256 } from './lib/evidence-statistics.mjs';
import { executionSnapshot } from '../server/execution-snapshot.mjs';

export function checkPublishedEvidence(directory) {
  const verification = JSON.parse(fs.readFileSync(path.join(directory, 'verification.json'), 'utf8'));
  assert.equal(verification.passed, true, 'Verification did not pass');
  assert.equal(verification.kind, 'controlled_fault_injection_not_live_llm');
  const checks = verification.checks;
  for (const name of ['test-ci', 'test-evidence', 'test-evidence-coverage', 'typecheck', 'build']) {
    const matches = checks.filter(check => check.name === name);
    assert.equal(matches.length, 1, 'Missing or duplicate check: ' + name);
    const check = matches[0];
    assert.equal(check.exitCode, 0, 'Failed check: ' + name);
    if (name.startsWith('test-')) {
      assert.ok(Number.isInteger(check.tests) && check.tests > 0);
      assert.equal(check.pass, check.tests);
      assert.equal(check.fail + check.cancelled + check.skipped, 0);
    }
  }
  const statistics = controlledReport(directory, { check: true });
  assert.equal(statistics.sourceSha256, verification.execution.resultsSha256, 'Result hash differs from verification');
  assert.deepEqual(statistics, verification.statistics, 'Report hashes differ from verification');
  const result = JSON.parse(fs.readFileSync(path.join(directory, 'statistics.json'), 'utf8'));
  assert.equal(result.rows, verification.execution.runs);
  assert.equal(verification.execution.failed, 0);
  assert.equal(verification.execution.providerCalls, 0);
  assert.equal(sha256(JSON.stringify(verification.sourceSnapshot.files)), verification.sourceSnapshot.sha256, 'Invalid source manifest');
  assert.equal(executionSnapshot().sha256, verification.sourceSnapshot.sha256, 'Published evidence uses outdated source; rerun verification');
  const drivers = JSON.parse(fs.readFileSync(path.join(directory, 'driver-source-hashes.json'), 'utf8'));
  for (const file of ['scripts/verify-evidence.mjs','scripts/analyze-controlled-evidence.mjs','scripts/check-published-evidence.mjs','scripts/lib/evidence-statistics.mjs','test/evidence-statistics.test.mjs','.github/workflows/ci.yml','.gitattributes']) {
    assert.ok(Object.hasOwn(drivers, file), 'Missing verification driver: ' + file);
  }
  for (const [file, hash] of Object.entries(drivers)) {
    assert.ok(/^(scripts\/|test\/|\.github\/workflows\/ci\.yml$|\.gitattributes$)/.test(file) && !file.split(/[\\/]/).includes('..'), 'Invalid driver path');
    assert.equal(sha256(fs.readFileSync(new URL('../' + file, import.meta.url))), hash, 'Published evidence uses outdated driver: ' + file);
  }
  return { passed: true, rows: result.rows, resultsSha256: statistics.sourceSha256, statistics: statistics.files };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    assert.equal(process.argv.length, 3, 'Usage: node scripts/check-published-evidence.mjs DIRECTORY');
    console.log(JSON.stringify(checkPublishedEvidence(path.resolve(process.argv[2]))));
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
