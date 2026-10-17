import { optimizationTool } from '../shared/optimization-tool.mjs';
import { validateModel } from '../shared/solver-model.mjs';
import { preflightModel } from '../shared/model-preflight.mjs';
import { agentLimits, inputHash, modelFingerprint, decide, ask, reserveCall, stageTokens } from './agent-policy.mjs';

export class OptimizationError extends Error {}
export function solverEvidence(record) {
  return { id: record.id, modelHash: record.modelHash, engine: record.engine, versions: record.versions, model: record.model, problem: record.problem, status: record.status,
    objective: record.objective ?? null, values: record.values ?? null, check: record.check ?? null, error: record.error ?? null, invoked: !!record.provenance?.solverInvoked,
    durationMs: record.durationMs ?? null, completedAt: record.completedAt ?? null };
}
export function explanationMessages(messages, record) {
  // Preserve every user fact once, but do not replay decisions, logs, or the full coefficient matrix.
  const facts = messages.filter(m => m.role === 'user').map(m => m.content).join('\n\n');
  const evidence = { status: record.status, objective: record.objective ?? null, values: record.values ?? null,
    check: record.check ? { feasible: record.check.feasible, violations: record.check.violations } : null };
  return [{ role: 'user', content: facts + '\n\n[Local solver record supplied by the application]\n' + JSON.stringify(evidence) +
    '\nThe app already displays the complete solution, numerical checks and executed mathematical model. Add only a concise business interpretation (normally 2–4 sentences), important assumptions or unresolved semantics. Do not repeat the question, variable list, formulas, logs or headings. Use only explicit units and meanings in the user facts; do not invent mappings. Do not claim semantic verification or reveal private reasoning. Do not ask follow-up questions unless a specific unresolved condition affects the answer. Follow the user’s requested language.' }];
}
export function recordContext(record) {
  return '\n\n[Local solver record supplied by the application. Interpret this record; do not replace its values with mental arithmetic. Distinguish optimal, infeasible, unbounded, time limit and failure. A feasible model is not proof of correct problem semantics. Use LaTeX for the model and explain variable units and constraints.]\n' + JSON.stringify(solverEvidence(record));
}
function aborted(signal) { if (signal.aborted) throw new DOMException('Aborted', 'AbortError'); }

