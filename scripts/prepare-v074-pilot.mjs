// Evaluation assets for the existing DEVELOPMENT controls only. No model calls.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import { SolverService } from '../server/solver.mjs';
const base='experiments/budget-boundary-20261011',out='experiments/v074-development';fs.mkdirSync(out,{recursive:true});
const cards=JSON.parse(fs.readFileSync(base+'/answers.private.json')),questions=JSON.parse(fs.readFileSync(base+'/questions.public.json'));
const specs={'703345038':{names:['A','B'],cost:[100,80],rows:[[10,7,30],[8,15,50]]},'-964250787':{names:['C','Y'],cost:[2,3],rows:[[1.5,5,5],[3,1,8]]},'2017354998':{names:['old_days','new_days'],cost:[300,200],rows:[[2,4,10],[2,1,9],[4,2,15]]}};
const directory=path.resolve('qa','v074-references-'+new Date().toISOString().replace(/[:.]/g,'-')),solver=new SolverService(directory),references=[];
const sourceHash=crypto.createHash('sha256').update(fs.readFileSync(base+'/questions.public.json')).digest('hex');
try{for(const c of cards){
  const hydrogen=c.question_id==='NL4OPT-NATIVE-HYDROGEN',spec=specs[c.source_id];if(!hydrogen&&!spec)throw Error('Unreviewed family');
  const [x,y]=hydrogen?['trailer','tanker']:spec.names;
  const prompt=questions.find(q=>q.question_id===c.question_id).prompt;
  const amount=hydrogen?3750:c.hidden_fixed_budget??Number(prompt.match(/总预算为 (\d+(?:\.\d+)?)/)?.[1]);if(!Number.isFinite(amount))throw Error('Unknown reference budget');
  const model={format:'llm4orovo.lp.v1',name:'Independent original task reference',sense:'minimize',variables:[x,y].map(name=>({name,type:hydrogen?'integer':'continuous',lower:0,upper:null})),objective:hydrogen?{[x]:1,[y]:1}:{[x]:spec.cost[0],[y]:spec.cost[1]},constraints:hydrogen?[{name:'transport',terms:{[x]:50,[y]:30},sense:'>=',rhs:1000},{name:'cost_cap',terms:{[x]:500,[y]:200},sense:'<=',rhs:amount},{name:'strict_order',terms:{[x]:1,[y]:-1},sense:'<=',rhs:-1}]:[...spec.rows.map(([a,b,rhs],i)=>({name:'requirement_'+i,terms:{[x]:a,[y]:b},sense:'>=',rhs})),{name:'cost_cap',terms:{[x]:spec.cost[0],[y]:spec.cost[1]},sense:'<=',rhs:amount}]};
  const r=solver.start({model,engine:'highs',seconds:30,problem:prompt});while(r.status==='running')await new Promise(resolve=>setTimeout(resolve,40));assert.equal(r.status,c.expected_final_status,c.question_id);
  if(r.status==='optimal'){const [n,d=1]=c.minimum_cost_exact.split('/').map(Number);assert.ok(Math.abs(r.objective-n/d)<1e-6);}
  references.push({caseId:c.question_id,reference:{version:'v074-development-reference-1',verified:true,provenance:{source:c.source_url??base,publicSourceHash:sourceHash,derivation:'Explicit independent coefficients from existing reviewed development controls; includes actual budget cap',localVerificationRunId:r.id,localVerificationDirectory:directory},status:r.status,model,objective:r.objective??null,
    requiredDisclosures:c.clarification_needed_for_actual_feasibility?['amount']:[],feasibilityTolerance:1e-6,objectiveTolerance:1e-6,
    ...(r.status==='infeasible'?{certificate:hydrogen?'Every unit transported costs at least 200/30, so 1000 units cost at least 20000/3 > 3750.':`Reviewed exact minimum ${c.minimum_cost_exact} USD exceeds the fixed budget ${amount} USD.`}:{}),
    alignmentRule:'Variable names are conventional only. Unknown model names require documented manual alignment or manual scoring; never match by array position.'}});
}
fs.writeFileSync(out+'/references.private.json',JSON.stringify(references,null,2));
fs.writeFileSync(out+'/pilot.json',JSON.stringify({title:'0.7.4 development paired pilot (not started)',casesFile:'../budget-boundary-20261011/questions.public.json',privateCardsFile:'../budget-boundary-20261011/answers.private.json',referencesFile:'references.private.json',provider:'deepseek',engine:'highs',language:'zh-CN',presets:['generic','full'],repeats:3,requestCap:384,scheduleSeed:20261013,protocolCorrection:true},null,2));
fs.writeFileSync(path.join(directory,'report.json'),JSON.stringify({purpose:'independent development reference verification, not model performance',controls:references.length,providerCalls:0,sourceHash,output:out+'/references.private.json'},null,2));
console.log(JSON.stringify({directory,controls:references.length,providerCalls:0,output:out}));
}finally{solver.close();}
