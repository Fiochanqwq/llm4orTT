import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { solverPython } from '../server/python-runtime.mjs';
const root=path.resolve('.'), out=path.join(root,'outputs/inverse/mamo-diet-20261020-v2');
const python=solverPython(root);
const excluded=new Set(process.argv.slice(2).map(Number));
const problems=JSON.parse(fs.readFileSync(path.join(out,'public/problems.json'),'utf8')).filter(p=>!excluded.has(p.id));
let cursor=0,failed=false;
async function worker(){
 while(cursor<problems.length){
  const problem=problems[cursor++];
  await new Promise((resolve,reject)=>{
   const child=spawn(python,['-X','utf8','research/mamo_experiment.py','run','--id',String(problem.id)],{cwd:root,stdio:'inherit',windowsHide:true});
   child.once('error',reject);child.once('exit',code=>code===0?resolve():reject(Error('Problem process failed: '+problem.id)));
  }).catch(e=>{console.error(e.message);failed=true;});
 }
}
// Independent short-lived processes bound memory; solver itself uses one thread.
await Promise.all(Array.from({length:6},()=>worker()));
if(failed)process.exitCode=1;
