import {preflightModel} from './model-preflight.mjs';

export function objectiveUnitFromContract(contract){
  const objectiveFacts=new Set((contract?.bindings||[]).filter(b=>b.disposition==='encoded'&&b.targetRefs?.includes('objective:$')).flatMap(b=>b.factIds));
  const units=[...new Set((contract?.facts||[]).filter(f=>f.status!=='superseded'&&objectiveFacts.has(f.id)&&f.unit?.trim()&&f.sourceSpan?.includes(f.unit.trim())).map(f=>f.unit.trim()))];
  return units.length===1?units[0]:null;
}
function objectiveDisplay(value){
  if(!Number.isFinite(value))return {value:null,approximate:false};
  const rounded=Number(value.toPrecision(12)),limit=Math.min(1e-9,1e-12*Math.max(1,Math.abs(value)));
  return Math.abs(rounded-value)<=limit?{value:rounded,approximate:rounded!==value}:{value,approximate:false};
}
export function numericalCheck(model, values, tolerance = 1e-6) {
  if (!values || model.variables.some(v => !Number.isFinite(values[v.name]))) return null;
  const violations = [];
  for (const v of model.variables) {
    const x = values[v.name];
    // Hold the tolerance at the floating-point resolution of the value instead of a fixed 1e-6: at 1e9
    // an absolute 1e-6 is 1e-15 relative, which double precision cannot deliver, so a correct solution
    // used to be rejected purely for being large. A genuine violation is still larger than this.
    const resolution = Math.max(tolerance, 64 * Number.EPSILON * Math.abs(x));
    if ((v.lower !== null && x < v.lower - resolution) || (v.upper !== null && x > v.upper + resolution) || (v.type !== 'continuous' && Math.abs(x - Math.round(x)) > resolution)) violations.push(v.name);
  }
  const dot = terms => Object.entries(terms).reduce((sum, [name, coefficient]) => sum + coefficient * values[name], 0);
  const constraints = model.constraints.map(c => {
    const lhs = dot(c.terms), slack = c.sense === '<=' ? c.rhs - lhs : c.sense === '>=' ? lhs - c.rhs : -Math.abs(lhs - c.rhs);
    // What float64 rounds is the sum of |a_j x_j|, not the residual: terms of 1e18 can cancel to a
    // residual of 1. The tolerance therefore has to follow the terms, or large models look infeasible.
    const magnitude = Object.entries(c.terms).reduce((sum, [name, coefficient]) => sum + Math.abs(coefficient * values[name]), 0);
    const rowTolerance = Math.max(tolerance * Math.max(1, Math.abs(lhs), Math.abs(c.rhs)), 64 * Number.EPSILON * magnitude);
    if (!Number.isFinite(lhs) || !Number.isFinite(slack) || slack < -rowTolerance) violations.push(c.name);
    return { name: c.name, lhs, sense: c.sense, rhs: c.rhs, slack };
  });
  const objective = dot(model.objective);
  if (!Number.isFinite(objective)) violations.push('objective');
  return { feasible: !violations.length, tolerance, violations, constraints, objective };
}

