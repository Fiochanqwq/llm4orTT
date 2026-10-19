import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
if (process.platform === 'win32') await import('./prepare-solver.mjs');
else {
  const lock = JSON.parse(fs.readFileSync('docs/solver-lock.json', 'utf8'));
  execFileSync('python3', ['-m', 'venv', 'runtime/python'], { stdio: 'inherit' });
  execFileSync(path.resolve('runtime/python/bin/python'), ['-m', 'pip', 'install', '--disable-pip-version-check', ...lock.packages.map(p => `${p.name}==${p.version}`)], { stdio: 'inherit' });
  fs.copyFileSync('docs/solver-lock.json', 'runtime/python/solver-lock.json');
}
