import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { Writable } from 'node:stream';
import { ExperimentService,digest } from '../server/experiments.mjs';
import { SolverService } from '../server/solver.mjs';
import { executeOptimization } from '../server/optimization.mjs';
import { initializeMethods } from '../server/optimization-v07.mjs';
import { taskFor,agentLimits } from '../server/agent-policy.mjs';
import { analysisRow,ExportService } from '../server/exports.mjs';
import { compactPlan,compactReviewed } from './fixtures/compact-v074.mjs';
import { buildEvidenceCases,referenceOptimum } from './fixtures/evidence-benchmark.mjs';

export async function runBenchmark(directory=path.resolve('experiments/programmatic-evidence-'+new Date().toISOString().replace(/[:.]/g,'-'))){
  fs.mkdirSync(directory,{recursive:true});
  const cases=buildEvidenceCases(),solver=new SolverService(directory);
  const config={id:'openai',model:'frozen-scripted-candidate-v1',maxTokens:12000,modelingTokens:12000,language:'zh-CN',protocolCorrection:false};
  const specs=cases.map(c=>({id:c.id,baseId:c.baseId,prompt:c.prompt,...(c.group!=='B'?{reference:{verified:true,provenance:'Independent vertex/integer enumeration; scripts/fixtures/evidence-benchmark.mjs',status:'optimal',model:c.correctModel,...referenceOptimum(c.correctModel)}}:{})}));
  fs.writeFileSync(path.join(directory,'cases.json'),JSON.stringify(specs,null,2));
  fs.writeFileSync(path.join(directory,'fault-injections.json'),JSON.stringify(cases,null,2));
  const protocol={kind:'controlled_fault_injection_not_live_llm',variantsPerBase:2,pairedUnit:'baseId (two parameter variants clustered)',presets:['structure','no_evidence','full'],limits:agentLimits,seed:20261018,review:'Frozen no-issue review to test errors missed by semantic review',repair:'Frozen correct candidate returned only when controller explicitly requests repair',providerCalls:0,primaryOutcome:'correctDelivery',secondaryOutcome:'correctFirstDecision',tests:'Two-sided exact McNemar on all-variants-success per base; Wilcoxon on base-mean budget differences; Holm within each test family',injectionHash:digest(cases),helper:'DeepSeek generated independent math suggestions only; all used cases constructed locally and independently checked'};
  fs.writeFileSync(path.join(directory,'protocol.json'),JSON.stringify(protocol,null,2));
  const sourceFiles=['scripts/run-evidence-benchmark.mjs','scripts/verify-evidence.mjs','scripts/analyze-evidence-benchmark.py','scripts/fixtures/evidence-benchmark.mjs','scripts/fixtures/compact-v074.mjs'];
  const sourceHashes=Object.fromEntries(sourceFiles.map(f=>[f,digest(fs.readFileSync(new URL('../'+f,import.meta.url),'utf8'))]));
  fs.writeFileSync(path.join(directory,'driver-source-hashes.json'),JSON.stringify(sourceHashes,null,2));
  const service=new ExperimentService(directory,{solver,runner:async({run,prompt,signal})=>{
    const c=cases.find(c=>c.id===run.caseId),user={id:crypto.randomUUID(),role:'user',content:prompt,status:'complete'},answer={id:crypto.randomUUID(),role:'assistant',content:'',status:'streaming',provenance:{},automation:{usage:{},task:taskFor({messages:[]},user,false)}};
    initializeMethods(answer.automation,config,'highs',run.preset);run.conversation.messages=[user,answer];
    let requestedRepair=false;
    const planner=async(cfg,messages)=>{
      const stage=answer.automation.stage;requestedRepair||=stage==='repairing';
      const response=cfg.tool.name==='review_optimization'?compactReviewed({budget:false}):compactPlan(messages[0].content,{model:requestedRepair?c.correctModel:c.candidateModel,budget:false});
      run.events.push({id:crypto.randomUUID(),state:'completed',stage,response,source:'frozen_scripted_response',createdAt:new Date().toISOString()});return response;
    };
    await executeOptimization({config,messages:[user],problem:prompt,engine:'highs',seconds:10,planner,solver,signal,answer,update:()=>{}});
    answer.status='complete';const f=answer.automation;
    run.status=f.stage==='complete'?'complete':'partial';
    if(f.stage==='clarification'){
      run.events.push({id:crypto.randomUUID(),state:'environment_decision',status:'recorded_without_answer',questions:f.questions,createdAt:new Date().toISOString()});
      run.environmentFailure={code:'UNATTENDED_CLARIFICATION_RECORDED',questions:f.questions};
    }
    if(f.task.calls>agentLimits.calls||f.task.solves>agentLimits.solves||f.task.clarifications>agentLimits.clarifications)throw Error('Budget exceeded');
    return run;
  }});
  const created=await service.create({title:'Programmatic evidence controlled paired benchmark',cases:specs,presets:protocol.presets,scheduleSeed:protocol.seed,requestCap:cases.length*3*agentLimits.calls,entry:'cli',unattended:true});
  const batch=service.batches.get(created.id);batch.controlledProtocol=protocol;service.save(batch);service.action(batch.id,'start');
  while(service.working){await new Promise(r=>setTimeout(r,250));}
  if(service.storageError)throw service.storageError;
  for(const [file,sha] of Object.entries(sourceHashes))if(digest(fs.readFileSync(new URL('../'+file,import.meta.url),'utf8'))!==sha)throw Error('Frozen benchmark driver changed during execution: '+file);
  const runs=batch.runs.map(r=>service.run(r.id)),rows=runs.map(run=>{
    const c=cases.find(c=>c.id===run.caseId),flow=run.conversation.messages.at(-1).automation;
    const row=analysisRow(run);
    return {...row,group:c.group,expectedDecision:c.expectedDecision,correctFirstDecision:row.firstDecision===c.expectedDecision,
      correctDelivery:run.score.independent.taskSuccess===true,silentErrorDelivery:run.status==='complete'&&(c.group==='B'||run.score.independent.taskSuccess===false),providerCalls:0};
  });
  fs.writeFileSync(path.join(directory,'analysis.jsonl'),rows.map(r=>JSON.stringify(r)).join('\n')+'\n');
  fs.writeFileSync(path.join(directory,'blind-review.json'),JSON.stringify(runs.map(r=>service.blindReview(r.id)),null,2));
  fs.writeFileSync(path.join(directory,'batch.json'),JSON.stringify(batch,null,2));
  const exporter=new ExportService(directory,{data:{conversations:[]}},solver,service),ticket=exporter.create({batchIds:[batch.id],format:'json',includePrivate:true});
  await new Promise((resolve,reject)=>{const chunks=[],res=new Writable({write(chunk,_encoding,cb){chunks.push(chunk);cb();}});res.writeHead=()=>{};res.on('finish',()=>{fs.writeFileSync(path.join(directory,'export-bundle.json'),Buffer.concat(chunks));resolve();});res.on('error',reject);exporter.download(ticket.url.split('/').at(-1),res);});
  await service.close();solver.close();
  console.log(JSON.stringify({directory,batchId:batch.id,rows:rows.length,failed:runs.filter(r=>r.status==='failed').map(r=>({caseId:r.caseId,error:r.error}))}));
  return {directory,rows};
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))runBenchmark(process.argv[2]&&path.resolve(process.argv[2])).catch(e=>{console.error(e);process.exitCode=1;});
