import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { solverPython } from '../server/python-runtime.mjs';
const root = fileURLToPath(new URL('../', import.meta.url));
const result = spawnSync(solverPython(), ['-X', 'utf8', '-m', 'unittest', 'discover', '-s', 'tests', '-v'], { cwd: root, windowsHide: true, stdio: 'inherit' });
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
