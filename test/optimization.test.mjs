import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import crypto from 'node:crypto';
import { startServer } from '../server/http.mjs';
import { demoModel, demoProblem } from '../shared/solver-model.mjs';
import { optimizationTool } from '../shared/optimization-tool.mjs';
import { Store } from '../server/store.mjs';

const plan = (args = { action: 'solve', model_json: JSON.stringify(demoModel), message: 'Software fixture' }) => ({ calls: [{ id: 'qa-call', name: optimizationTool.name, arguments: JSON.stringify(args) }], usage: { input: 12, output: 20 }, truncated: false, text: 'This pre-solve prose must not be displayed.' });
async function fixture(options = {}) {
  let plannerCalls = 0, explanationCalls = 0, received, planConfig, planMessages;
  const f = await startServer({ directory: path.resolve('qa', 'automatic-' + crypto.randomUUID()), staticDir: path.resolve('dist'), port: 0,
    secretVault: { protect: async x => Buffer.from(x).toString('base64'), unprotect: async x => Buffer.from(x, 'base64').toString() },
    planner: async (...args) => { plannerCalls++; [planConfig, planMessages] = args; return options.planner ? options.planner(...args) : plan(); },
    generator: async function* (...args) { explanationCalls++; received = args[1]; if (options.generator) yield* options.generator(...args); else yield { text: 'Fixture interpretation only.', usage: { input: 8, output: 5 } }; }
  });
  await f.store.configure('openai', { apiKey: 'qa-only-not-real', region: 'global', model: 'qa-model', maxTokens: 1024 });
  f.store.data.preferences.methodPreset = 'legacy'; // Frozen 0.6.4 comparison; v0.7 has separate tests.
  const c = f.store.create();
  const send = async (extra = {}) => { const r = await fetch(f.origin + '/api/chat', { method: 'POST', headers: { 'content-type': 'application/json', 'x-fyppppp-token': f.token }, body: JSON.stringify({ conversationId: c.id, provider: 'openai', message: demoProblem.en, ...extra }) }); return { status: r.status, text: await r.text() }; };
  return { ...f, c, send, counts: () => ({ plannerCalls, explanationCalls }), received: () => received, planned: () => ({ config: planConfig, messages: planMessages }), answer: () => c.messages.at(-1) };
}

test('default auto solve executes real HiGHS before explanation, persists evidence and sums two request usages', async t => {
  const f = await fixture(); t.after(() => f.close());
  assert.equal(f.store.data.preferences.chatMode, 'solve');
  const r = await f.send({ objective: 99999, provenance: { solverRun: { id: 'fake' } } });
  assert.equal(r.status, 200); assert.ok(!r.text.includes('"type":"delta","text":"This pre-solve'));
  const a = f.answer(); assert.equal(a.status, 'complete'); assert.equal(a.automation.stage, 'complete');
  assert.equal(a.automation.result.status, 'optimal'); assert.equal(a.automation.result.objective, 1000);
  assert.deepEqual(a.automation.result.values, { A: 10, B: 20 }); assert.equal(a.automation.result.invoked, true);
  assert.equal(a.provenance.solverRun.id, a.automation.runId); assert.equal(f.solver.get(a.automation.runId).modelHash.length, 64);
  assert.deepEqual(f.counts(), { plannerCalls: 1, explanationCalls: 1 }); assert.deepEqual(a.usage, { input: 20, output: 25 });
  assert.match(f.received().at(-1).content, /"objective":1000/); assert.ok(!f.received().at(-1).content.includes('99999'));
  const firstId = a.automation.runId;
  await f.send({ retry: true, mode: 'chat', engine: 'gurobi' });
  assert.equal(f.answer().automation.engine, 'highs'); assert.equal(f.answer().automation.decision.code, 'no_new_information');
  assert.equal(f.solver.get(firstId).objective, 1000);
  assert.equal(f.solver.list().length, 1); assert.deepEqual(f.counts(), { plannerCalls: 1, explanationCalls: 1 });
});

