import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';
import { startServer } from './http.mjs';
import packageInfo from '../package.json' with { type: 'json' };
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export function dataDirectory() { return process.env.FYPPPPP_DATA_DIR || path.join(process.env.LOCALAPPDATA || root, 'FYPPPPP', 'workspace'); }
// A fixed port collides whenever anything else owns it, and two Windows users on one machine keep
// separate profiles, so the "existing instance" probe cannot see the other listener.
async function startOnFreePort(options) {
  const explicit = options.port ?? (process.env.FYPPPPP_PORT ? Number(process.env.FYPPPPP_PORT) : null);
  const base = Number.isInteger(explicit) && explicit > 0 ? explicit : 43127;
  const candidates = Number.isInteger(explicit) && explicit > 0 ? [base] : Array.from({ length: 11 }, (_, index) => base + index);
  for (const port of candidates) {
    try { return await startServer({ ...options, port }); }
    catch (error) { if (error.code !== 'EADDRINUSE') throw error; }
  }
  throw new Error(`端口 ${base}–${base + 10} 均被占用。请关闭占用端口的程序，或设置环境变量 FYPPPPP_PORT 指定其它端口后重试。`);
}
export async function ensureService(options = {}) {
  const directory = options.directory || dataDirectory(); fs.mkdirSync(directory, { recursive: true });
  const runtimeFile = path.join(directory, 'runtime.json'), lockFile = path.join(directory, 'server.lock');
  for (let attempt = 0; attempt < 40; attempt++) {
    if (fs.existsSync(runtimeFile)) {
      let connected;
      try {
        const current = JSON.parse(fs.readFileSync(runtimeFile, 'utf8'));
        if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(current.origin)) throw new Error('Invalid local origin');
        const response = await fetch(current.origin + '/api/state', { headers: { 'x-fyppppp-token': current.token }, signal: AbortSignal.timeout(800) });
        if (response.ok && (await response.json()).version === 1) connected = current;
      } catch { /* A stale runtime file can remain after an interrupted process. */ }
      if (connected) {
        const health = await fetch(connected.origin + '/api/health', { signal: AbortSignal.timeout(1000) }).then(response => response.json());
        if (health.version !== packageInfo.version) throw new Error(`旧版本服务仍在运行（${health.version || '未知'}），当前程序为 ${packageInfo.version}。请先从系统托盘退出旧程序，再重新启动；仅关闭窗口不会退出服务。`);
        return { ...connected, owned: false };
      }
    }
    try {
      fs.writeFileSync(lockFile, String(process.pid), { flag: 'wx', mode: 0o600 });
      try {
        const service = await startOnFreePort({ directory, staticDir: path.join(root, 'dist'), dev: process.env.FYPPPPP_DEV === '1', ...options });
        const runtime = { origin: service.origin, token: service.token, pid: process.pid };
        fs.writeFileSync(runtimeFile, JSON.stringify(runtime), { mode: 0o600 });
        const cleanup = () => { for (const f of [runtimeFile, lockFile]) { try { fs.unlinkSync(f); } catch {} } };
        process.once('exit', cleanup);
        return { ...service, owned: true, cleanup };
      } catch (error) { try { fs.unlinkSync(lockFile); } catch {} throw error; }
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
      try { const pid = Number(fs.readFileSync(lockFile, 'utf8')); if (!Number.isInteger(pid) || pid < 1) throw new Error('stale'); process.kill(pid, 0); }
      catch { try { fs.unlinkSync(lockFile); } catch {} }
      await new Promise(resolve => setTimeout(resolve, 150));
    }
  }
  throw new Error('本地服务正在启动，请稍后重试。');
}
export function openBrowser(url) {
  // The URL comes only from the loopback service; do not pass arbitrary user input to the shell.
  if (!/^http:\/\/127\.0\.0\.1:\d+\/#token=[a-f0-9]{64}$/.test(url)) throw new Error('Invalid launch URL');
  const child = spawn('rundll32.exe', ['url.dll,FileProtocolHandler', url], { windowsHide: true, detached: true, stdio: 'ignore' }); child.unref();
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  ensureService().then(service => {
    console.log('llm4orTT · ' + service.origin);
    if (process.argv.includes('--browser')) openBrowser(service.origin + '/#token=' + service.token);
    if (service.owned) for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, async () => { await service.close(); service.cleanup(); process.exit(0); });
  }).catch(error => { console.error(error.message); process.exit(1); });
}
