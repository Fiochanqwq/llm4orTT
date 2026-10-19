import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fs.realpathSync(fileURLToPath(new URL('../', import.meta.url)));
const target = path.resolve(root, 'dist');
if (path.dirname(target) !== root || path.basename(target) !== 'dist') throw Error('Invalid build output path');
if (fs.existsSync(target)) {
  if (fs.lstatSync(target).isSymbolicLink() || fs.realpathSync(target) !== target) throw Error('Build output must stay inside this project');
  // Explicit deletion also works on filesystems where recursive rm can silently leave stale chunks.
  function remove(file) {
    if (!file.startsWith(target + path.sep) && file !== target) throw Error('Invalid build cleanup path');
    const stat = fs.lstatSync(file);
    if (stat.isDirectory() && !stat.isSymbolicLink()) {
      for (const name of fs.readdirSync(file)) remove(path.join(file, name));
      fs.rmdirSync(file);
    } else { if (!stat.isSymbolicLink()) fs.chmodSync(file, 0o666); fs.unlinkSync(file); }
  }
  remove(target);
  if (fs.existsSync(target)) throw Error('Build output could not be cleared');
}
