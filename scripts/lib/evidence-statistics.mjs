import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import { decisionMetrics, decisionMetricsVersion, validDecisionEvents } from '../../server/decision-metrics.mjs';

export const statisticsSchema = 'llm4orovo.controlled-statistics.v1';
const methods = ['structure', 'no_evidence', 'full'];
const outcomes = ['correctDelivery', 'correctFirstDecision'];
export const sha256 = data => crypto.createHash('sha256').update(data).digest('hex');

// Conditional on discordant pairs, X is Binomial(b+c, 1/2). Sum the smaller tail
// in log space, so a large number of pairs does not overflow binomial coefficients.
export function exactMcNemar(b, c) {
  assert.ok([b, c].every(n => Number.isSafeInteger(n) && n >= 0), 'Invalid discordant counts');
  const n = b + c;
  assert.ok(Number.isSafeInteger(n), 'Too many pairs');
  const k = Math.min(b, c);
  let logTerm = -n * Math.LN2, logSum = logTerm;
  for (let i = 1; i <= k; i++) {
    logTerm += Math.log(n - i + 1) - Math.log(i);
    const high = Math.max(logSum, logTerm);
    logSum = high + Math.log1p(Math.exp(Math.min(logSum, logTerm) - high));
  }
  return Math.min(1, 2 * Math.exp(logSum));
}

export function holm(pValues) {
  assert.ok(pValues.every(p => Number.isFinite(p) && p >= 0 && p <= 1), 'Invalid p-value');
  const result = new Array(pValues.length);
  let previous = 0;
  pValues.map((p, i) => ({ p, i })).sort((a, b) => a.p - b.p).forEach(({ p, i }, rank) => {
    result[i] = previous = Math.max(previous, Math.min(1, p * (pValues.length - rank)));
  });
  return result;
}

