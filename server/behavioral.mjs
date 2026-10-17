import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { queuedSolve } from './solver-queue.mjs';
// Offline metamorphic checks test solver/model behavior, not correspondence to prose.
export async function behavioralChecks(solver,source,directory,signal){
  if(!source?.model||!source.provenance?.solverInvoked||source.status!=='optimal'||!source.check?.feasible)throw Error('请选择已验证最优的真实记录');
  const reverse=structuredClone(source.model);reverse.variables.reverse();reverse.constraints.reverse();
  const scaled=structuredClone(source.model);scaled.objective=Object.fromEntries(Object.entries(scaled.objective).map(([k,v])=>[k,v*2]));
  const reduced=structuredClone(source.model);reduced.constraints=source.model.constraints.slice(1);
  const cases=[{name:'ordering_invariance',model:reverse,relation:'same_optimum',expected:source.objective,assumptions:'Variable and constraint order does not change the feasible set.'},{name:'positive_objective_scaling',model:scaled,relation:'scaled_optimum',expected:source.objective*2,assumptions:'Multiply every objective coefficient by positive scalar 2; feasible set unchanged.'},...(source.model.constraints.length?[{name:'constraint_removal_direction',model:reduced,relation:source.model.sense==='minimize'?'not_greater':'not_less',expected:source.objective,assumptions:'Removing one constraint expands the feasible set. An unchanged optimum is legal and is NOT evidence of omission.'}]:[])];
  const analysis={id:crypto.randomUUID(),version:'offline-behavior-1',sourceRunId:source.id,sourceModelHash:source.modelHash,createdAt:new Date().toISOString(),scope:'offline_solver_behavior_only',rows:[]};
  for(const c of cases){const record=await queuedSolve(solver,{model:c.model,engine:source.engine,seconds:30,problem:'Offline behavioral check: '+c.name},signal,()=>{});let passed=null;
    if(record.status==='optimal'&&record.check?.feasible){const difference=record.objective-c.expected,tolerance=1e-6*Math.max(1,Math.abs(c.expected));passed=c.relation==='not_greater'?difference<=tolerance:c.relation==='not_less'?difference>=-tolerance:Math.abs(difference)<=tolerance;}
    else if(c.name==='constraint_removal_direction'&&record.status==='unbounded')passed=true;
    analysis.rows.push({name:c.name,relation:c.relation,assumptions:c.assumptions,expected:c.expected,observed:record.objective??null,status:record.status,runId:record.id,passed});
  }
  const destination=path.join(directory,'behavioral');fs.mkdirSync(destination,{recursive:true});fs.writeFileSync(path.join(destination,analysis.id+'.json'),JSON.stringify(analysis,null,2));return analysis;
}