for (const [name, response] of [
  ['prose instead of a tool', { ...plan(), calls: [], text: 'The optimal answer is 99999. I ran HiGHS.' }],
  ['unknown tool', { ...plan(), calls: [{ name: 'execute_python', arguments: '{"code":"print(99999)"}' }] }],
  ['multiple calls', { ...plan(), calls: [...plan().calls, ...plan().calls] }],
  ['truncated call', { ...plan(), truncated: true }],
  ['invalid argument JSON', { ...plan(), calls: [{ name: optimizationTool.name, arguments: '{' }] }],
  ['extra executable field', plan({ action: 'solve', model_json: JSON.stringify(demoModel), message: '', code: 'malicious' })]
]) test('fail closed: ' + name, async t => {
  const f = await fixture({ planner: async () => response }); t.after(() => f.close()); await f.send();
  assert.equal(f.answer().status, 'error'); assert.ok(!f.answer().content.includes('99999')); assert.equal(f.answer().automation.stage, 'error');
  assert.equal(f.answer().automation.questions.length, 0);
  assert.equal(f.answer().automation.task.clarifications, 0);
  assert.equal(f.answer().provenance.solverRun, undefined); assert.equal(f.solver.jobs.size, 0);
  assert.deepEqual(f.counts(), { plannerCalls: 1, explanationCalls: 0 }); assert.deepEqual(f.answer().automation.plan, response);
});

for (const action of ['clarify', 'unsupported']) test(action + ' stops before any numerical answer or solve', async t => {
  const f = await fixture({ planner: async () => plan({ action, model_json: '', message: action === 'clarify' ? 'Labor capacity is missing.' : 'This nonlinear model is outside the LP/MILP scope.', questions: action === 'clarify' ? [{ field: 'labor', question: 'What is the labor capacity?', impact: 'Sets resource capacity.' }] : [] }) }); t.after(() => f.close()); await f.send();
  assert.equal(f.answer().status, 'complete'); assert.equal(f.answer().automation.stage, action === 'clarify' ? 'clarification' : 'unsupported');
  assert.equal(f.solver.jobs.size, 0); assert.equal(f.answer().provenance.solverRun, undefined); assert.equal(f.counts().explanationCalls, 0);
});

test('invalid model is retained as a rejected run and does not reach explanation', async t => {
  const f = await fixture({ planner: async () => plan({ action: 'solve', model_json: JSON.stringify({ ...demoModel, objective: { missing: 1 } }), message: '' }) }); t.after(() => f.close()); await f.send();
  assert.equal(f.answer().status, 'complete'); assert.equal(f.answer().automation.stage, 'clarification'); assert.equal(f.answer().automation.result.status, 'rejected');
  assert.equal(f.answer().automation.result.invoked, false); assert.equal(f.solver.jobs.size, 1); assert.equal(f.counts().explanationCalls, 0);
});

test('obvious bound conflict stops before starting a solver', async t => {
  const model = structuredClone(demoModel); model.constraints.push({ name: 'impossible', terms: { A: 1 }, sense: '<=', rhs: -1 });
  const f = await fixture({ planner: async () => plan({ action: 'solve', model_json: JSON.stringify(model), message: '' }) }); t.after(() => f.close()); await f.send();
  assert.equal(f.answer().automation.decision.code, 'bounds_conflict'); assert.equal(f.answer().automation.result, undefined);
  assert.match(f.answer().automation.preflight.evidence.join(' '), /impossible/);
  assert.equal(f.solver.jobs.size, 0); assert.equal(f.counts().explanationCalls, 0);
});

test('chat bypasses tools; unconfigured Gurobi fails before making a provider request', async t => {
  const f = await fixture(); t.after(() => f.close()); await f.send({ mode: 'chat' });
  assert.equal(f.answer().automation, undefined); assert.deepEqual(f.counts(), { plannerCalls: 0, explanationCalls: 1 });
  await f.send({ mode: 'solve', engine: 'gurobi' }); assert.equal(f.answer().status, 'error');
  assert.deepEqual(f.counts(), { plannerCalls: 0, explanationCalls: 1 }); assert.equal(f.solver.jobs.size, 0);
});

test('explanation failure keeps the genuine solver result for the user', async t => {
  const f = await fixture({ generator: async function* () { throw Object.assign(Error('secret not for UI'), { status: 429 }); } }); t.after(() => f.close()); await f.send();
  const a = f.answer(); assert.equal(a.status, 'error'); assert.equal(a.automation.result.objective, 1000); assert.ok(a.provenance.solverRun);
  assert.equal(a.usage.input, null); assert.equal(a.usage.output, null); assert.equal(a.automation.usage.modeling.input, 12);
  assert.ok(!a.error.includes('secret')); assert.deepEqual(f.counts(), { plannerCalls: 1, explanationCalls: 1 });
});

