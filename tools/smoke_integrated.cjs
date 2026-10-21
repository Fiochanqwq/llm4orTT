// Invoke the shipped Electron executable with ELECTRON_RUN_AS_NODE=1.
// All persistent state lives in work/desktop-smoke-v012, never the real profile.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const http = require('node:http');
const { pathToFileURL } = require('node:url');
const root = path.resolve(__dirname, '..');

function scenario() {
  const sample = (id, base, decision) => ({
    id,
    model: {
      sense: 'minimize',
      variables: [{ name: 'x', type: 'binary', lower: 0, upper: 1 }],
      objective: { x: base }, constraints: []
    },
    features: { price: { kind: 'linear', terms: { x: 1 } } },
    decision: { x: decision }
  });
  return {
    schema: 'contextual-inverse.v1',
    hypotheses: [{ id: 'price', label: '隐藏费用', lower: 0, upper: 1 }],
    samples: [sample('history', -0.4, 1)],
    deployment: sample('new-context', -0.6, 0),
    lambda: 0, pruneThreshold: 0, maxIterations: 40, seconds: 3,
    certification: {
      noise: { kind: 'absolute', budget: 0 }, threshold: 0.1,
      maxSeconds: 5, maxOracleCalls: 80, maxAssignments: 16,
      sensitivity: {
        upperNoise: { kind: 'absolute', budget: 0.4 },
        maxSeconds: 5, maxOracleCalls: 80
      }
    }
  };
}

function client(service) {
  const exchange = (route, body) => new Promise((resolve, reject) => {
    const req = http.request(service.origin + route, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { 'x-fyppppp-token': service.token, 'content-type': 'application/json' }
    }, res => {
      let text = '';
      res.setEncoding('utf8');
      res.on('data', chunk => { text += chunk; });
      res.on('error', reject);
      res.on('end', () => resolve({ status: res.statusCode, text }));
    });
    req.on('error', reject);
    req.setTimeout(120000, () => req.destroy(new Error('Smoke request timed out')));
    req.end(body === undefined ? undefined : JSON.stringify(body));
  });
  return {
    exchange,
    request: async (route, body) => {
      const response = await exchange(route, body);
      const value = JSON.parse(response.text);
      assert.ok(response.status >= 200 && response.status < 300, JSON.stringify(value));
      return value;
    }
  };
}

