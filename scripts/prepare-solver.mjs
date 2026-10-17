import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';
const root = path.resolve('runtime/python'), cache = path.resolve('.downloads/solver');
fs.mkdirSync(cache, { recursive: true });
const lockPath = 'docs/solver-lock.json';
let lock;
if (fs.existsSync(lockPath)) lock = JSON.parse(fs.readFileSync(lockPath, 'utf8'));
else {
  lock = { python: { version: '3.13.16', filename: 'python-3.13.16-embed-amd64.zip', url: 'https://www.python.org/ftp/python/3.13.16/python-3.13.16-embed-amd64.zip', sha256: '97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297' }, packages: [] };
  for (const [name, version] of [['pyomo', '6.10.1'], ['highspy', '1.15.1'], ['numpy', '2.5.3']]) {
    const response = await fetch(`https://pypi.org/pypi/${name}/${version}/json`); if (!response.ok) throw Error(response.status);
    const metadata = await response.json();
    const wheel = metadata.urls.find(f => /cp313-cp313-win_amd64\.whl$/.test(f.filename)) || metadata.urls.find(f => /py3-none-any\.whl$/.test(f.filename));
    if (!wheel) throw Error('No compatible wheel: ' + name);
    lock.packages.push({ name, version, filename: wheel.filename, url: wheel.url, sha256: wheel.digests.sha256, bytes: wheel.size, requires: metadata.info.requires_dist, license: metadata.info.license_expression || metadata.info.license });
  }
  fs.writeFileSync(lockPath, JSON.stringify(lock, null, 2));
}
for (const item of [lock.python, ...lock.packages]) {
  const file = path.join(cache, item.filename);
  if (!fs.existsSync(file)) { console.log('Downloading ' + item.filename); const response = await fetch(item.url); if (!response.ok) throw Error(response.status); fs.writeFileSync(file, Buffer.from(await response.arrayBuffer())); }
  if (crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex') !== item.sha256) throw Error('SHA256 mismatch: ' + item.filename);
  const destination = item === lock.python ? root : path.join(root, 'Lib/site-packages');
  fs.mkdirSync(destination, { recursive: true });
  const zip = file.endsWith('.zip') ? file : file + '.zip'; if (zip !== file) fs.copyFileSync(file, zip);
  execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', 'Expand-Archive -LiteralPath $env:SOLVER_ZIP -DestinationPath $env:SOLVER_DEST -Force'], { windowsHide: true, env: { ...process.env, SOLVER_ZIP: zip, SOLVER_DEST: destination } });
}
// Isolated paths: no global/user Python packages, pip or startup scripts.
fs.writeFileSync(path.join(root, 'python313._pth'), 'python313.zip\n.\nLib/site-packages\n');
fs.copyFileSync(lockPath, path.join(root, 'solver-lock.json'));
console.log('Prepared pinned local solver runtime: ' + root);