test('cancellation during modeling prevents local execution', async t => {
  let started;
  const ready = new Promise(r => { started = r; });
  const f = await fixture({ planner: async (_c, _m, signal) => { started(); await new Promise((_r, reject) => signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })); } }); t.after(() => f.close());
  const controller = new AbortController();
  const response = await fetch(f.origin + '/api/chat', { method: 'POST', signal: controller.signal, headers: { 'content-type': 'application/json', 'x-fyppppp-token': f.token }, body: JSON.stringify({ conversationId: f.c.id, provider: 'openai', message: demoProblem.en }) });
  await ready; controller.abort(); await response.text().catch(() => {});
  for (let i = 0; i < 50 && f.answer().status === 'streaming'; i++) await new Promise(r => setTimeout(r, 25));
  assert.equal(f.answer().status, 'stopped'); assert.equal(f.solver.jobs.size, 0); assert.equal(f.counts().explanationCalls, 0);
});

test('cancellation during solving stops exactly the owned job and retains its record', async t => {
  const f = await fixture(); t.after(() => f.close()); let stoppedId;
  const start = f.solver.start.bind(f.solver), stop = f.solver.stop.bind(f.solver);
  // A controlled service boundary keeps the job running long enough to test cancellation deterministically.
  f.solver.start = input => { const r = { id: crypto.randomUUID(), status: 'running', engine: input.engine, model: input.model, provenance: { solverInvoked: true } }; f.solver.jobs.set(r.id, r); return r; };
  f.solver.stop = id => { stoppedId = id; const r = f.solver.get(id); r.status = 'stopped'; return r; };
  t.after(() => { f.solver.start = start; f.solver.stop = stop; });
  const controller = new AbortController();
  const response = await fetch(f.origin + '/api/chat', { method: 'POST', signal: controller.signal, headers: { 'content-type': 'application/json', 'x-fyppppp-token': f.token }, body: JSON.stringify({ conversationId: f.c.id, provider: 'openai', message: demoProblem.en }) });
  for (let i = 0; i < 50 && !f.answer().automation.runId; i++) await new Promise(r => setTimeout(r, 10));
  controller.abort(); await response.text().catch(() => {});
  for (let i = 0; i < 50 && f.answer().status === 'streaming'; i++) await new Promise(r => setTimeout(r, 25));
  assert.equal(f.answer().status, 'stopped'); assert.equal(stoppedId, f.answer().automation.runId); assert.equal(f.answer().automation.result.status, 'stopped'); assert.equal(f.counts().explanationCalls, 0);
});

test('solver-proven integer infeasibility delivers without forced clarification or paid explanation', async t => {
  const model = structuredClone(demoModel);
  model.constraints = [{ name: 'sum', terms: { A: 1, B: 1 }, sense: '=', rhs: 1 }, { name: 'equal', terms: { A: 1, B: -1 }, sense: '=', rhs: 0 }];
  const f = await fixture({ planner: async () => plan({ action: 'solve', model_json: JSON.stringify(model), message: '', questions: [] }) }); t.after(() => f.close());
  await f.send();
  const a = f.answer(); assert.equal(a.automation.result.status, 'infeasible'); assert.equal(a.automation.result.invoked, true);
  assert.equal(a.automation.stage, 'complete'); assert.equal(a.automation.questions.length, 0);
  assert.equal(f.counts().explanationCalls, 0);
  await f.send({ message: '全部保留这些条件，请再确认。' });
  assert.equal(f.answer().automation.decision.code, 'duplicate_model'); assert.equal(f.solver.jobs.size, 1);
  assert.equal(f.counts().plannerCalls, 2);
});

