import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import { extractFile } from '@electron/asar';
import { executionSnapshot } from '../server/execution-snapshot.mjs';
const version=JSON.parse(fs.readFileSync('package.json','utf8')).version;
const destination=`release/${version}/win-unpacked`,archive=destination+'/resources/app.asar';
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const list=(dir,prefix='')=>fs.readdirSync(dir,{withFileTypes:true}).flatMap(e=>e.isDirectory()?list(path.join(dir,e.name),prefix+e.name+'/'):[prefix+e.name]);
const checked=[];
// Builder may generate its own npm lockfile in stage; it is intentionally
// excluded from ASAR. dependency-lock.json is the checked source lock copy.
for(const file of list('build/stage').filter(f=>!['package.json','package-lock.json'].includes(f))){
  const expected=sha(fs.readFileSync('build/stage/'+file));
  const packed=['README.txt','THIRD_PARTY_NOTICES.txt'].includes(file)?fs.readFileSync(destination+'/'+file):extractFile(archive,path.normalize(file));
  assert.equal(sha(packed),expected,file);checked.push({file,sha256:expected});
}
assert.equal(JSON.parse(extractFile(archive,'package.json').toString()).version,version);
const builtFrom=JSON.parse(extractFile(archive,'execution-source.json').toString());
assert.equal(builtFrom.sha256,executionSnapshot().sha256,'package source differs from final source');
const resources=['solver/worker.py','runtime/python/python.exe'];
for(const file of resources)assert.equal(sha(fs.readFileSync(destination+'/resources/'+file)),sha(fs.readFileSync(file)),file);
for(const entry of ['Start-Browser.cmd','Start-Desktop.cmd']){
  const source=fs.readFileSync(entry,'utf8');assert.ok(source.includes('release\\'+version+'\\win-unpacked'));assert.ok(!source.includes('release\\0.6.4'));
}
const exe=destination+'/llm4orOvO.exe';
const report={status:'passed',appVersion:version,checkedStageFiles:checked.length,checked,builtFromSourceHash:builtFrom.sha256,resourceChecks:resources,executable:{path:exe,sha256:sha(fs.readFileSync(exe)),bytes:fs.statSync(exe).size},providerNetworkCalls:0,installerBuilt:false};
fs.writeFileSync('logs/graduation-20261015/package-integrity.json',JSON.stringify(report,null,2));
console.log(JSON.stringify({...report,checked:undefined},null,2));