export async function executeOptimization({ config, messages, problem, engine, seconds, planner, solver, signal, answer, update, retry = false }) {
  const flow = answer.automation;
  const task = flow.task, en = config.language === 'en', say = (zh, english) => en ? english : zh;
  const pause = (code, summary) => { decide(answer, code, summary, [], 'paused'); update(); return null; };
  const clarify = (code, summary, questions) => { ask(answer, code, summary, questions, config.language); update(); return null; };
  aborted(signal);
  if (retry || task.inputs.includes(inputHash(problem))) return pause('no_new_information', say('没有新的条件，已停止重复调用。请补充或更正信息后再发送；新题请新建对话。', 'No new conditions were supplied. Add or correct information before continuing; use a new conversation for a new problem.'));
  if (task.solves >= agentLimits.solves) return pause('solver_budget', say('已达到本题 2 次求解上限，请查看记录并整理条件后新建对话。', 'The limit of two solver runs for this problem has been reached. Review the records before starting a new conversation.'));
  if (task.clarifications >= agentLimits.clarifications && task.calls >= agentLimits.calls) return pause('call_budget', say('已达到本题预算上限，请整理完整条件后新建对话。', 'This problem has reached its budget. Consolidate the conditions and start a new conversation.'));
  if (!solver.info().engines[engine]?.available) throw new OptimizationError('所选求解器未就绪，请先在设置中配置或切换 HiGHS');
  if (solver.active) throw new OptimizationError('当前已有求解任务，请等待完成后再发送补充信息');
  if (!reserveCall(answer, messages, config.language)) { update(); return null; }
  task.inputs.push(inputHash(problem));
  flow.stage = 'modeling'; update();
  const started = Date.now();
  flow.usage.modeling = { input: null, output: null };
  const plan = await planner({ ...config, maxTokens: stageTokens(config, 'modeling') }, messages, signal);
  flow.plan = plan; flow.modelingMs = Date.now() - started;
  flow.usage.modeling = plan.usage || { input: null, output: null }; update();
  aborted(signal);
  if (plan.truncated) throw new OptimizationError('建模输出不完整，已停止。请精简问题或在设置中调整输出上限后补充说明');
  let submission;
  if (Array.isArray(plan.calls) && plan.calls.length === 1 && plan.calls[0].name === optimizationTool.name) {
    submission = plan.calls[0].arguments;
    flow.submissionSource = 'native_tool';
  } else if (config.id === 'deepseek' && Array.isArray(plan.calls) && plan.calls.length === 0 && typeof plan.text === 'string' && plan.text.length <= 250000) {
    // Some compatible responses put the entire submission in content. Accept only
    // a complete JSON document, never an extracted prose answer or executable code.
    const text = plan.text.trim();
    const fenced = text.match(/^```(?:json)?\s*\n([\s\S]*?)\n```$/i);
    try {
      const candidate = JSON.parse(fenced ? fenced[1] : text);
      if (candidate && !Array.isArray(candidate) && ['action', 'model_json', 'message', 'questions'].every(key => Object.hasOwn(candidate, key))) submission = candidate;
    } catch { /* Keep the original response and report a transport failure below. */ }
    if (submission) flow.submissionSource = 'json_content';
  }
  if (submission === undefined) throw new OptimizationError('模型未提交可校验的建模数据，未执行求解；请检查执行记录中的提交状态，或更换模型后继续');
  let args;
  try { args = typeof submission === 'string' ? JSON.parse(submission) : submission; } catch { throw new OptimizationError('工具参数不是有效 JSON，未执行求解'); }
  if (!args || typeof args !== 'object' || Array.isArray(args) || Object.keys(args).some(k => !['action', 'model_json', 'message', 'questions'].includes(k)) ||
      !['solve', 'clarify', 'unsupported'].includes(args.action) || typeof args.model_json !== 'string' || args.model_json.length > 200000 || typeof args.message !== 'string' || args.message.length > 600) throw new OptimizationError('工具参数不符合模型格式，未执行求解');
  // Empty questions on legacy solve/unsupported responses are accepted for local migration.
  const questions = args.questions ?? (args.action === 'clarify' ? null : []);
  if (!Array.isArray(questions) || questions.length > agentLimits.questions || questions.some(q => !q || typeof q !== 'object' || Array.isArray(q) || Object.keys(q).some(k => !['field', 'question', 'impact'].includes(k)) ||
    Object.entries({ field: 80, question: 240, impact: 160 }).some(([k, max]) => typeof q[k] !== 'string' || !q[k].trim() || q[k].length > max)) ||
    (args.action === 'clarify' ? !questions.length : questions.length)) throw new OptimizationError('澄清格式无效：每轮只允许 1–3 个关键问题，已停止调用');
  if (args.action !== 'solve') {
    if (args.model_json || !args.message.trim()) throw new OptimizationError('工具参数不符合模型格式，未执行求解');
    if (args.action === 'clarify') return clarify('missing_conditions', args.message.trim(), questions);
    decide(answer, 'unsupported', args.message.trim(), [], 'unsupported'); update(); return null;
  }
  let model;
  flow.modelingSummary = args.message.trim();
  flow.showModel = /(?:完整|建立|写出|展示|解释).{0,8}(?:数学模型|约束)|(?:show|write|explain|formulate).{0,30}(?:mathematical model|constraints)/i.test(problem);
  try { model = JSON.parse(args.model_json); } catch { throw new OptimizationError('模型不是有效 JSON，未执行求解'); }
  aborted(signal);
  if (solver.active) throw new OptimizationError('当前已有求解任务，请等待完成后重试');
  let valid = false;
  try { model = validateModel(model); valid = true; } catch { /* SolverService retains a rejected run with exact validation evidence. */ }
  if (valid) {
    flow.stage = 'checking'; flow.preflight = preflightModel(model); update();
    if (flow.preflight.status === 'conflict') return clarify('bounds_conflict', say('边界检查发现提交模型中有冲突，已在求解前暂停。请核对它是否忠实表达原题。', 'The submitted model has a bound conflict. Execution is paused; check whether it represents the original problem.'), [{ field: say('冲突条件', 'Conflicting conditions'), question: say('下列证据对应的条件是否都必须成立？如有录入或建模误差，请给出原始条件；若均正确，可以保留“无可行解”的结论。', 'Must all the conditions in the evidence hold? Correct any transcription/modeling error, or retain infeasibility if they are intentional.'), impact: say('决定保留不可行结论，还是按原题修正模型；不会自动放宽约束。', 'Determines whether to retain infeasibility or correct the model; constraints are never relaxed automatically.') }]);
    const fingerprint = modelFingerprint(model);
    if (task.attempts.some(a => a.fingerprint === fingerprint)) return pause('duplicate_model', say('模型的变量、目标和约束未发生变化，已停止重复求解。请明确需修正的条件；已有记录可继续查看。', 'The variables, objective and constraints are unchanged. Re-solving is stopped. Specify the condition to correct; the previous record remains available.'));
    task.attempts.push({ fingerprint });
  }
  task.solves++;
  flow.stage = 'solving'; update();
  const record = solver.start({ model, engine, seconds, problem: problem.slice(0, 12000) });
  if (valid) Object.assign(task.attempts.at(-1), { runId: record.id });
  flow.runId = record.id; flow.stage = 'solving'; update();
  const cancel = () => solver.stop(record.id);
  signal.addEventListener('abort', cancel, { once: true });
  try {
    while (record.status === 'running') { if (signal.aborted) cancel(); await new Promise(resolve => setTimeout(resolve, 75)); }
  } finally {
    signal.removeEventListener('abort', cancel);
    flow.result = solverEvidence(record);
    if (record.provenance?.solverInvoked) answer.provenance.solverRun = { id: record.id, engine: record.engine, status: record.status, modelHash: record.modelHash };
    update();
  }
  aborted(signal);
  if (record.provenance?.solverInvoked && ['infeasible', 'unbounded'].includes(record.status)) {
    flow.interpretation = 'not_needed';
    decide(answer, 'delivered_' + record.status, record.status === 'infeasible'
      ? say('求解器报告当前模型无可行解。', 'The solver reports that the submitted model is infeasible.')
      : say('求解器报告当前模型目标无界。', 'The solver reports that the submitted model has an unbounded objective.'), [], 'complete');
    update(); return null;
  }
  if (record.provenance?.solverInvoked && record.status === 'time_limit') {
    flow.interpretation = 'not_needed';
    decide(answer, 'solver_time_limit', record.check?.feasible
      ? say('已达到求解时限；保留当前可行方案，尚未证明最优。', 'Time limit reached; the feasible solution is retained, without proven optimality.')
      : say('已达到求解时限，未取得经数值复核的可行方案。', 'Time limit reached without a numerically verified feasible solution.'), [], 'paused');
    update(); return null;
  }
  if (record.status !== 'optimal' || !record.provenance?.solverInvoked || !record.check?.feasible) {
    const diagnoses = {
      infeasible: [say('求解器报告该模型不可行，已暂停；这不等于题目或建模必然错误。', 'The solver reports this model is infeasible. This does not by itself imply an error in the problem or model.'), say('请核对需求下限、资源上限和等式条件：全部应保留，还是有具体条件需要更正？', 'Should all demand minima, resource maxima and equalities be retained, or is there a specific correction?')],
      unbounded: [say('求解器报告目标无界，已暂停。', 'The solver reports an unbounded objective; execution is paused.'), say('是否遗漏变量或资源的有限上限？若题意确实允许无界，请确认。', 'Is a finite variable/resource bound missing, or is unboundedness intentional?')],
      infeasible_or_unbounded: [say('求解器尚未区分不可行与无界，已暂停。', 'The solver has not distinguished infeasibility from unboundedness; execution is paused.'), say('请先核对资源界限与必须满足的需求；有哪些条件需要补充或更正？', 'Check resource bounds and mandatory demand. Which conditions need clarification or correction?')],
      time_limit: [say('已达到求解时限，保留当前记录并停止；未证明最优。', 'The solver time limit was reached. The record is saved; optimality is not proven.'), say('是否可以缩小规模或收紧已知边界？请给出具体修改，再决定是否重算。', 'Can the model be reduced or known bounds tightened? Provide a specific change before a new solve.')],
      rejected: [say('模型格式校验失败，未调用求解器。', 'Model validation failed; the solver was not invoked.'), say('请查看记录中的校验字段，并补充相应变量或约束的原始描述。', 'Check the validation field in the record and supply the original variable or constraint description.')]
    };
    const [summary, question] = diagnoses[record.status] || [say('工具执行或数值复核异常，已停止；请先处理记录中的问题。', 'Tool execution or numerical validation failed. Resolve the issue in the record before continuing.'), say('请查看记录：需要修复求解器环境，还是更正模型条件？处理后再发送补充信息。', 'Does the record require an environment fix or a model correction? Address it before sending a follow-up.')];
    return clarify('solver_' + record.status, summary, [{ field: say('下一步', 'Next step'), question, impact: say('有明确修正后才重新建模，不自动重试或放宽条件。', 'Remodel only after an explicit correction; no automatic retries or relaxation.') }]);
  }
  flow.decision = { code: 'verified_result', summary: say('本地求解完成，数值复核通过。', 'Local solve completed and numerical checks passed.') };
  flow.stage = 'interpreting'; update();
  return record;
}