test('identical input and retry do not spend another request; fresh clarification resumes with bounded context and tokens', async t => {
  let index = 0, explanationCap;
  const f = await fixture({ planner: async () => ++index === 1 ? plan({ action: 'clarify', model_json: '', message: 'Capacity is missing.', questions: [{ field: 'capacity', question: 'How much?', impact: 'Sets the bound.' }] }) : plan(), generator: async function* (config) { explanationCap = config.maxTokens; yield { text: 'Test result' }; } });
  t.after(() => f.close()); await f.store.configure('openai', { region: 'global', model: 'qa-model', maxTokens: 16000 });
  await f.send({ message: '生产产品，资源需要补充。' }); const first = structuredClone(f.answer().automation.task);
  await f.send({ retry: true }); await f.send({ message: '生产产品，资源需要补充。' });
  assert.equal(f.counts().plannerCalls, 1); assert.equal(f.answer().automation.decision.code, 'no_new_information');
  await f.send({ message: '机器时间40，人工50，其余条件同生产示例。' });
  assert.equal(f.answer().automation.stage, 'complete'); assert.equal(f.answer().automation.task.calls, 3);
  assert.equal(f.answer().automation.task.id, first.id); assert.equal(first.calls, 1);
  assert.equal(f.planned().config.maxTokens, 4096); assert.equal(explanationCap, 768);
  assert.ok(f.planned().messages.some(m => m.content.includes('资源需要补充')));
  assert.ok(f.planned().messages.some(m => m.content.includes('How much?')));
  assert.ok(f.planned().messages.every(m => !m.content.includes('qa-call')));
});

test('327680 output-token setting reaches both automatic model requests without altering the default budget', async t => {
  let explanationCap;
  const f = await fixture({ generator: async function* (config) { explanationCap = config.maxTokens; yield { text: 'Software fixture result.' }; } });
  t.after(() => f.close());
  await f.store.configure('openai', { region: 'global', model: 'qa-model', maxTokens: 327680, modelingTokens: 327680, explanationTokens: 327680 });
  assert.equal(f.store.publicState().providers.openai.maxTokens, 327680);
  await f.send();
  assert.equal(f.answer().automation.result.objective, 1000);
  assert.equal(f.planned().config.maxTokens, 327680);
  assert.equal(explanationCap, 327680);
  assert.equal(f.answer().automation.task.calls, 2);
  await assert.rejects(() => f.store.configure('openai', { region: 'global', model: 'qa-model', maxTokens: 327681 }), /256–327680/);
});

test('clarification count is bounded across turns and repeated questions stop without solver work', async t => {
  let index = 0;
  const f = await fixture({ planner: async () => plan({ action: 'clarify', model_json: '', message: 'Need essential data.', questions: [{ field: 'field' + (++index), question: 'What is condition ' + index + '?', impact: 'Defines a constraint.' }] }) }); t.after(() => f.close());
  for (const message of ['Initial', 'Fact one', 'Fact two']) await f.send({ message });
  assert.equal(f.answer().automation.decision.code, 'clarification_budget'); assert.equal(f.answer().automation.task.clarifications, 2);
  await f.send({ message: 'Fact three' }); await f.send({ message: 'Fact four' });
  assert.equal(f.answer().automation.decision.code, 'call_budget'); assert.equal(f.counts().plannerCalls, 4); assert.equal(f.solver.jobs.size, 0);
  const repeated = await fixture({ planner: async () => plan({ action: 'clarify', model_json: '', message: 'Missing.', questions: [{ field: 'A', question: 'Capacity?', impact: 'Bounds.' }] }) }); t.after(() => repeated.close());
  await repeated.send(); await repeated.send({ message: 'Capacity was 40.' });
  assert.equal(repeated.answer().automation.decision.code, 'repeated_clarification'); assert.equal(repeated.answer().automation.task.clarifications, 1);
});

test('overlong context and too many clarification questions stop without downstream calls', async t => {
  const f = await fixture({ planner: async () => plan({ action: 'clarify', model_json: '', message: 'Missing.', questions: Array.from({ length: 4 }, (_, i) => ({ field: 'f' + i, question: 'Q', impact: 'I' })) }) }); t.after(() => f.close());
  await f.send({ message: 'x'.repeat(24001) }); assert.equal(f.answer().automation.decision.code, 'context_budget'); assert.equal(f.counts().plannerCalls, 0);
  // Isolate a fresh problem; the oversized root is deliberately never silently truncated.
  f.c.messages = []; await f.send(); assert.equal(f.answer().status, 'error'); assert.equal(f.solver.jobs.size, 0); assert.equal(f.counts().explanationCalls, 0);
});

test('two rejected solve attempts exhaust the persisted budget before a third model call', async t => {
  const f = await fixture({ planner: async () => plan({ action: 'solve', model_json: JSON.stringify({ ...demoModel, objective: { unknown: 1 } }), message: '' }) }); t.after(() => f.close());
  await f.send(); await f.send({ message: '补充原始变量说明 A。' }); await f.send({ message: '再次补充说明 B。' });
  assert.equal(f.answer().automation.decision.code, 'solver_budget'); assert.equal(f.answer().automation.task.solves, 2);
  assert.equal(f.counts().plannerCalls, 2); assert.equal(f.counts().explanationCalls, 0);
});

