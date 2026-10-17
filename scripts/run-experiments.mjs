import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseCases } from '../server/experiments.mjs';
import { methodPresets } from '../shared/methods.mjs';
import { agentLimits } from '../server/agent-policy.mjs';
export function readBatchConfig(file){
  const absolute=path.resolve(file),directory=path.dirname(absolute),data=JSON.parse(fs.readFileSync(absolute,'utf8'));
  const read=name=>JSON.parse(fs.readFileSync(path.resolve(directory,name),'utf8'));
  if(data.casesFile)data.cases=read(data.casesFile);
  if(data.privateCardsFile)data.privateCards=read(data.privateCardsFile);
  if(data.referencesFile){const refs=read(data.referencesFile);const rows=Array.isArray(data.cases)?data.cases:data.cases.cases;data.cases=rows.map(r=>({...r,reference:refs.find(ref=>String(ref.caseId??ref.id)===String(r.id??r.question_id))?.reference??null}));}
  for(const field of ['casesFile','privateCardsFile','referencesFile'])delete data[field];
  const rows=parseCases(data.cases,data.privateCards||[]),presets=data.presets||['generic','full'],repeats=data.repeats??1;
  if(!Array.isArray(presets)||!presets.length||new Set(presets).size!==presets.length||presets.some(p=>!Object.hasOwn(methodPresets,p)&&p!=='native_api')||!Number.isInteger(repeats)||repeats<1||repeats>100)throw Error('Invalid methods or repeat count');
  const trajectories=rows.length*presets.length*repeats,maximumRequests=trajectories*agentLimits.calls,requestCap=data.requestCap??100;
  if(trajectories>10000||!Number.isInteger(requestCap)||requestCap<1||requestCap>40000)throw Error('Invalid batch size or request cap');
  return {data:{...data,presets,repeats,entry:'cli'},summary:{cases:rows.length,baseProblems:new Set(rows.map(c=>c.baseId)).size,presets,repeats,trajectories,maximumRequests,requestCap,budgetSufficient:requestCap>=maximumRequests,
    privateCards:rows.filter(c=>c.privateCard).length,references:rows.filter(c=>c.privateReference).length,provider:data.provider??null,providerRequests:0}};
}
export async function runCLI(argv=process.argv.slice(2)){
  const [command,...rest]=argv,flags={};for(let i=0;i<rest.length;i+=2){if(!rest[i].startsWith('--')||rest[i+1]===undefined)throw Error('Use --name value arguments');flags[rest[i].slice(2)]=rest[i+1];}
  if(!['dry-run','create','start','run','status','export','resume','pause','cancel'].includes(command))throw Error('Commands: dry-run/create/run --config FILE; start/status/resume/pause/cancel/export --batch ID [--data DIRECTORY]; create saves without model requests; start/run/resume can incur API charges; export --output FILE --format json|jsonl|zip');
  const loaded=['run','create','dry-run'].includes(command)?readBatchConfig(flags.config||''):null;
  if(command==='dry-run'){console.log(JSON.stringify(loaded.summary,null,2));return loaded.summary;}
  if(command==='run'&&!loaded.summary.budgetSufficient)throw Error(`Configured request cap ${loaded.summary.requestCap} is below the batch maximum ${loaded.summary.maximumRequests}. Set a sufficient cap or split paired batches explicitly.`);
  const {ensureService}=await import('../server/launcher.mjs');
  const service=await ensureService(flags.data?{directory:path.resolve(flags.data)}:{});
  const request=async(route,body)=>{const response=await fetch(service.origin+route,{method:body===undefined?'GET':'POST',headers:{'x-fyppppp-token':service.token,...(body===undefined?{}:{'Content-Type':'application/json'})},...(body===undefined?{}:{body:JSON.stringify(body)})});if(!response.ok)throw Error((await response.json()).error||`HTTP ${response.status}`);return response;};
  let batch=flags.batch;
  try{
    if(command==='create'){const created=await (await request('/api/experiments',loaded.data)).json();console.log(JSON.stringify(created,null,2));return created;}
    if(command==='run'){const created=await (await request('/api/experiments',loaded.data)).json();batch=created.id;await request(`/api/experiments/${batch}/start`,{});console.log(JSON.stringify({batchId:batch,entry:'cli',maximumRequests:loaded.summary.maximumRequests}));}
    if(!/^[a-f0-9-]{36}$/.test(batch||''))throw Error('Provide a valid --batch ID');
    if(['start','resume','pause','cancel'].includes(command))await request(`/api/experiments/${batch}/${command}`,{});
    if(command==='export'){
      if(!flags.output)throw Error('Provide --output FILE');
      const ticket=await (await request('/api/downloads',{batchIds:[batch],format:flags.format||'json',includePrivate:false})).json();
      const response=await request(ticket.url);fs.writeFileSync(path.resolve(flags.output),Buffer.from(await response.arrayBuffer()));console.log(JSON.stringify({batchId:batch,output:path.resolve(flags.output)}));return;
    }
    let last='';
    do{
      const state=await (await request(`/api/experiments/${batch}`)).json();
      const progress={batchId:batch,status:state.status,requestCount:state.requestCount,total:state.total,completed:state.counts?.complete??0};
      const line=JSON.stringify(progress);if(line!==last){console.log(line);last=line;}
      if(command==='status')console.log(JSON.stringify(state,null,2));
      if(!['run','start','resume'].includes(command)||state.status!=='running')break;
      await new Promise(resolve=>setTimeout(resolve,1000));
    }while(true);
  }finally{if(service.owned){await service.close();service.cleanup();}}
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))runCLI().catch(error=>{console.error(error.message);process.exitCode=1;});
