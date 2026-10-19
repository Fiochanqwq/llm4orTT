import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { ChatService } from '../server/chat.mjs';
import { startServer } from '../server/http.mjs';

const directory = () => { const dir = path.resolve('qa', 'chat-' + crypto.randomUUID()); fs.mkdirSync(dir, { recursive: true }); return dir; };
const config = async () => ({ id: 'openai', model: 'fixture' });
const request = (id, extra = {}) => ({ conversationId: id, message: '你好', requestId: crypto.randomUUID(), ...extra });

test('ordinary chat restores legacy text, preserves source history and does not resurrect deleted chats', () => {
  const dir = directory(), file = path.join(dir, 'workspace.json');
  const legacy = JSON.stringify({ conversations: [{ id: 'old-id', title: '以前的聊天', messages: [{ id: 'u', role: 'user', content: '以前的问题' }, { id: 'a', role: 'assistant', content: '以前的回答', automation: { secret: 'old-research' }, status: 'streaming' }] }] });
  fs.writeFileSync(file, legacy);
  const chats = new ChatService(dir), restored = chats.get('old-id');
  assert.equal(restored.messages[1].content, '以前的回答'); assert.equal(restored.messages[1].status, 'stopped');
  assert.ok(!JSON.stringify(restored).includes('old-research')); assert.equal(fs.readFileSync(file, 'utf8'), legacy);
  chats.remove('old-id'); assert.equal(new ChatService(dir).list().length, 0);
});

test('chat keeps context, sends plain-chat purpose, persists replies, deduplicates and retries', async () => {
  const dir = directory(), chats = new ChatService(dir), c = chats.create(), events = [], seen = [];
  const generator = async function* (settings, messages) { seen.push(messages); assert.equal(settings.purpose, 'chat'); yield { text: '普通' }; yield { text: '回答' }; };
  const signal = new AbortController().signal, first = request(c.id);
  await chats.send(first, config, generator, signal, event => events.push(structuredClone(event)));
  assert.deepEqual(events.map(e => e.type), ['start', 'delta', 'delta', 'done']);
  assert.equal(chats.get(c.id).messages[1].content, '普通回答');
  await chats.send(first, config, generator, signal, () => {}); assert.equal(seen.length, 1);
  await chats.send(request(c.id, { message: '再说说' }), config, generator, signal, () => {});
  assert.deepEqual(seen[1].map(m => m.role), ['user', 'assistant', 'user']);
  await chats.send(request(c.id, { retry: true }), config, generator, signal, () => {});
  assert.equal(chats.get(c.id).messages.length, 4); assert.equal(seen[2].at(-1).content, '再说说');
  chats.rename(c.id, '我的对话'); assert.equal(new ChatService(dir).get(c.id).title, '我的对话');
});

test('missing credentials never consumes user message; provider error preserves a retryable turn', async () => {
  const chats = new ChatService(directory()), c = chats.create(), signal = new AbortController().signal;
  await assert.rejects(chats.send(request(c.id), async () => { throw Error('请先填写密钥'); }, async function* () {}, signal, () => {}), /请先/);
  assert.equal(c.messages.length, 0);
  await chats.send(request(c.id), config, async function* () { yield { text: '部分内容' }; throw Object.assign(Error('secret sk-private'), { status: 429 }); }, signal, () => {});
  assert.equal(c.messages[1].status, 'error'); assert.equal(c.messages[1].content, '部分内容'); assert.ok(!c.messages[1].error.includes('sk-private'));
});

test('HTTP streaming and stop retain partial content, enforce one generation and survive restart', async t => {
  const dir = directory(); let ready;
  const started = new Promise(resolve => { ready = resolve; });
  const service = await startServer({ directory: dir, staticDir: path.resolve('dist'), port: 0, secretVault: { protect: async x => x, unprotect: async x => x },
    generator: async function* (_config, _messages, signal) { yield { text: '已经收到' }; ready(); await new Promise((resolve, reject) => { signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true }); }); } });
  t.after(() => service.close());
  const call = (route, method = 'GET', data) => fetch(service.origin + '/api' + route, { method, headers: { 'content-type': 'application/json', 'x-fyppppp-token': service.token }, ...(data ? { body: JSON.stringify(data) } : {}) });
  await service.store.configure('openai', { ...service.store.data.providers.openai, apiKey: 'fixture-key' });
  const c = await (await call('/conversations', 'POST', {})).json();
  const response = call('/chat', 'POST', request(c.id)); await started;
  assert.equal((await call('/chat', 'POST', request(c.id))).status, 400);
  assert.equal((await call('/conversations/' + c.id, 'DELETE')).status, 400);
  await call('/conversations/' + c.id + '/stop', 'POST', {});
  const chunks = (await (await response).text()).trim().split('\n').map(JSON.parse);
  assert.equal(chunks.at(-1).conversation.messages[1].status, 'stopped');
  assert.equal(new ChatService(dir).get(c.id).messages[1].content, '已经收到');
  assert.equal((await call('/conversations/' + c.id, 'DELETE')).status, 200);
});

test('unreadable history fails safely rather than silently erasing it', () => {
  const dir = directory(), file = path.join(dir, 'conversations.json'); fs.writeFileSync(file, '{broken');
  assert.throws(() => new ChatService(dir), /本地记录/); assert.equal(fs.readFileSync(file, 'utf8'), '{broken');
});