export function analyzeControlledEvidence(serialized, protocol) {
  assert.equal(protocol.kind, 'controlled_fault_injection_not_live_llm');
  assert.equal(protocol.variantsPerBase, 2);
  assert.deepEqual(protocol.presets, methods);
  assert.equal(protocol.primaryOutcome, outcomes[0]);
  assert.equal(protocol.secondaryOutcome, outcomes[1]);
  assert.equal(protocol.providerCalls, 0);
  assert.ok(Array.isArray(protocol.caseManifest) && protocol.caseManifest.length > 0, 'Missing frozen case manifest');
  const expectedCases = new Map(protocol.caseManifest.map(item => [item.caseId, item]));
  assert.equal(expectedCases.size, protocol.caseManifest.length, 'Duplicate frozen case');
  const rows = serialized.trim().split('\n').map(line => JSON.parse(line));
  assert.equal(rows.length, expectedCases.size * methods.length, 'Incomplete or duplicate frozen runs');
  const bases = new Map(), identities = new Set();
  for (const row of rows) {
    assert.ok(typeof row.caseId === 'string' && typeof row.baseId === 'string' && row.baseId.length > 0, 'Missing case identity');
    const expectedCase = expectedCases.get(row.caseId);
    assert.ok(expectedCase && expectedCase.baseId === row.baseId && expectedCase.expectedDecision === row.expectedDecision, 'Unmatched frozen case');
    assert.ok(methods.includes(row.preset), 'Unknown preset');
    const identity = JSON.stringify([row.caseId, row.preset]);
    assert.ok(!identities.has(identity), 'Duplicate case/preset'); identities.add(identity);
    assert.ok(['complete', 'partial'].includes(row.status), 'Unsettled or failed run');
    assert.equal(row.providerCalls, 0, 'Controlled runs cannot include provider calls');
    assert.equal(row.decisionMetricsVersion, decisionMetricsVersion, 'Historical actions require a rerun');
    assert.ok(validDecisionEvents(row.decisionEvents) && row.decisionEvents.length > 0, 'Missing or invalid action chronology');
    const metrics = decisionMetrics(row);
    for (const key of ['firstDecision', 'semanticRepairs', 'programmaticRepairs', 'toolRepairs']) {
      assert.equal(row[key], metrics[key], 'Action metric mismatch: ' + key);
    }
    assert.ok(['repair', 'clarify', 'deliver'].includes(row.expectedDecision), 'Invalid expected decision');
    for (const key of [...outcomes, 'silentErrorDelivery']) assert.equal(typeof row[key], 'boolean', 'Missing Boolean outcome: ' + key);
    assert.equal(row.correctFirstDecision, row.firstDecision === row.expectedDecision, 'Incorrect first-decision score');
    assert.ok(!row.correctDelivery || row.status === 'complete', 'Partial run cannot be correct delivery');
    assert.ok(!row.silentErrorDelivery || (row.status === 'complete' && !row.correctDelivery), 'Invalid silent-error score');
    for (const key of ['calls', 'solves', 'clarifications']) {
      assert.ok(Number.isSafeInteger(protocol.limits?.[key]) && protocol.limits[key] >= 0, 'Missing budget');
      assert.ok(Number.isSafeInteger(row[key]) && row[key] >= 0 && row[key] <= protocol.limits[key], 'Invalid/exceeded budget: ' + key);
      let previous = 0;
      for (const event of row.decisionEvents) {
        assert.ok(Number.isSafeInteger(event[key]) && event[key] >= previous && event[key] <= row[key], 'Invalid event budget chronology: ' + key);
        previous = event[key];
      }
    }
    if (!bases.has(row.baseId)) bases.set(row.baseId, new Map(methods.map(method => [method, []])));
    bases.get(row.baseId).get(row.preset).push(row);
  }
  // Match the same two cases across all methods; mere equal group sizes are insufficient.
  for (const group of bases.values()) {
    const expected = group.get('full').map(r => [r.caseId, r.expectedDecision]).sort((a, b) => a[0].localeCompare(b[0]));
    assert.equal(expected.length, 2, 'Incomplete base/preset pair');
    for (const sample of group.values()) {
      assert.equal(sample.length, 2, 'Incomplete base/preset pair');
      assert.deepEqual(sample.map(r => [r.caseId, r.expectedDecision]).sort((a, b) => a[0].localeCompare(b[0])), expected, 'Unmatched variants across presets');
    }
  }
  const comparisons = [];
  for (const baseline of methods.slice(0, 2)) for (const outcome of outcomes) {
    const table = [[0, 0], [0, 0]];
    for (const group of bases.values()) {
      const before = group.get(baseline).every(r => r[outcome]);
      const after = group.get('full').every(r => r[outcome]);
      table[Number(before)][Number(after)]++;
    }
    const improved = table[0][1], regressed = table[1][0];
    comparisons.push({ baseline, outcome, units: bases.size, table, improved, regressed,
      baselineSuccesses: table[1][0] + table[1][1], fullSuccesses: table[0][1] + table[1][1],
      effect: (improved - regressed) / bases.size, p: exactMcNemar(improved, regressed) });
  }
  const adjusted = holm(comparisons.map(r => r.p));
  comparisons.forEach((r, i) => { r.pHolm = adjusted[i]; r.significant = r.pHolm < 0.05; });
  return { schema: statisticsSchema, kind: protocol.kind, decisionMetricsVersion,
    source: { file: 'controlled-results.jsonl', sha256: sha256(serialized) },
    rows: rows.length, baseUnits: bases.size, variantsPerBase: 2, pairedSuccess: 'all_variants_success',
    primaryOutcome: protocol.primaryOutcome, secondaryOutcome: protocol.secondaryOutcome,
    alpha: 0.05, alternative: 'two-sided', correction: 'Holm across both outcomes and both baselines (4 tests)',
    methods: methods.map(preset => {
      const sample = rows.filter(r => r.preset === preset);
      return { preset, runs: sample.length, complete: sample.filter(r => r.status === 'complete').length,
        partial: sample.filter(r => r.status === 'partial').length,
        correctDelivery: sample.filter(r => r.correctDelivery).length,
        correctFirstDecision: sample.filter(r => r.correctFirstDecision).length,
        silentErrorDelivery: sample.filter(r => r.silentErrorDelivery).length };
    }), comparisons,
    limitations: [
      'Hand-built template families are not a random sample; p-values describe this controlled mechanism check, not real-world superiority.',
      'Candidates, reviews and repairs are scripted; external model calls are zero.',
      'Two variants share a baseId and are combined, not counted as independent pairs.',
      'A correct clarification without an answer is partial, not a correct final delivery.',
      'Historical actions are not reconstructed; missing or inconsistent event logs fail validation.',
      'Number coverage is not a proof of semantic completeness.'
    ] };
}

