/** Exercise the actual authenticated local API with an isolated experiment store. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { startServer } from '../server/http.mjs';

export async function auditLocalApi(output) {
  const directory = path.join(output, 'api-workspace');
  const reportPath = path.join(output, 'api-verification.json');
  if (fs.existsSync(reportPath)) {
    const previous = JSON.parse(fs.readFileSync(reportPath, 'utf8'));
    assert.equal(previous.passed, true, 'A failed API audit requires a new study directory');
    return previous;
  }
  const app = await startServer({
    directory, staticDir: path.resolve('dist'), port: 0,
    secretVault: { set() { throw Error('No credentials are needed'); }, get() { return null; }, remove() {} },
    generator: async function* () { throw Error('This study must not make model calls'); },
  });
  const report = { schema: 'publication-api-audit.v1', passed: false, newModelCalls: 0, checks: [] };
  const headers = { 'Content-Type': 'application/json', 'x-fyppppp-token': app.token };
  try {
    assert.equal((await fetch(app.origin + '/api/inverse/demo')).status, 401);
    report.checks.push('Unauthenticated experiment requests are rejected');
    const health = await (await fetch(app.origin + '/api/health')).json();
    assert.equal(health.version, '0.1.2');
    const input = await (await fetch(app.origin + '/api/inverse/demo', { headers })).json();
    input.certification = {
      ...input.certification, noise: { kind: 'absolute', budget: 0 }, threshold: 0.25,
      maxSeconds: 5, maxOracleCalls: 256,
      sensitivity: { upperNoise: { kind: 'absolute', budget: 1 }, maxSeconds: 5, maxOracleCalls: 256 },
    };
    const response = await fetch(app.origin + '/api/inverse/recover', {
      method: 'POST', headers,
      body: JSON.stringify({ input, useLLM: false, localAnalysis: true, maxModelCalls: 0 }),
      signal: AbortSignal.timeout(180000),
    });
    const result = await response.json();
    assert.equal(response.status, 201, JSON.stringify(result));
    assert.equal(result.status, 'optimal');
    assert.ok(result.localAnalysis && result.localAnalysis.status !== 'failed', 'Local analysis must complete');
    assert.ok(result.localAnalysis.compatibility, 'The production pipeline must expose certification');
    assert.equal(result.localAnalysis.compatibility.noiseSensitivity.schema, 'noise-budget-sensitivity.v1');
    report.checks.push('Real Python fit and two-endpoint certificate execute through HTTP');
    const stored = await (await fetch(app.origin + '/api/inverse/runs/' + result.id, { headers })).json();
    assert.deepEqual(stored, result);
    const listing = await (await fetch(app.origin + '/api/inverse/runs', { headers })).json();
    assert.ok(JSON.stringify(listing).includes(result.id));
    report.checks.push('Saved run is listed and reloads without changing its result');
    report.runId = result.id;
    report.certificationStatus = result.localAnalysis.compatibility.decisionCertificate.status;
    report.passed = true;
  } catch (error) {
    report.error = String(error);
    throw error;
  } finally {
    await app.close();
    fs.mkdirSync(output, { recursive: true });
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
  }
  return report;
}
