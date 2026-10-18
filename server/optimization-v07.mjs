import crypto from 'node:crypto';
import { methodPresets, methodVersion, paperRefs, frozenConfig } from '../shared/methods.mjs';
import { researchTool as legacyResearchTool, reviewTool as legacyReviewTool, researchPrompt as legacyResearchPrompt, reviewPrompt as legacyReviewPrompt } from '../shared/research-tool.mjs';
import { compactVersion, actionTool, compactResearchTool, compactReviewTool, compactPrompt, compactReviewPrompt, compactCatalog, compileCompactContract, compileCompactReview, readCompactObject, mergeCompactQuestions, compactCorrectionHints, previousFactHandle } from '../shared/compact-protocol.mjs';
import { validateModel } from '../shared/solver-model.mjs';
import { validateContract, validateReview, parseSubmission } from '../shared/task-contract.mjs';
import { sourceCatalog, targetCatalog, protocolVersion, questionSchema, assertShape, diagnosticFor, diagnosticText, issue } from '../shared/protocol-schema.mjs';
import { resultContract, resultText, numericalCheck, objectiveUnitFromContract } from '../shared/result-contract.mjs';
import { preflightModel } from '../shared/model-preflight.mjs';
import { agentLimits, reserveCall, inputHash, modelFingerprint, decide, stageTokens } from './agent-policy.mjs';
import { OptimizationError, solverEvidence } from './optimization-legacy.mjs';
import { budgetDecision, resolveBudgetReply } from './budget-relevance.mjs';
import { queuedSolve } from './solver-queue.mjs';
import { evidenceDecision, evidenceRepairInstruction, evidenceQuestion } from './evidence-routing.mjs';
import { decisionMetricsVersion, recordAction } from './decision-metrics.mjs';
const hash = x => crypto.createHash('sha256').update(typeof x === 'string' ? x : JSON.stringify(x)).digest('hex');
export function initializeMethods(flow, config, engine, preset = 'full') {
  const task = flow.task;
  task.frozen ||= frozenConfig(config, engine, preset);
  if (task.frozen.methodVersion !== methodVersion && task.frozen.preset !== 'legacy') throw new OptimizationError('当前任务属于旧协议版本。历史记录已保留，请新建对话使用更新后的方法。');
  task.factVersion ||= 0; task.questions ||= []; task.requests ||= [];
  if (!task.calls) { task.decisionMetricsVersion = decisionMetricsVersion; task.decisionEvents ||= []; }
  const id = task.frozen.preset;
  if (!Object.hasOwn(methodPresets,id)) throw new OptimizationError('未知方法预设');
  if(id!=='legacy'){flow.policyVersion='0.7.7-local-1';flow.executionPolicyVersion='0.7.7-contract-1';}
  flow.methods = { preset: id, version: methodVersion, ...methodPresets[id], paperRefs,
    protocolVersion:compactVersion, protocolCorrection: task.frozen.protocolCorrection === true,
    modeling: 'not_run', semanticReview: 'not_run', repairStatus: 'not_run', protocolRepairStatus: 'not_run', toolRepairStatus: 'not_run', budgetRelevance: 'not_run', behavioral: 'offline_only' };
  return flow.methods;
}
export function validateReply(task, reply) {
  if (!reply || reply.taskId !== task.id || reply.factVersion !== task.factVersion) throw new OptimizationError('当前问题已更新，请使用最新问题卡');
  const question = task.questions?.find(q => q.id === reply.questionId && q.gapId === reply.gapId && q.status === 'pending');
  if (!question) throw new OptimizationError('当前问题已回答或已失效');
  return question;
}
export async function executeV07({ config, messages, problem, engine, seconds, planner, solver, signal, answer, update, retry = false, compact = false, continuation = false }) {
  const flow = answer.automation, task = flow.task, methods = flow.methods, en = config.language === 'en';
  let evidenceEnabled = !!methods.programmatic && !task.evidenceDisabled;
  const disableEvidence = error => {
    signal.throwIfAborted();
    evidenceEnabled = false;
    task.evidenceDisabled = { code: 'EVIDENCE_UNAVAILABLE', reason: String(error?.message || error).slice(0, 2000) };
    flow.programmaticEvidence = { diagnostic_error: task.evidenceDisabled.reason };
    (flow.evidenceDecisions ||= []).push({ action: 'fallback', phase: 'availability', reasons: ['evidence_unavailable'], fallbackMode: 'no_evidence' });
    update();
  };
  const researchTool=compact?(methods.structured?compactResearchTool:actionTool):legacyResearchTool,reviewTool=compact?compactReviewTool:legacyReviewTool;
  const researchPrompt=compact?language=>compactPrompt(language,methods):legacyResearchPrompt,reviewPrompt=compact?compactReviewPrompt:legacyReviewPrompt;
  const say = (zh, english) => en ? english : zh;
  const unfinished = outcome => { flow.taskOutcome=outcome; if(flow.resultContract)flow.resultContract.taskOutcome=outcome; flow.publicOutcome={status:null,values:null,objective:null,complete:false,source:'unfinished'}; };
  const stop = (code, zh, english, stage = 'paused') => { recordAction(task,'fallback',code); unfinished(stage === 'unsupported' ? 'unsupported' : 'partial'); decide(answer, code, say(zh, english), [], stage); update(); return null; };
  const fail = (zh, english) => { recordAction(task,'fallback','technical_failure'); task.technicalFailure = true; unfinished('failed'); flow.failure ||= {layer:flow.result?'numeric':'solver',code:flow.result?'RESULT_VALIDATION_FAILED':'SOLVER_UNAVAILABLE',stage:flow.stage,path:'$',recoverable:false}; update(); throw new OptimizationError(say(zh, english)); };
  const publish = (record, extra = {}) => {
    flow.result = solverEvidence(record); flow.runId = record.id;
    flow.resultContract = resultContract(record, { factVersion: task.factVersion, modelVersion: task.modelVersion,
      modelPurpose: flow.contract?.modelPurpose || 'final_task', semanticReviewStatus: flow.review?.status || 'not_run',
      objectiveUnit:objectiveUnitFromContract(flow.contract),
      entities:flow.entities||task.attempts.findLast(a=>a.runId===record.id)?.entities||[],budget:flow.contract?.budget??null,budgetAnswer:task.budgetAnswer??null,...extra });
    if(flow.contract?.modelPurpose==='budget_threshold_base'&&!['all_feasible','all_infeasible'].includes(extra.budgetDecision))flow.resultContract.taskOutcome='partial';
    if(extra.budgetDecision==='all_infeasible')flow.resultContract.taskOutcome='complete';
    if(compact&&!methods.structured)flow.resultContract.taskOutcome='partial'; // the agent must still deliver its final answer
    flow.taskOutcome = flow.resultContract.taskOutcome;
    flow.interpretation = 'local_template'; flow.stage = flow.resultContract.taskOutcome === 'complete' ? 'complete' : 'paused';
    if(flow.stage==='complete'&&!task.inputs.includes(inputHash(problem)))task.inputs.push(inputHash(problem));
    if (record.provenance?.solverInvoked) answer.provenance.solverRun = { id: record.id, engine: record.engine, status: record.status, modelHash: record.modelHash };
    answer.content = resultText(flow.resultContract, config.language); flow.decision = { code: 'local_result', summary: answer.content }; update();
    const finalStatus=flow.stage==='complete'?(extra.budgetDecision==='all_infeasible'?'infeasible':record.status):null;
    flow.resultContract.finalStatus=finalStatus;
    flow.publicOutcome={status:finalStatus,values:finalStatus==='optimal'?flow.resultContract.displayValues:null,objective:finalStatus==='optimal'?flow.resultContract.objectiveRecomputed:null,complete:flow.stage==='complete',source:'displayed_result'};
  };
  const askQuestions = (questions, gaps, summary) => {
    if (task.clarifications >= agentLimits.clarifications) return stop('clarification_budget', '已达到澄清上限，保留未解决缺口。', 'Clarification limit reached; unresolved gaps are retained.');
    task.clarifications++;
    recordAction(task,'clarify','business_conditions');
    flow.questions = questions.map((q,i) => ({ ...q, id: crypto.randomUUID(), taskId: task.id, gapId: gaps[i].id, factVersion: task.factVersion, status: 'pending' }));
    for (const [i,q] of flow.questions.entries()) { gaps[i].status = 'asked'; gaps[i].questionId = q.id; task.questions.push(q); }
    task.contract = structuredClone(flow.contract);
    unfinished('awaiting_answer'); flow.stage = 'clarification'; flow.decision = { code: 'missing_conditions', summary }; answer.content = summary; update(); return null;
  };
  async function request(stage, prompt, tool, input, repairKind = null) {
    signal.throwIfAborted();
    const all = [{role:'system',content:prompt}, ...input];
    if (!reserveCall(answer, all, config.language)) { recordAction(task,'fallback','request_budget'); flow.taskOutcome='partial'; update(); return null; }
    if(stage==='protocol_repair'){task.protocolCorrections=(task.protocolCorrections||0)+1;methods.protocolRepairStatus='executed';}
    if(repairKind){recordAction(task,'repair','repair_request_reserved',repairKind);if(repairKind==='semantic')task.semanticRepairs=(task.semanticRepairs||0)+1;}
    const req = { id: crypto.randomUUID(), stage, repairKind, status: 'reserved', createdAt: new Date().toISOString(), promptHash: hash(prompt), prompt, input: structuredClone(input), usage: {input:null,output:null} };
    task.requests.push(req); flow.stage = stage; flow.usage[req.id] = req.usage; update();
    req.status = 'queued'; update();
    try {
      const response = await planner({...config, tool, stagePrompt: prompt, maxTokens: stageTokens(config,'modeling'),onDispatch:()=>{req.status='sent';update();}}, input, signal);
      req.response = response; req.usage = response.usage || req.usage; req.status = 'completed'; req.completedAt = new Date().toISOString();
      flow.usage[req.id] = req.usage; flow.plan = response; update(); return response;
    } catch (error) { req.status = signal.aborted ? 'cancelled_unknown' : 'failed'; req.httpStatus = Number(error.status) || null; task.technicalFailure = true; if(flow.failure?.layer!=='budget')flow.failure = { layer: 'transport', code: signal.aborted ? 'REQUEST_INTERRUPTED' : 'REQUEST_FAILED', stage, path: '$', httpStatus: req.httpStatus, recoverable: false }; flow.taskOutcome = signal.aborted ? 'stopped' : 'failed'; update(); throw error; }
  }
  function recordIssue(error, stage) {
    const d = diagnosticFor(error, stage);
    flow.validationError = error.message; flow.protocolError = d; flow.failure = d;
    (flow.protocolIssues ||= []).push(d); update(); return d;
  }
  async function acceptOrCorrect(response, stage, prompt, tool, input, accept, reserveAfter = 0) {
    try { return accept(response); } catch (error) {
      const d = recordIssue(error, stage);
      const mayCorrect = methods.protocolCorrection && d.recoverable && !(task.protocolCorrections || 0) && task.calls + 1 + reserveAfter <= agentLimits.calls;
      if (!mayCorrect) { flow.taskOutcome = 'failed'; answer.content = diagnosticText(d, config.language); update(); return fail(answer.content, answer.content); }
      // Protocol repair is a separate, frozen treatment. It never changes user facts,
      // bypasses semantic review, retries transport failures or resets task counters.
      let rejectedArgs;
      try{rejectedArgs=parseSubmission(response,config.id,tool.name).value;}catch{}
      const correctionInput = [{ role: 'user', content: JSON.stringify({
        context: JSON.parse(input[0].content), rejectedResponse: response.calls?.length ? response.calls : response.text,
        issue: d, ...(model ? { targetCatalog: targetCatalog(model, compact?[]:contract?.gaps || []) } : {}),
        ...(compact?{compactProtocol:compactCorrectionHints(rejectedArgs,model,{messages:original,previous:previousContract})}:{}),
        instruction: 'Correct only the identified protocol/reference failure. Retain the mathematical model, original facts and any substantive review findings. Do not delete diagnoses to make the response pass. '+(compact?'Use sourceCatalog s-handles for sources, previousFacts p-handles for previous/replaces, and typed locations from compactProtocol for targets. pendingGaps identifies the prior fact and candidate new evidence; resolve it only if that evidence actually answers it. ':'Choose source/target IDs from the supplied catalog. ')+'If a semantic uncertainty remains, report it.'
      }) }];
      const corrected = await request('protocol_repair', prompt, tool, correctionInput);
      if (!corrected) return null;
      try {
        // A format repair may relocate references, but may not rewrite mathematics
        // or erase an adverse review. Such changes need the semantic repair path.
        let beforeArgs;
        try { beforeArgs = parseSubmission(response,config.id,tool.name).value; } catch {}
        const afterArgs = parseSubmission(corrected,config.id,tool.name).value;
        if (tool.name === reviewTool.name && beforeArgs) {
          let prior; try { prior=compact?readCompactObject(beforeArgs.review_json,'$.review_json'):JSON.parse(beforeArgs.review_json); } catch {}
          const next=compact?readCompactObject(afterArgs.review_json,'$.review_json'):JSON.parse(afterArgs.review_json);
          if (prior) {
            if(compact&&prior.checks&&Object.entries(prior.checks).some(([k,v])=>['uncertain','not_checked'].includes(v)&&next.checks?.[k]!==v))issue('CORRECTION_CHANGED_FINDING','$.checks','preserve substantive uncertainty during protocol correction',next.checks,{layer:'semantic',recoverable:false});
            const findings = d => ({code:d.code,evidence:d.evidence,repairable:d.repairable});
            if (['mismatch','uncertain'].includes(prior.status) && next.status!==prior.status || ['supported','unsupported','uncertain','not_applicable'].includes(prior.budgetApplicability) && next.budgetApplicability!==prior.budgetApplicability || Array.isArray(prior.diagnostics) && prior.diagnostics.some(d=>!(next.diagnostics||[]).some(n=>JSON.stringify(findings(d))===JSON.stringify(findings(n))))) issue('CORRECTION_CHANGED_FINDING','$','preserve substantive review findings during protocol correction',next.status,{layer:'semantic',recoverable:false});
          }
        } else if (beforeArgs?.action === 'solve') {
          let prior; try { prior=validateModel(JSON.parse(beforeArgs.model_json)); } catch {}
          if(prior&&(afterArgs.action!=='solve'||modelFingerprint(prior)!==modelFingerprint(validateModel(JSON.parse(afterArgs.model_json)))))issue('CORRECTION_CHANGED_MODEL','$.model_json','preserve valid mathematics during protocol correction',afterArgs.action,{layer:'semantic',recoverable:false});
        }
        const result = accept(corrected); delete flow.protocolError; delete flow.failure; update(); return result;
      }
      catch (next) { const final = recordIssue(next, stage); flow.taskOutcome = 'failed'; answer.content = diagnosticText(final, config.language); update(); return fail(answer.content, answer.content); }
    }
  }
  signal.throwIfAborted();
  const newestUser=messages.findLast(m=>m.role==='user');
  // An identical short answer can supply different facts in different questions.
  const questionContext=task.questions.filter(q=>q.status==='pending').map(q=>q.id).sort();
  const turnInputHash=inputHash(questionContext.length?JSON.stringify({text:problem.trim(),questions:questionContext,replyTo:newestUser?.replyTo?.questionId||null}):problem);
  // Explicit retry may resume only a technical failure, with the same counters.
  if (!continuation && (retry || task.inputs.includes(turnInputHash)) && !task.technicalFailure) return stop('no_new_information','没有新的条件，已停止重复调用。','No new conditions; duplicate execution stopped.');
  if (task.pendingBudget && !retry) {
    const p = task.pendingBudget, reply = resolveBudgetReply(p, problem), record = solver.get(p.runId);
    const pauseReply=(code,zh,english)=>{
      (p.unappliedReplies||=[]).push({messageId:newestUser?.id,contentHash:hash(problem),reason:code});
      stop(code,zh,english);flow.questions=structuredClone(task.questions.filter(q=>q.status==='pending'&&q.gapId===p.budget.gapId));update();return null;
    };
    if (reply.status === 'unit_conflict') return pauseReply('budget_unit_conflict',`预算单位与原条件不一致：原单位为 ${reply.expectedUnit}，答复为 ${reply.receivedUnit}。请确认本次金额；如果是在修改原单位，请说明“更正预算……”。`,`The answer uses ${reply.receivedUnit}, while the original budget uses ${reply.expectedUnit}. Confirm the amount, or explicitly state a correction to the original budget.`);
    if (reply.status === 'conflict') return pauseReply('budget_conflict','预算答复超出原区间。请确认金额；若要修改原预算条件，可说明“更正预算为……”。','The amount is outside the original interval. Confirm it, or explicitly state a correction to the original budget.');
    const priorSources=messages.filter(m=>m.role==='user').slice(0,-1).filter(m=>!p.unappliedReplies?.some(r=>r.messageId===m.id&&r.contentHash===hash(m.content))).map(({id,content})=>({id,content}));
    const cachedResult=record&&resultContract(record);
    if (['amount','side'].includes(reply.status) && record?.provenance?.solverInvoked && cachedResult?.numericCheck?.feasible && cachedResult.objectiveMatches && p.modelVersion === task.modelVersion && p.factVersion === task.factVersion && hash(task.frozen) === p.configHash && p.evidenceFingerprint === modelFingerprint(record.model) && p.sourceHash === hash(priorSources)) {
      const decision = reply.status === 'side' ? (reply.side ? 'all_feasible' : 'all_infeasible') : budgetDecision(record, {...p.budget,lower:reply.value,upper:reply.value}).status;
      if (['all_feasible','all_infeasible'].includes(decision)) {
        task.factVersion++; task.inputs.push(turnInputHash); task.questions.filter(q=>q.status==='pending').forEach(q=>q.status='answered');
        flow.contract = p.contract; flow.review = p.review;
        Object.assign(flow.contract.gaps.find(g=>g.id===p.budget.gapId), { status: reply.status==='amount'?'resolved':'proven_irrelevant',
          resolution: { kind: 'budget_reply', runId: record.id, factVersion: task.factVersion, modelVersion: task.modelVersion, sourceMessageId: messages.findLast(m=>m.role==='user')?.id, decision } });
        task.budgetAnswer = { ...reply, sourceMessageId: messages.findLast(m=>m.role==='user')?.id, runId: record.id, unappliedReplies: structuredClone(p.unappliedReplies||[]) };
        flow.contract.facts.push({id:'budget-answer-'+task.factVersion,kind:'budget_answer',sourceMessageId:task.budgetAnswer.sourceMessageId,sourceSpan:problem,entityRefs:[],unit:p.budget.unit,value:reply.value??reply.side,status:'active',supersedes:[]});
        flow.contract.bindings.push({factIds:['budget-answer-'+task.factVersion],targetRefs:['gap:'+p.budget.gapId],disposition:'deferred_to_budget_gate',reason:'Validated answer to the current budget question'});task.contract=flow.contract;
        delete task.pendingBudget; publish(record,{budgetDecision:decision,evidenceReused:true}); recordAction(task,flow.stage==='complete'?'deliver':'fallback','cached_budget_result'); update(); return null;
      }
      if (reply.status === 'amount') return stop('budget_boundary','预算位于数值边界，现有浮点证据不足以确认。记录保留，需更强证书。','The budget lies on a numerical boundary; stronger evidence is required.');
    }
    // Any non-budget update invalidates the cached threshold and its questions.
    delete task.pendingBudget;
  }
  task.technicalFailure = false;
  if (!retry&&!continuation) { task.factVersion++; task.questions.filter(q=>q.status==='pending').forEach(q=>q.status='superseded'); delete task.budgetAnswer; }
  if (!solver.info().engines[engine]?.available) return fail('所选求解器未就绪。请修正设置后继续。','The selected solver is unavailable. Correct the settings before resuming.');
  if (!task.inputs.includes(turnInputHash)) task.inputs.push(turnInputHash);
  const original = messages.filter(m=>m.role==='user');
  const previousContract=task.contract?structuredClone(task.contract):null;
  const sources = sourceCatalog(original);
  flow.sourceCatalog = sources;
  const toolEvidence=task.attempts.map((a,i)=>({handle:`r${i+1}`,factVersion:a.factVersion,...solverEvidence(solver.get(a.runId)||{id:a.runId,provenance:{}})}));
  const input = [{role:'user',content:JSON.stringify({originalMessages:original,...(compact?compactCatalog(original,task.contract):{sourceCatalog:sources,previousLedger:task.contract||null}),...(compact?{toolEvidence}:{}),...(task.toolFeedback?{toolFeedback:task.toolFeedback,repairRule:'One local correction using actual numerical/tool evidence and original facts. Never relax user conditions or invent bounds. Preserve mathematical semantics.'}:{})})}];
  let candidate, model, contract;
  const accept = plan => {
    const parsed = parseSubmission(plan, config.id, researchTool.name), args = structuredClone(parsed.value); flow.submissionSource = parsed.source;
    if(compact)assertShape(args,researchTool.parameters);
    else if (Object.keys(args).some(k=>!['action','model_json','contract_json','message','questions'].includes(k)) || !['solve','clarify','unsupported'].includes(args.action) || typeof args.message!=='string' || args.message.length>600 || typeof args.model_json!=='string' || args.model_json.length>200000 || typeof args.contract_json!=='string' || args.contract_json.length>200000 || !Array.isArray(args.questions) || args.questions.length>3) throw Error('Invalid structured submission');
    if(compact&&args.action==='final'){
      if(args.model_json||args.questions.length||!args.final)issue('FINAL_ACTION','$.final','final outcome without model or questions',args);
      if(methods.structured)issue('FINAL_REQUIRES_VALIDATED_CANDIDATE','$.action','submit a current candidate for the configured review and budget gates',args.action,{layer:'state'});
      const evidence=args.final.evidence.map(h=>{const m=/^r([1-9]\d*)$/.exec(h),r=m&&toolEvidence[Number(m[1])-1];if(!r?.invoked)issue('UNKNOWN_EVIDENCE','$.final.evidence','actual tool handle',h,{layer:'reference'});return r;});
      if(args.final.status!=='uncertain'&&!evidence.length)issue('SOLVER_EVIDENCE_REQUIRED','$.final.evidence','actual tool evidence for a conclusion',[]);
      if(args.final.status==='unbounded'&&!evidence.some(r=>r.status==='unbounded'))issue('UNBOUNDED_EVIDENCE_REQUIRED','$.final','an actual unbounded solver result',args.final,{layer:'numeric'});
      if(args.final.status==='optimal'){
        const checked=evidence.some(r=>{if(r.status!=='optimal'||!r.model)return false;const v=numericalCheck(r.model,args.final.values);return v?.feasible&&Number.isFinite(args.final.objective)&&Math.abs(v.objective-args.final.objective)<=1e-6*Math.max(1,Math.abs(v.objective))&&Math.abs(v.objective-r.objective)<=1e-6*Math.max(1,Math.abs(v.objective));});
        if(!checked)issue('FINAL_NUMERIC_MISMATCH','$.final','solution validated against actual solver evidence',args.final,{layer:'numeric'});
      }
      return args;
    }
    model = args.action==='solve' ? validateModel(JSON.parse(args.model_json)) : null;
    if(compact&&args.action==='clarify'&&args.model_json){
      (flow.normalizations||=[]).push({rule:'unexecuted_clarification_model',model_json:args.model_json});args.model_json='';
    }
    if(compact&&methods.structured){
      const compiled=compileCompactContract(args.contract_json,original,model,{previous:previousContract,budgetEnabled:methods.budget,candidateId:`c${task.factVersion}r${task.calls}`,action:args.action});contract=compiled.contract;
      if(compiled.questions.length){
        mergeCompactQuestions(args.questions,compiled.questions);
        if(args.questions.length)contract.normalizations.push({rule:'duplicate_question_metadata',envelope:structuredClone(args.questions)});
        args.questions=compiled.questions;
      }
      flow.normalizations=[...(flow.normalizations||[]),...contract.normalizations];
    }
    else if(compact){contract={format:compactVersion,modelPurpose:'final_task',facts:[],bindings:[],gaps:args.questions.map((q,i)=>({id:`q${task.factVersion}-${task.calls}-${i}`,kind:q.field||'question',status:'open'})),budget:null};args.questions=args.questions.map((q,i)=>({...q,field:q.field||q.question.slice(0,80),impact:q.impact||say('用于确定任务条件。','Determines the task conditions.'),gapId:contract.gaps[i].id}));}
    else contract = validateContract(JSON.parse(args.contract_json),original,model,{budgetEnabled:methods.budget});
    if(compact){
      const catalog=sourceCatalog(original),pending=args.action==='clarify';
      const entities=(args.entities||[]).map(e=>{
        if((!pending&&!model?.variables.some(v=>v.name===e.variable))||!e.sources.length)issue('ENTITY_REFERENCE','$.entities','actual variable and source evidence',e);
        const refs=e.sources.map(h=>{const m=/^s([1-9]\d*)$/.exec(h),s=m&&catalog[Number(m[1])-1];if(!s)issue('UNKNOWN_REFERENCE','$.entities.sources','source handle',h);return s;});
        return {...e,sourceEvidence:refs};
      });
      flow.entities=pending?[]:entities;delete flow.pendingEntities;
      if(pending&&entities.length){flow.pendingEntities=entities;(flow.normalizations||=[]).push({rule:'pending_entity_labels',entities:structuredClone(entities)});}
    }
    const newest=original.at(-1);
    const resolutions=[];
    for(const old of args.action==='unsupported'||compact&&!methods.structured?[]:previousContract?.gaps||[]) {
      if(!['open','asked','uncertain'].includes(old.status))continue;
      const carried=contract.gaps.some(g=>g.factId===old.factId);
      if(carried)continue;
      const replacement=contract.facts.find(f=>f.supersedes.includes(old.factId)&&f.sourceEvidence.some(s=>s.messageId===newest?.id));
      // The originating card gives context, not a limit on what the user can
      // answer. Every resolved gap still needs its own new evidence and review.
      if(!replacement){
        const reference=compact?compactCatalog(original,previousContract).pendingGaps.find(g=>g.previousFact===previousFactHandle(previousContract,old.factId)):old.id;
        issue('GAP_RESOLUTION_REQUIRED','$.gaps',compact?'retain this missing fact with missing.previous, or explicitly use its previousFact handle in requirement.replaces with relevant new user sources':'retain unresolved gaps, or bind a new original answer fact that supersedes the missing fact',reference,{layer:'state'});
      }
      resolutions.push({gapId:old.id,factId:replacement.id,kind:'anchored_user_answer',sourceMessageId:newest.id,factVersion:task.factVersion});
    }
    flow.gapResolutions=resolutions;
    if ((args.action==='clarify') !== !!args.questions.length || (args.action!=='solve'&&args.model_json)) throw Error('Invalid action content');
    if (model && contract.modelPurpose==='final_task' && contract.gaps.length) issue('UNRESOLVED_GAP', '$.gaps', 'clarify before final solve; only the registered budget base can defer a gap', contract.gaps, {layer:'state'});
    if (args.action==='unsupported' && (contract.facts.length || contract.bindings.length || contract.gaps.length || contract.budget)) issue('UNSUPPORTED_CONTENT', '$', 'empty ledger for unsupported', args.action);
    args.questions = args.questions.map((q,i) => {
      if (contract.format!=='llm4orovo.submission.v3' && !q.gapId && contract.gaps.length===1 && args.questions.length===1) q={...q,gapId:contract.gaps[0].id};
      assertShape(q,questionSchema,`$.questions[${i}]`);
      if (!contract.gaps.some(g=>g.id===q.gapId) || args.questions.slice(0,i).some(x=>x.gapId===q.gapId)) issue('QUESTION_GAP',`$.questions[${i}].gapId`,'one distinct existing gap per question',q.gapId,{layer:'reference'});
      return q;
    });
    for(const resolution of resolutions)for(const q of task.questions.filter(q=>q.gapId===resolution.gapId)){q.status='answered';q.answerSourceMessageId=resolution.sourceMessageId;}
    flow.contract = contract; task.contract = contract; flow.modelingSummary = args.message; methods.modeling = 'executed'; return args;
  };
  const initialRepairKind=task.programmaticFeedback?(task.programmaticFeedback.execution_error?'tool':'programmatic'):task.toolFeedback?'tool':null;
  let plan = await request(task.programmaticFeedback?'repairing':'modeling',researchPrompt(config.language,methods.budget)+(task.programmaticFeedback?'\n'+evidenceRepairInstruction(task.programmaticFeedback):''),researchTool,input,initialRepairKind); if (!plan) return null;
  delete task.programmaticFeedback; delete task.toolFeedback;
  candidate = await acceptOrCorrect(plan,'modeling',researchPrompt(config.language,methods.budget),researchTool,input,accept,methods.semantic?1:0); if(!candidate)return null;
  if(compact&&candidate.action==='final'){
    const complete=candidate.final.status!=='uncertain';flow.publicOutcome={...candidate.final,complete,source:'model_final_action'};flow.taskOutcome=complete?'complete':'partial';flow.stage=complete?'complete':'paused';flow.questions=[];
    const reference=candidate.final.evidence[0],attempt=reference&&task.attempts[Number(reference.slice(1))-1],saved=attempt&&solver.get(attempt.runId);
    if(saved){flow.result=solverEvidence(saved);flow.runId=saved.id;answer.provenance.solverRun={id:saved.id,engine:saved.engine,status:saved.status,modelHash:saved.modelHash};flow.resultContract=resultContract(saved,{modelPurpose:'agent_evidence',entities:attempt.entities||[]});}
    const finalCheck=candidate.final.status==='optimal'&&saved?.model?numericalCheck(saved.model,candidate.final.values):null;
    flow.resultContract={...(flow.resultContract||{}),taskOutcome:flow.taskOutcome,finalStatus:candidate.final.status,displayValues:candidate.final.values,values:candidate.final.values,displayValidation:finalCheck,objectiveRecomputed:candidate.final.objective,semanticReviewStatus:'not_run'};answer.content=candidate.message;flow.decision={code:'model_final',summary:candidate.message};methods.modeling='executed';
    task.questions.filter(q=>['pending','superseded'].includes(q.status)).forEach(q=>q.status='answered');if(complete&&!task.inputs.includes(inputHash(problem)))task.inputs.push(inputHash(problem));recordAction(task,complete?'deliver':'fallback','model_final');update();return null;
  }
  if(candidate.action==='unsupported') return stop('unsupported',candidate.message,candidate.message,'unsupported');
  if(candidate.action==='clarify') {
    if(initialRepairKind)return stop('repair_incomplete','程序修模不能改成向用户追问。证据已保存。','A code repair cannot consume user clarification budget.');
    const gaps=candidate.questions.map(q=>contract.gaps.find(g=>g.id===q.gapId));
    return askQuestions(candidate.questions,gaps,candidate.message);
  }
  // Run on the constructed solver object before paying for a semantic review.
  // Injected legacy test solvers without audit retain their previous interface.
  if(evidenceEnabled&&typeof solver.audit!=='function')disableEvidence('Solver audit is unavailable');
  if(evidenceEnabled&&contract.modelPurpose==='final_task'){
    for(let pass=0;pass<2;pass++){
      try {
        flow.programmaticEvidence=await solver.audit(model,original.map(m=>m.content).join('\n'),signal);
        if(!flow.programmaticEvidence||flow.programmaticEvidence.diagnostic_error)throw Error(flow.programmaticEvidence?.diagnostic_error||'Audit returned no evidence');
      } catch(error) { disableEvidence(error); break; }
      const decision=evidenceDecision(flow.programmaticEvidence,{limits:agentLimits,calls:task.calls,solves:task.solves,clarifications:task.clarifications,repair:methods.repair});
      (flow.evidenceDecisions||=[]).push({...decision,phase:'static'});update();
      if(decision.action==='continue')break;
      if(pass||task.programmaticRepairCount||decision.action!=='repair')return stop('programmatic_unresolved','程序核验仍有疑点，已保留模型与差异明细；未作为正确答案交付。','Deterministic findings remain unresolved; evidence retained without claiming a correct answer.');
      task.programmaticRepairCount=(task.programmaticRepairCount||0)+1;
      const repairInput=[{role:'user',content:JSON.stringify({originalMessages:original,...(compact?compactCatalog(original,previousContract):{sourceCatalog:sources}),model,programmaticEvidence:flow.programmaticEvidence})}];
      const prompt=researchPrompt(config.language,methods.budget)+'\n'+evidenceRepairInstruction(flow.programmaticEvidence);
      plan=await request('repairing',prompt,researchTool,repairInput,'programmatic');if(!plan)return null;
      candidate=await acceptOrCorrect(plan,'repairing',prompt,researchTool,repairInput,accept,1);if(!candidate)return null;
      if(candidate.action!=='solve')return stop('repair_incomplete','修模未返回可核验模型，未消耗追问额度。','Repair did not produce a model; no clarification budget consumed.');
      methods.repairStatus='executed';
    }
  }
  if(methods.semantic) {
    for(let pass=0; pass<2; pass++) {
      const reviewInput=[{role:'user',content:JSON.stringify({originalMessages:original,...(compact?compactCatalog(original,previousContract):{sourceCatalog:sources}),model,...(flow.programmaticEvidence?{programmaticEvidence:flow.programmaticEvidence}:{}),...(compact?{semantics:contract.normalizations?.[0]?.raw,entities:flow.entities}:{contract,targetCatalog:targetCatalog(model,contract.gaps)})})}];
      flow.targetCatalog=targetCatalog(model,contract.gaps);
      const reviewed=await request('reviewing',reviewPrompt(config.language),reviewTool,reviewInput); if(!reviewed)return null;
      const acceptReview = response => {
        const r=parseSubmission(response,config.id,reviewTool.name).value;
        if(Object.keys(r).length!==1||(!compact&&typeof r.review_json!=='string')||compact&&!Object.hasOwn(r,'review_json'))throw Error('Invalid review envelope');
        return compact?compileCompactReview(r.review_json,contract,original,model):validateReview(JSON.parse(r.review_json),contract,original,model);
      };
      const acceptedReview = await acceptOrCorrect(reviewed,'reviewing',reviewPrompt(config.language),reviewTool,reviewInput,acceptReview); if(!acceptedReview)return null;
      flow.review=acceptedReview; methods.semanticReview='executed';
      if(flow.review.normalizations.length)(flow.normalizations ||= []).push(...flow.review.normalizations);
      task.reviews ||= []; task.reviews.push(structuredClone(flow.review));
      if(flow.review.status==='no_issue_found')break;
      if(pass===0 && methods.repair && flow.review.status==='mismatch' && flow.review.diagnostics.every(d=>d.repairable) && task.calls+2<=agentLimits.calls) {
        task.candidates ||= []; task.candidates.push({model,contract,review:flow.review});
        const repairInput=[{role:'user',content:JSON.stringify({originalMessages:original,...(compact?compactCatalog(original,previousContract):{sourceCatalog:sources}),model,...(compact?{semantics:contract.normalizations?.[0]?.raw,entities:flow.entities}:{contract,targetCatalog:targetCatalog(model,contract.gaps)}),diagnosis:flow.review})}];
        const repairPrompt=researchPrompt(config.language,methods.budget)+'\nMake ONE targeted repair of the anchored semantic mismatches. Preserve all original facts. Never relax conditions to obtain feasibility.';
        plan=await request('repairing',repairPrompt,researchTool,repairInput,'semantic'); if(!plan)return null;
        candidate=await acceptOrCorrect(plan,'repairing',repairPrompt,researchTool,repairInput,accept,1);if(!candidate)return null;
        if(candidate.action!=='solve')return stop('repair_incomplete','修复未产生完整模型，任务尚未完成。','The repair did not produce a complete model; the task remains incomplete.');
        methods.repairStatus='executed'; continue;
      }
      return stop('semantic_unresolved','语义审核仍有未解决问题，已保存原文锚点与诊断；未修改用户条件。','Semantic review has unresolved findings; source anchors and diagnoses are saved. User conditions were retained.');
    }
  }
  if(contract.modelPurpose==='budget_threshold_base' && methods.semantic && flow.review?.budgetApplicability!=='supported') return stop('budget_not_supported','预算特例的适用条件未获支持，不能交付阈值结论。','Budget special-case applicability was not supported; no threshold conclusion is delivered.');
  flow.preflight=preflightModel(model); // A conflict is solver evidence, not a request to change the problem.
  const fingerprint=modelFingerprint(model);
  const reusable=task.attempts.filter(a=>(!evidenceEnabled||contract.modelPurpose!=='final_task')&&a.fingerprint===fingerprint).map(a=>solver.get(a.runId)).find(r=>{
    if(!r?.provenance?.solverInvoked||r.status!=='optimal'||r.engine&&r.engine!==engine||modelFingerprint(r.model)!==fingerprint)return false;
    const verified=resultContract(r);return verified.numericCheck?.feasible&&verified.objectiveMatches;
  });
  if(!reusable&&task.solves>=agentLimits.solves)return stop('solver_budget','已达到本题求解上限。','The solver budget for this task is exhausted.');
  task.modelVersion=(task.modelVersion||0)+1; flow.stage=reusable?'checking':'queued';update();
  const allowance=evidenceEnabled&&contract.modelPurpose==='final_task'?Math.max(0,Math.min(2,agentLimits.solves-task.solves-1)):0;
  const record=reusable||await queuedSolve(solver,{model,engine,seconds,problem:original.map(m=>m.content).join('\n').slice(0,12000),evidence:evidenceEnabled,auxiliarySolveAllowance:allowance,perturb:evidenceEnabled},signal,r=>{task.solves+=1+allowance;task.attempts.push({fingerprint,runId:r.id,factVersion:task.factVersion,modelVersion:task.modelVersion,entities:structuredClone(flow.entities||[]),reservedSolves:1+allowance});flow.runId=r.id;flow.stage='solving';update();});
  if(!reusable&&(record.programmaticEvidence||record.workerResponseValidated))task.solves-=Math.max(0,allowance-(record.programmaticEvidence?.auxiliary_solves||0));
  if(record.programmaticEvidence)flow.programmaticEvidence=record.programmaticEvidence;
  const reuseContext=reusable?{evidenceReused:true,reuseReason:'same_mathematics_after_current_validation'}:{};
  if(reusable)flow.evidenceReuse={runId:record.id,fingerprint,modelVersion:task.modelVersion,factVersion:task.factVersion,currentModel:structuredClone(model),semanticReviewStatus:flow.review?.status||'not_run'};
  publish(record,reuseContext); signal.throwIfAborted();
  if(evidenceEnabled&&['error','rejected'].includes(record.status)&&!task.programmaticRepairCount&&methods.repair&&task.calls+2<=agentLimits.calls&&task.solves<agentLimits.solves){
    task.programmaticRepairCount=1;task.programmaticFeedback={execution_error:record.error,status:record.status};task.technicalFailure=true;methods.repairStatus='executed';
    return executeV07({config,messages,problem,engine,seconds,planner,solver,signal,answer,update,retry:true,compact});
  }
  if(evidenceEnabled&&record.programmaticEvidence?.diagnostic_error)disableEvidence(record.programmaticEvidence.diagnostic_error);
  if(evidenceEnabled&&record.programmaticEvidence&&contract.modelPurpose==='final_task'){
    const e=record.programmaticEvidence, decision=evidenceDecision(e,{status:record.status,review:flow.review?.status,calls:task.calls,solves:task.solves,clarifications:task.clarifications,limits:agentLimits,repair:methods.repair});
    (flow.evidenceDecisions||=[]).push({...decision,phase:'postsolve'});update();
    if(decision.action==='repair'&&!task.programmaticRepairCount){
      task.programmaticRepairCount=1;task.programmaticFeedback=e;task.technicalFailure=true;methods.repairStatus='executed';
      return executeV07({config,messages,problem,engine,seconds,planner,solver,signal,answer,update,retry:true,compact});
    }
    if(decision.action==='clarify'){
      const factId='solver-anomaly-'+task.modelVersion,gap={id:factId,factId,kind:'solver_anomaly',status:'open',questionId:null};
      contract.facts.push({id:factId,kind:'solver_anomaly',value:null,unit:'',status:'unresolved',supersedes:[],sourceMessageId:original.at(-1).id,sourceSpan:original.at(-1).content,sourceEvidence:[{messageId:original.at(-1).id,text:original.at(-1).content}]});
      contract.gaps.push(gap);contract.bindings.push({factIds:[factId],targetRefs:['gap:'+gap.id],disposition:'pending_clarification',reason:'Solver anomaly needs confirmation of business conditions'});
      const question=evidenceQuestion(e,record.status);
      return askQuestions([{field:'业务边界与冲突条件',question,impact:'确认题面条件，不擅自放宽模型。'}],[gap],question);
    }
    if(decision.action==='fallback'||decision.action==='repair')return stop('programmatic_fallback','预算内无法消除程序核验疑点。已保留求解证据，结果仅供复核，不标记为已验证正确。','Evidence remains unresolved within budget. Saved results are provisional, not verified correct.');
  }
  if(!record.provenance?.solverInvoked || !['optimal','infeasible','unbounded','time_limit'].includes(record.status) || record.values && (!flow.resultContract.numericCheck?.feasible||!flow.resultContract.objectiveMatches)){
    const numericFailure=record.provenance?.solverInvoked&&record.status==='optimal'&&record.values&&(!flow.resultContract.numericCheck?.feasible||!flow.resultContract.objectiveMatches);
    if(numericFailure&&methods.repair&&!task.toolRepairCount&&task.calls+2<=agentLimits.calls&&task.solves<agentLimits.solves){
      task.toolRepairCount=1;task.technicalFailure=true;task.toolFeedback={runId:record.id,model:record.model,check:flow.resultContract.numericCheck,objective:record.objective,objectiveMatches:flow.resultContract.objectiveMatches};methods.toolRepairStatus='executed';update();
      return executeV07({config,messages,problem,engine,seconds,planner,solver,signal,answer,update,retry:true,compact});
    }
    return fail('求解或数值复核失败，记录已保留。未消耗澄清轮次。','Solver execution or numerical validation failed. Evidence is retained; no clarification round was consumed.');
  }
  if(compact&&!methods.structured){
    flow.stage='modeling';flow.taskOutcome='partial';flow.resultContract.taskOutcome='partial';update();
    return executeV07({config,messages,problem,engine,seconds,planner,solver,signal,answer,update,compact,continuation:true});
  }
  if(contract.modelPurpose==='budget_threshold_base') {
    const relevance=budgetDecision(record,contract.budget); flow.budgetEvidence=relevance;methods.budgetRelevance='executed';
    publish(record,{...reuseContext,budgetDecision:relevance.status});
    if(relevance.status==='needs_clarification') {
      flow.resultContract.taskOutcome='awaiting_answer';
      const gap=contract.gaps.find(g=>g.id===contract.budget.gapId);
      const q={field:say('已批准预算','Approved budget'),question:relevance.exact ? say(`已批准且不可追加的预算是否至少为 ${relevance.exact.objective} ${contract.budget.unit}？可回答是/否，或填写实际预算。`,`Is the fixed approved budget at least ${relevance.exact.objective} ${contract.budget.unit}? Answer yes/no or enter the actual amount.`) : say(`已批准且不可追加的预算是多少？当前浮点成本阈值约为 ${relevance.threshold} ${contract.budget.unit}。`,`What is the fixed approved budget? The floating-point cost threshold is approximately ${relevance.threshold} ${contract.budget.unit}.`),impact:say('用于判断当前最低成本方案是否可负担；无需重新求解。','Determines affordability of the minimum-cost plan without another solve.'), ...(relevance.exact?{options:en?['Yes','No']:['是','否']}:{})};
      task.pendingBudget={budget:contract.budget,threshold:relevance.threshold,exact:relevance.exact,runId:record.id,contract:structuredClone(contract),review:flow.review,factVersion:task.factVersion,modelVersion:task.modelVersion,configHash:hash(task.frozen),evidenceFingerprint:modelFingerprint(record.model),sourceHash:hash(original.map(({id,content})=>({id,content})))};
      return askQuestions([q],[gap],answer.content);
    }
    if(relevance.status==='uncertain'){flow.resultContract.taskOutcome='partial';flow.stage='paused';answer.content=say('预算结论仍不确定：可能处于数值边界或缺少可信界。基础模型结果已保留，实际任务尚未完成。','Budget relevance remains uncertain due to a numerical boundary or missing reliable bound. The base-model evidence is retained; the actual task is incomplete.');}
    else {Object.assign(contract.gaps.find(g=>g.id===contract.budget.gapId),{status:'proven_irrelevant',resolution:{kind:'solver_budget_evidence',runId:record.id,factVersion:task.factVersion,modelVersion:task.modelVersion,decision:relevance.status}});flow.resultContract.taskOutcome=relevance.status==='all_infeasible'||record.status==='optimal'?'complete':'partial';flow.stage=flow.resultContract.taskOutcome==='complete'?'complete':'paused';}
    flow.taskOutcome=flow.resultContract.taskOutcome;task.contract=structuredClone(contract);
    if(flow.decision)flow.decision.summary=answer.content;update();
  }
  recordAction(task,flow.stage==='complete'?'deliver':'fallback','final_result');update();
  return null;
}
