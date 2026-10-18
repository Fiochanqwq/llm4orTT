import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { fileVault } from '../server/file-vault.mjs';
import { codespaceConfig } from '../server/codespace-config.mjs';
import { startServer } from '../server/http.mjs';

test('cloud vault persists encrypted keys and rejects tampering and other workspaces', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'llm4or-vault-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const vault = fileVault(dir), value = 'test-only-key', encrypted = await vault.protect(value);
  assert.ok(!encrypted.includes(value));
  assert.notEqual(encrypted, await vault.protect(value));
  assert.equal(await fileVault(dir).unprotect(encrypted), value);
  const bytes = Buffer.from(encrypted.slice(3), 'base64'); bytes[bytes.length - 1] ^= 1;
  await assert.rejects(() => vault.unprotect('v1:' + bytes.toString('base64')));
  await assert.rejects(() => fileVault(path.join(dir, 'other')).unprotect(encrypted));
  await assert.rejects(() => vault.unprotect('legacy-dpapi'));
  if (process.platform !== 'win32') assert.equal(fs.statSync(path.join(dir, 'vault.key')).mode & 0o777, 0o600);
});

test('Codespaces origin is explicit and does not accept URLs from arbitrary input', () => {
  const env = { CODESPACES: 'true', CODESPACE_NAME: 'my-space-123', GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN: 'app.github.dev' };
  assert.equal(codespaceConfig(env).externalOrigin, 'https://my-space-123-43127.app.github.dev');
  assert.throws(() => codespaceConfig({}));
  assert.throws(() => codespaceConfig({ ...env, CODESPACE_NAME: 'bad/host' }));
  assert.throws(() => codespaceConfig({ ...env, GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN: 'host/path' }));
});

test('forwarded HTTPS host keeps token and origin checks, without trusting proxy headers', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'llm4or-cloud-'));
  const externalOrigin = 'https://test-space-43127.app.github.dev';
  const service = await startServer({ directory: dir, staticDir: path.resolve('dist'), port: 0, externalOrigin, secretVault: fileVault(dir) });
  t.after(async () => { await service.close(); fs.rmSync(dir, { recursive: true, force: true }); });
  const request = headers => new Promise((resolve, reject) => {
    http.get(service.origin + '/api/state', { headers }, res => { res.resume(); res.on('end', () => resolve(res.statusCode)); }).on('error', reject);
  });
  const headers = { host: new URL(externalOrigin).host, origin: externalOrigin, 'x-fyppppp-token': service.token };
  assert.equal(await request(headers), 200);
  assert.equal(await request({ host: headers.host }), 401);
  assert.equal(await request({ ...headers, 'x-fyppppp-token': '0'.repeat(64) }), 401);
  assert.equal(await request({ ...headers, origin: 'https://evil.invalid' }), 403);
  assert.equal(await request({ ...headers, host: 'evil.invalid', 'x-forwarded-host': headers.host }), 403);
  assert.equal(await request({ ...headers, 'sec-fetch-site': 'cross-site' }), 403);
});
