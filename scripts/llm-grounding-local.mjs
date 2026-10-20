import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';
const out=path.resolve('outputs/inverse/deepseek-grounding-20261020-v1');
const feedback=process.argv.includes('--feedback');
const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
const write=(p,v)=>{fs.mkdirSync(path.dirname(p),{recursive:true});fs.writeFileSync(p,JSON.stringify(v,null,2));};
const sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const cfg=read(path.join(out,'protocol.json'));
const lock=path.join(out,'local.lock'),fd=fs.openSync(lock,'wx');
const mode=feedback?'evaluate-feedback':'evaluate';
const ledgerPath=path.join(out,feedback?'feedback-ledger.json':'local-ledger.json');
const ledger=fs.existsSync(ledgerPath)?read(ledgerPath):{startedUtc:new Date().toISOString(),mode,workers:2,attempts:[]};
const files=['research/llm_grounding.py','research/mamo_experiment.py','scripts/llm-grounding-api.mjs','scripts/llm-grounding-local.mjs'];
const freezePath=path.join(out,'execution-code-freeze.json');
if(!fs.existsSync(freezePath)){
 write(freezePath,{createdUtc:new Date().toISOString(),files:Object.fromEntries(files.map(f=>[f,sha(f)]))});
 for(const f of files){const dest=path.join(out,'code',f);fs.mkdirSync(path.dirname(dest),{recursive:true});fs.copyFileSync(f,dest);}
}
for(const [f,h] of Object.entries(read(freezePath).files))if(sha(f)!==h)throw Error('Execution code changed: '+f);
const jobs=read(path.join(out,'models.json')).flatMap(m=>cfg.seeds.map(seed=>({id:m.id,seed})));
let cursor=0;
try{
 async function worker(){
  while(cursor<jobs.length){
   const job=jobs[cursor++];
   if(fs.existsSync(path.join(out,feedback?'feedback-results':'jobs',`${job.id}-s${job.seed}.json`)))continue;
   const record={...job,startedUtc:new Date().toISOString(),status:'running'};
   ledger.attempts.push(record);write(ledgerPath,ledger);
   await new Promise(resolve=>{
    const child=spawn(path.resolve('runtime/python/python.exe'),['research/llm_grounding.py',mode,'--id',job.id,'--seed',String(job.seed)],{windowsHide:true,stdio:['ignore','pipe','pipe']});
    let stderr='';child.stdout.on('data',b=>process.stdout.write(b));child.stderr.on('data',b=>{stderr+=b.toString();});
    const timer=setTimeout(()=>{record.watchdog='600seconds';child.kill();},600000);
    child.on('error',e=>{record.status='spawn_failed';record.error=e.message;});
    child.on('close',code=>{clearTimeout(timer);record.exitCode=code;record.status=code===0?'complete':'failed';record.stderr=stderr;record.finishedUtc=new Date().toISOString();write(ledgerPath,ledger);resolve();});
   });
  }
 }
 await Promise.all([worker(),worker()]);
 ledger.finishedUtc=new Date().toISOString();write(ledgerPath,ledger);
}finally{fs.closeSync(fd);fs.unlinkSync(lock);}
