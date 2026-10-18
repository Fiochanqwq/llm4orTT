// Only the fixed worker's result fields may cross the process boundary.
const statuses = new Set(['optimal','infeasible','unbounded','infeasible_or_unbounded','time_limit','unknown','error','unavailable']);
export function parseSolverResponse(text, model) {
  const value = JSON.parse(text);
  if (!value || typeof value !== 'object' || Array.isArray(value) || !statuses.has(value.status)) throw Error('Invalid solver status');
  const result = Object.fromEntries(['status','termination','objective','values','bound','versions','error','solverElapsedMs','programmaticEvidence'].filter(k=>Object.hasOwn(value,k)).map(k=>[k,value[k]]));
  if(result.programmaticEvidence){
    const e=result.programmaticEvidence;
    if(e.version!=='programmatic-evidence-1'||!Number.isInteger(e.auxiliary_solves)||e.auxiliary_solves<0||e.auxiliary_solves>2)throw Error('Invalid evidence accounting');
    for(const k of ['missing_prompt_numbers','hallucinated_numbers','integrality_mismatch','sense_mismatch','has_scaling_issue','is_trivial_solution','hit_artificial_bound','monotonicity_violated'])if(typeof e[k]!=='boolean')throw Error('Invalid evidence flag');
    for(const k of ['missing_prompt_number_values','hallucinated_number_values','infeasible_conflict_constraints','probes'])if(!Array.isArray(e[k]))throw Error('Invalid evidence details');
  }
  for(const key of ['objective','bound','solverElapsedMs'])if(result[key]!=null && !Number.isFinite(result[key]))throw Error('Invalid solver number');
  if(result.values!=null && (typeof result.values!=='object'||Array.isArray(result.values)||Object.values(result.values).some(v=>!Number.isFinite(v))))throw Error('Invalid solver values');
  if(result.status==='optimal' && (!Number.isFinite(result.objective) || !result.values || model.variables.some(v=>!Number.isFinite(result.values[v.name]))))throw Error('Incomplete optimal result');
  return result;
}
