// Deterministic policy shared by interactive execution and paired experiments.
export const evidenceVersion='programmatic-evidence-1';
export function evidenceDecision(e, {status='not_solved',review='not_run',calls=0,solves=0,clarifications=0,limits,repair=true}={}) {
  const flags=['missing_prompt_numbers','hallucinated_numbers','integrality_mismatch','sense_mismatch','has_scaling_issue','monotonicity_violated'].filter(k=>e?.[k]&&!(k==='missing_prompt_numbers'&&e.number_coverage_ambiguous));
  if(['error','rejected'].includes(status))flags.push('execution_error');
  if(flags.length)return {action:repair&&calls+2<=limits.calls&&solves<limits.solves?'repair':'fallback',reasons:flags,confidence:'screen_requires_targeted_verification'};
  if(!e||e.diagnostic_error)return {action:'fallback',reasons:['evidence_unavailable']};
  if(status==='not_solved')return {action:'continue',reasons:[]};
  const abnormal=['infeasible','unbounded','infeasible_or_unbounded'].includes(status)||e.is_trivial_solution||e.hit_artificial_bound;
  if(abnormal){
    if(e.number_coverage_ambiguous)return {action:'fallback',reasons:['ambiguous_numeric_coverage_requires_review']};
    if(e.prompt_audited&&review==='no_issue_found')return {action:clarifications<limits.clarifications?'clarify':'fallback',reasons:[status,...['is_trivial_solution','hit_artificial_bound'].filter(k=>e[k])],confidence:'numeric_coverage_plus_semantic_review_not_proof'};
    return {action:'fallback',reasons:['anomaly_without_semantic_clearance']};
  }
  return {action:status==='optimal'&&review==='no_issue_found'?'deliver':'fallback',reasons:status==='optimal'?[]:[status]};
}
export function evidenceRepairInstruction(e){return 'Check the deterministic findings against original facts and make ONE targeted correction. Do not invent user conditions, relax business constraints, or ask the user to fix code. Number/scaling screens can have false positives: retain valid unit conversions and explain them in the ledger. Findings: '+JSON.stringify(e);}
export function evidenceQuestion(e,status){
  const rows=(e.infeasible_conflict_constraints||[]).map(c=>`${c.name}: ${JSON.stringify(c.expression)} (slack=${c.slack})`).join('; ');
  if(status==='infeasible')return `当前条件下没有可行方案。请核实这些业务条件是否同时成立：${rows||'变量边界、整数要求及各项限制'}。若有录入错误，请给出更正后的条件。松弛结果仅定位排查线索，不表示允许放宽约束。`;
  if(status==='unbounded'||e.hit_artificial_bound)return `请提供 ${(e.artificial_bound_variables?.length?e.artificial_bound_variables:e.unbounded_variable_candidates||[]).join(', ')||'决策变量'} 的实际业务上限，或确认业务确实没有上限。当前模型出现无界或人为大上界贴边。`;
  return '当前最优目标为零或所有决策量均为零。请确认零方案是否符合业务目标，还是遗漏了最低需求或必须执行的条件。';
}
