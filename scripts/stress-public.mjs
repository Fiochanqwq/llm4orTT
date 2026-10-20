import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {solverPython} from '../server/python-runtime.mjs';
const root=process.cwd(),python=solverPython(root),out=path.resolve(process.env.STRESS_OUT||'outputs/inverse/public-stress-20261020-v2');
function run(args,limit=600000){return new Promise(resolve=>{
 const started=Date.now(),c=spawn(python,['-X','utf8',...args],{cwd:root,windowsHide:true,stdio:['ignore','pipe','pipe']});let stderr='',timedOut=false;
 const timer=setTimeout(()=>{timedOut=true;c.kill()},limit);
 c.stdout.on('data',x=>process.stdout.write(x));c.stderr.on('data',x=>stderr+=x);
 c.once('error',e=>{clearTimeout(timer);resolve({status:'spawn_error',error:e.message,wallSeconds:(Date.now()-started)/1000})});
 c.once('close',code=>{clearTimeout(timer);resolve({status:timedOut?'watchdog_timeout':code===0?'complete':'process_failed',exitCode:code,stderr,wallSeconds:(Date.now()-started)/1000})});
})}
const test=await run(['test/stress-public-test.py']);
if(test.status!=='complete')throw Error(JSON.stringify(test));
console.log(test.stderr.trim());
if(!process.argv.includes('--test')){
 if(fs.existsSync(path.join(out,'execution-ledger.json')))throw Error('Existing execution ledger preserved. Set STRESS_OUT to a new directory for another run.');
 const freeze=await run(['research/stress_public.py','freeze']);
 if(freeze.status!=='complete')throw Error(JSON.stringify(freeze));
 const cfg=JSON.parse(fs.readFileSync(path.join(out,'protocol.json'),'utf8')),models=JSON.parse(fs.readFileSync(path.join(out,'models.json'),'utf8'));
 const jobs=models.flatMap(m=>cfg.seeds.map(seed=>({id:m.id,seed})));
 // Fixed interleaving by seed and source before inverse outcomes; not randomized run order.
 jobs.sort((a,b)=>a.seed-b.seed||a.id.localeCompare(b.id));
 const started=Date.now(),records=[];
 await Promise.all(Array.from({length:3},async()=>{for(let job;job=jobs.shift();){
  const result=await run(['research/stress_public.py','run','--id',job.id,'--seed',String(job.seed)],cfg.solver.secondsPerJob*1000);
  records.push({...job,...result});fs.writeFileSync(path.join(out,'execution-ledger.json'),JSON.stringify({startedUtc:new Date(started).toISOString(),elapsedWallSeconds:(Date.now()-started)/1000,parallelWorkers:3,jobs:records,paidApiCalls:0},null,2));
 }}));
 console.log(JSON.stringify({jobs:records.length,processFailures:records.filter(r=>r.status!=='complete').length,wallSeconds:(Date.now()-started)/1000,paidApiCalls:0}));
}
