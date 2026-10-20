import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { inverseDemo, runInversePipeline } from '../server/inverse.mjs';
import { proposalCache, proposalKey } from '../server/inverse-cache.mjs';
import { deepseekRequest } from '../server/deepseek.mjs';

const config = { id: 'deepseek', model: 'deepseek-flash', apiKey: 'secret-test-only', maxTokens: 8192, baseURL: 'https://api.example.test' };
const input = inverseDemo();
const answer = { hypotheses: input.hypotheses, samples: input.samples.map(s => ({ id: s.id, features: s.features })) };
const fitted = (residual = 1) => ({ status: 'optimal', meanResidual: residual, theta: {}, anomalies: residual ? [{ id: 'a', residual }] : [] });
const generator = async function* (c) { assert.equal(c.economy, true); assert.equal(c.maxTokens, 4096); yield { text: JSON.stringify(answer), usage: { input: 123, output: 45 } }; };

test('already-explained history and offline mode never contact the model', async () => {
  const fail = async function* () { assert.fail('Network must not be used'); };
  for (const useLLM of [true, false]) {
    const result = await runInversePipeline(input, { config, generator: fail, useLLM, solve: async () => fitted(0) });
    assert.equal(result.spending.modelCalls, 0);
  }
});
test('a persisted proposal is reused across independent pipeline runs at zero call budget', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'inverse-cache-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const options = { config, generator, useLLM: true, solve: async () => fitted(), cacheDirectory: dir };
  const first = await runInversePipeline(input, options);
  assert.equal(first.spending.modelCalls, 1);
  assert.equal(first.spending.inputTokens, 123);
  const second = await runInversePipeline(input, { ...options, maxModelCalls: 0, generator: async function* () { assert.fail('Cache hit must be free'); } });
  assert.equal(second.spending.modelCalls, 0); assert.equal(second.spending.cacheHits, 1);
  assert.deepEqual(second.input, first.input);
  assert.ok(!fs.readFileSync(path.join(dir, fs.readdirSync(dir)[0]), 'utf8').includes(config.apiKey));
});
test('cache identity separates provider settings and changed prompts but not credentials', () => {
  assert.equal(proposalKey('A', config), proposalKey('A', { ...config, apiKey: 'another-key' }));
  assert.notEqual(proposalKey('A', config), proposalKey('B', config));
  assert.notEqual(proposalKey('A', config), proposalKey('A', { ...config, model: 'other-model' }));
  assert.notEqual(proposalKey('A', config), proposalKey('A', { ...config, baseURL: 'https://different.test' }));
});
test('one-call budget stops a continuing refinement loop', async () => {
  let solves = 0;
  const result = await runInversePipeline(input, { config, generator, useLLM: true, rounds: 5, solve: async () => fitted(++solves === 1 ? 2 : 1) });
  assert.equal(result.spending.modelCalls, 1); assert.equal(result.stopReason, 'model_budget');
});
test('model failure and oversized prompts preserve local solution without retries', async () => {
  const failed = await runInversePipeline(input, { config, useLLM: true, solve: async () => fitted(), generator: async function* () { throw Error('test failure'); } });
  assert.equal(failed.spending.modelCalls, 1); assert.equal(failed.meanResidual, 1); assert.equal(failed.stopReason, 'model_failed');
  const huge = await runInversePipeline({ ...input, description: 'x'.repeat(61000) }, { config, generator, useLLM: true, solve: async () => fitted() });
  assert.equal(huge.spending.modelCalls, 0); assert.equal(huge.stopReason, 'prompt_too_large');
});
test('corrupt cache is a miss; unavailable local analysis preserves base solution', async t => {
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'inverse-cache-')); t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
  const key='a'.repeat(64); fs.writeFileSync(path.join(dir,key+'.json'),'{broken');
  assert.equal(proposalCache(dir).read(key),null);
  const result=await runInversePipeline(input,{localAnalysis:true,solve:async()=>fitted(),analyze:async()=>{throw Error('Timeout');}});
  assert.equal(result.meanResidual,1); assert.equal(result.localAnalysis.status,'failed'); assert.equal(result.spending.modelCalls,0);
});
test('DeepSeek economy mode changes only explicit economy requests', () => {
  const normal=deepseekRequest(config), economy=deepseekRequest({...config,economy:true});
  assert.equal(normal.options.thinking.type,'enabled'); assert.equal(normal.options.reasoning_effort,'high');
  assert.equal(economy.options.thinking.type,'disabled'); assert.equal(economy.options.reasoning_effort,undefined);
  const legacy=deepseekRequest({...config,model:'deepseek-chat',economy:true}); assert.equal(legacy.options.thinking,undefined);
});
