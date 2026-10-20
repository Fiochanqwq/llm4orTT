import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import packageInfo from '../package.json' with { type: 'json' };
import { Store, catalog } from './store.mjs';
import { vault } from './secrets.mjs';
import { generate, listModels, testConnection, readableError } from './providers.mjs';
import { StorageError } from './persistence.mjs';
import { UserInputError } from './user-error.mjs';
import { listenLoopback } from './listen-loopback.mjs';
import { ChatService } from './chat.mjs';
import { inverseDemo, listInverseRuns, readInverseRun, runInversePipeline, saveInverseRun } from './inverse.mjs';

const mime = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon' };
export async function startServer({ directory, staticDir, port = 43127, dev = false, externalOrigin = null, secretVault = vault, generator = generate, modelLister = listModels, connectionTester = testConnection, inverseRunner = runInversePipeline }) {
  if (externalOrigin && (new URL(externalOrigin).protocol !== 'https:' || new URL(externalOrigin).origin !== externalOrigin)) throw Error('Invalid external origin');
  const store = new Store(directory, secretVault), token = crypto.randomBytes(32).toString('hex'), active = new Set();
  const chats = new ChatService(directory);
  let origin, inverseBusy = false;
  const json = (res, status, data) => { if (res.destroyed || res.writableEnded) return; res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' }); res.end(JSON.stringify(data)); };
  async function body(req) {
    if (!req.headers['content-type']?.includes('application/json')) throw new UserInputError('INPUT', '请求需要 JSON');
    let size = 0; const chunks = [];
    for await (const chunk of req) { size += chunk.length; if (size > 2 * 1024 * 1024) throw new UserInputError('INPUT', '输入不能超过 2 MB'); chunks.push(chunk); }
    try { return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks)) || '{}'); }
    catch { throw new UserInputError('INPUT', 'JSON 格式无效'); }
  }
  async function cancellable(res, milliseconds, action) {
    const controller = new AbortController(); active.add(controller);
    const timer = setTimeout(() => controller.abort(), milliseconds);
    const closed = () => { if (!res.writableEnded) controller.abort(); }; res.on('close', closed);
    try { return await action(controller.signal); }
    finally { clearTimeout(timer); active.delete(controller); res.removeListener('close', closed); }
  }
  const server = http.createServer(async (req, res) => {
    try {
      res.setHeader('X-Content-Type-Options', 'nosniff'); res.setHeader('Referrer-Policy', 'no-referrer'); res.setHeader('X-Frame-Options', 'DENY');
      res.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'");
      const allowed = [origin, ...(externalOrigin ? [externalOrigin] : []), ...(dev ? ['http://127.0.0.1:5173'] : [])];
      if (!allowed.some(o => new URL(o).host === req.headers.host) || (req.headers.origin && !allowed.includes(req.headers.origin)) || req.headers['sec-fetch-site'] === 'cross-site') return json(res, 403, { error: '访问来源无效' });
      const route = new URL(req.url, origin).pathname;
      if (route === '/api/health') return json(res, 200, { app: 'llm4orTT', version: packageInfo.version });
      if (route.startsWith('/api/')) {
        const incoming = req.headers['x-fyppppp-token'];
        if (typeof incoming !== 'string' || !/^[a-f0-9]{64}$/.test(incoming) || !crypto.timingSafeEqual(Buffer.from(incoming), Buffer.from(token))) return json(res, 401, { error: '请从桌面快捷方式打开程序' });
      }
      if (route === '/api/state' && req.method === 'GET') return json(res, 200, store.publicState());
      if (route === '/api/conversations' && req.method === 'GET') return json(res, 200, chats.list());
      if (route === '/api/conversations' && req.method === 'POST') return json(res, 201, chats.create());
      const conversation = route.match(/^\/api\/conversations\/([^/]+)(?:\/(stop))?$/);
      if (conversation) {
        const [, id, action] = conversation;
        if (action === 'stop' && req.method === 'POST') { chats.stop(id); return json(res, 200, { ok: true }); }
        if (!action && req.method === 'GET') return json(res, 200, chats.get(id));
        if (!action && req.method === 'PATCH') return json(res, 200, chats.rename(id, (await body(req)).title));
        if (!action && req.method === 'DELETE') { chats.remove(id); return json(res, 200, { ok: true }); }
      }
      if (route === '/api/chat' && req.method === 'POST') {
        const request = await body(req);
        const emit = value => {
          if (res.destroyed || res.writableEnded) return;
          if (!res.headersSent) res.writeHead(200, { 'Content-Type': 'application/x-ndjson; charset=utf-8', 'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no' });
          res.write(JSON.stringify(value) + '\n');
        };
        try {
          await cancellable(res, 600000, signal => chats.send(request, () => store.credentials(request.provider || store.data.preferences.provider), generator, signal, emit));
        } catch (error) {
          if (!res.headersSent) throw error;
          emit({ type: 'error', error: error instanceof StorageError ? error.message : readableError(error) });
        }
        res.end(); return;
      }
      if (route === '/api/preferences' && req.method === 'PATCH') {
        const values = await body(req);
        if (values.provider !== undefined && !catalog.some(p => p.id === values.provider)) throw new UserInputError('INPUT', '服务商无效');
        if (values.theme !== undefined && !['light', 'graphite'].includes(values.theme)) throw new UserInputError('INPUT', '主题无效');
        for (const key of ['provider', 'theme']) if (values[key] !== undefined) store.data.preferences[key] = values[key];
        store.save(); return json(res, 200, store.publicState());
      }
      const provider = route.match(/^\/api\/providers\/([a-z]+)(?:\/(models|test))?$/);
      if (provider) {
        const [, id, action] = provider;
        if (!catalog.some(p => p.id === id)) return json(res, 404, { error: '服务商不存在' });
        if (!action && req.method === 'PUT') { try { return json(res, 200, await store.configure(id, await body(req))); } catch (e) { throw e instanceof StorageError ? e : new UserInputError('PROVIDER_SETTINGS', e.message); } }
        if (action && req.method === 'POST') {
          const value = await cancellable(res, 120000, async signal => {
            const config = await store.credentials(id);
            try { return await (action === 'test' ? connectionTester : modelLister)(config, signal); }
            catch (e) { throw new UserInputError('PROVIDER', readableError(e)); }
          });
          if (action === 'models') {
            store.assertWritable();
            store.data.providers[id].models = value.models;
            store.save();
          }
          return json(res, 200, value);
        }
      }
      if (route === '/api/inverse/demo' && req.method === 'GET') return json(res, 200, inverseDemo());
      if (route === '/api/inverse/runs' && req.method === 'GET') return json(res, 200, listInverseRuns(directory));
      const run = route.match(/^\/api\/inverse\/runs\/([a-f0-9-]{36})$/);
      if (run && req.method === 'GET') { try { return json(res, 200, readInverseRun(directory, run[1])); } catch (e) { if (e.code === 'ENOENT') return json(res, 404, { error: '运行不存在' }); throw e; } }
      if (route === '/api/inverse/recover' && req.method === 'POST') {
        if (inverseBusy) return json(res, 409, { error: '已有任务正在运行' });
        const request = await body(req); store.assertWritable();
        if (inverseBusy) return json(res, 409, { error: '已有任务正在运行' });
        inverseBusy = true;
        try {
          const result = await cancellable(res, 600000, async signal => {
            const config = request.useLLM === true ? await store.credentials(request.provider || store.data.preferences.provider) : null;
            const value = await inverseRunner(request.input, { config, generator, signal, useLLM: request.useLLM === true, rounds: request.rounds ?? 3,
              localAnalysis: request.localAnalysis === true, maxModelCalls: request.maxModelCalls ?? 1, cacheDirectory: path.join(directory, 'inverse-proposal-cache') });
            signal.throwIfAborted(); store.assertWritable(); return saveInverseRun(directory, value);
          });
          return json(res, 201, result);
        } catch (e) { throw e instanceof UserInputError || e instanceof StorageError ? e : new UserInputError('INVERSE_FAILED', readableError(e)); }
        finally { inverseBusy = false; }
      }
      if (route.startsWith('/api/')) return json(res, 404, { error: '接口不存在' });
      if (!['GET', 'HEAD'].includes(req.method)) return json(res, 405, { error: '方法不支持' });
      const root = path.resolve(staticDir); let file = path.resolve(root, decodeURIComponent(route).replace(/^\/+/, '') || 'index.html');
      if (!file.startsWith(root + path.sep)) return json(res, 403, { error: '路径无效' });
      if (!fs.existsSync(file) || !fs.statSync(file).isFile()) file = path.join(root, 'index.html');
      if (!fs.existsSync(file)) return json(res, 503, { error: '请先构建前端' });
      res.writeHead(200, { 'Content-Type': mime[path.extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-cache' });
      if (req.method === 'HEAD') res.end(); else fs.createReadStream(file).on('error', () => res.destroy()).pipe(res);
    } catch (e) { json(res, e instanceof StorageError ? 503 : 400, { error: e instanceof StorageError || e instanceof UserInputError || /^请先/.test(e.message) ? e.message : '操作失败，请检查输入后重试' }); }
  });
  await listenLoopback(server, port); origin = 'http://127.0.0.1:' + server.address().port;
  return { server, store, token, origin, close: async () => { for (const controller of active) controller.abort(); await new Promise(resolve => server.close(resolve)); } };
}
