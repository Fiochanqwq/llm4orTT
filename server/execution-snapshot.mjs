import fs from 'node:fs';
import crypto from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const root=new URL('../',import.meta.url);
const sha=text=>crypto.createHash('sha256').update(text).digest('hex');
// Only code/dependency inputs, never workspace settings or credentials.
export function executionSnapshot(){
  // electron-builder omits npm lockfiles; the staged copy has an explicit name.
  const dependencyLock=fs.existsSync(new URL('package-lock.json',root))?'package-lock.json':'dependency-lock.json';
  const files=['package.json',dependencyLock,...['server','shared'].flatMap(dir=>fs.readdirSync(new URL(dir+'/',root)).filter(n=>n.endsWith('.mjs')).map(n=>dir+'/'+n)),'solver/worker.py','solver/evidence.py'];
  if(fs.existsSync(new URL('scripts/run-experiments.mjs',root)))files.push('scripts/run-experiments.mjs');
  const rootPath=fileURLToPath(root),resourceRoot=rootPath.replace(/[\\/]+$/,'').endsWith('app.asar')?path.dirname(rootPath.replace(/[\\/]+$/,'')):rootPath;
  const hashes=Object.fromEntries(files.sort().map(file=>[file,sha(fs.readFileSync(path.join(file.startsWith('solver/')?resourceRoot:rootPath,file)))]));
  const sourceFile=new URL('execution-source.json',root);
  return {appVersion:JSON.parse(fs.readFileSync(new URL('package.json',root),'utf8')).version,sha256:sha(JSON.stringify(hashes)),files:hashes,...(fs.existsSync(sourceFile)?{builtFrom:JSON.parse(fs.readFileSync(sourceFile,'utf8'))}:{} )};
}
