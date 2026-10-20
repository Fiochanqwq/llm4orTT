import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {solverPython} from '../server/python-runtime.mjs';
const root=process.cwd(),python=solverPython(root);
if(process.argv.includes('--recompute')){
 process.env.MULTIFAMILY_OUT=path.join(root,'outputs/inverse','multifamily-recompute-'+new Date().toISOString().replaceAll(':','-').replaceAll('.','-'));
}
function run(args){return new Promise((resolve,reject)=>{const child=spawn(python,['-X','utf8',...args],{cwd:root,windowsHide:true,stdio:['ignore','pipe','pipe']});let error='';child.stdout.on('data',v=>process.stdout.write(v));child.stderr.on('data',v=>error+=v);child.on('error',reject);child.on('exit',code=>code===0?resolve():reject(Error(error)))});}
await run(['test/multifamily-test.py']);
if(!process.argv.includes('--test')){
await run(['research/multifamily.py','freeze']);
const out=path.resolve(process.env.MULTIFAMILY_OUT||'outputs/inverse/multifamily-20261020-v1');
const models=JSON.parse(fs.readFileSync(path.join(out,'models.json'),'utf8')),cfg=JSON.parse(fs.readFileSync(path.join(out,'protocol.json'),'utf8'));
const jobs=models.flatMap(m=>cfg.seeds.map(seed=>({id:m.id,seed})));
await Promise.all(Array.from({length:5},async()=>{for(let job;job=jobs.shift();){await run(['research/multifamily.py','run','--id',String(job.id),'--seed',String(job.seed)])}}));
await run(['research/multifamily_analyze.py']);
await run(['research/multifamily_crosscheck.py']);
console.log(JSON.stringify({complete:true,problems:models.length,repeats:cfg.seeds.length,paidCalls:0}));
}
