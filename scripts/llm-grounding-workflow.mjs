import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
const python=path.resolve('runtime/python/python.exe');
const run=(cmd,args)=>new Promise((resolve,reject)=>{
 const p=spawn(cmd,args,{stdio:'inherit',windowsHide:true});
 p.on('error',reject);p.on('exit',c=>c===0?resolve():reject(Error(cmd+' exit '+c)));
});
const mode=process.argv[2];
if(mode==='initial'){
 for(const stage of ['proposal','no_logs','shuffled','guess']){
  await run(python,['research/llm_grounding.py',stage]);
  await run(process.execPath,['scripts/llm-grounding-api.mjs',stage]);
 }
}else if(mode==='feedback'){
 await run(python,['research/llm_grounding.py','feedback']);
 await run(python,['research/llm_grounding_feedback_requests.py']);
 await run(process.execPath,['scripts/llm-grounding-api.mjs','feedback']);
}else if(mode==='clarified'){
 for(const stage of ['clarified','clarified_no_logs','clarified_shuffled']){
  await run(process.execPath,['scripts/llm-grounding-clarified.mjs',stage]);
 }
}else throw Error('unknown workflow');
