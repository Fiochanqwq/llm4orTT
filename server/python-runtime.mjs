import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const resourceRoot = appRoot.endsWith('app.asar') ? path.dirname(appRoot) : appRoot;
export function solverPython(root = resourceRoot, platform = process.platform) {
  const candidates = platform === 'win32'
    ? ['runtime/python/python.exe', 'runtime/python/Scripts/python.exe']
    : ['runtime/python/bin/python', 'runtime/python/bin/python3'];
  return candidates.map(p => path.join(root, p)).find(p => fs.existsSync(p)) || path.join(root, candidates[0]);
}
