import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import http from 'node:http';
import { startServer } from '../server/http.mjs';
import { vault } from '../server/secrets.mjs';
import { Store } from '../server/store.mjs';
const directory = () => path.resolve('qa', 'server-' + crypto.randomUUID());
const fakeVault = { protect: async value => Buffer.from(value).toString('base64'), unprotect: async value => Buffer.from(value, 'base64').toString() };
const fakeGenerator = async function* (_config, _messages, signal) {
  yield { text: '测试响应，' };
  await new Promise((resolve, reject) => { const timer = setTimeout(resolve, 25); signal.addEventListener('abort', () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); }, { once: true }); });
  yield { text: '仅用于软件检查。', usage: { input: 8, output: 5 } };
};

test('single conversation export keeps all attempts and only linked solver evidence, without provider settings', async t => {
  const f = await fixture(); t.after(() => f.close());
  await f.request('/api/providers/openai', 'PUT', { apiKey: 'export-secret-fixture', region: 'global', model: 'test', maxTokens: 1024 });
  const selected = f.store.create(), unrelated = f.store.create();
  unrelated.messages.push({ role: 'user', content: 'unrelated-private-message' });
  const runId = crypto.randomUUID(), missingId = crypto.randomUUID();
  const run = { id: runId, status: 'optimal', model: { name: 'model fixture' }, log: 'solver evidence fixture', values: { A: 10 }, objective: 20 };
  f.solver.jobs.set(runId, run);
  f.solver.jobs.set(crypto.randomUUID(), { log: 'unrelated-solver-record' });
  selected.messages.push(
    { id: 'u', role: 'user', content: '预算改为290\n保留之前条件', status: 'complete', solverRunId: runId },
    { id: 'a1', role: 'assistant', content: '部分回答', status: 'stopped', usage: { input: null, output: null }, automation: { runId, plan: { action: 'solve' } } },
    { id: 'a2', role: 'assistant', content: '', status: 'error', error: 'fixture failure', provenance: { solverRun: { id: missingId } } }
  );
  f.store.touch(selected);
  const route = '/api/conversations/' + selected.id + '/export';
  assert.equal((await fetch(f.origin + route)).status, 401);
  assert.equal((await f.request('/api/conversations/' + crypto.randomUUID() + '/export')).status, 404);
  const response = await f.request(route), data = await response.json();
  assert.equal(response.status, 200);
  assert.deepEqual(data.conversations, [selected]);
  assert.deepEqual(data.solverRuns, [run]);
  assert.deepEqual(data.missingSolverRunIds, [missingId]);
  assert.ok(Number.isFinite(Date.parse(data.exportedAt)));
  for (const privateText of ['export-secret-fixture', 'encryptedKey', 'providers', 'unrelated-private-message', 'unrelated-solver-record']) assert.ok(!JSON.stringify(data).includes(privateText));
  run.status = 'running';
  assert.equal((await (await f.request(route)).json()).complete, false);
  run.status = 'optimal';
  const empty = f.store.create();
  const emptyExport = await (await f.request('/api/conversations/' + empty.id + '/export')).json();
  assert.deepEqual(emptyExport.conversations[0].messages, []);
  assert.deepEqual(emptyExport.solverRuns, []);
});

