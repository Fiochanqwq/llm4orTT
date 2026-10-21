// Network-only stage: reads prevalidated requests, never reads numeric truth.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { solverPython } from '../server/python-runtime.mjs';
import { Store } from '../server/store.mjs';
import { vault } from '../server/secrets.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2), i = args.indexOf('--out');
if (i < 0 || !args[i + 1]) throw Error('--out required');
const base = path.resolve(root, args[i + 1]), out = path.join(base, 'language');
const rel = path.relative(path.join(root, '实验'), base);
if (!rel || rel.startsWith('..') || path.isAbsolute(rel)) throw Error('Fresh experiment child required');
const read = p => JSON.parse(fs.readFileSync(p, 'utf8'));
const save = (p, value) => fs.writeFileSync(p, JSON.stringify(value, null, 2) + '\n', { flag: 'wx' });
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
function local(mode, destination = out) {
  const p = spawnSync(solverPython(root), ['-B', '-X', 'utf8', 'research/language_stage.py', mode, '--out', destination], {
    cwd: root, windowsHide: true, encoding: 'utf8', maxBuffer: 4e6, timeout: 180000,
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
  });
  if (p.error || p.status !== 0) throw Error(p.error?.message || p.stderr.slice(-4000) || p.stdout);
  return JSON.parse(p.stdout);
}
const started = Date.now();
if (!args.includes('--prepared')) console.log(JSON.stringify(local(args.includes('--density') ? 'prepare-density' : 'prepare')));
const freeze = read(path.join(out, 'freeze.json'));
local('verify');
if (freeze.entries.some(e => fs.existsSync(path.join(out, e.relativeDirectory, 'call.started.json'))))
  throw Error('A previous request exists; no automatic retries/resume');
// Only the request/trace transport gets credentials. No key copies or logs.
const state = read(path.join(process.env.LOCALAPPDATA, 'FYPPPPP/workspace/inverse-workspace.json'));
const config = await Store.prototype.credentials.call({ data: state, vault }, 'deepseek');
if (config.id !== 'deepseek' || config.model !== freeze.settings.model) throw Error('Frozen model does not match configured model');
const configured = new URL(config.baseURL.replace(/\/$/, '') + '/chat/completions');
if (configured.href !== freeze.endpoint) throw Error('Frozen credential destination mismatch');
let calls = 0;
for (const entry of freeze.entries) {
  if (calls >= freeze.budget.maxModelCalls || (Date.now() - started) / 1000 > freeze.budget.maxWallSeconds)
    throw Error(`Budget exhausted: calls=${calls}; elapsedSeconds=${(Date.now() - started) / 1000}`);
  const folder = path.join(out, entry.relativeDirectory);
  const requestFile = path.join(folder, 'request.json'), promptFile = path.join(folder, 'prompt.txt');
  if (sha(fs.readFileSync(requestFile)) !== entry.requestSha256 || sha(fs.readFileSync(promptFile)) !== entry.promptSha256)
    throw Error('Frozen request changed');
  const body = read(requestFile);
  const trace = {
    schema: 'language-study-call.v1', instanceId: entry.id, phase: entry.phase,
    provider: 'deepseek', requestedModel: body.model, endpoint: freeze.endpoint,
    promptSha256: entry.promptSha256, requestSha256: entry.requestSha256,
    startedUTC: new Date().toISOString(), newModelCalls: 1, requestAttempts: 1,
    retries: 0, cacheUsed: false, responsesReceived: 0, callStatus: 'started', finalStatus: 'running',
    inputTokens: null, outputTokens: null, responseId: null, finish_reason: null,
    wallClockLatencyMs: null, nodeVersion: process.version,
  };
  save(path.join(folder, 'call.started.json'), trace);
  calls++;
  const tick = performance.now();
  let error = null;
  try {
    const response = await fetch(freeze.endpoint, {
      method: 'POST', redirect: 'error',
      headers: { Authorization: `Bearer ${config.apiKey}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(body), signal: AbortSignal.timeout(60000),
    });
    trace.responsesReceived = 1;
    trace.httpStatus = response.status;
    const raw = await response.text();
    trace.wallClockLatencyMs = performance.now() - tick;
    trace.callFinishedUTC = new Date().toISOString();
    fs.writeFileSync(path.join(folder, 'response.raw.json'), raw, { flag: 'wx' });
    if (!response.ok) throw Error('DeepSeek HTTP ' + response.status);
    const value = JSON.parse(raw);
    trace.responseId = value.id ?? null;
    trace.returnedModel = value.model ?? null;
    trace.systemFingerprint = value.system_fingerprint ?? null;
    trace.finish_reason = value.choices?.[0]?.finish_reason ?? null;
    trace.usage = value.usage ?? null;
    trace.inputTokens = value.usage?.prompt_tokens ?? null;
    trace.outputTokens = value.usage?.completion_tokens ?? null;
    if (trace.finish_reason !== 'stop' || !trace.responseId ||
        !Number.isInteger(trace.inputTokens) || !Number.isInteger(trace.outputTokens))
      throw Error('Incomplete response/usage metadata');
    trace.callStatus = 'complete';
    save(path.join(folder, 'proposal.json'), JSON.parse(value.choices[0].message.content));
  } catch (failure) {
    error = String(failure.message).replaceAll(config.apiKey, '[REDACTED]');
    if (trace.callStatus === 'started') trace.callStatus = 'failed';
    trace.wallClockLatencyMs ??= performance.now() - tick;
    trace.callFinishedUTC ??= new Date().toISOString();
    if (!fs.existsSync(path.join(folder, 'response.raw.json')))
      fs.writeFileSync(path.join(folder, 'response.raw.json'), 'null\n', { flag: 'wx' });
    if (!fs.existsSync(path.join(folder, 'proposal.json')))
      save(path.join(folder, 'proposal.json'), { status: 'failed', error });
  }
  try {
    const evaluation = local('evaluate', folder);
    if (evaluation.status !== 'complete') error ??= JSON.stringify(evaluation.failures);
  } catch (failure) {
    error ??= failure.message;
    if (!fs.existsSync(path.join(folder, 'result.json')))
      save(path.join(folder, 'result.json'), { status: 'failed', scores: {}, error });
  }
  if (!fs.existsSync(path.join(folder, 'proposed-input.json')))
    save(path.join(folder, 'proposed-input.json'), { status: 'failed', error });
  trace.finalStatus = error ? 'failed' : 'complete';
  if (error) {
    trace.error = error;
    fs.appendFileSync(path.join(root, 'research/scratch/DEAD_ENDS.md'),
      `${new Date().toISOString()} ${entry.id}: ${error.replace(/[\r\n]+/g, ' ')}; original failure retained, no retry.\n`);
  }
  trace.finishedUTC = new Date().toISOString();
  trace.totalInstanceMs = performance.now() - tick;
  save(path.join(folder, 'call.json'), trace);
  console.log(JSON.stringify({ instance: entry.id, phase: entry.phase, calls, status: trace.finalStatus }));
}
const summary = local('finish');
save(path.join(out, 'language-stage-audit.json'), {
  schema: 'language-stage-audit.v1', ...summary.calls,
  plannedFormalInstances: 60, completedFormalInstances: summary.completed,
  failedOrMissingFormalInstances: summary.failedOrMissing,
  finalStatus: summary.completed === 60 ? 'complete' : 'complete_with_failures',
  elapsedSeconds: (Date.now() - started) / 1000, retries: 0,
});
console.log(JSON.stringify({ status: 'complete', ...summary }));