test('an optimal result is retained when the explanation request exceeds the task call budget', async t => {
  let index = 0;
  const f = await fixture({ planner: async () => {
    index++;
    if (index <= 3) return plan({ action: 'clarify', model_json: '', message: 'Missing data.', questions: [{ field: 'f' + index, question: 'Q' + index, impact: 'Constraint.' }] });
    return plan();
  } }); t.after(() => f.close());
  for (const message of ['Initial', 'First fact', 'Second fact', 'Complete facts']) await f.send({ message });
  assert.equal(f.answer().automation.result.objective, 1000); assert.equal(f.answer().automation.decision.code, 'call_budget');
  assert.equal(f.answer().automation.task.calls, 4); assert.equal(f.counts().explanationCalls, 0);
});

for (const status of ['error', 'optimal']) test('controlled solver boundary pauses on ' + status + (status === 'optimal' ? ' with failed numerical validation' : ''), async t => {
  const f = await fixture(); t.after(() => f.close());
  f.solver.start = () => ({ id: crypto.randomUUID(), engine: 'highs', status, objective: status === 'optimal' ? 1 : null, values: null, check: { feasible: false }, provenance: { solverInvoked: status !== 'error' } });
  await f.send();
  assert.equal(f.answer().automation.stage, 'clarification'); assert.equal(f.answer().automation.result.status, status);
  assert.equal(f.answer().automation.task.solves, 1); assert.equal(f.answer().automation.questions.length, 1); assert.equal(f.counts().explanationCalls, 0);
});

for (const status of ['unbounded', 'time_limit']) test('terminal solver status is separate from clarification: ' + status, async t => {
 const f = await fixture(); t.after(() => f.close());
 f.solver.start = input => ({ id: crypto.randomUUID(), engine: 'highs', status, model: input.model, objective: null, values: null, check: null, provenance: { solverInvoked: true } });
 await f.send(); const a = f.answer();
 assert.equal(a.automation.stage, status === 'unbounded' ? 'complete' : 'paused');
 assert.deepEqual(a.automation.questions, []); assert.equal(f.counts().explanationCalls, 0);
 assert.equal(a.automation.result.status, status); assert.equal(a.automation.interpretation, 'not_needed');
});

test('compact interpretation preserves all user facts without resending coefficient matrix or decision history', async t => {
 const f = await fixture(); t.after(() => f.close()); await f.send();
 const sent = f.received(); assert.equal(sent.length, 1);
 assert.ok(sent[0].content.includes(demoProblem.en));
 assert.ok(sent[0].content.includes('"values":{"A":10,"B":20}'));
 assert.ok(!sent[0].content.includes('"terms"')); assert.ok(!sent[0].content.includes('"modelHash"'));
 assert.equal(f.answer().automation.tokenBudgets.interpretation, 768);
 assert.equal(f.answer().automation.policyVersion, '0.6.2-compact-1');
});

test('interpretation failure does not ask the user to remodel a solved problem', async t => {
 const f = await fixture({ generator: async function* () { throw Error('test'); } }); t.after(() => f.close()); await f.send();
 const a = f.answer(); assert.equal(a.automation.stage, 'complete'); assert.equal(a.automation.interpretation, 'error');
 assert.deepEqual(a.automation.questions, []); assert.equal(a.automation.task.clarifications, 0); assert.equal(a.automation.result.objective, 1000);
});

test('time limit retains a checked feasible solution without claiming optimality', async t => {
 const f = await fixture(); t.after(() => f.close());
 f.solver.start = input => ({ id: crypto.randomUUID(), engine: 'highs', status: 'time_limit', model: input.model, objective: 1000, values: { A: 10, B: 20 }, check: { feasible: true }, provenance: { solverInvoked: true } });
 await f.send(); assert.equal(f.answer().automation.result.objective, 1000); assert.equal(f.answer().automation.result.status, 'time_limit'); assert.equal(f.answer().automation.stage, 'paused'); assert.equal(f.counts().explanationCalls, 0);
});

