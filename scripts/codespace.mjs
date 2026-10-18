import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { ensureService } from '../server/launcher.mjs';
import { fileVault } from '../server/file-vault.mjs';
import { appRoot, codespaceConfig } from '../server/codespace-config.mjs';
process.chdir(appRoot);
const config = codespaceConfig();
fs.mkdirSync(config.directory, { recursive: true, mode: 0o700 });
if (process.argv.includes('--serve')) {
  const service = await ensureService({ ...config, secretVault: fileVault(config.directory) });
  if (service.owned) for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, async () => { await service.close(); service.cleanup(); process.exit(0); });
} else {
  const runtime = path.join(config.directory, 'runtime.json');
  async function ready() {
    try {
      const current = JSON.parse(fs.readFileSync(runtime, 'utf8'));
      if (current.origin !== 'http://127.0.0.1:43127' || !/^[a-f0-9]{64}$/.test(current.token)) return null;
      const res = await fetch(current.origin + '/api/state', { headers: { 'x-fyppppp-token': current.token }, signal: AbortSignal.timeout(1000) });
      return res.ok ? current : null;
    } catch { return null; }
  }
  let current = await ready();
  if (!current) {
    const log = fs.openSync(path.join(config.directory, 'server.log'), 'a', 0o600);
    const child = spawn(process.execPath, ['scripts/codespace.mjs', '--serve'], { cwd: appRoot, detached: true, stdio: ['ignore', log, log] });
    child.unref(); fs.closeSync(log);
    for (let i = 0; i < 60 && !current; i++) { await new Promise(r => setTimeout(r, 500)); current = await ready(); }
  }
  if (!current) throw Error('启动未完成，请检查 .local/codespace-workspace/server.log。');
  console.log('\n打开下面的完整链接使用 llm4orOvO（仅供本人使用，请勿分享）：\n');
  console.log(config.externalOrigin + '/#token=' + current.token);
  console.log('\n若网页未打开，请等待 Ports 面板出现 43127，保持端口可见性为 Private，再点击上面的链接。\n');
}
