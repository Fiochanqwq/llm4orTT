import type { Failure, Language } from './types';
export function ExecutionIssue({issue,legacy,language,solves=0}:{issue?:Failure;legacy?:string;language:Language;solves?:number}) {
  const en=language==='en';
  if(!issue&&!legacy)return null;
  const code=issue?.code||legacy||'';
  const source=issue?.layer==='source'||code.includes('source reference');
  const reference=issue?.layer==='reference'||code.includes('coverage reference')||code.includes('model target');
  const state=issue?.layer==='state';
  const stage=issue?.stage&&({modeling:en?'Modeling':'建模',reviewing:en?'Semantic review':'语义审核',protocol_repair:en?'Submission correction':'提交纠正',repairing:en?'Model repair':'模型修复',solving:en?'Solving':'求解'}[issue.stage]||issue.stage);
  const label=source?(en?'The source reference could not be verified.':'无法核对提交的原文引用。'):reference?(en?'A reference does not match the current object list.':'提交的引用与当前对象清单不一致。'):state?(en?'The claimed state has no verified evidence.':'提交的状态缺少可验证的证据。'):(en?'This stage did not finish successfully.':'当前阶段未能完成。');
  return <section className="issue-card execution-issue" role="status"><h3>{en?'Task incomplete':'任务未完成'}</h3><p>{label}</p><p>{solves===0?(en?'The solver has not been invoked; this is not a mathematical infeasibility result.':'尚未调用求解器；这不表示题目无解。'):(en?'Existing solver records are retained; the whole task is not yet complete.':'已有求解记录已保留，整个任务仍未完成。')}</p><details><summary>{en?'Failure details':'查看具体原因'}</summary><dl><dt>{en?'Stage':'阶段'}</dt><dd>{stage||'—'}</dd><dt>{en?'Field':'字段'}</dt><dd>{issue?.path||'—'}</dd><dt>{en?'Code':'原因代码'}</dt><dd>{code}</dd>{issue?.expected&&<><dt>{en?'Expected':'允许内容'}</dt><dd>{issue.expected}</dd></>}{issue?.received&&<><dt>{en?'Received':'实际内容'}</dt><dd>{issue.received}</dd></>}</dl></details></section>;
}