test('restart marks interrupted interpretation without discarding the solver result', async t => {
  const f = await fixture(); t.after(() => f.close()); await f.send();
  f.answer().status = 'streaming'; f.answer().automation.interpretation = 'running'; f.answer().automation.stage = 'interpreting'; f.store.save();
  const restored = new Store(f.store.directory, f.store.vault).get(f.c.id).messages.at(-1);
  assert.equal(restored.status, 'interrupted'); assert.equal(restored.automation.interpretation, 'stopped');
  assert.equal(restored.automation.stage, 'complete'); assert.equal(restored.automation.result.objective, 1000);
});

test('DeepSeek complete JSON content executes through the real solver and retains transport provenance', async t => {
  const args = { action: 'solve', model_json: JSON.stringify(demoModel), message: 'Software fixture', questions: [] };
  const original = { calls: [], text: JSON.stringify(args), usage: { input: 5, output: 8 }, truncated: false };
  const f = await fixture({ planner: async () => original }); t.after(() => f.close());
  await f.store.configure('deepseek', { apiKey: 'fake-only', region: 'global', model: 'deepseek-flash', maxTokens: 4096 });
  await f.send({ provider: 'deepseek' });
  const a = f.answer();
  assert.equal(a.status, 'complete'); assert.equal(a.automation.result.objective, 1000);
  assert.equal(a.automation.result.invoked, true); assert.equal(a.automation.submissionSource, 'json_content');
  assert.deepEqual(a.automation.plan, original); assert.deepEqual(a.automation.plan.calls, []);
  assert.equal(f.counts().plannerCalls, 1); assert.equal(a.automation.task.clarifications, 0);
});

for (const [name, response] of [
  ['prose answer', { calls: [], text: 'I ran the solver. Answer: 1000' }],
  ['embedded object', { calls: [], text: 'Here is my answer: ' + JSON.stringify({ action: 'solve', model_json: JSON.stringify(demoModel), message: '', questions: [] }) }],
  ['extra executable field', { calls: [], text: JSON.stringify({ action: 'solve', model_json: JSON.stringify(demoModel), message: '', questions: [], code: 'print(1)' }) }],
  ['two objects', { calls: [], text: '{}\n{}' }],
  ['truncated JSON response', { calls: [], text: JSON.stringify({ action: 'solve', model_json: JSON.stringify(demoModel), message: '', questions: [] }), truncated: true }],
  ['unknown native call with valid JSON content', { calls: [{ name: 'execute_python', arguments: '{}' }], text: JSON.stringify({ action: 'solve', model_json: JSON.stringify(demoModel), message: '', questions: [] }) }]
]) test('DeepSeek JSON compatibility still fails closed: ' + name, async t => {
  const f = await fixture({ planner: async () => ({ ...response, usage: { input: 1, output: 1 } }) }); t.after(() => f.close());
  await f.store.configure('deepseek', { apiKey: 'fake-only', region: 'global', model: 'deepseek-flash', maxTokens: 4096 });
  await f.send({ provider: 'deepseek' });
  assert.equal(f.answer().status, 'error'); assert.equal(f.solver.jobs.size, 0); assert.equal(f.counts().explanationCalls, 0);
  assert.equal(f.answer().automation.task.clarifications, 0);
});

test('a successful answer followed by changes keeps the same call and solver budget', async t => {
  let plans = 0;
  const f = await fixture({ planner: async () => { const model = structuredClone(demoModel); model.constraints[0].rhs += ++plans; return plan({ action: 'solve', model_json: JSON.stringify(model), message: '', questions: [] }); } });
  t.after(() => f.close()); await f.send(); const taskId = f.answer().automation.task.id;
  await f.send({ message: '修改机器容量，其余条件保留。' });
  assert.equal(f.answer().automation.task.id, taskId); assert.equal(f.answer().automation.task.calls, 4); assert.equal(f.answer().automation.task.solves, 2);
  await f.send({ message: '再修改机器容量。' });
  assert.equal(f.answer().automation.decision.code, 'solver_budget'); assert.equal(plans, 2);
});

for (const stage of ['modeling', 'checking', 'solving']) test('restart clears stale active automation stage: ' + stage, async t => {
  const f = await fixture(); t.after(() => f.close());
  f.c.messages.push({ role: 'assistant', status: 'streaming', content: '', automation: { stage, interpretation: 'not_started' } }); f.store.touch(f.c);
  const restored = new Store(f.store.directory, f.store.vault).get(f.c.id).messages.at(-1);
  assert.equal(restored.status, 'interrupted'); assert.equal(restored.automation.stage, 'stopped');
});
