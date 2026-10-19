import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { Store } from '../server/store.mjs';
import { startServer } from '../server/http.mjs';
import { fileVault } from '../server/file-vault.mjs';

const fakeVault = { protect: async s => 'encrypted:' + s, unprotect: async s => s.slice(10) };
function folder() { const dir = path.resolve('qa', 'workspace-' + crypto.randomUUID()); fs.mkdirSync(dir, { recursive: true }); return dir; }

test('new settings import credentials without loading or modifying legacy history', async () => {
  const directory = folder();
  fs.writeFileSync(path.join(directory, 'workspace.json'), JSON.stringify({ version: 1, preferences: { provider: 'openai', methodPreset: 'old-research', chatMode: 'chat' }, providers: { openai: { encryptedKey: 'encrypted:fixture', region: 'global', model: 'test-model' } }, conversations: [{ id: 'legacy-secret-history', messages: [] }] }));
  const legacy = fs.readFileSync(path.join(directory, 'workspace.json'), 'utf8');
  const store = new Store(directory, fakeVault);
  assert.equal((await store.credentials('openai')).apiKey, 'fixture');
  for (const file of ['inverse-workspace.json', 'inverse-workspace.json.bak']) {
    const raw = fs.readFileSync(path.join(directory, file), 'utf8');
    assert.ok(!raw.includes('legacy-secret-history')); assert.ok(!raw.includes('methodPreset'));
  }
  assert.ok(!JSON.stringify(store.publicState()).includes('encrypted:fixture'));
  assert.ok(!Object.hasOwn(store.publicState(), 'conversations'));
  assert.equal(fs.readFileSync(path.join(directory, 'workspace.json'), 'utf8'), legacy);
});

test('file vault detects tampering and uses a persistent private key', async () => {
  const dir = folder(), vault = fileVault(dir), value = await vault.protect('fixture');
  assert.equal(await fileVault(dir).unprotect(value), 'fixture');
  const bytes = Buffer.from(value.slice(3), 'base64'); bytes[15] ^= 1;
  await assert.rejects(vault.unprotect('v1:' + bytes.toString('base64')));
});

test('model discovery persists all versions and a custom selection survives restart', async t => {
  const directory = folder();
  const service = await startServer({ directory, staticDir: path.resolve('dist'), port: 0, secretVault: fakeVault,
    modelLister: async config => { assert.equal(config.baseURL, 'https://gateway.invalid/v1'); return { models: ['legacy/DeepSeek-R1', 'custom/future-model'], source: 'api', verified: true }; } });
  t.after(() => service.close());
  const request = (route, method, data) => fetch(service.origin + '/api' + route, { method, headers: { 'x-fyppppp-token': service.token, 'content-type': 'application/json' }, body: JSON.stringify(data) });
  const settings = { region: 'global', model: 'legacy/DeepSeek-R1', baseURL: 'https://gateway.invalid/v1', maxTokens: 393216, apiKey: 'fixture' };
  assert.equal((await request('/providers/deepseek', 'PUT', settings)).status, 200);
  const result = await request('/providers/deepseek/models', 'POST', {});
  assert.equal(result.status, 200);
  const state = new Store(directory, fakeVault).publicState();
  assert.deepEqual(state.providers.deepseek.models, ['legacy/DeepSeek-R1', 'custom/future-model']);
  assert.equal(state.providers.deepseek.model, 'legacy/DeepSeek-R1');
  assert.equal(state.providers.deepseek.maxTokens, 393216);
  assert.equal((await request('/providers/deepseek', 'PUT', { ...settings, maxTokens: 393217 })).status, 400);
});

test('workbench HTTP service preserves authentication, source policy, inverse persistence and retired research routes', async t => {
  const directory = folder(); let inputSeen;
  const service = await startServer({ directory, staticDir: path.resolve('dist'), port: 0, secretVault: fakeVault,
    inverseRunner: async input => { inputSeen = input; return { status: 'optimal', meanResidual: 0, input, theta: {}, history: [] }; } });
  t.after(() => service.close());
  const request = (route, method = 'GET', data, headers = {}) => fetch(service.origin + route, { method, headers: { 'x-fyppppp-token': service.token, 'content-type': 'application/json', ...headers }, ...(data !== undefined ? { body: JSON.stringify(data) } : {}) });
  assert.equal((await fetch(service.origin + '/api/state')).status, 401);
  assert.equal((await request('/api/state', 'GET', undefined, { origin: 'https://evil.invalid' })).status, 403);
  assert.equal((await request('/api/state', 'GET', undefined, { 'sec-fetch-site': 'cross-site' })).status, 403);
  for (const route of ['/api/experiments', '/api/solver', '/api/export']) assert.equal((await request(route)).status, 404);
  const demo = await (await request('/api/inverse/demo')).json();
  const response = await request('/api/inverse/recover', 'POST', { input: demo });
  assert.equal(response.status, 201);
  const run = await response.json(); assert.deepEqual(inputSeen, demo); assert.match(run.inputSha256, /^[a-f0-9]{64}$/);
  assert.equal((await (await request('/api/inverse/runs')).json()).length, 1);
  assert.equal((await (await request('/api/inverse/runs/' + run.id)).json()).status, 'optimal');
  assert.equal((await request('/api/inverse/runs/' + crypto.randomUUID())).status, 404);
  assert.equal((await request('/api/preferences', 'PATCH', { theme: 'unknown' })).status, 400);
  assert.equal((await request('/api/preferences', 'PATCH', { theme: 'graphite' })).status, 200);
});

test('closing service cancels active inverse work and never saves a partial result', async () => {
  const directory = folder(); let started;
  const ready = new Promise(resolve => { started = resolve; });
  const service = await startServer({ directory, staticDir: path.resolve('dist'), port: 0, secretVault: fakeVault,
    inverseRunner: (_input, { signal }) => new Promise((_resolve, reject) => { signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true }); started(); }) });
  const response = fetch(service.origin + '/api/inverse/recover', { method: 'POST', headers: { 'x-fyppppp-token': service.token, 'content-type': 'application/json' }, body: JSON.stringify({ input: {} }) });
  await ready; await service.close(); await response;
  assert.equal(fs.existsSync(path.join(directory, 'inverse-runs')), false);
});
