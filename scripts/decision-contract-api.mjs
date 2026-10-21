/** Bounded research requests. Every attempted request is reserved on disk first. */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import crypto from 'node:crypto';
import { Store } from '../server/store.mjs';
import { vault } from '../server/secrets.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
const option = (name, fallback) => { const i = args.indexOf(name); return i < 0 ? fallback : args[i + 1]; };
const out = path.resolve(root, option('--out', '实验/决策契约研究_2026-10-21_01'));
const relative = path.relative(path.join(root, '实验'), out);
if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) throw Error('Output must be an experiment child');
const queue = JSON.parse(fs.readFileSync(path.resolve(option('--queue', '')), 'utf8'));
if (!Array.isArray(queue) || new Set(queue.map(x => x.id)).size !== queue.length) throw Error('Invalid or duplicate requests');
fs.mkdirSync(path.join(out, 'network'), { recursive: true });
const lock = path.join(out, 'request.lock');
const fd = fs.openSync(lock, 'wx');
const save = (file, data) => fs.writeFileSync(file, JSON.stringify(data, null, 2) + '\n', { flag: 'wx' });
let secret = '';
try {
  const state = JSON.parse(fs.readFileSync(path.join(process.env.LOCALAPPDATA, 'FYPPPPP/workspace/inverse-workspace.json'), 'utf8').replace(/^\uFEFF/, ''));
  const config = await Store.prototype.credentials.call({ data: state, vault }, 'deepseek');
  secret = config.apiKey;
  const endpoint = new URL(config.baseURL.replace(/\/$/, '') + '/chat/completions');
  if (endpoint.protocol !== 'https:' || endpoint.hostname !== 'api.deepseek.com') throw Error('Unexpected credential destination');
  const ledger = path.join(out, 'calls.jsonl');
  const existing = fs.existsSync(ledger) ? fs.readFileSync(ledger, 'utf8').trim().split('\n').filter(Boolean).map(JSON.parse) : [];
  const attempted = new Set(existing.filter(x => x.event === 'started').map(x => x.id));
  let count = attempted.size, position = 0, transportFailures = 0;
  const record = data => fs.appendFileSync(ledger, JSON.stringify({ ...data, utc: new Date().toISOString() }) + '\n');
  async function worker() {
    while (position < queue.length && transportFailures < 3) {
      const item = queue[position++];
      if (!/^[A-Za-z0-9_-]+$/.test(item.id)) throw Error('Unsafe request ID');
      if (attempted.has(item.id)) continue; // Completed or failed attempts are never silently repeated.
      if (count >= 300) throw Error('Global 300 request ceiling reached');
      const tokens = item.maxTokens ?? 4096;
      if (!Number.isInteger(tokens) || tokens < 1 || tokens > 8192) throw Error('Invalid token limit');
      const request = { model: config.model, messages: item.messages, temperature: 0,
        thinking: { type: 'disabled' }, max_tokens: tokens, stream: false,
        ...(item.json ? { response_format: { type: 'json_object' } } : {}) };
      const file = path.join(out, 'network', item.id);
      save(file + '.request.json', request);
      const sequence = ++count;
      record({ event: 'started', id: item.id, sequence, model: config.model,
        promptSha256: crypto.createHash('sha256').update(JSON.stringify(request)).digest('hex') });
      attempted.add(item.id);
      const start = performance.now();
      let result;
      try {
        const response = await fetch(endpoint, { method: 'POST', redirect: 'error',
          headers: { Authorization: `Bearer ${secret}`, 'Content-Type': 'application/json' },
          body: JSON.stringify(request), signal: AbortSignal.timeout(150000) });
        const rawText = await response.text();
        fs.writeFileSync(file + '.raw.json', rawText.replaceAll(secret, '[REDACTED]'), { flag: 'wx' });
        const raw = JSON.parse(rawText);
        const finish = raw.choices?.[0]?.finish_reason;
        result = { status: response.ok && finish === 'stop' ? 'complete' : 'failed',
          httpStatus: response.status, responseId: raw.id ?? null, returnedModel: raw.model ?? null,
          text: raw.choices?.[0]?.message?.content ?? '', finishReason: finish ?? null, usage: raw.usage ?? null };
        if (!response.ok) transportFailures++;
      } catch (error) {
        transportFailures++;
        result = { status: 'failed', error: String(error.message).replaceAll(secret, '[REDACTED]'), usage: null };
      }
      result.wallMs = performance.now() - start;
      save(file + '.result.json', result);
      record({ event: 'finished', id: item.id, sequence, status: result.status, usage: result.usage, wallMs: result.wallMs });
      console.log(JSON.stringify({ id: item.id, status: result.status, attempted: count, ceiling: 300 }));
    }
  }
  const concurrency = Math.max(1, Math.min(3, Number(option('--concurrency', '2'))));
  await Promise.all(Array.from({ length: concurrency }, worker));
  if (transportFailures >= 3) throw Error('Transport failure circuit breaker reached; attempts retained');
} catch (error) {
  console.error(String(error.message).replaceAll(secret || '\0', '[REDACTED]'));
  process.exitCode = 1;
} finally {
  fs.closeSync(fd);
  fs.unlinkSync(lock);
}
