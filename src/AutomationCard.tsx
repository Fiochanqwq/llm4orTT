import { MathSymbol } from './MathSymbol';
import { ModelExport } from './ModelExport';
import { Calculator, LoaderCircle, ArrowUpRight } from 'lucide-react';
import { MathFormula } from './MathFormula';
import { modelLatex } from '../shared/math-format.mjs';
import type { Automation, Language } from './types';

export function AutomationCard({ flow, language, open, streaming }: { flow: Automation; language: Language; open: (id: string) => void; streaming: boolean }) {
  const en = language === 'en', result = flow.result, label = (zh: string, english: string) => en ? english : zh;
  const number = (value: number) => new Intl.NumberFormat(en ? 'en' : 'zh-CN', { maximumSignificantDigits: 10 }).format(value);
  const statuses: Record<string, string> = en ? { optimal: 'Optimal for submitted model', infeasible: 'Submitted model is infeasible', unbounded: 'Submitted model is unbounded', infeasible_or_unbounded: 'Infeasible or unbounded', time_limit: 'Time limit · optimality unproven', rejected: 'Invalid model', unavailable: 'Unavailable', error: 'Failed', stopped: 'Stopped', interrupted: 'Interrupted' } : { optimal: '当前模型最优解', infeasible: '当前模型无可行解', unbounded: '当前模型目标无界', infeasible_or_unbounded: '不可行或无界', time_limit: '达到时限 · 未证明最优', rejected: '模型校验失败', unavailable: '未就绪', error: '求解失败', stopped: '已停止', interrupted: '已中断' };
  const verified = !!result?.invoked && !!result.check?.feasible && ['optimal', 'time_limit'].includes(result.status);
  const constraints = result?.check?.constraints || [], failures = result?.check?.violations || [];
  const interpretation = flow.interpretation;
  const interpretationLabels: Record<string, string> = en ? { not_started: 'Not started', not_needed: 'Not needed', running: 'In progress', complete: 'Complete', incomplete: 'Incomplete', skipped: 'Skipped · budget limit', error: 'Failed · result retained', stopped: 'Stopped · result retained' } : { not_started: '尚未开始', not_needed: '无需解读', running: '解读中', complete: '已完成', incomplete: '未完成', skipped: '预算限制 · 未调用', error: '解读失败 · 结果保留', stopped: '解读停止 · 结果保留' };
  const interaction = flow.stage === 'complete' ? label('已交付', 'Delivered') : flow.stage === 'clarification' ? label('等待澄清', 'Awaiting clarification') : flow.stage === 'paused' ? label('已暂停', 'Paused') : flow.stage === 'stopped' ? label('已取消', 'Cancelled') : flow.stage === 'error' ? label('执行异常', 'Execution error') : flow.stage === 'unsupported' ? label('超出范围', 'Outside scope') : label('处理中', 'In progress');
  return <div className="automation-card" data-stage={flow.stage} data-invoked={!!result?.invoked}>
    <div className="automation-result-heading"><span><Calculator size={14}/>{label('结论', 'Result')}</span><strong>{result ? (result.status === 'optimal' && !verified ? label('最优报告未通过数值确认', 'Optimal report not numerically verified') : statuses[result.status] || result.status) : interaction}</strong></div>
    {streaming && !result && <p className="automation-progress"><LoaderCircle size={14} className="spin"/>{flow.stage === 'solving' ? label('本地求解中', 'Solving locally') : flow.stage === 'checking' ? label('检查模型边界', 'Checking model bounds') : label('建立数学模型', 'Building the model')}</p>}
    {flow.decision && flow.decision.code !== 'verified_result' && <p className="automation-decision">{flow.decision.summary}</p>}
    {result?.invoked && ['infeasible', 'unbounded'].includes(result.status) && <p className="automation-note">{label('这是提交模型的求解状态；尚未独立核对原题，未推断额外的业务原因。', 'This status applies to the submitted model; original requirements have not been independently verified.')}</p>}
    {verified && result && <>
      {result.objective !== null && <div className="automation-objective"><span>{label('目标值', 'Objective')}</span><strong>{number(result.objective)}</strong></div>}
      <h4>{label('方案', 'Solution')}</h4>
      <div className="automation-values">{Object.entries(result.values || {}).map(([key, value]) => <span key={key}><MathSymbol name={key}/><b title={String(value)}>{number(value)}</b></span>)}</div>
    </>}
    {result && <section className="automation-checks"><h4>{label('条件核对', 'Checks')}</h4>
      <p>{result.check ? (result.check.feasible ? label('提交模型数值检查通过', 'Submitted-model numerical checks passed') : label('提交模型数值检查未通过', 'Submitted-model numerical checks failed')) : label('没有可供数值复核的方案', 'No solution available for numerical checks')}</p>
      {!!failures.length && <p className="automation-failures">{label('未通过：', 'Failed: ')}{failures.join(', ')}</p>}
      <p className="automation-note">{label('原题语义未独立审核；未执行行为测试。', 'Original semantics not independently audited; behavioral tests not performed.')}</p>
      {!!constraints.length && <details><summary>{label('全部约束检查', 'All constraint checks')} · {constraints.length}</summary><div className="automation-check-list">{constraints.map(c => <div key={c.name} data-failed={failures.includes(c.name)}><MathSymbol name={c.name}/><span title={c.lhs + ' ' + c.sense + ' ' + c.rhs}>{number(c.lhs)} {c.sense} {number(c.rhs)}</span><span>{label('余量', 'Slack')} {number(c.slack)}</span></div>)}</div></details>}
    </section>}
    {!!flow.questions?.length && <ol className="automation-questions" aria-label={label('需要澄清', 'Clarification')}>{flow.questions.map((q, i) => <li key={i}><strong>{q.field}</strong><p>{q.question}</p><small>{q.impact}</small></li>)}</ol>}
    {!!flow.preflight?.evidence.length && <div className="automation-evidence">{flow.preflight.evidence.map((line, i) => <code key={i}>{line}</code>)}</div>}
    {interpretation && !['complete', 'not_started', 'not_needed'].includes(interpretation) && <p className="automation-interpretation" role="status">{interpretationLabels[interpretation]}</p>}
    <details className="automation-reasoning"><summary>{label('推理摘要', 'Reasoning summary')}</summary><ol>
      {flow.modelingSummary && <li>{label('模型提交说明：', 'Model submission: ')}{flow.modelingSummary}</li>}
      {flow.preflight && <li>{flow.preflight.status === 'conflict' ? label('边界预检发现冲突，未进入求解。', 'Bound preflight found a conflict; solving was not started.') : label('边界预检未发现冲突；这不证明可行性或题意正确。', 'Bound preflight found no conflict; this is not proof of feasibility or semantic correctness.')}</li>}
      {result && <li>{result.engine} · {result.invoked ? label('实际调用', 'Actual call') : label('未调用', 'Not invoked')} · {statuses[result.status] || result.status}</li>}
      <li>{flow.decision?.summary || interaction}</li>
    </ol></details>
    {result?.model && <details className="automation-model" open={flow.showModel || undefined}><summary>{label('完整模型', 'Complete model')}</summary><MathFormula text={modelLatex(result.model)}/><ModelExport model={result.model} language={language} engine={result.engine}/></details>}
    <details className="automation-details"><summary>{label('执行记录', 'Execution record')}</summary>
      {flow.submissionSource && <p>{label('建模提交：', 'Model submission: ')}{flow.submissionSource === 'json_content' ? label('JSON 兼容提交（非原生工具调用；仍须校验和实际求解）', 'JSON compatibility submission (not a native tool call; validation and actual solving still required)') : label('原生工具调用', 'Native tool call')}</p>}
      <p>{label('交互：', 'Interaction: ')}{interaction}{interpretation && <> · {label('解读：', 'Explanation: ')}{interpretationLabels[interpretation]}</>}</p>
      {flow.task && <div className="automation-budget"><span>{label('模型调用', 'Model calls')} {flow.task.calls}/{flow.limits?.calls ?? '—'}</span><span>{label('求解尝试', 'Solve attempts')} {flow.task.solves}/{flow.limits?.solves ?? '—'}</span><span>{label('澄清', 'Clarify')} {flow.task.clarifications}/{flow.limits?.clarifications ?? '—'}</span></div>}
      {Object.entries(flow.usage || {}).map(([phase, usage]) => <p key={phase}>{phase === 'modeling' ? label('建模', 'Modeling') : label('解读', 'Explanation')} · token {usage.input ?? '—'} / {usage.output ?? '—'} ({label('输入 / 输出', 'input / output')})</p>)}
      {result && <><p>{result.engine} {JSON.stringify(result.versions || {})} · {result.durationMs == null ? '—' : result.durationMs + ' ms'}</p><p>{result.completedAt}</p><code>{result.id}</code><code>{result.modelHash}</code></>}
      {flow.policyVersion && <p>{label('展示策略', 'Display policy')} {flow.policyVersion}</p>}
      {flow.executionPolicyVersion && <p>{label('执行策略', 'Execution policy')} {flow.executionPolicyVersion}</p>}
      {flow.runId && <button className="automation-record" onClick={() => open(flow.runId!)}>{label('查看模型与求解记录', 'View model & solver record')}<ArrowUpRight size={13}/></button>}
    </details>
  </div>;
}