test('single conversation export rejects active generation and works after cancellation', async t => {
  const f = await fixture({ generator: async function* (_config, _messages, signal) {
    yield { text: 'partial export fixture' };
    await new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true }));
  } });
  t.after(() => f.close());
  await f.request('/api/providers/openai', 'PUT', { apiKey: 'fake-key', region: 'global', model: 'test', maxTokens: 1024 });
  const c = f.store.create(), controller = new AbortController();
  const response = await fetch(f.origin + '/api/chat', { method: 'POST', signal: controller.signal,
    headers: { 'content-type': 'application/json', 'x-fyppppp-token': f.token },
    body: JSON.stringify({ conversationId: c.id, provider: 'openai', message: 'export fixture' }) });
  await response.body.getReader().read();
  const route = '/api/conversations/' + c.id + '/export';
  assert.equal((await f.request(route)).status, 409);
  controller.abort();
  for (let i = 0; i < 50 && c.messages.at(-1).status === 'streaming'; i++) await new Promise(resolve => setTimeout(resolve, 20));
  const exported = await f.request(route);
  assert.equal(exported.status, 200);
  assert.equal((await exported.json()).conversations[0].messages.at(-1).status, 'stopped');
});
async function fixture(extra = {}) {
  const dir = directory();
  const server = await startServer({ directory: dir, staticDir: path.resolve('dist'), port: 0, secretVault: fakeVault, generator: fakeGenerator, planner: async () => { throw Error('Unexpected planner in chat-mode fixture; no network allowed'); }, ...extra });
  server.store.data.preferences.chatMode = 'chat'; server.store.save();
  const request = (url, method = 'GET', body, headers = {}) => fetch(server.origin + url, { method, headers: { 'content-type': 'application/json', 'x-fyppppp-token': server.token, ...headers }, body: body === undefined ? undefined : JSON.stringify(body) });
  return { ...server, request, dir };
}

