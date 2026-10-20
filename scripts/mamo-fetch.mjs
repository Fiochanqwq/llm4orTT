import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {execFileSync} from 'node:child_process';
const revision='2c91069dee5c1e4db4b899eb176ec987d0251bb3';
const base=`https://raw.githubusercontent.com/FreedomIntelligence/Mamo/${revision}/`;
const files=['LICENSE','README.md','data/optimization/Complex_LP/mamo_complex_lp.jsonl','data/optimization/Easy_LP/mamo_easy_lp.jsonl'];
const dir=path.resolve('datasets/mamo');fs.mkdirSync(dir,{recursive:true});
const manifest=[];
for(const file of files){
 let buffer;
 try{
  const response=await fetch(base+file,{signal:AbortSignal.timeout(60000)});
  if(!response.ok)throw Error('Source download failed: '+response.status);
  buffer=Buffer.from(await response.arrayBuffer());
 }catch(error){
  if(process.platform!=='win32')throw error;
  const temp=path.join(dir,'.download-'+crypto.randomUUID());
  const quote=s=>"'"+s.replaceAll("'","''")+"'";
  try{
   execFileSync('powershell.exe',['-NoProfile','-NonInteractive','-Command',`$ErrorActionPreference='Stop'; Invoke-WebRequest -Uri ${quote(base+file)} -OutFile ${quote(temp)} -TimeoutSec 60`],{windowsHide:true,timeout:70000,stdio:'pipe'});
   buffer=fs.readFileSync(temp);
  }finally{if(fs.existsSync(temp))fs.unlinkSync(temp);}
 }
 const dest=path.join(dir,path.basename(file));
 if(fs.existsSync(dest)&&!fs.readFileSync(dest).equals(buffer))throw Error('Local dataset differs from pinned revision: '+file);
 if(!fs.existsSync(dest))fs.writeFileSync(dest,buffer);
 manifest.push({path:file,url:base+file,bytes:buffer.length,sha256:crypto.createHash('sha256').update(buffer).digest('hex')});
}
fs.writeFileSync(path.join(dir,'source-manifest.json'),JSON.stringify({revision,license:'CC BY-SA 4.0',checkedAt:new Date().toISOString(),files:manifest},null,2));
console.log(JSON.stringify({verified:manifest.length,revision}));
