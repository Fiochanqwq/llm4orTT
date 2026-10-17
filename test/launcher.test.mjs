import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import packageInfo from '../package.json' with { type: 'json' };
import { ensureService } from '../server/launcher.mjs';

for (const version of ['0.6.2', packageInfo.version]) test('existing local service version check: ' + version, async t => {
  const server = http.createServer((req, res) => { res.setHeader('content-type', 'application/json'); res.end(JSON.stringify(req.url === '/api/state' ? { version: 1 } : { app: 'llm4orOvO', version })); });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  const directory = path.resolve('qa', 'launcher-' + crypto.randomUUID()); fs.mkdirSync(directory, { recursive: true });
  const runtime = JSON.stringify({ origin: 'http://127.0.0.1:' + server.address().port, token: 'fixture', pid: process.pid });
  const file = path.join(directory, 'runtime.json'); fs.writeFileSync(file, runtime);
  if (version === packageInfo.version) assert.equal((await ensureService({ directory })).owned, false);
  else await assert.rejects(() => ensureService({ directory }), /旧版本服务仍在运行/);
  assert.equal(fs.readFileSync(file, 'utf8'), runtime);
  assert.equal(fs.existsSync(path.join(directory, 'workspace.json')), false);
});
