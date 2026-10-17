import { numericalCheck } from '../shared/result-contract.mjs';
import { validateModel } from '../shared/solver-model.mjs';
export const scorerVersion='original-task-score-2';
const finite=x=>typeof x==='number'&&Number.isFinite(x);
export function publicOutcome(run) {
  const last=run.conversation?.messages.findLast(m=>m.role==='assistant');
  const finalAction=run.actions?.findLast(a=>a.type==='final')?.outcome;
  const publicAction=finalAction??last?.automation?.publicOutcome;
  // Adapters expose the same observable result; no review verdict is used as truth.
  const finished=run.status==='complete'&&(!last?.automation||last.automation.stage==='complete'&&!last.automation.failure);
  if(publicAction&&finished&&publicAction.complete!==false)return {text:last?.content||'',...structuredClone(publicAction),complete:true};
  // Never synthesize an original-task answer from a candidate solver status.
  // Historical stored scores are preserved; re-evaluation may need extraction.
  return {text:last?.content||'',status:null,values:null,objective:null,complete:false,source:publicAction?'unfinished_public_outcome':'unextracted_text'};
}
export function scoreOriginalTask(run,reference=null) {
  const outcome=publicOutcome(run),base={version:scorerVersion,verdict:'unknown',evidence:[],outcome,
    executionComplete:run.status==='complete',explanation:'unknown',units:'unknown',information:'unknown',requiresHumanReview:true};
  if(run.status!=='complete')return {...base,taskSuccess:false,evidence:[{code:'INCOMPLETE_ATTEMPT',status:run.status}]};
  if(!reference?.verified||!reference?.provenance)return {...base,taskSuccess:null,evidence:[{code:'NO_VERIFIED_REFERENCE'}]};
  if(reference.requiredDisclosures!==undefined&&(!Array.isArray(reference.requiredDisclosures)||reference.requiredDisclosures.some(x=>typeof x!=='string'))||['feasibilityTolerance','objectiveTolerance'].some(k=>reference[k]!==undefined&&(!finite(reference[k])||reference[k]<0)))return {...base,taskSuccess:null,evidence:[{code:'INVALID_REFERENCE_CONFIGURATION'}]};
  if(!outcome.status)return {...base,taskSuccess:null,evidence:[{code:'ANSWER_EXTRACTION_REQUIRED'}]};
  const finish=(verdict,evidence)=>{const required=reference.requiredDisclosures??[],disclosed=new Set((run.events||[]).filter(e=>e.state==='environment_decision').flatMap(e=>(e.decisions||[]).filter(d=>d.disclosed).map(d=>d.factKind)));
    const missing=required.filter(f=>!disclosed.has(f)),manual=(run.events||[]).some(e=>e.state==='human_reply');const effective=verdict==='correct'&&missing.length?(manual?'unknown':'incorrect'):verdict;
    return {...base,verdict:effective,mathematicalVerdict:verdict,information:missing.length?'missing':required.length?'obtained':'not_required_by_reference',taskSuccess:effective==='correct'?true:effective==='incorrect'?false:null,evidence:[...evidence,...(missing.length?[{code:'REQUIRED_INFORMATION_NOT_OBTAINED',missing}]:[])],
    requiresHumanReview:effective==='unknown',referenceVersion:reference.version??null,referenceProvenance:reference.provenance};
  };
  if(!['optimal','infeasible','unbounded'].includes(reference.status))return finish('unknown',[{code:'REFERENCE_STATUS_UNSUPPORTED'}]);
  if(!['optimal','infeasible','unbounded'].includes(outcome.status))return finish('unknown',[{code:'ANSWER_STATUS_UNRESOLVED'}]);
  if(outcome.status!==reference.status)return finish('incorrect',[{code:'ORIGINAL_STATUS_MISMATCH',expected:reference.status,actual:outcome.status}]);
  if(outcome.status!=='optimal') {
    if(!reference.certificate&&!reference.reviewEvidence)return finish('unknown',[{code:'REFERENCE_PROOF_REQUIRED'}]);
    return finish('correct',[{code:'INDEPENDENT_STATUS_REFERENCE',certificate:reference.certificate??reference.reviewEvidence}]);
  }
  if(!reference.model||!outcome.values||!finite(reference.objective))return finish('unknown',[{code:'REFERENCE_MODEL_OR_VALUES_REQUIRED'}]);
  let model;try{model=validateModel(reference.model);}catch{return finish('unknown',[{code:'INVALID_REFERENCE_MODEL'}]);}
  const mapping=reference.variableMap??Object.fromEntries(model.variables.map(v=>[v.name,v.name]));
  const values=Object.fromEntries(model.variables.map(v=>[v.name,outcome.values[mapping[v.name]]]));
  const check=numericalCheck(model,values,reference.feasibilityTolerance??1e-6);
  if(!check)return finish('unknown',[{code:'VARIABLE_ALIGNMENT_REQUIRED'}]);
  const tolerance=reference.objectiveTolerance??1e-6*Math.max(1,Math.abs(reference.objective));
  if(!check.feasible||Math.abs(check.objective-reference.objective)>tolerance)return finish('incorrect',[{code:'ORIGINAL_MODEL_CHECK',check,referenceObjective:reference.objective,tolerance}]);
  if(!finite(outcome.objective))return finish('unknown',[{code:'OBJECTIVE_EXTRACTION_REQUIRED',check}]);
  if(Math.abs(outcome.objective-check.objective)>tolerance)return finish('incorrect',[{code:'DISPLAYED_OBJECTIVE_MISMATCH',check,displayed:outcome.objective,tolerance}]);
  return finish('correct',[{code:'ORIGINAL_MODEL_AND_OPTIMUM',check,referenceObjective:reference.objective,tolerance}]);
}