test('experiment start returns safe actionable cap and source errors without dispatching a request',async t=>{
  const f=await fixture();t.after(()=>f.close());
  await f.request('/api/providers/openai','PUT',{apiKey:'local-fixture-only',region:'global',model:'test',maxTokens:1024});
  const created=await f.request('/api/experiments','POST',{title:'cap-check',cases:[{id:'case',prompt:'Minimize x with x >= 3.'}],presets:['generic','full'],requestCap:1,provider:'openai'});
  assert.equal(created.status,201);const b=await created.json();
  const response=await f.request(`/api/experiments/${b.id}/start`,'POST',{}),error=await response.json();
  assert.equal(response.status,400);assert.equal(error.code,'EXPERIMENT_REQUEST_CAP');assert.match(error.error,/8 次请求额度/);
  f.experiments.batches.get(b.id).sourceSnapshot.sha256='fixture-stale-source';
  const changed=await f.request(`/api/experiments/${b.id}/start`,'POST',{}),detail=await changed.json();
  assert.equal(detail.code,'EXPERIMENT_SOURCE_CHANGED');assert.match(detail.error,/源码、环境或评分器/);assert.equal(f.experiments.batches.get(b.id).requestCount,0);
});
test('local API requires token and rejects foreign origins/hosts', async t => {
  const f = await fixture(); t.after(() => f.close());
  assert.equal((await fetch(f.origin + '/api/state')).status, 401);
  assert.equal((await f.request('/api/state', 'GET', undefined, { Origin: 'https://example.com' })).status, 403);
  const hostStatus = await new Promise((resolve, reject) => { const req = http.get(f.origin + '/api/state', { headers: { Host: 'evil.example', 'x-fyppppp-token': f.token } }, res => { res.resume(); resolve(res.statusCode); }); req.on('error', reject); });
  assert.equal(hostStatus, 403);
  assert.equal((await f.request('/api/state', 'GET', undefined, { 'Sec-Fetch-Site': 'cross-site' })).status, 403);
  assert.equal((await f.request('/api/state')).status, 200);
  assert.equal((await fetch(f.origin)).status, 200);
});
test('settings keep keys outside frontend state/export; all six can be configured', async t => {
  const f = await fixture(); t.after(() => f.close());
  const initial = await (await f.request('/api/state')).json();
  assert.equal(initial.catalog.length, 6);
  for (const provider of initial.catalog) {
    const result = await f.request('/api/providers/' + provider.id, 'PUT', { apiKey: 'fake-secret-for-test', region: provider.regions[0].id, model: provider.defaultModel, maxTokens: 1024 });
    const text = await result.text(); assert.equal(result.status, 200, text); assert.ok(!text.includes('fake-secret-for-test')); assert.ok(!text.includes('encryptedKey'));
  }
  const exported = await (await f.request('/api/export')).text(); assert.ok(!exported.includes('fake-secret')); assert.ok(!exported.includes('providers'));
  const rejected = await f.request('/api/providers/openai', 'PUT', { region: 'global', model: 'test', baseURL: 'http://insecure.example', maxTokens: 1024 }); assert.equal(rejected.status, 400);
});
test('stream completes, retries preserve previous attempts, failures persist, reload works', async t => {
  let fail = false;
  const f = await fixture({ generator: async function* (...args) { if (fail) throw Object.assign(new Error('do-not-leak-secret'), { status: 401 }); yield* fakeGenerator(...args); } }); t.after(() => f.close());
  await f.request('/api/providers/openai', 'PUT', { apiKey: 'fake-key', region: 'global', model: 'test-model', maxTokens: 1024 });
  const c = await (await f.request('/api/conversations', 'POST', {})).json();
  const run = async retry => { const r = await f.request('/api/chat', 'POST', { conversationId: c.id, provider: 'openai', message: '软件验收用输入，不是研究数据', retry }); assert.equal(r.status, 200); return r.text(); };
  let stream = await run(false); assert.match(stream, /测试响应/); assert.match(stream, /"type":"done"/);
  fail = true; stream = await run(true); assert.ok(!stream.includes('do-not-leak-secret')); assert.match(stream, /密钥无效/);
  const saved = await (await f.request('/api/conversations/' + c.id)).json();
  assert.equal(saved.messages.length, 3); assert.equal(saved.messages[1].status, 'complete'); assert.equal(saved.messages[2].status, 'error');
  assert.equal(saved.messages[1].usage.input, 8); assert.equal(saved.messages[2].usage.input, null);
  const audit = fs.readFileSync(path.join(f.dir, 'requests.ndjson'), 'utf8').trim().split('\n'); assert.equal(audit.length, 2);
  assert.ok(!audit.join('').includes('fake-key'));
  assert.equal(JSON.parse(fs.readFileSync(path.join(f.dir, 'workspace.json'))).conversations[0].messages.length, 3);
});
test('client cancellation retains partial output and allows a later request', async t => {
  const f = await fixture({ generator: async function* (_config, _messages, signal) { yield { text: '保留这段已生成内容' }; await new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })); } }); t.after(() => f.close());
  await f.request('/api/providers/openai', 'PUT', { apiKey: 'fake-key', region: 'global', model: 'test', maxTokens: 1024 });
  const c = await (await f.request('/api/conversations', 'POST', {})).json();
  const controller = new AbortController();
  const r = await fetch(f.origin + '/api/chat', { method: 'POST', headers: { 'content-type': 'application/json', 'x-fyppppp-token': f.token }, body: JSON.stringify({ conversationId: c.id, provider: 'openai', message: '取消测试' }), signal: controller.signal });
  const reader = r.body.getReader(); await reader.read(); controller.abort();
  let saved;
  for (let i = 0; i < 30; i++) { await new Promise(r => setTimeout(r, 20)); saved = await (await f.request('/api/conversations/' + c.id)).json(); if (saved.messages.at(-1).status !== 'streaming') break; }
  assert.equal(saved.messages.at(-1).status, 'stopped'); assert.equal(saved.messages.at(-1).content, '保留这段已生成内容');
});
test('Windows DPAPI round trip protects persisted test key', { skip: process.platform !== 'win32' }, async () => {
  const secret = 'qa-only-' + crypto.randomUUID(), encrypted = await vault.protect(secret);
  assert.notEqual(encrypted, secret); assert.ok(!encrypted.includes(secret)); assert.equal(await vault.unprotect(encrypted), secret);
});

test('v0.1 workspace upgrade preserves conversations and encrypted provider keys', () => {
  const dir = directory(), initial = new Store(dir, fakeVault);
  const existing = initial.create(); existing.title = '既有对话'; existing.messages.push({ id: 'legacy-message', role: 'user', content: 'Keep original content', status: 'complete' });
  initial.data.providers.openai.encryptedKey = 'preserve-exact-encrypted-value';
  delete initial.data.preferences.language; delete initial.data.preferences.fontSize;
  initial.data.preferences.theme = 'navy'; initial.save();
  const before = structuredClone(initial.data), upgraded = new Store(dir, fakeVault);
  assert.equal(upgraded.data.preferences.language, 'zh-CN'); assert.equal(upgraded.data.preferences.fontSize, 18);
  assert.equal(upgraded.data.preferences.theme, 'navy');
  assert.deepEqual(upgraded.data.providers, before.providers); assert.deepEqual(upgraded.data.conversations, before.conversations);
});

