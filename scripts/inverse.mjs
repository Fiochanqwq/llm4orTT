import { spawn } from 'node:child_process';
import path from 'node:path';
import { resourceRoot, solverPython } from '../server/python-runtime.mjs';
const args = process.argv.slice(2);
const testing = args[0] === 'test';
const scripts = testing ? ['test/inverse-python-test.py', 'test/inverse-local-test.py'] : ['solver/inverse_benchmark.py'];
for (const script of scripts) {
  const code = await new Promise(resolve => {
    const child = spawn(solverPython(), ['-X', 'utf8', path.join(resourceRoot, script), ...(testing ? [] : args)], { stdio: 'inherit', windowsHide: true });
    child.on('error', error => { console.error(error.message); resolve(1); });
    child.on('exit', code => resolve(code ?? 1));
  });
  if (code !== 0) { process.exitCode = code; break; }
}
