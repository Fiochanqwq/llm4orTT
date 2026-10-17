import { useState } from 'react';
import type { Automation, Language, Question, ReplyTo } from './types';
import { api } from './api';
import { ExecutionIssue } from './ExecutionIssue';
function QuestionForm({q,disabled,language,reply}:{q:Question;disabled:boolean;language:Language;reply:(text:string,to:ReplyTo)=>void}){
  const [value,setValue]=useState('');const en=language==='en';
  return <form className="clarification-card" onSubmit={e=>{e.preventDefault();if(value.trim()&&q.id&&q.taskId&&q.gapId&&q.factVersion!==undefined)reply(value.trim(),{taskId:q.taskId,questionId:q.id,gapId:q.gapId,factVersion:q.factVersion});}}>
    <h3>{q.field}</h3><p>{q.question}</p><p className="card-context">{q.impact}</p>
    {!disabled ? <><div className="question-options">{q.options?.map(option=><label key={option}><input type="radio" name={q.id} checked={value===option} onChange={()=>setValue(option)}/>{option}</label>)}</div><label>{en?'Your answer':'你的答复'}<input value={value} onChange={e=>setValue(e.target.value)} maxLength={2000}/></label><button className="primary-button" disabled={!value.trim()}>{en?'Submit answer':'提交答复'}</button></>:<p>{en?'This question is inactive.':'此问题已回答、失效或正在处理。'}</p>}
  </form>;
}
export function ResearchCard({flow,language,open,streaming,active,busy,reply}:{flow:Automation;language:Language;open:(id:string)=>void;streaming:boolean;active:boolean;busy:boolean;reply:(text:string,to:ReplyTo)=>void}){
  const en=language==='en',s=(zh:string,english:string)=>en?english:zh,r=flow.resultContract;
  const [behavior,setBehavior]=useState<unknown>(null),[checking,setChecking]=useState(false);
  const stages:Record<string,string>=en?{modeling:'Building model',reviewing:'Reviewing original requirements',repairing:'Targeted model repair',protocol_repair:'Correcting submission references',queued:'Waiting for solver',solving:'Local solver running',clarification:'Awaiting your answer',complete:'Delivered',paused:'Paused',error:'Execution issue',failed:'Execution issue',stopped:'Stopped'}:{modeling:'建立模型',reviewing:'核对原文与模型',repairing:'定向修复模型',protocol_repair:'纠正提交字段与引用',queued:'等待求解器',solving:'本地求解中',clarification:'等待你的答复',complete:'已交付',paused:'已暂停',error:'执行问题',failed:'执行问题',stopped:'已停止'};
  stages.checking=s('复核已有求解记录','Rechecking saved solver evidence');
  return <div className="research-answer" data-stage={flow.stage}>
    <div className="research-state" role="status">{stages[flow.stage]||flow.stage}{streaming?' …':''}</div>
    {['error','failed'].includes(flow.stage)&&<ExecutionIssue issue={flow.failure||flow.protocolError} legacy={flow.validationError} language={language} solves={flow.task?.solves}/>}
    {r&&<section className="result-card"><h3>{flow.stage==='complete'&&r.taskOutcome==='complete'?s('结果','Result'):s('当前证据 · 任务未完成','Current evidence · task incomplete')}</h3>
      <p className="preserve-lines">{flow.decision?.summary}</p>
      {r.evidenceReused&&<p className="card-context">{s('已核对当前条件并复用已有求解记录，本次没有重新求解。','The current conditions were checked against saved solver evidence; no new solve was needed.')}</p>}
      {r.displayValues&&r.budgetDecision==='all_infeasible'&&<p className="card-context">{s('以下为无预算基础模型的参考值，并非当前预算下可执行的方案。','The values below describe the base model without the budget cap, not an executable plan under the current budget.')}</p>}
      {r.displayValues&&<dl className="result-values">{Object.entries(r.displayValues).map(([name,value])=>{const entity=r.entities?.find(e=>e.variable===name);return <div key={name}><dt>{entity?.label||name}</dt><dd>{String(value)}{entity?.unit?' '+entity.unit:''}</dd></div>;})}</dl>}
      <p className="card-context">{s('展示值复核','Display validation')}: {r.displayValues&&r.displayValidation?.feasible?s('通过','Passed'):s('暂无可验证展示值','No validated display values')} · {s('语义审核','Semantic review')}: {r.semanticReviewStatus==='no_issue_found'?s('未发现问题（非证明）','No issue found (not a proof)'):r.semanticReviewStatus==='not_run'?s('未额外审核','Not separately reviewed'):r.semanticReviewStatus}</p>
      {flow.contract?.modelPurpose==='budget_threshold_base'&&<p className="card-context">{s('求解记录对应无预算基础模型；实际预算判断单独记录。','The solve is for the base model without the budget cap; budget relevance is recorded separately.')}</p>}
    </section>}
    {!r&&flow.decision&&<section className="issue-card"><p>{flow.decision.summary}</p></section>}
    {flow.review?.diagnostics.map((d,i)=><section className="issue-card" key={i}><h3>{s('原文与模型核对','Source/model review')}</h3><blockquote>{d.sourceSpan}</blockquote><p>{d.evidence}</p></section>)}
    {flow.questions?.map((q,i)=><QuestionForm key={q.id||i} q={q} language={language} disabled={!active||busy||q.status!=='pending'} reply={reply}/>)}
    <details className="research-evidence"><summary>{s('查看证据与方法记录','Evidence and method record')}</summary><p>{s('方法预设','Method preset')}: {flow.methods?.preset} · {flow.methods?.version}</p>
      <p>{s('模型调用 / 求解 / 澄清轮次','Model calls / solves / clarification rounds')}: {flow.task?.calls} / {flow.task?.solves} / {flow.task?.clarifications}</p>
      <p>{s('协议纠正次数（已计入模型调用）','Protocol corrections (included in model calls)')}: {flow.task?.protocolCorrections||0} · {s('本任务开关','Frozen option')}: {flow.methods?.protocolCorrection?s('开启','On'):s('关闭','Off')}</p>
      {!!flow.protocolIssues?.length&&<details><summary>{s('提交问题与纠正记录','Submission issues and correction history')}</summary><pre>{JSON.stringify(flow.protocolIssues,null,2)}</pre></details>}
      <p>{s('行为检验仅用于离线实验，不代表本轮已执行。','Behavioral testing belongs to offline experiments; it was not executed in this turn.')}</p>
      {flow.runId&&<button className="secondary-button" onClick={()=>open(flow.runId!)}>{s('查看实际求解记录','Open actual solver record')}</button>}
      {flow.runId&&r?.solverStatus==='optimal'&&<button className="secondary-button" disabled={checking||streaming} onClick={async()=>{setChecking(true);try{setBehavior(await api('/solver/runs/'+flow.runId+'/behavioral','POST',{}));}catch(e){setBehavior({error:(e as Error).message});}finally{setChecking(false);}}}>{checking?s('离线检查中…','Offline checks running…'):s('离线行为检查（最多 3 次本地求解）','Offline behavioral checks (up to 3 local solves)')}</button>}
      {behavior!==null&&<pre>{JSON.stringify(behavior,null,2)}</pre>}
      {flow.contract&&<details><summary>{s('事实、模型对应与缺口','Facts, bindings and gaps')}</summary><pre>{JSON.stringify(flow.contract,null,2)}</pre></details>}
    </details>
  </div>;
}