test('language/font preferences validate, persist and pass language to generation', async t => {
  let receivedLanguage;
  const f = await fixture({ generator: async function* (config) { receivedLanguage = config.language; yield { text: 'Software fixture only' }; } }); t.after(() => f.close());
  let response = await f.request('/api/preferences', 'PATCH', { language: 'en', fontSize: 24 }); assert.equal(response.status, 200);
  for (const invalid of [{ fontSize: 13 }, { fontSize: 25 }, { fontSize: '20' }, { language: 'de' }]) { response = await f.request('/api/preferences', 'PATCH', { theme: 'black', ...invalid }); assert.equal(response.status, 400); }
  const persisted = new Store(f.dir, fakeVault); assert.equal(persisted.data.preferences.language, 'en'); assert.equal(persisted.data.preferences.fontSize, 24); assert.equal(persisted.data.preferences.theme, 'light');
  await f.request('/api/providers/openai', 'PUT', { apiKey: 'fake-key', region: 'global', model: 'test', maxTokens: 1024 });
  const conversation = await (await f.request('/api/conversations', 'POST', {})).json(); assert.equal(conversation.title, 'New chat');
  await (await f.request('/api/chat', 'POST', { conversationId: conversation.id, provider: 'openai', message: 'An English title' })).text();
  assert.equal(receivedLanguage, 'en'); assert.equal(f.store.get(conversation.id).title, 'An English title');
  assert.equal(f.store.get(conversation.id).messages[0].content, 'An English title');
});

test('LLM assertions cannot create solver badges; server attaches only real completed runs', async t => {
  let received;
  const f = await fixture({ generator: async function* (_config, messages) { received = messages; yield { text: 'I ran HiGHS and verified this result: 99999. (Deliberately false QA assertion)' }; } }); t.after(() => f.close());
  await f.request('/api/providers/openai', 'PUT', { apiKey: 'fake-key', region: 'global', model: 'test', maxTokens: 1024 });
  const c = await (await f.request('/api/conversations', 'POST', {})).json();
  const send = extra => f.request('/api/chat', 'POST', { conversationId: c.id, provider: 'openai', message: 'QA only', ...extra });
  await (await send({ provenance: { source: 'solver' } })).text();
  assert.deepEqual(f.store.get(c.id).messages.at(-1).provenance, { source: 'llm' });
  assert.equal((await send({ solverRunId: 'made-up-id' })).status, 400);
  const { demoModel } = await import('../shared/solver-model.mjs');
  const r = f.solver.start({ model: demoModel, engine: 'highs', seconds: 15, problem: 'Software demo only' });
  while (r.status === 'running') await new Promise(resolve => setTimeout(resolve, 100));
  assert.equal(r.status, 'optimal'); assert.equal(r.provenance.solverInvoked, true); assert.equal(r.modelHash.length, 64);
  await (await send({ solverRunId: r.id, objective: 99999 })).text();
  const answer = f.store.get(c.id).messages.at(-1);
  assert.equal(answer.provenance.source, 'llm'); assert.equal(answer.provenance.solverRun.id, r.id);
  assert.match(received.at(-1).content, /"objective":1000/); assert.ok(!received.at(-1).content.includes('99999'));
  await (await send({ retry: true })).text(); assert.equal(f.store.get(c.id).messages.at(-1).provenance.solverRun.id, r.id);
});

test('non-ASCII authentication headers are rejected without crashing the local service', async t => {
  const f = await fixture(); t.after(() => f.close());
  const response = await f.request('/api/state', 'GET', undefined, { 'x-fyppppp-token': 'é'.repeat(64) });
  assert.equal(response.status, 401);
  assert.equal((await f.request('/api/state')).status, 200);
});
