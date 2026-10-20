// Resume only unfinished jobs; immutable inputs and completed jobs are retained.
import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {solverPython} from '../server/python-runtime.mjs';
const root=process.cwd(),out=path.resolve(process.env.STRESS_OUT||'outputs/inverse/public-stress-20261020-v2');
const lock=path.join(out,'resume.lock');
fs.writeFileSync(lock,JSON.stringify({pid:process.pid,startedUtc:new Date().toISOString()}),{flag:'wx'});
process.on('exit',()=>{try{fs.unlinkSync(lock)}catch{}});
const prior=JSON.parse(fs.readFileSync(path.join(out,'execution-ledger.json'),'utf8'));
let attempt=1;
while(fs.existsSync(path.join(out,`interrupted-v2-attempt${attempt}`)))attempt++;
const archive=path.join(out,`interrupted-v2-attempt${attempt}`);
fs.mkdirSync(archive);
fs.copyFileSync(path.join(out,'execution-ledger.json'),path.join(archive,'execution-ledger.json'));
const cfg=JSON.parse(fs.readFileSync(path.join(out,'protocol.json'),'utf8'));
const models=JSON.parse(fs.readFileSync(path.join(out,'models.json'),'utf8'));
const records=[],jobs=[],partial=[];
for(const m of models)for(const seed of cfg.seeds){
 const name=`${m.id}-s${seed}.json`,p=path.join(out,'jobs',name);
 if(fs.existsSync(p)){
  const j=JSON.parse(fs.readFileSync(p,'utf8'));
  if(j.stage==='complete'){records.push(prior.jobs.find(r=>r.id===m.id&&r.seed===seed)||{id:m.id,seed,status:'complete',wallSeconds:j.wallSeconds,recoveredCompletedCheckpoint:true});continue;}
  fs.renameSync(p,path.join(archive,name));
  const d=path.join(out,'derived',name);
  if(fs.existsSync(d))fs.copyFileSync(d,path.join(archive,`derived-${name}`));
  partial.push({id:m.id,seed,checkpointRows:j.rows.length,recordedCPUSeconds:j.rows.reduce((a,r)=>a+(r.cpuSeconds||0),0)});
 }
 jobs.push({id:m.id,seed});
}
const interruption={reason:process.env.STRESS_RESUME_REASON||'Manual recovery; this script does not determine whether prior processes have terminated. See the preserved incident records for the verified cause.',previousRecordedWallSeconds:prior.elapsedWallSeconds,unrecordedCPU:'unknown',partial,retainedCompleteJobs:records.length,restartedJobs:jobs.length};
fs.writeFileSync(path.join(archive,'interruption.json'),JSON.stringify(interruption,null,2));
jobs.sort((a,b)=>a.seed-b.seed||a.id.localeCompare(b.id));
const started=Date.now();
await Promise.all(Array.from({length:3},async()=>{for(let job;job=jobs.shift();){
 const t=Date.now(),result=await new Promise(resolve=>{
  let stderr='',timeout=false;
  const c=spawn(solverPython(root),['-X','utf8','research/stress_public.py','run','--id',job.id,'--seed',String(job.seed)],{cwd:root,windowsHide:true});
  const timer=setTimeout(()=>{timeout=true;c.kill()},cfg.solver.secondsPerJob*1000);
  c.stdout.on('data',x=>process.stdout.write(x));c.stderr.on('data',x=>stderr+=x);
  c.once('error',e=>{clearTimeout(timer);resolve({status:'spawn_error',error:e.message})});
  c.once('close',code=>{clearTimeout(timer);resolve({status:timeout?'watchdog_timeout':code===0?'complete':'process_failed',exitCode:code,stderr})});
 });
 records.push({...job,...result,wallSeconds:(Date.now()-t)/1000});
 fs.writeFileSync(path.join(out,'execution-ledger.json'),JSON.stringify({startedUtc:prior.startedUtc,resumedUtc:new Date(started).toISOString(),elapsedWallSeconds:prior.elapsedWallSeconds+(Date.now()-started)/1000,wallScope:'recorded active wall lower bound; gap and interrupted work beyond checkpoint unknown',parallelWorkers:3,jobs:records,interruption,paidApiCalls:0},null,2));
}}));
console.log('All scheduled jobs accounted for.');
