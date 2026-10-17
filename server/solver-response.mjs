// Only the fixed worker's result fields may cross the process boundary.
const statuses = new Set(['optimal','infeasible','unbounded','infeasible_or_unbounded','time_limit','unknown','error','unavailable']);
export function parseSolverResponse(text, model) {
  const value = JSON.parse(text);
  if (!value || typeof value !== 'object' || Array.isArray(value) || !statuses.has(value.status)) throw Error('Invalid solver status');
  const result = Object.fromEntries(['status','termination','objective','values','bound','versions','error','solverElapsedMs'].filter(k=>Object.hasOwn(value,k)).map(k=>[k,value[k]]));
  for(const key of ['objective','bound','solverElapsedMs'])if(result[key]!=null && !Number.isFinite(result[key]))throw Error('Invalid solver number');
  if(result.values!=null && (typeof result.values!=='object'||Array.isArray(result.values)||Object.values(result.values).some(v=>!Number.isFinite(v))))throw Error('Invalid solver values');
  if(result.status==='optimal' && (!Number.isFinite(result.objective) || !result.values || model.variables.some(v=>!Number.isFinite(result.values[v.name]))))throw Error('Incomplete optimal result');
  return result;
}
