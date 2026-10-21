// Separate paid language stage. Existing offline studies retain modelCalls === 0.
// Run: node scripts/research-language-once.mjs --call-once --out 实验/NEW_DIRECTORY
// Replay saved response without credentials/network: --replay --out 实验/EXISTING_DIRECTORY
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { proposeHypotheses, applyProposal } from '../server/inverse.mjs';
import { solverPython } from '../server/python-runtime.mjs';
import { Store } from '../server/store.mjs';
import { vault } from '../server/secrets.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = p => JSON.parse(fs.readFileSync(p, 'utf8').replace(/^\uFEFF/, ''));
const save = (p, v) => fs.writeFileSync(p, JSON.stringify(v, null, 2) + '\n', { flag: 'wx' });
const sha = text => crypto.createHash('sha256').update(text, 'utf8').digest('hex');

export function instance() {
  const actions = [{ handover: 1, direct: 0 }, { handover: 0, direct: 1 }];
  const model = directCost => ({
    sense: 'minimize',
    variables: ['handover', 'direct'].map(name => ({ name, type: 'binary', lower: 0, upper: 1 })),
    objective: { handover: 0, direct: directCost },
    constraints: [{ terms: { handover: 1, direct: 1 }, sense: '=', rhs: 1 }],
  });
  const input = {
    schema: 'contextual-inverse.v1',
    description: '每班必须在交接处理 handover 和直接处理 direct 中选一种。二者均可行。变量在所有班次含义不变。唯一未计入已知费用的因素是交接负担，单位定义为每选一次交接发生一次负担；直接处理没有这项负担。请从日志提出成本特征，不猜权重。历史选择可能不完美，不要为不同班次创造不同特征。',
    logs: ['交接处理需要额外交接工作，每次的负担相同，做得越多负担越多。直接处理无需交接。', '工资等已知费用已经记在模型里，没有其他未计入的成本。'],
    hypotheses: [],
    samples: actions.map((decision, i) => ({
      id: `history-${i + 1}`, model: model(0.4), features: {}, decision,
    })),
    lambda: 0, pruneThreshold: 0, maxIterations: 40, seconds: 5,
    certification: { noise: { kind: 'absolute', budget: 0 }, threshold: 0.25 },
  };
  const task = {
    id: 'handover-misspecified-cap-one-instance',
    synthetic: true, construction: 'Deliberately constructed before the model call; no seed search.',
    feasibleActions: actions,
    deployment: { id: 'deployment', model: model(0.6), decision: actions[0], features: {} },
    hiddenTruth: { handoverWeight: 1 },
    declaredNoiseCap: 0, actualNoiseCap: 0.6, dangerThreshold: 0.25,
    primaryStartingArm: 'language_structure_plus_inverse_fit',
    releaseRule: 'Release a feasible optimal point-estimate recommendation; no risk audit.',
    estimand: 'Released dangerous plans / dangerous plans in this single constructed instance; null if denominator is zero.',
    unit: 'One instance; the two histories are not independent experimental units.',
    featureTransfer: 'Same variables and physical actions in all contexts; transfer identical LLM-returned history features to deployment. Inconsistent features fail without repair.',
    plannedModelCalls: 1, automaticRetries: 0, plannedInstances: 1, ideas: 1,
    target: 'Fill the starting release-rate blank with a scoped observation; general-journal claim scrutiny. Defer CCF-A.',
    untouchedBlanks: ['postAuditDangerousPlanReleaseRate', 'preAuditUsablePlanAvailabilityRate', 'postAuditUsablePlanAvailabilityRate'],
    falsification: 'Replay the saved raw response through applyProposal and the original inverse solver; independently enumerate both feasible deployment actions using hidden handover cost 1. The proposed counterexample is refuted if no feasible plan is released, its true regret is <= 0.25, or the realized historical regret is <= the declared zero noise cap. Do not replace this task or repair the response after seeing it.',
  };
  return { input, task };
}

