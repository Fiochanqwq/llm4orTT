import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const script = fileURLToPath(new URL('./secrets.ps1', import.meta.url)).replace(/app\.asar([\\/])/, 'app.asar.unpacked$1');
function transform(action, bytes) {
  if (process.platform !== 'win32') throw new Error('当前版本的密钥保护需要 Windows。');
  return new Promise((resolve, reject) => {
    const child = spawn('powershell.exe', ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', script, action], { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
    let output = '';
    const timer = setTimeout(() => { child.kill(); reject(new Error('系统密钥保护超时，请重试。')); }, 15000);
    child.stdout.on('data', data => { output += data.toString(); });
    child.stderr.resume();
    child.on('error', () => { clearTimeout(timer); reject(new Error('无法启动 Windows 密钥保护。')); });
    child.on('close', code => { clearTimeout(timer); code === 0 ? resolve(Buffer.from(output.trim(), 'base64')) : reject(new Error('无法读取密钥，请在当前 Windows 账户下重新保存。')); });
    child.stdin.on('error', () => {});
    child.stdin.end(bytes.toString('base64'));
  });
}
export const vault = {
  async protect(value) { return (await transform('protect', Buffer.from(value, 'utf8'))).toString('base64'); },
  async unprotect(value) { return (await transform('unprotect', Buffer.from(value, 'base64'))).toString('utf8'); }
};
