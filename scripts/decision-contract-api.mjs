/** Bounded research requests. Every attempted request is reserved on disk first. */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import crypto from 'node:crypto';
import { Store } from '../server/store.mjs';
import { vault } from '../server/secrets.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
const option = (name, fallback) => { const i = args.indexOf(name); return i < 0 ? fallback : args[i + 1]; };
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const budgetPath = option('--budget', null);
const budget = budgetPath ? JSON.parse(fs.readFileSync(path.resolve(budgetPath), 'utf8')) : null;
const out = path.resolve(root, option('--out', '实验/决策契约研究_2026-10-21_01'));
const relative = path.relative(path.join(root, '实验'), out);
if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) throw Error('Output must be an experiment child');
const queue = JSON.parse(fs.readFileSync(path.resolve(option('--queue', '')), 'utf8'));
if (!Array.isArray(queue) || new Set(queue.map(x => x.id)).size !== queue.length) throw Error('Invalid or duplicate requests');
let broughtForward = 0, measuredForward = 0;
if (budget) {
  const prereg = JSON.parse(fs.readFileSync(path.join(out, 'prereg.json'), 'utf8'));
  if (budget.schema === 'task-board-budget.v2') {
    const limits = {T8: {n: 80, calls: 720}, T11: {n: 300, calls: 1200}};
    const limit = limits[prereg.task];
    if (prereg.task === 'T8' && prereg.phase === 'screening') {
      if (!Number.isInteger(prereg.screening_n) || prereg.screening_n < 1 || prereg.screening_n > 2000 ||
          JSON.stringify(prereg.screening_arms) !== JSON.stringify(['A', 'B'])) throw Error('Invalid T8 screening registration');
      limit.calls = 2*prereg.screening_n;
    }
    if (!limit || prereg.n !== limit.n || !Number.isFinite(budget.total_CNY) || budget.total_CNY <= 0 || budget.total_CNY > 15 ||
        !Number.isFinite(budget.stop_remaining_CNY) ||
        Math.abs(budget.stop_remaining_CNY-budget.total_CNY*.2) > 1e-12 ||
        !Number.isInteger(budget.max_model_calls) || budget.max_model_calls < 1 || budget.max_model_calls > limit.calls ||
        queue.length !== budget.max_model_calls || budget.model !== 'deepseek-flash' ||
        prereg.budget?.total_CNY !== budget.total_CNY || prereg.budget?.stop_remaining_CNY !== budget.stop_remaining_CNY ||
        prereg.budget?.max_model_calls !== budget.max_model_calls || prereg.budget?.automatic_retries !== 0 ||
        !Array.isArray(prereg.arms) || prereg.arms.length !== 3 || !Object.hasOwn(prereg, 'MDE') ||
        !Array.isArray(prereg.switching_rules) || !prereg.switching_rules.length ||
        !Array.isArray(budget.prior_spend_reports) || JSON.stringify(prereg.budget.prior_spend_reports) !== JSON.stringify(budget.prior_spend_reports)) {
      throw Error('Budget or task contract differs');
    }
    const paths = new Set();
    for (const report of budget.prior_spend_reports) {
      const filename = path.resolve(root, report.path);
      const experimentPath = path.relative(path.join(root, '实验'), filename);
      if (!experimentPath || experimentPath.startsWith('..') || path.isAbsolute(experimentPath) || paths.has(filename)) throw Error('Invalid prior spend report');
      paths.add(filename);
      const bytes = fs.readFileSync(filename);
      if (hash(bytes) !== report.sha256) throw Error('Prior spend report changed');
      const prior = JSON.parse(bytes.toString('utf8'));
      const upper = prior.current_run_accounted_CNY ?? prior.accounted_upper_CNY;
      const measured = prior.current_run_measured_CNY ?? prior.measured_usage_cost_CNY;
      if (!Number.isFinite(upper) || !Number.isFinite(measured) || upper < 0 || measured < 0 || measured > upper+1e-10 ||
          !Number.isFinite(prior.in_flight_reserved_CNY) || Math.abs(prior.in_flight_reserved_CNY) > 1e-10) throw Error('Prior spending is unresolved');
      broughtForward += Math.max(upper, measured);
      measuredForward += measured;
    }
  } else if (budget.total_CNY !== 6 || budget.stop_remaining_CNY !== 1.2 || budget.model !== 'deepseek-flash' ||
             budget.max_model_calls !== 600 || queue.length !== 600) throw Error('Budget or task contract differs');
  for (const period of ['peak', 'off_peak']) {
    const rates = budget.prices?.[period];
    if (!rates || ['hit', 'miss', 'output'].some(k => !Number.isFinite(rates[k]) || rates[k] < 0) || rates.miss <= 0 || rates.output <= 0 || rates.hit > rates.miss) throw Error('Invalid registered prices');
  }
  if (['hit', 'miss', 'output'].some(k => budget.prices.peak[k] < budget.prices.off_peak[k])) throw Error('Peak prices must bound all reservations');
  if (hash(fs.readFileSync(path.resolve(option('--queue', '')))) !== budget.queue_sha256 ||
      hash(fs.readFileSync(path.join(out, 'prereg.json'))) !== budget.prereg_sha256) throw Error('Registered inputs changed');
  const firstLine = fs.readFileSync(path.join(out, 'execution.log'), 'utf8').split('\n')[0];
  if (!firstLine.includes('预估费用') || !firstLine.includes('预估调用数')) throw Error('Missing first-line estimate');
  const estimate = prereg.estimate.costs.peak.total_CNY;
  if (!Number.isFinite(estimate) || estimate < 0 || estimate + broughtForward > budget.total_CNY-budget.stop_remaining_CNY) throw Error('Estimate exceeds available authorized budget');
}
fs.mkdirSync(path.join(out, 'network'), { recursive: true });
const lock = path.join(out, 'request.lock');
const fd = fs.openSync(lock, 'wx');
const save = (file, data) => fs.writeFileSync(file, JSON.stringify(data, null, 2) + '\n', { flag: 'wx' });
let secret = '';
try {
  const state = JSON.parse(fs.readFileSync(path.join(process.env.LOCALAPPDATA, 'FYPPPPP/workspace/inverse-workspace.json'), 'utf8').replace(/^\uFEFF/, ''));
  const config = await Store.prototype.credentials.call({ data: state, vault }, 'deepseek');
  secret = config.apiKey;
  if (budget && config.model !== budget.model) throw Error('Configured model changed');
  const endpoint = new URL(config.baseURL.replace(/\/$/, '') + '/chat/completions');
  if (endpoint.protocol !== 'https:' || endpoint.hostname !== 'api.deepseek.com') throw Error('Unexpected credential destination');
  const ledger = path.join(out, 'calls.jsonl');
  const existing = fs.existsSync(ledger) ? fs.readFileSync(ledger, 'utf8').trim().split('\n').filter(Boolean).map(JSON.parse) : [];
  const attempted = new Set(existing.filter(x => x.event === 'started').map(x => x.id));
  // Paid continuation is never an implicit retry or recovery of an unknown attempt.
  if (budget && attempted.size) throw Error('This paid queue already has attempts; zero retry policy');
  let count = attempted.size, position = 0, transportFailures = 0;
  let committed = broughtForward, measured = measuredForward, reserved = 0, unknownCharges = 0, stopReason = null;
  const ceiling = budget?.max_model_calls ?? 300;
  const pricing = budget?.prices;
  const spend = () => {
    if (budget) fs.writeFileSync(path.join(out, 'budget-spend.json'), JSON.stringify({
      total_budget_CNY: budget.total_CNY, measured_usage_cost_CNY: measured,
      accounted_upper_CNY: committed, in_flight_reserved_CNY: reserved,
      brought_forward_accounted_CNY: broughtForward, brought_forward_measured_CNY: measuredForward,
      current_run_accounted_CNY: committed-broughtForward, current_run_measured_CNY: measured-measuredForward,
      remaining_lower_CNY: budget.total_CNY - committed - reserved,
      unknown_charge_attempts: unknownCharges, attempted: count, stop_reason: stopReason, retries: 0,
      billing_note: 'Measured token charge at published rates; boundary calls use the higher applicable rate. Unknown usage retains peak maximum reservation.'
    }, null, 2)+'\n');
  };
  // This registered run is on a non-holiday weekday; all reservations use peak prices.
  const ratePeriod = date => {
    const local = new Date(date.getTime()+8*3600000), weekday = local.getUTCDay();
    const minute = local.getUTCHours()*60+local.getUTCMinutes();
    return weekday >= 1 && weekday <= 5 && ((minute >= 540 && minute < 720) || (minute >= 840 && minute < 1080)) ? 'peak' : 'off_peak';
  };
  const record = data => fs.appendFileSync(ledger, JSON.stringify({ ...data, utc: new Date().toISOString() }) + '\n');
  async function worker() {
    while (position < queue.length && transportFailures < 3 && !stopReason) {
      const item = queue[position++];
      if (!/^[A-Za-z0-9_-]+$/.test(item.id)) throw Error('Unsafe request ID');
      if (attempted.has(item.id)) continue; // Completed or failed attempts are never silently repeated.
      if (count >= ceiling) throw Error('Request ceiling reached');
      const tokens = item.maxTokens ?? 4096;
      if (!Number.isInteger(tokens) || tokens < 1 || tokens > 8192) throw Error('Invalid token limit');
      const request = { model: config.model, messages: item.messages, temperature: 0,
        thinking: { type: 'disabled' }, max_tokens: tokens, stream: false,
        ...(item.json ? { response_format: { type: 'json_object' } } : {}) };
      const inputUpper = Buffer.byteLength(JSON.stringify(item.messages), 'utf8')+256;
      const reservation = budget ? (inputUpper*pricing.peak.miss+tokens*pricing.peak.output)/1e6 : 0;
      if (budget && (budget.total_CNY-committed-reserved < budget.stop_remaining_CNY ||
          committed+reserved+reservation > budget.total_CNY-budget.stop_remaining_CNY)) {
        stopReason = '20_percent_budget_floor'; spend(); return;
      }
      reserved += reservation;
      const startedUTC = new Date();
      const file = path.join(out, 'network', item.id);
      save(file + '.request.json', request);
      const sequence = ++count;
      record({ event: 'started', id: item.id, sequence, model: config.model,
        promptSha256: crypto.createHash('sha256').update(JSON.stringify(request)).digest('hex'),
        ...(budget ? {reservation_CNY:reservation,input_token_upper:inputUpper} : {}) });
      attempted.add(item.id);
      spend();
      const start = performance.now();
      let result;
      try {
        const response = await fetch(endpoint, { method: 'POST', redirect: 'error',
          headers: { Authorization: `Bearer ${secret}`, 'Content-Type': 'application/json' },
          body: JSON.stringify(request), signal: AbortSignal.timeout(150000) });
        const rawText = await response.text();
        fs.writeFileSync(file + '.raw.json', rawText.replaceAll(secret, '[REDACTED]'), { flag: 'wx' });
        const raw = JSON.parse(rawText);
        const finish = raw.choices?.[0]?.finish_reason;
        result = { status: response.ok && finish === 'stop' ? 'complete' : 'failed',
          httpStatus: response.status, responseId: raw.id ?? null, returnedModel: raw.model ?? null,
          text: raw.choices?.[0]?.message?.content ?? '', finishReason: finish ?? null, usage: raw.usage ?? null };
        if (!response.ok) transportFailures++;
      } catch (error) {
        transportFailures++;
        result = { status: 'failed', error: String(error.message).replaceAll(secret, '[REDACTED]'), usage: null };
      }
      result.wallMs = performance.now() - start;
      if (budget) {
        const u = result.usage;
        const valid = u && Number.isInteger(u.prompt_tokens) && Number.isInteger(u.completion_tokens) &&
          u.prompt_tokens >= 0 && u.completion_tokens >= 0;
        const period = ratePeriod(startedUTC)==='peak' || ratePeriod(new Date())==='peak' ? 'peak' : 'off_peak';
        const rates = pricing[period];
        const hit = valid ? (u.prompt_cache_hit_tokens ?? u.prompt_tokens_details?.cached_tokens ?? 0) : 0;
        if (valid && (!Number.isInteger(hit) || hit < 0 || hit > u.prompt_tokens)) {
          stopReason = 'invalid_usage_metadata';
        }
        const cost = valid && stopReason !== 'invalid_usage_metadata' ?
          (hit*rates.hit+(u.prompt_tokens-hit)*rates.miss+u.completion_tokens*rates.output)/1e6 : null;
        reserved = Math.max(0, reserved-reservation);
        committed += cost ?? reservation;
        if (cost === null) unknownCharges++; else measured += cost;
        if (cost !== null && (cost > reservation || u.prompt_tokens > inputUpper || u.completion_tokens > tokens)) stopReason = 'reservation_contract_exceeded';
        result.cost = {period,measured_CNY:cost,accounted_upper_CNY:cost ?? reservation,reservation_CNY:reservation};
        spend();
      }
      save(file + '.result.json', result);
      record({ event: 'finished', id: item.id, sequence, status: result.status, usage: result.usage, wallMs: result.wallMs, ...(budget ? {cost:result.cost} : {}) });
      console.log(JSON.stringify({ id: item.id, status: result.status, attempted: count, ceiling, ...(budget ? {costUpper:committed} : {}) }));
    }
  }
  const concurrency = Math.max(1, Math.min(budget?.schema === 'task-board-budget.v2' ? 8 : 3, Number(option('--concurrency', '2'))));
  await Promise.all(Array.from({ length: concurrency }, worker));
  if (budget && transportFailures >= 3) stopReason = 'transport_failure_circuit_breaker';
  spend();
  if (transportFailures >= 3) throw Error('Transport failure circuit breaker reached; attempts retained');
} catch (error) {
  console.error(String(error.message).replaceAll(secret || '\0', '[REDACTED]'));
  process.exitCode = 1;
} finally {
  fs.closeSync(fd);
  fs.unlinkSync(lock);
}