export function evaluate(payload) {
  const run = spawnSync(solverPython(root), ['-B', '-X', 'utf8', 'research/language_once.py'], {
    cwd: root, input: JSON.stringify(payload), encoding: 'utf8', windowsHide: true,
    timeout: 60000, maxBuffer: 4e6, env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
  });
  if (run.error) throw run.error;
  let value;
  try { value = JSON.parse(run.stdout); } catch { throw Error('Evaluator produced invalid JSON: ' + run.stderr.slice(-1500)); }
  if (run.status !== 0 || value.status !== 'complete') throw Error(value.error || 'Evaluator failed');
  return value;
}

async function main() {
  const args = process.argv.slice(2), index = args.indexOf('--out');
  if (index < 0 || !args[index + 1] || args.includes('--call-once') === args.includes('--replay'))
    throw Error('Use exactly one of --call-once or --replay, and --out DIRECTORY');
  const out = path.resolve(root, args[index + 1]);
  const rel = path.relative(path.join(root, '实验'), out);
  if (!rel || rel.startsWith('..') || path.isAbsolute(rel)) throw Error('Output must be a fresh child of 实验');
  if (args.includes('--replay')) {
    const original = read(path.join(out, 'input.json')), trace = read(path.join(out, 'call.json'));
    const prompt = fs.readFileSync(path.join(out, 'prompt.txt'), 'utf8');
    assert.equal(sha(prompt), trace.promptSha256);
    assert.deepEqual(trace.request.messages, [{ role: 'user', content: prompt }]);
    const raw = read(path.join(out, 'response.raw.json'));
    assert.equal(raw.id, trace.responseId);
    assert.equal(raw.choices[0].finish_reason, 'stop');
    assert.equal(raw.usage.prompt_tokens, trace.inputTokens);
    assert.equal(raw.usage.completion_tokens, trace.outputTokens);
    const proposedInput = applyProposal(original.input, JSON.parse(raw.choices[0].message.content));
    const result = evaluate({ proposedInput, task: original.task });
    assert.deepEqual(result.science, read(path.join(out, 'result.json')).science);
    console.log(JSON.stringify({ status: 'replay_matches', newModelCalls: 0, science: result.science }));
    return;
  }
  // Refuse reuse, including partially failed attempts. No hidden retries or cache.
  fs.mkdirSync(out);
  fs.mkdirSync(path.join(out, 'scratch'));
  const original = instance();
  save(path.join(out, 'input.json'), original);
  const trace = {
    schema: 'language-stage-call.v1', provider: 'deepseek', requestedModel: 'deepseek-flash',
    startedUTC: new Date().toISOString(), nodeVersion: process.version,
    requestAttempts: 0, newModelCalls: 0, responsesReceived: 0,
    inputTokens: null, outputTokens: null, responseId: null, finish_reason: null,
    wallClockLatencyMs: null, callStatus: 'not_started', finalStatus: 'running',
    retries: 0, cacheUsed: false,
  };
  const runStart = performance.now();
  let secret = '';
  try {
    const state = read(path.join(process.env.LOCALAPPDATA, 'FYPPPPP/workspace/inverse-workspace.json'));
    const config = await Store.prototype.credentials.call({ data: state, vault }, 'deepseek');
    secret = config.apiKey;
    if (config.id !== 'deepseek' || config.model !== 'deepseek-flash') throw Error('Configured model differs from the authorized model');
    const endpoint = new URL(config.baseURL.replace(/\/$/, '') + '/chat/completions');
    if (endpoint.protocol !== 'https:' || endpoint.hostname !== 'api.deepseek.com') throw Error('Unexpected credential destination');
    async function* generator(_config, messages) {
      if (trace.requestAttempts !== 0) throw Error('Exactly one request is permitted');
      const body = { model: config.model, messages, temperature: 0, thinking: { type: 'disabled' },
        max_tokens: 2048, response_format: { type: 'json_object' }, stream: false };
      trace.request = body;
      trace.endpoint = endpoint.href;
      trace.promptSha256 = sha(messages[0].content);
      fs.writeFileSync(path.join(out, 'prompt.txt'), messages[0].content, { flag: 'wx' });
      save(path.join(out, 'request.json'), body);
      trace.requestAttempts = 1;
      trace.newModelCalls = 1;
      trace.callStatus = 'started';
      trace.callStartedUTC = new Date().toISOString();
      save(path.join(out, 'call.started.json'), trace);
      const start = performance.now();
      try {
        const response = await fetch(endpoint, {
          method: 'POST', redirect: 'error',
          headers: { Authorization: `Bearer ${config.apiKey}`, 'Content-Type': 'application/json' },
          body: JSON.stringify(body), signal: AbortSignal.timeout(60000),
        });
        trace.httpStatus = response.status;
        trace.responsesReceived = 1;
        const text = await response.text();
        fs.writeFileSync(path.join(out, 'response.raw.json'), text, { flag: 'wx' });
        if (!response.ok) throw Error('DeepSeek HTTP ' + response.status);
        const raw = JSON.parse(text);
        trace.responseId = raw.id ?? null;
        trace.returnedModel = raw.model ?? null;
        trace.finish_reason = raw.choices?.[0]?.finish_reason ?? null;
        trace.inputTokens = raw.usage?.prompt_tokens ?? null;
        trace.outputTokens = raw.usage?.completion_tokens ?? null;
        trace.usage = raw.usage ?? null;
        if (trace.finish_reason !== 'stop' || !trace.responseId ||
            !Number.isInteger(trace.inputTokens) || !Number.isInteger(trace.outputTokens))
          throw Error('Incomplete response or usage metadata');
        trace.callStatus = 'complete';
        yield { text: raw.choices[0].message.content,
          usage: { input: trace.inputTokens, output: trace.outputTokens } };
      } finally {
        trace.wallClockLatencyMs = performance.now() - start;
        trace.callFinishedUTC = new Date().toISOString();
      }
    }
    const proposal = await proposeHypotheses(original.input, config, generator, AbortSignal.timeout(65000));
    if (!proposal.input || proposal.cacheHit) throw Error('No fresh language proposal');
    save(path.join(out, 'proposal.json'), proposal.proposal);
    save(path.join(out, 'proposed-input.json'), proposal.input);
    const result = evaluate({ proposedInput: proposal.input, task: original.task });
    save(path.join(out, 'result.json'), result);
    // Deterministic replay of the same saved response, not another experiment.
    const replayInput = applyProposal(original.input,
      JSON.parse(read(path.join(out, 'response.raw.json')).choices[0].message.content));
    const replay = evaluate({ proposedInput: replayInput, task: original.task });
    assert.deepEqual(result.science, replay.science);
    trace.offlineReplay = 'matches';
    trace.finalStatus = 'complete';
    console.log(JSON.stringify({ status: 'complete', output: out, science: result.science }));
  } catch (error) {
    trace.finalStatus = 'failed';
    if (trace.callStatus === 'started') trace.callStatus = 'failed';
    trace.error = String(error.message).replaceAll(secret || '\0', '[REDACTED]');
    fs.appendFileSync(path.join(out, 'scratch/DEAD_ENDS.md'),
      `${new Date().toISOString()} ${trace.error.replace(/[\r\n]+/g, ' ')}; original attempt retained; no retry.\n`);
    process.exitCode = 1;
    console.error(JSON.stringify({ status: 'failed', error: trace.error, output: out }));
  } finally {
    trace.finishedUTC = new Date().toISOString();
    trace.totalPipelineMs = performance.now() - runStart;
    save(path.join(out, 'call.json'), trace);
    save(path.join(out, 'language-stage-audit.json'), {
      stage: 'language-once', newModelCalls: trace.newModelCalls,
      requestAttempts: trace.requestAttempts, responsesReceived: trace.responsesReceived,
      finalStatus: trace.finalStatus, offlinePipelineCallAssertionsUnchanged: true,
    });
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