export function resultContract(record, context = {}) {
  const check = record.model ? numericalCheck(record.model, record.values) : null;
  const objectiveMatches = !!check && Number.isFinite(record.objective) && Math.abs(check.objective - record.objective) <= 1e-6 * Math.max(1, Math.abs(check.objective));
  let displayValues = null, displayValidation = null;
  if (check?.feasible && objectiveMatches) {
    for (const precision of [10, 12, 15, 17]) {
      const candidate = Object.fromEntries(record.model.variables.map(({name}) => [name, Number(record.values[name].toPrecision(precision))]));
      const validation = numericalCheck(record.model, candidate);
      if (validation?.feasible && Math.abs(validation.objective - check.objective) <= 1e-6 * Math.max(1, Math.abs(check.objective))) { displayValues = candidate; displayValidation = validation; break; }
    }
  }
  const displayedObjective=objectiveDisplay(check?.objective);
  const conflictEvidence=record.status==='infeasible'&&record.provenance?.solverInvoked&&record.model?preflightModel(record.model):null;
  return { format: 'llm4orovo.result.v1', ...context, runId: record.id, modelHash: record.modelHash,
    solverStatus: record.status, solverInvoked: !!record.provenance?.solverInvoked, numericCheck: check,
    objective: record.objective ?? null, objectiveRecomputed: check?.objective ?? null, objectiveMatches,
    displayObjective:displayedObjective.value,displayObjectiveApproximate:displayedObjective.approximate,
    conflictEvidence:conflictEvidence?.status==='conflict'?conflictEvidence:null,
    values: record.values ?? null, displayValues, displayValidation, interpretationStatus: 'local_template',
    taskOutcome: record.provenance?.solverInvoked && (record.status === 'optimal' && check?.feasible && objectiveMatches || ['infeasible', 'unbounded'].includes(record.status)) ? 'complete' : 'partial',
    semanticReviewStatus: context.semanticReviewStatus || 'not_run', budgetDecision: context.budgetDecision || 'not_applicable', evidenceRefs: [record.id] };
}