async function main() {
  const directory = path.join(root, 'work', 'integration-smoke-20261020');
  fs.mkdirSync(directory, { recursive: true });
  const appRoot = process.env.LLM4OR_PACKAGE_ROOT || root;
  const asar = path.join(appRoot, 'resources', 'app.asar');
  const { startServer } = await import(pathToFileURL(path.join(asar, 'server', 'http.mjs')).href);
  let service = await startServer({ directory, staticDir: path.join(asar, 'dist'), port: 0 });
  try {
    let api = client(service);
    const health = await api.request('/api/health');
    assert.equal(health.version, '0.1.2');
    const packageInfo = JSON.parse(fs.readFileSync(path.join(asar, 'package.json'), 'utf8'));
    assert.equal(packageInfo.version, '0.1.2');
    const html = await api.exchange('/');
    assert.equal(html.status, 200);
    const asset = html.text.match(/src="([^"]+\.js)"/);
    assert.ok(asset, 'Built entry script is linked');
    const js = await api.exchange(asset[1]);
    assert.equal(js.status, 200);
    assert.match(js.text, /本次综合结论/);
    assert.match(js.text, /inverse-noise-upper/);
    assert.ok(Array.isArray(await api.request('/api/conversations')));
    const demo = await api.request('/api/inverse/demo');
    assert.deepEqual(demo.certification.noise, { kind: 'absolute', budget: 0 });
    const input = scenario();
    fs.writeFileSync(path.join(directory, 'smoke-input.json'), JSON.stringify(input, null, 2));
    const result = await api.request('/api/inverse/recover', {
      input, useLLM: false, localAnalysis: true, maxModelCalls: 0
    });
    assert.equal(result.status, 'optimal');
    assert.equal(result.spending.modelCalls, 0);
    assert.equal(result.spending.maxModelCalls, 0);
    assert.equal(result.localAnalysis.modelCalls, 0);
    const compatible = result.localAnalysis.compatibility;
    assert.ok(compatible);
    assert.equal(compatible.modelCalls, 0);
    assert.equal(compatible.deploymentSource, 'provided_context');
    assert.equal(compatible.decisionCertificate.status, 'safe');
    assert.equal(compatible.decisionCertificate.upperBound, 0);
    assert.equal(compatible.noiseSensitivity.status, 'sensitive');
    assert.equal(compatible.noiseSensitivity.upperStatus, 'risk_witness');
    assert.equal(compatible.noiseSensitivity.upperAnalysis.modelCalls, 0);
    assert.equal(compatible.noiseSensitivity.fixedDecisionVerified, true);
    assert.equal(compatible.noiseSensitivity.budgetUpperBoundValidated, false);
    assert.equal(compatible.noiseSensitivity.criticalBudgetEstimated, false);
    assert.equal(compatible.decisionGuidance.status, 'risk_witness');
    assert.equal(compatible.decisionGuidance.scope, 'declared_upper_budget');
    assert.deepEqual(compatible.decisionCertificate.chosenDecision, { x: 1 });
    assert.deepEqual(compatible.noiseSensitivity.upperCertificate.chosenDecision, { x: 1 });
    assert.ok(Math.abs(compatible.noiseSensitivity.upperCertificate.lowerBound - 0.2) < 1e-12);
    assert.ok(Math.abs(compatible.noiseSensitivity.upperCertificate.upperBound - 0.2) < 1e-12);
    assert.equal(compatible.assumptionAudit.trainingFitValidatesNoiseBudget, false);
    const saved = await api.request('/api/inverse/runs/' + result.id);
    assert.deepEqual(saved.localAnalysis.compatibility, compatible);
    const noUpper = scenario();
    delete noUpper.certification.sensitivity;
    const nominalOnly = await api.request('/api/inverse/recover', {
      input: noUpper, useLLM: false, localAnalysis: true, maxModelCalls: 0
    });
    assert.equal(nominalOnly.spending.modelCalls, 0);
    assert.equal(nominalOnly.localAnalysis.compatibility.noiseSensitivity.status, 'not_requested');
    assert.equal(nominalOnly.localAnalysis.compatibility.noiseSensitivity.upperNoise, null);
    assert.equal(nominalOnly.localAnalysis.compatibility.decisionGuidance.scope, 'nominal_budget_only');
    await service.close();
    service = null;
    service = await startServer({ directory, staticDir: path.join(asar, 'dist'), port: 0 });
    api = client(service);
    const restored = await api.request('/api/inverse/runs/' + result.id);
    assert.deepEqual(restored.localAnalysis.compatibility, compatible);
    const listed = await api.request('/api/inverse/runs');
    assert.ok(Array.isArray(listed));
    assert.ok(listed.some(run => run.id === result.id));
    const summary = {
      status: 'passed', version: health.version, packedPackageVersion: packageInfo.version,
      actualAsarServer: true, frontendServed: true, chatRouteAvailable: true,
      useLLM: false, modelCalls: result.spending.modelCalls,
      resultStatus: result.status, nominalStatus: compatible.decisionCertificate.status,
      upperStatus: compatible.noiseSensitivity.upperStatus,
      guidanceStatus: compatible.decisionGuidance.status,
      sensitivityStatus: compatible.noiseSensitivity.status,
      fixedDecisionVerified: compatible.noiseSensitivity.fixedDecisionVerified,
      upperRisk: {
        lower: compatible.noiseSensitivity.upperCertificate.lowerBound,
        upper: compatible.noiseSensitivity.upperCertificate.upperBound
      },
      noUpperStatus: nominalOnly.localAnalysis.compatibility.noiseSensitivity.status,
      persistedAfterServerRestart: true, runIds: [result.id, nominalOnly.id],
      isolatedProfile: directory,
      visualBrowserLayoutTested: false
    };
    fs.writeFileSync(path.join(directory, 'summary.json'), JSON.stringify(summary, null, 2));
    console.log(JSON.stringify(summary));
  } finally {
    if (service) await service.close();
  }
}
main().catch(error => { console.error(error.stack); process.exitCode = 1; });
