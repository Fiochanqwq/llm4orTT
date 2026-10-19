import { spawn } from 'node:child_process';
import path from 'node:path';
import { resourceRoot, solverPython } from '../server/python-runtime.mjs';
const args = process.argv.slice(2);
const testing = args[0] === 'test';
const script = testing ? 'test/inverse-python-test.py' : 'solver/inverse_benchmark.py';
const child = spawn(solverPython(), ['-X', 'utf8', path.join(resourceRoot, script), ...(testing ? [] : args)], { stdio: 'inherit', windowsHide: true });
child.on('error', error => { console.error(error.message); process.exitCode = 1; });
child.on('exit', code => { process.exitCode = code ?? 1; });