export function renderControlledReport(result) {
  const number = n => Number(n.toPrecision(10)).toString();
  const primary = result.comparisons.filter(r => r.outcome === result.primaryOutcome);
  const secondary = result.comparisons.filter(r => r.outcome === result.secondaryOutcome);
  const verdict = rows => rows.map(r => `${r.baseline}：${r.significant ? '显著' : '不显著'}（Holm p=${number(r.pHolm)}）`).join('；');
  return [
    '# 程序证据：当前动作日志的受控配对检验', '',
    '**固定脚本故障注入实验，外部模型调用为零；不是真实大模型能力评测。**', '',
    `数据：${result.rows} 条运行，${result.baseUnits} 个 baseId，每个方法每个 baseId 两个变体。两个变体均成功才记该配对单位成功。`, '',
    `动作版本：\`${result.decisionMetricsVersion}\`。`,
    `输入：[controlled-results.jsonl](controlled-results.jsonl)，SHA256：\`${result.source.sha256}\`。`,
    '机器可读结果：[statistics.json](statistics.json)；冻结协议：[protocol.json](protocol.json)。', '',
    '## 结论', '',
    `主指标 correctDelivery：${verdict(primary)}。`,
    `次指标 correctFirstDecision：${verdict(secondary)}。`,
    '判断阈值为 0.05；两个对照、两个指标共四项检验统一 Holm 校正。不显著不等于无效果；次指标不能代替主指标。', '',
    '## 实际运行计数', '',
    '| 方法 | 运行数 | complete | partial | 正确交付 | 首次决策正确 | 静默错误交付 |',
    '|---|---:|---:|---:|---:|---:|---:|',
    ...result.methods.map(r => `| ${r.preset} | ${r.runs} | ${r.complete} | ${r.partial} | ${r.correctDelivery} | ${r.correctFirstDecision} | ${r.silentErrorDelivery} |`), '',
    '## 双侧精确 McNemar 检验', '',
    '改善/退步指同一 baseId 从对照到 full 的成败变化。成功率差是 full 减对照，以 baseId 为分母。', '',
    '| 对照 | 指标 | 改善 | 退步 | 成功率差 | 精确 p | Holm p | 校正后显著 |',
    '|---|---|---:|---:|---:|---:|---:|---|',
    ...result.comparisons.map(r => `| ${r.baseline} | ${r.outcome} | ${r.improved} | ${r.regressed} | ${(100 * r.effect).toFixed(2)}% | ${number(r.p)} | ${number(r.pHolm)} | ${r.significant ? '是' : '否'} |`), '',
    '计算：给定不一致配对数 n=改善+退步，双侧 p=min(1, 2×P[Binomial(n, 0.5)≤min(改善,退步)])。全部一致时 p=1。', '',
    '## 边界与复现', '',
    ...result.limitations.map(text => '- ' + text), '',
    '校验已提交的报告：`npm run verify:evidence:published`。',
    '重新执行测试、求解、统计并发布：`npm run verify:evidence -- qa/evidence-fresh --publish docs/evidence/controlled`，输出目录必须不存在。', '',
    '本报告由当前 JSONL 自动计算；生成和核验不依赖额外 Python 统计包。预算 Wilcoxon 与描述性 bootstrap 可用独立的 Python 扩展分析生成，不属于本报告。', ''
  ].join('\n');
}