export function resultText(result, language = 'zh-CN') {
  const en = language === 'en', say = (zh, english) => en ? english : zh;
  const lines = [];
  if (result.budgetDecision === 'all_infeasible' && result.solverStatus === 'infeasible') lines.push(say('不加预算限制时，其他条件构成的基础模型已经无可行解。无法据此判断增加预算能解决问题。', 'The base model is infeasible even without the budget cap. Increasing the budget is not established as a remedy.'));
  else if (result.budgetDecision === 'all_infeasible') lines.push(say('已知预算不足以满足当前模型，当前条件下无可行方案。', 'The known budget is insufficient for the current model.'));
  else if (result.budgetDecision === 'needs_clarification') lines.push(say('已得到预算阈值，实际任务仍等待预算答复。', 'A budget threshold is available; the actual task awaits a budget answer.'));
  else if (result.solverStatus === 'infeasible') lines.push(say('求解器报告当前模型无可行解。未放宽用户条件。', 'The solver reports the current model is infeasible. User conditions were retained.'));
  else if (result.solverStatus === 'unbounded') lines.push(say('求解器报告当前模型目标无界。', 'The solver reports an unbounded objective for the current model.'));
  else if (result.numericCheck?.feasible && result.objectiveMatches) {
    lines.push(result.solverStatus === 'optimal' ? say('当前模型已求得最优方案（浮点求解，含数值容差）。', 'Optimal solution for the current model (floating-point solution with numerical tolerance).') : say('保留经数值复核的可行方案，尚未证明最优。', 'A numerically checked feasible solution is retained; optimality is unproven.'));
    const objective=result.displayObjective??result.objectiveRecomputed,unit=result.objectiveUnit||result.budget?.unit;
    lines.push(say('目标值：', 'Objective: ') + (result.displayObjectiveApproximate?'≈ ':'') + objective+(unit?' '+unit:say('（单位未提供）',' (unit not supplied)')));
    if (result.displayValues) lines.push(Object.entries(result.displayValues).map(([k, v]) => {const entity=result.entities?.find(e=>e.variable===k);return `${entity?.label||k} = ${v}${entity?.unit?' '+entity.unit:''}`;}).join('; '));
    else lines.push(say('近似值未通过展示校验，不可直接作为执行安排。', 'Rounded values failed display validation; do not use them as an execution plan.'));
  } else lines.push(say('未取得可确认的求解结果，请查看执行记录。', 'No verified solution is available. See the execution record.'));
  if(result.solverStatus==='infeasible'){
    const conflicts=result.conflictEvidence?.conflicts||[];
    if(conflicts.length){
      lines.push(say('当前模型中可核查的冲突（变量界与线性约束推导，含浮点容差）：','Checkable conflicts in the submitted model (bounds and linear constraints, with floating-point tolerance):'));
      for(const c of conflicts){
        const sources=c.sources.join(', ');
        if(c.kind==='bounds')lines.push(say(`${c.variable} 的下界 ${c.lower} 大于上界 ${c.upper}；依据：${sources}。`,`${c.variable}: lower bound ${c.lower} exceeds upper bound ${c.upper}; sources: ${sources}.`));
        else {const terms=Object.entries(c.terms).map(([name,a])=>`${a}×${name}`).join(' + '),low=Number.isFinite(c.min)?String(c.min):'-∞',high=Number.isFinite(c.max)?String(c.max):'+∞';
          lines.push(say(`约束 ${c.constraint} 要求 ${terms} ${c.sense} ${c.rhs}，但由变量界及已列约束可得左端范围为 [${low}, ${high}]，无法满足；依据：${sources}。`,`Constraint ${c.constraint} requires ${terms} ${c.sense} ${c.rhs}, but the bounds imply a left-hand range [${low}, ${high}]; sources: ${sources}.`));}
      }
    }else lines.push(say('当前未提取到具体冲突证据；无解状态来自求解器，不能据此指定某个条件是原因。','No specific conflict was extracted; infeasibility is reported by the solver, without attributing it to a particular condition.'));
  }
  if(result.displayObjectiveApproximate)lines.push(say('目标值仅作展示近似；原始求解值与重算值保留在结果记录中。','Only the displayed objective is rounded; raw and recomputed values remain in the result record.'));
  const unit=result.budget?.unit||'',cost=result.objectiveRecomputed??result.objective;
  if(result.budgetAnswer?.status==='amount'&&['all_feasible','all_infeasible'].includes(result.budgetDecision))lines.push(say(`依据本次提供的实际预算 ${result.budgetAnswer.value} ${unit}，最低成本为 ${cost} ${unit}，${result.budgetDecision==='all_feasible'?'当前方案可负担。':'预算不足。'}`,`Using the actual budget ${result.budgetAnswer.value} ${unit} and minimum cost ${cost} ${unit}, ${result.budgetDecision==='all_feasible'?'the solution is affordable.':'the budget is insufficient.'}`));
  else if(result.budgetAnswer?.status==='side'&&['all_feasible','all_infeasible'].includes(result.budgetDecision))lines.push(say('依据你对最低成本阈值的答复作出此结论；未获得预算的精确金额。','This conclusion uses your answer about the minimum-cost threshold; the exact budget remains unknown.'));
  else if (result.budgetDecision === 'all_feasible') lines.push(say(`根据当前模型与求解证据，已知预算区间${result.budget?` [${result.budget.lower}, ${result.budget.upper}] ${unit}`:''}内均能负担当前方案；这不表示预算不影响其他方案。`, `Based on the current model and solver evidence, the current solution is affordable throughout the known budget interval${result.budget?` [${result.budget.lower}, ${result.budget.upper}] ${unit}`:''}; other solutions can still be affected.`));
  if(result.budgetDecision==='all_infeasible'&&result.solverStatus==='optimal'&&Number.isFinite(cost)&&!result.budgetAnswer)lines.push(say(`最低成本 ${cost} ${unit} 高于已知预算上限 ${result.budget?.upper??'未知'} ${unit}。`,`The minimum cost ${cost} ${unit} exceeds the known budget cap ${result.budget?.upper??'unknown'} ${unit}.`));
  if (result.numericCheck) lines.push(say('数值检查容差：', 'Numerical tolerance: ') + result.numericCheck.tolerance);
  if(result.modelPurpose==='budget_threshold_base')lines.push(say('预算判断以固定预算仅限制当前成本目标、其他条件完整且模型忠实于原题为前提；程序不能自动证明这些自然语言前提。','Budget conclusions assume a fixed cap on this cost objective, complete other conditions and a faithful model; these language premises are not automatically proved.'));
  lines.push(result.semanticReviewStatus === 'no_issue_found' ? say('语义审核未发现问题；模型审核不构成数学证明。', 'Semantic review found no issue; model review is not a mathematical proof.') : say('语义审核状态：', 'Semantic review: ') + result.semanticReviewStatus);
  return lines.join('\n\n');
}
