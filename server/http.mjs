import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import packageInfo from '../package.json' with { type: 'json' };
import { Store, catalog } from './store.mjs';
import { SolverService } from './solver.mjs';
import { vault } from './secrets.mjs';
import { generate, planOptimization, listModels, testConnection, readableError } from './providers.mjs';
import { executeOptimization, OptimizationError, recordContext, explanationMessages } from './optimization.mjs';
import { stageTokens, answerPolicyVersion, executionPolicyVersion } from './agent-policy.mjs';
import { agentLimits, taskFor, taskMessages, reserveCall, decide } from './agent-policy.mjs';
import { initializeMethods, validateReply } from './optimization-v07.mjs';
import { methodPresets, methodVersion } from '../shared/methods.mjs';
import { diagnosticText } from '../shared/protocol-schema.mjs';
import { ExperimentService } from './experiments.mjs';
import { ExportService, conversationExport, readStoredZip } from './exports.mjs';
import { createModelQueue } from './model-queue.mjs';
import { behavioralChecks } from './behavioral.mjs';
import { StorageError } from './persistence.mjs';
import { UserInputError } from './user-error.mjs';
import { listenLoopback } from './listen-loopback.mjs';
const mime = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.woff': 'font/woff', '.ttf': 'font/ttf', '.png': 'image/png', '.ico': 'image/x-icon', '.txt': 'text/plain; charset=utf-8' };
export async function startServer({ directory, staticDir, port = 43127, dev = false, externalOrigin = null, secretVault = vault, generator = generate, planner = planOptimization, modelLister = listModels, connectionTester = testConnection }) {
  if (externalOrigin && (new URL(externalOrigin).protocol !== 'https:' || new URL(externalOrigin).origin !== externalOrigin)) throw Error('Invalid external origin');
  const store = new Store(directory, secretVault), token = crypto.randomBytes(32).toString('hex'), active = new Map();
  const solver = new SolverService(directory);
  const modelQueue=createModelQueue(), rawPlanner=planner, rawGenerator=generator;
  planner=(config,messages,signal)=>modelQueue(()=>{assertWritable();config.onDispatch?.();return rawPlanner(config,messages,signal);},signal);
  // Hold one slot throughout streaming without buffering the provider output.
  generator=async function*(config,messages,signal){
    let release,entered;const ready=new Promise(r=>{entered=r;}),done=new Promise(r=>{release=r;});
    const lock=modelQueue(async()=>{entered();await done;},signal).catch(e=>{entered(e);});
    const error=await ready;if(error)throw error;
    try{assertWritable();yield*rawGenerator(config,messages,signal);}finally{release();await lock;}
  };
  const experiments=new ExperimentService(directory,{store,solver,planner,generator});
  const exports=new ExportService(directory,store,solver,experiments);
  const storageFailure = error => {
    store.storageError ||= error instanceof StorageError ? error : new StorageError(error);
    for (const controller of active.values()) controller.abort();
    experiments.controller?.abort();
    if (solver.active) solver.stop(solver.active.id);
  };
  solver.onStorageError = storageFailure; experiments.onStorageError = storageFailure;
  const assertWritable = () => { store.assertWritable(); if(solver.storageError)throw solver.storageError; experiments.assertWritable(); };
  let origin;
  function json(res, status, value) { if (res.destroyed || res.writableEnded) return; if(res.headersSent){res.end();return;} res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' }); res.end(JSON.stringify(value)); }
  function authorized(req) {
    const incoming = req.headers['x-fyppppp-token'];
    return typeof incoming === 'string' && /^[a-f0-9]{64}$/.test(incoming) && crypto.timingSafeEqual(Buffer.from(incoming), Buffer.from(token));
  }
  async function body(req,limit=2*1024*1024) {
    if (!req.headers['content-type']?.includes('application/json')) throw new Error('请求需要 JSON');
    const chunks=[];let bytes=0;
    for await (const chunk of req) { bytes+=chunk.length;if(bytes>limit)throw new Error('输入过长');chunks.push(chunk); }
    const text=new TextDecoder('utf-8',{fatal:true}).decode(Buffer.concat(chunks));
    return JSON.parse(text || '{}');
  }
  const server = http.createServer(async (req, res) => {
    try {
    res.setHeader('X-Content-Type-Options', 'nosniff'); res.setHeader('Referrer-Policy', 'no-referrer');
    res.setHeader('X-Frame-Options', 'DENY');
    res.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'");
    const allowedOrigins = [origin, ...(externalOrigin ? [externalOrigin] : []), ...(dev ? ['http://127.0.0.1:5173'] : [])];
    if (!allowedOrigins.some(allowed => req.headers.host === new URL(allowed).host)) return json(res, 403, { error: '访问来源无效' });
    if (req.headers.origin && !allowedOrigins.includes(req.headers.origin)) return json(res, 403, { error: '访问来源无效' });
    if (req.headers['sec-fetch-site'] === 'cross-site') return json(res, 403, { error: '访问来源无效' });
    const url = new URL(req.url, origin), route = url.pathname;
    if (route === '/api/health') return json(res, 200, { app: 'llm4orOvO', version: packageInfo.version });
    const download=route.match(/^\/api\/download\/([a-f0-9]{64})$/);
    if(download&&req.method==='GET'){if(!exports.download(download[1],res))json(res,404,{error:'下载链接已过期'});return;}
    if (route.startsWith('/api/') && !authorized(req)) return json(res, 401, { error: '请通过应用启动入口打开此页面' });
    if(!['GET','HEAD'].includes(req.method) && route!=='/api/downloads' && !route.endsWith('/stop'))assertWritable();
      if(route==='/api/downloads'&&req.method==='POST')return json(res,201,exports.create(await body(req)));
      if(route==='/api/imports'&&req.method==='POST')return json(res,201,exports.import(await body(req,64*1024*1024)));
      if(route==='/api/imports'&&req.method==='GET')return json(res,200,exports.imports());
      const imported=route.match(/^\/api\/imports\/([a-f0-9-]{36})(\/cases)?$/);if(imported&&req.method==='GET')return json(res,200,imported[2]?exports.importedCases(imported[1]):exports.imported(imported[1]));
      if(route==='/api/imports/zip'&&req.method==='POST'){const chunks=[];let bytes=0;for await(const chunk of req){bytes+=chunk.length;if(bytes>64*1024*1024)throw Error('输入归档过大');chunks.push(chunk);}return json(res,201,exports.import(readStoredZip(Buffer.concat(chunks))));}
      if(route==='/api/experiments'&&req.method==='GET')return json(res,200,experiments.list());
      if(route==='/api/experiments'&&req.method==='POST')return json(res,201,await experiments.create(await body(req)));
      const experimentSummary=route.match(/^\/api\/experiments\/([a-f0-9-]{36})\/summary$/);if(experimentSummary&&req.method==='GET')return json(res,200,experiments.summary(experimentSummary[1]));
      const rerun=route.match(/^\/api\/experiments\/([a-f0-9-]{36})\/rerun$/);if(rerun&&req.method==='POST')return json(res,201,await experiments.rerun(rerun[1],(await body(req)).runIds));
      const experiment=route.match(/^\/api\/experiments\/([a-f0-9-]{36})(?:\/(start|pause|resume|cancel))?$/);
      if(experiment){if(req.method==='GET'&&!experiment[2])return json(res,200,experiments.view(experiment[1],Math.max(0,Number(url.searchParams.get('offset'))||0)));if(req.method==='POST'&&experiment[2])return json(res,200,experiments.action(experiment[1],experiment[2]));}
      const experimentRun=route.match(/^\/api\/experiments\/([a-f0-9-]{36})\/runs\/([a-f0-9-]{36})(?:\/(answer|score))?$/);
      if(experimentRun){const [,batchId,runId,action]=experimentRun;if(!experiments.batches.get(batchId)?.runs.some(r=>r.id===runId))return json(res,404,{error:'运行不存在'});if(req.method==='GET'&&!action)return json(res,200,url.searchParams.get('blind')==='1'?experiments.blindReview(runId):experiments.run(runId));if(req.method==='POST'&&action){const value=await body(req);return json(res,200,action==='answer'?experiments.answer(batchId,runId,value.message):experiments.evaluate(batchId,runId,value));}}
      if (route === '/api/solver' && req.method === 'GET') return json(res, 200, solver.info());
      if (route === '/api/solver' && req.method === 'PUT') return json(res, 200, solver.configure(await body(req)));
      if (route === '/api/solver/runs' && req.method === 'GET') return json(res, 200, solver.list());
      if (route === '/api/solver/runs' && req.method === 'POST') return json(res, 201, solver.start(await body(req)));
      const behavior=route.match(/^\/api\/solver\/runs\/([a-f0-9-]+)\/behavioral$/);if(behavior&&req.method==='POST'){const controller=new AbortController();res.on('close',()=>{if(!res.writableEnded)controller.abort();});return json(res,200,await behavioralChecks(solver,solver.get(behavior[1]),directory,controller.signal));}
      const solverRun = route.match(/^\/api\/solver\/runs\/([a-f0-9-]+)(\/stop)?$/);
      if (solverRun) {
        const record = solverRun[2] && req.method === 'POST' ? solver.stop(solverRun[1]) : req.method === 'GET' && !solverRun[2] ? solver.get(solverRun[1]) : null;
        return json(res, record ? 200 : 404, record || { error: '记录不存在' });
      }
      if (route === '/api/state' && req.method === 'GET') return json(res, 200, { ...store.publicState(), storageError: store.storageError?.message || solver.storageError?.message || experiments.storageError?.message || null, skippedRecords: solver.skipped.length + experiments.skipped.length });
      if (route === '/api/preferences' && req.method === 'PATCH') {
        const value = await body(req);
        if (value.theme && !['light', 'graphite', 'black', 'navy'].includes(value.theme)) throw new Error('主题无效');
        if (value.provider && !catalog.some(p => p.id === value.provider)) throw new Error('服务商无效');
        if (value.language !== undefined && !['zh-CN', 'en'].includes(value.language)) throw new Error('请选择有效语言');
        if (value.fontSize !== undefined && (!Number.isInteger(value.fontSize) || value.fontSize < 14 || value.fontSize > 24)) throw new Error('字号应为 14–24');
        if (value.chatMode !== undefined && !['solve', 'chat'].includes(value.chatMode)) throw new Error('请选择有效的对话模式');
        if (value.chatEngine !== undefined && !['highs', 'gurobi'].includes(value.chatEngine)) throw new Error('请选择有效的求解器');
        if (value.methodPreset !== undefined && (!Object.hasOwn(methodPresets,value.methodPreset)||value.methodPreset==='no_evidence')) throw new Error('请选择有效的交互式方法预设');
        if (value.protocolCorrection !== undefined && typeof value.protocolCorrection !== 'boolean') throw new Error('请选择有效的协议纠正开关');
        if (value.readingFont !== undefined && !['system','calibri','times','arial','georgia','verdana'].includes(value.readingFont)) throw new Error('请选择有效字体');
        for (const key of ['theme', 'provider', 'sidebarCollapsed', 'language', 'fontSize', 'chatMode', 'chatEngine','methodPreset','readingFont','protocolCorrection']) if (value[key] !== undefined) store.data.preferences[key] = value[key];
        store.save(); return json(res, 200, store.publicState());
      }
      const matchProvider = route.match(/^\/api\/providers\/([a-z]+)(?:\/(models|test))?$/);
      if (matchProvider) {
        const [, id, action] = matchProvider;
        if (!catalog.some(p => p.id === id)) return json(res, 404, { error: '服务商不存在' });
        if (!action && req.method === 'PUT') return json(res, 200, await store.configure(id, await body(req)));
        if (action && req.method === 'POST') {
          const config = await store.credentials(id), controller = new AbortController();
          config.language = store.data.preferences.language;
          const timeout = setTimeout(() => controller.abort(), 120000);
          res.on('close', () => { if (!res.writableEnded) controller.abort(); });
          try {
            const result = action === 'models' ? await modelLister(config, controller.signal) : await connectionTester(config, controller.signal);
            if (action === 'models' && result.source === 'api') { store.data.providers[id].models = result.models; store.save(); }
            if (action === 'test') store.record({ kind: 'connection_test', provider: id, model: config.model, status: 'complete' });
            return json(res, 200, result);
          } catch (e) {
            store.record({ kind: action, provider: id, model: config.model, status: 'error' });
            return json(res, 400, { error: readableError(e) });
          } finally { clearTimeout(timeout); }
        }
      }
      if (route === '/api/conversations' && req.method === 'POST') return json(res, 201, store.create());
      if (route === '/api/conversations' && req.method === 'DELETE') {
        if (active.size) return json(res, 409, { error: '请先停止生成' });
        store.data.conversations = []; store.save(); return json(res, 200, store.publicState());
      }
      const exportConversation = route.match(/^\/api\/conversations\/([a-f0-9-]+)\/export$/);
      if (exportConversation && req.method === 'GET') {
        const conversation = store.get(exportConversation[1]);
        if (!conversation) return json(res, 404, { error: '对话不存在' });
        if (active.has(conversation.id)) return json(res, 409, { error: '请先停止生成' });
        return json(res, 200, conversationExport([conversation],solver));
      }
      const matchConversation = route.match(/^\/api\/conversations\/([a-f0-9-]+)$/);
      if (matchConversation) {
        const conversation = store.get(matchConversation[1]);
        if (!conversation) return json(res, 404, { error: '对话不存在' });
        if (req.method === 'GET') return json(res, 200, conversation);
        if (req.method === 'PATCH') { const data = await body(req); if (typeof data.title !== 'string' || !data.title.trim()) throw new Error('名称不能为空'); conversation.title = data.title.trim().slice(0, 100); conversation.autoTitle = false; store.touch(conversation); return json(res, 200, conversation); }
        if (req.method === 'DELETE') { if (active.has(conversation.id)) return json(res, 409, { error: '请先停止生成' }); store.data.conversations = store.data.conversations.filter(c => c.id !== conversation.id); store.save(); return json(res, 200, { ok: true }); }
      }
      if (route === '/api/export' && req.method === 'GET') return json(res, 200, conversationExport(store.data.conversations,solver));
      if (route === '/api/chat' && req.method === 'POST') {
        const data = await body(req), conversation = store.get(data.conversationId);
        if (!conversation) return json(res, 404, { error: '对话不存在' });
        if (active.has(conversation.id)) return json(res, 409, { error: '此对话正在生成' });
        if (data.requestId && (typeof data.requestId!=='string' || !/^[a-f0-9-]{36}$/.test(data.requestId))) throw new Error('请求标识无效');
        if (data.requestId && conversation.messages.some(m=>m.requestId===data.requestId)) return json(res,409,{error:'请求已处理，请刷新对话'});
        if (data.replyTo) validateReply(conversation.messages.findLast(m=>m.automation?.task)?.automation.task || {},data.replyTo);
        if (!data.retry && (typeof data.message !== 'string' || !data.message.trim() || data.message.length > 60000)) throw new Error('请输入不超过 60000 字符的内容');
        const requestedRunId = data.retry ? conversation.messages.findLast(m => m.role === 'user')?.solverRunId : data.solverRunId;
        const referencedRun = requestedRunId ? solver.get(requestedRunId) : null;
        if (requestedRunId && (!referencedRun || referencedRun.status === 'running' || !referencedRun.provenance?.solverInvoked)) throw new Error('请选择已调用求解器的真实运行记录');
        const priorUser = conversation.messages.findLast(m => m.role === 'user');
        const mode = data.retry ? priorUser?.mode || 'chat' : data.mode ?? store.data.preferences.chatMode;
        const engine = data.retry ? priorUser?.engine || 'highs' : data.engine ?? store.data.preferences.chatEngine;
        if (!['solve', 'chat'].includes(mode) || !['highs', 'gurobi'].includes(engine)) throw new Error('请选择有效的对话模式和求解器');
        const config = await store.credentials(data.provider);
        assertWritable();
        if (active.has(conversation.id)) return json(res, 409, { error: '此对话正在生成' });
        if (data.requestId && conversation.messages.some(m=>m.requestId===data.requestId)) return json(res,409,{error:'请求已处理，请刷新对话'});
        config.language = store.data.preferences.language;
        if (data.model) { if (typeof data.model !== 'string' || data.model.length > 150) throw new Error('模型 ID 无效'); config.model = data.model; }
        const previousFrozen=conversation.messages.findLast(m=>m.automation?.task?.frozen)?.automation.task.frozen;
        config.protocolCorrection=store.data.preferences.protocolCorrection;
        if(mode==='solve'&&previousFrozen?.methodVersion&&previousFrozen.methodVersion!==methodVersion&&previousFrozen.preset!=='legacy')throw new OptimizationError('当前任务属于旧协议版本。历史记录已保留，请新建对话使用更新后的方法。');
        if(mode==='solve'&&previousFrozen?.provider&&previousFrozen.provider!==config.id)throw new OptimizationError('当前任务已固定服务商，请新建对话切换');
        if (!data.retry) {
          conversation.messages.push({ id: crypto.randomUUID(), role: 'user', content: data.message.trim(), createdAt: new Date().toISOString(), status: 'complete', mode, engine, requestId:data.requestId, ...(data.replyTo ? {replyTo:data.replyTo} : {}), ...(referencedRun ? { solverRunId: referencedRun.id } : {}) });
          if (conversation.autoTitle || (conversation.autoTitle === undefined && conversation.title === '新对话')) { conversation.title = data.message.trim().replace(/\s+/g, ' ').slice(0, 28); conversation.autoTitle = false; }
        }
        const lastUser = conversation.messages.findLastIndex(m => m.role === 'user');
        if (lastUser < 0) throw new Error('没有可重试的消息');
        const context = conversation.messages.slice(0, lastUser + 1).filter(m => m.role === 'user' || (m.status === 'complete' && m.content));
        // Retries remain visible in the record; only the last complete answer per user turn enters future context.
        const normalized = [];
        for (const original of context) {
          let message = original;
          const recordId = original.role === 'user' ? original.solverRunId : original.provenance?.solverRun?.id;
          const record = recordId ? solver.get(recordId) : null;
          if (record?.provenance?.solverInvoked) message = { ...original, content: original.content + recordContext(record) };
          if (normalized.at(-1)?.role === 'assistant' && message.role === 'assistant') normalized[normalized.length - 1] = message;
          else if (normalized.at(-1)?.role === 'user' && message.role === 'user') normalized[normalized.length - 1] = { ...message, content: normalized.at(-1).content + '\n\n' + message.content };
          else normalized.push(message);
        }
        const answer = { id: crypto.randomUUID(), role: 'assistant', content: '', provider: config.id, model: config.model, createdAt: new Date().toISOString(), status: 'streaming', usage: { input: null, output: null }, provenance: { source: 'llm', ...(referencedRun ? { solverRun: { id: referencedRun.id, engine: referencedRun.engine, status: referencedRun.status, modelHash: referencedRun.modelHash } } : {}) } };
        if (mode === 'solve' && !referencedRun) answer.automation = { stage: 'modeling', engine, seconds: agentLimits.seconds, usage: {}, limits: agentLimits, task: taskFor(conversation, conversation.messages[lastUser], data.retry), policyVersion: answerPolicyVersion, executionPolicyVersion, interpretation: 'not_started', tokenBudgets: { modeling: stageTokens(config, 'modeling'), interpretation: stageTokens(config, 'interpretation') } };
        if (answer.automation) {
          initializeMethods(answer.automation,config,engine,store.data.preferences.methodPreset);
          const frozen=answer.automation.task.frozen;
          if(frozen.provider!==config.id) throw new OptimizationError('当前任务已固定服务商，请新建对话切换');
          for(const key of ['model','baseURL','region','maxTokens','modelingTokens','language']) if(frozen[key]!==undefined)config[key]=frozen[key];
          answer.model=config.model; answer.automation.engine=frozen.engine;
        }
        const modelingMessages = answer.automation ? taskMessages(conversation, answer.automation.task) : normalized;
        conversation.messages.push(answer); store.touch(conversation);
        const controller = new AbortController(); active.set(conversation.id, controller);
        const send = value => { if (!res.destroyed) res.write('data: ' + JSON.stringify(value) + '\n\n'); };
        res.writeHead(200, { 'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'no-cache, no-transform', Connection: 'keep-alive' });
        res.on('close', () => { if (!res.writableEnded) controller.abort(); });
        send({ type: 'start', conversation });
        const update = () => {
          if (answer.automation) for (const field of ['input', 'output']) {
            const phases = Object.values(answer.automation.usage);
            answer.usage[field] = phases.every(p => Number.isFinite(p[field])) ? phases.reduce((sum, p) => sum + p[field], 0) : null;
          }
          store.touch(conversation); send({ type: 'progress', conversation });
        };
        let savedAt = Date.now(); const startedAt = Date.now();
        const timeout = setTimeout(() => controller.abort(), 300000);
        try {
          let explanation = true, generationMessages = normalized;
          if (answer.automation) {
            const record = await executeOptimization({ config, messages: modelingMessages, problem: conversation.messages[lastUser].content, engine:answer.automation.engine, seconds: agentLimits.seconds, planner, solver, signal: controller.signal, answer, update, retry: !!data.retry });
            explanation = !!record;
            if (record) {
              generationMessages = explanationMessages(modelingMessages, record);
              explanation = reserveCall(answer, generationMessages, config.language);
              answer.automation.interpretation = explanation ? 'running' : 'skipped';
              if (explanation) answer.automation.usage.interpretation = { input: null, output: null };
              update();
            }
          }
          if (explanation) for await (const chunk of generator(answer.automation ? { ...config, maxTokens: stageTokens(config, 'interpretation') } : config, generationMessages, controller.signal)) {
            if (controller.signal.aborted) throw new DOMException('Aborted', 'AbortError');
            if (chunk.text) { answer.content += chunk.text; send({ type: 'delta', text: chunk.text }); }
            if (chunk.usage) {
              if (answer.automation) { Object.assign(answer.automation.usage.interpretation, chunk.usage); update(); }
              else Object.assign(answer.usage, chunk.usage);
            }
            if (chunk.rawUsage) answer.rawUsage = chunk.rawUsage;
            if (chunk.requestMetadata) answer.requestMetadata = chunk.requestMetadata;
            if (chunk.warning) answer.warning = chunk.warning;
            if (Date.now() - savedAt > 750) { store.touch(conversation); savedAt = Date.now(); }
          }
          if (!answer.content) throw new Error('Empty provider response');
          if (answer.automation?.stage === 'interpreting') {
            answer.automation.stage = 'complete';
            answer.automation.interpretation = answer.warning ? 'incomplete' : 'complete';
          }
          answer.status = 'complete';
        } catch (error) {
          answer.status = controller.signal.aborted ? 'stopped' : 'error';
          answer.error = controller.signal.aborted ? '生成已停止' : error instanceof OptimizationError ? error.message : readableError(error);
          if (answer.automation) {
            if (answer.automation.result?.invoked && answer.automation.interpretation === 'running') {
              answer.automation.interpretation = controller.signal.aborted ? 'stopped' : 'error';
              answer.automation.stage = 'complete';
              answer.automation.questions = [];
            }
            else if (controller.signal.aborted) answer.automation.stage = 'stopped';
            else {
              const en = config.language === 'en';
              answer.automation.taskOutcome='failed';
              const d=answer.automation.protocolError;
              decide(answer, d?.code||'tool_or_api_error', d?diagnosticText(d,config.language):(en?'The request or execution failed. The task is incomplete; see the saved error. No transport retry was made.':'请求或执行失败，任务尚未完成。具体错误已保存；未自动重试网络请求。'), [], 'error');
            }
          }
        }
        finally {
          clearTimeout(timeout); active.delete(conversation.id);
          answer.durationMs = Date.now() - startedAt; store.touch(conversation);
          store.record({ kind: 'generation', id: answer.id, conversationId: conversation.id, provider: config.id, model: config.model, status: answer.status, durationMs: answer.durationMs, usage: answer.usage,
            ...(answer.automation ? { mode: 'solve', phases: answer.automation.usage, solverRunId: answer.automation.runId || null, modelingMs: answer.automation.modelingMs ?? null, task: answer.automation.task, decision: answer.automation.decision || null, preflight: answer.automation.preflight || null, policyVersion: answer.automation.policyVersion, executionPolicyVersion: answer.automation.executionPolicyVersion, submissionSource: answer.automation.submissionSource || null, tokenBudgets: answer.automation.tokenBudgets, interpretation: answer.automation.interpretation } : {}) });
          send({ type: 'done', conversation }); res.end();
        }
        return;
      }
      if (route.startsWith('/api/')) return json(res, 404, { error: '接口不存在' });
      if (req.method !== 'GET' && req.method !== 'HEAD') return json(res, 405, { error: '方法不支持' });
      const relative = decodeURIComponent(route).replace(/^\/+/, '');
      let file = path.resolve(staticDir, relative || 'index.html');
      if (!file.startsWith(path.resolve(staticDir) + path.sep)) return json(res, 403, { error: '路径无效' });
      if (!fs.existsSync(file) || !fs.statSync(file).isFile()) file = path.join(staticDir, 'index.html');
      if (!fs.existsSync(file)) return json(res, 503, { error: '请先构建前端' });
      res.writeHead(200, { 'Content-Type': mime[path.extname(file)] || 'application/octet-stream', 'Cache-Control': path.basename(file) === 'index.html' ? 'no-cache' : 'public, max-age=3600' });
      if (req.method === 'HEAD') res.end(); else fs.createReadStream(file).on('error',()=>res.destroy()).pipe(res);
    } catch (error) { if(error instanceof StorageError)storageFailure(error); json(res, error instanceof StorageError ? 503 : 400, { error: error instanceof StorageError || error instanceof UserInputError || /^(密钥|请|模型|名称|主题|地区|输出|自定义|未知|没有|当前|本地|输入|服务商|请求|不支持)/.test(error.message || '') ? error.message : '操作失败，请检查输入后重试', ...(error instanceof UserInputError || error instanceof StorageError?{code:error.code}:{}) }); }
  });
  await listenLoopback(server, port);
  origin = 'http://127.0.0.1:' + server.address().port;
  return { server, store, solver, experiments, exports, token, origin, close: async () => { for (const controller of active.values()) controller.abort(); await experiments.close(); solver.close(); await new Promise(resolve => server.close(resolve)); } };
}
