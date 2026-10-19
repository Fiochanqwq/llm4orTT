import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { atomicJson, StorageError } from './persistence.mjs';
import { UserInputError } from './user-error.mjs';
import { readableError } from './providers.mjs';

const uuid = () => crypto.randomUUID();
const now = () => new Date().toISOString();
const invalid = message => new UserInputError('CHAT_INPUT', message);
const valid = data => data?.version === 1 && Array.isArray(data.conversations) && data.conversations.every(c => typeof c.id === 'string' && typeof c.title === 'string' && Array.isArray(c.messages) && c.messages.every(m => typeof m.content === 'string' && ['user', 'assistant'].includes(m.role)));

export class ChatService {
  constructor(directory) {
    this.file = path.join(directory, 'conversations.json'); this.busy = new Map();
    let data;
    for (const file of [this.file, this.file + '.bak']) {
      try { const value = JSON.parse(fs.readFileSync(file, 'utf8')); if (valid(value)) { data = value; break; } }
      catch (e) { if (!(e instanceof SyntaxError) && e.code !== 'ENOENT') throw new StorageError(e); }
    }
    if (!data && (fs.existsSync(this.file) || fs.existsSync(this.file + '.bak'))) throw new StorageError(new Error('Chat history is unreadable'));
    if (!data) {
      let legacy;
      for (const file of ['workspace.json', 'workspace.json.bak']) {
        try { const value = JSON.parse(fs.readFileSync(path.join(directory, file), 'utf8')); if (Array.isArray(value.conversations)) { legacy = value.conversations; break; } }
        catch (e) { if (!(e instanceof SyntaxError) && e.code !== 'ENOENT') throw new StorageError(e); }
      }
      data = { version: 1, conversations: (legacy || []).filter(c => c && Array.isArray(c.messages)).map(c => ({
        id: typeof c.id === 'string' ? c.id : uuid(), title: String(c.title || '新对话'), createdAt: c.createdAt || now(), updatedAt: c.updatedAt || now(),
        messages: c.messages.filter(m => ['user', 'assistant'].includes(m.role) && typeof m.content === 'string').map(m => ({ id: m.id || uuid(), role: m.role, content: m.content, createdAt: m.createdAt || now(), status: m.status === 'streaming' ? 'stopped' : (m.status || 'complete'), ...(m.error ? { error: m.error } : {}) }))
      })) };
    }
    this.data = data;
    for (const c of data.conversations) for (const m of c.messages) if (m.status === 'streaming') { m.status = 'stopped'; m.error = '上次生成已中断'; }
    this.committed = structuredClone(data); this.save();
  }
  save() {
    if (this.failure) throw this.failure;
    try { atomicJson(this.file + '.bak', this.committed); atomicJson(this.file, this.data); this.committed = structuredClone(this.data); }
    catch (e) { this.data = structuredClone(this.committed); this.failure = e instanceof StorageError ? e : new StorageError(e); throw this.failure; }
  }
  list() { return this.data.conversations.toSorted((a, b) => b.updatedAt.localeCompare(a.updatedAt)); }
  get(id) { const c = this.data.conversations.find(c => c.id === id); if (!c) throw invalid('对话不存在'); return c; }
  create() { const c = { id: uuid(), title: '新对话', createdAt: now(), updatedAt: now(), messages: [] }; this.data.conversations.push(c); this.save(); return c; }
  rename(id, title) { if (typeof title !== 'string' || !title.trim() || title.length > 200) throw invalid('标题需为 1–200 个字符'); const c = this.get(id); c.title = title.trim(); c.updatedAt = now(); this.save(); return c; }
  remove(id) { if (this.busy.has(id)) throw invalid('请先停止正在生成的回复'); this.get(id); this.data.conversations = this.data.conversations.filter(c => c.id !== id); this.save(); }
  stop(id) { this.busy.get(id)?.abort(); }
  async send(request, credentials, generator, externalSignal, emit) {
    const { conversationId: id, message, requestId, retry = false } = request;
    if (typeof requestId !== 'string' || !/^[a-f0-9-]{36}$/.test(requestId)) throw invalid('请求编号无效');
    const c = this.get(id);
    if (this.busy.has(id)) throw invalid('这段对话正在生成，请稍候');
    if (c.messages.some(m => m.requestId === requestId)) { emit({ type: 'done', conversation: c }); return; }
    if (retry !== true && (typeof message !== 'string' || !message.trim() || message.length > 100000)) throw invalid('消息不能为空，且不能超过 10 万字');
    if (retry === true && !(c.messages.at(-1)?.role === 'assistant' && c.messages.at(-2)?.role === 'user')) throw invalid('没有可以重试的回复');
    const controller = new AbortController(), abort = () => controller.abort();
    this.busy.set(id, controller); externalSignal.addEventListener('abort', abort, { once: true });
    let reply;
    try {
      externalSignal.throwIfAborted();
      const config = { ...await credentials(), purpose: 'chat' };
      controller.signal.throwIfAborted();
      const context = (retry ? c.messages.slice(0, -1) : [...c.messages, { role: 'user', content: message.trim() }]).filter(m => m.content).map(({ role, content }) => ({ role, content }));
      if (context.reduce((n, m) => n + m.content.length, 0) > 500000) throw invalid('这段对话太长，请新建对话后继续');
      if (retry) c.messages.pop();
      else {
        c.messages.push({ id: uuid(), role: 'user', content: message.trim(), createdAt: now(), status: 'complete' });
        if (c.title === '新对话') c.title = message.trim().replace(/\s+/g, ' ').slice(0, 36);
      }
      reply = { id: uuid(), requestId, role: 'assistant', content: '', createdAt: now(), status: 'streaming', model: config.model };
      c.messages.push(reply); c.updatedAt = now(); this.save(); emit({ type: 'start', conversation: c });
      let checkpoint = Date.now();
      for await (const chunk of generator(config, context, controller.signal)) {
        controller.signal.throwIfAborted();
        if (chunk.text) {
          if (reply.content.length + chunk.text.length > 1000000) throw invalid('回复过长，已停止');
          reply.content += chunk.text; emit({ type: 'delta', text: chunk.text });
        }
        if (chunk.warning) reply.warning = chunk.warning;
        if (chunk.usage) reply.usage = { ...reply.usage, ...chunk.usage };
        if (Date.now() - checkpoint > 500) { this.save(); checkpoint = Date.now(); }
      }
      controller.signal.throwIfAborted();
      if (!reply.content) throw invalid('模型返回了空回复，请重试');
      reply.status = 'complete';
    } catch (error) {
      if (!reply) throw error;
      reply.status = controller.signal.aborted ? 'stopped' : 'error';
      reply.error = controller.signal.aborted ? '已停止生成' : error instanceof UserInputError || error instanceof StorageError ? error.message : readableError(error);
    } finally {
      externalSignal.removeEventListener('abort', abort); this.busy.delete(id);
      if (reply) { c.updatedAt = now(); this.save(); emit({ type: 'done', conversation: c }); }
    }
  }
}
