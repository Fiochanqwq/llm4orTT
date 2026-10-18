"""Paired analysis of frozen controlled runs. Never represent scripted calls as API calls."""
import csv
import json
import platform
import sys
from pathlib import Path
import numpy as np
import scipy
from scipy.stats import wilcoxon, PermutationMethod
import statsmodels
from statsmodels.stats.contingency_tables import mcnemar
from statsmodels.stats.multitest import multipletests


def mean(values):
    return float(np.mean(values)) if len(values) else None


def analyze(directory):
    root = Path(directory)
    rows = [json.loads(line) for line in (root / 'analysis.jsonl').read_text(encoding='utf8').splitlines()]
    for row in rows:
        events = row.get('decisionEvents', [])
        if row.get('decisionMetricsVersion') != 'controller-actions-2' or not events or row['firstDecision'] != events[0]['action']:
            raise ValueError('Missing/current action provenance required; rerun historical benchmarks instead of inferring firstDecision')
    methods = ['structure', 'no_evidence', 'full']
    bases = sorted({r['baseId'] for r in rows})
    keys = [(r['caseId'], r['preset'], r['repeat']) for r in rows]
    if len(keys) != len(set(keys)) or any(len([r for r in rows if r['baseId'] == b and r['preset'] == m]) != 2 for b in bases for m in methods):
        raise ValueError('Incomplete/duplicate pairs; do not silently drop failures')
    metrics = []
    for group in ['all', 'A', 'B', 'C']:
        for method in methods:
            sample = [r for r in rows if r['preset'] == method and (group == 'all' or r['group'] == group)]
            metrics.append(dict(group=group, method=method, n=len(sample),
                                correctDelivery=mean([r['correctDelivery'] for r in sample]),
                                silentErrorDelivery=mean([r['silentErrorDelivery'] for r in sample]),
                                correctFirstDecision=mean([r['correctFirstDecision'] for r in sample]),
                                plannerCalls=mean([r['calls'] for r in sample]),
                                providerCalls=mean([r['providerCalls'] for r in sample]),
                                solves=mean([r['solves'] for r in sample]),
                                interactions=mean([r['clarifications'] for r in sample])))
    decisions = []
    for method in methods:
        sample = [r for r in rows if r['preset'] == method]
        for action in ['repair', 'clarify', 'deliver']:
            tp = sum(r['firstDecision'] == action and r['expectedDecision'] == action for r in sample)
            fp = sum(r['firstDecision'] == action and r['expectedDecision'] != action for r in sample)
            positives = sum(r['expectedDecision'] == action for r in sample)
            negatives = len(sample) - positives
            decisions.append(dict(method=method, action=action, truePositive=tp, falsePositive=fp,
                                  accuracy=(tp + negatives - fp) / len(sample), recall=tp / positives,
                                  falsePositiveRate=fp / negatives, precision=tp / (tp + fp) if tp + fp else None))
    paired = []
    signed = []
    rng = np.random.default_rng(20261018)
    for baseline in methods[:-1]:
        for outcome in ['correctDelivery', 'correctFirstDecision']:
            a, b = [], []
            for base in bases:
                a.append(all(r[outcome] for r in rows if r['baseId'] == base and r['preset'] == baseline))
                b.append(all(r[outcome] for r in rows if r['baseId'] == base and r['preset'] == 'full'))
            table = [[sum(x == i and y == j for x, y in zip(a, b)) for j in [False, True]] for i in [False, True]]
            difference = np.asarray(b, dtype=float) - np.asarray(a, dtype=float)
            bootstrap = np.mean(rng.choice(difference, (20000, len(bases)), replace=True), axis=1)
            paired.append(dict(baseline=baseline, outcome=outcome, units=len(bases), table=table,
                               p=float(mcnemar(table, exact=True).pvalue), effect=float(difference.mean()),
                               descriptiveClusterBootstrap95=np.quantile(bootstrap, [.025, .975]).tolist()))
        for budget in ['calls', 'solves', 'clarifications']:
            diffs = np.asarray([mean([r[budget] for r in rows if r['baseId'] == b and r['preset'] == 'full']) - mean([r[budget] for r in rows if r['baseId'] == b and r['preset'] == baseline]) for b in bases])
            p = 1.0 if np.all(diffs == 0) else float(wilcoxon(diffs, zero_method='pratt', alternative='two-sided', method=PermutationMethod(n_resamples=100000, random_state=20261018)).pvalue)
            signed.append(dict(baseline=baseline, outcome=budget, units=len(bases), meanDifference=float(diffs.mean()), medianDifference=float(np.median(diffs)), zeroPairs=int(sum(diffs == 0)), differences=diffs.tolist(), p=p))
    for family in [paired, signed]:
        for result, corrected in zip(family, multipletests([r['p'] for r in family], method='holm')[1]):
            result['pHolm'] = float(corrected)
    result = dict(kind='controlled_fault_injection_not_live_llm', date='2026-10-18', rows=len(rows), baseUnits=len(bases),
                  versions=dict(python=platform.python_version(), scipy=scipy.__version__, statsmodels=statsmodels.__version__, numpy=np.__version__), metrics=metrics, decisions=decisions, mcnemar=paired, wilcoxon=signed,
                  limitations=['Hand-built template families are not a random sample of real tasks; p-values are conditional mechanism checks, not proof of real-world superiority.',
                               'Frozen candidate and repair responses; frozen reviewer misses every injected error. All actual external provider calls are zero.',
                               'Two parameter variants per family are clustered; not treated as independent observations.',
                               'Group B requests clarification and is settled without simulated facts: correct routing is not correct final delivery.',
                               'Wilcoxon assumes symmetric paired differences; the small discrete differences show asymmetry, so p-values are descriptive sensitivity checks.',
                               'Number coverage does not prove semantic completeness. Zero objectives and coefficient scaling can be legitimate.'])
    (root / 'statistics.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    for filename, data in [('metrics.csv', metrics), ('decisions.csv', decisions), ('mcnemar.csv', paired), ('wilcoxon.csv', signed)]:
        with (root / filename).open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(data[0])); writer.writeheader(); writer.writerows(data)
    lines = ['# 程序化求解证据：受控配对初步实验', '',
             '**这是固定模型回答下的故障注入实验，不是真实大模型能力评测。所有求解使用本地 Pyomo/HiGHS。**', '',
             f'{len(rows)} 条运行；24 道题，A/B/C 各 8 道；12 个模板家庭，每家庭 2 个参数变体。配对单位按家庭合并。', '',
             '三组方法使用相同候选、同一固定审核回答、相同预算上限（调用 4、求解 2、交互 2）；仅在系统请求修模时返回预置修正版。真实 API 调用为 0，表中的调用数是实际执行的脚本规划请求。', '',
             '| 分组 | 方法 | 正确交付率 | 静默错误交付率 | 首次决策正确率 | 规划请求均值 | 本地求解均值 | 交互均值 |',
             '|---|---|---:|---:|---:|---:|---:|---:|']
    for r in metrics:
        lines.append(f"| {r['group']} | {r['method']} | {r['correctDelivery']:.1%} | {r['silentErrorDelivery']:.1%} | {r['correctFirstDecision']:.1%} | {r['plannerCalls']:.3f} | {r['solves']:.3f} | {r['interactions']:.3f} |")
    lines += ['', '正确交付率分母为该分组全部运行。B 组尚未获得补充条件，正确追问不计为正确最终交付。静默错误包括 A/C 的错误数值交付，以及 B 组未澄清就终结业务任务。', '',
              '| 方法 | 决策 | 准确率（one-vs-rest） | 召回率 | 误报率 |', '|---|---|---:|---:|---:|']
    for r in decisions:
        lines.append(f"| {r['method']} | {r['action']} | {r['accuracy']:.1%} | {r['recall']:.1%} | {r['falsePositiveRate']:.1%} |")
    lines += ['', '## 配对检验', '', 'McNemar：家庭的两个变体都成功才记成功；双侧精确检验，4 项检验统一 Holm 校正。', '', '| 对照 | 指标 | 完整系统增益 | p | Holm p |', '|---|---|---:|---:|---:|']
    for r in paired:
        lines.append(f"| {r['baseline']} | {r['outcome']} | {r['effect']:.1%} | {r['p']:.6g} | {r['pHolm']:.6g} |")
    lines += ['', 'Wilcoxon：每个家庭内预算均值配对，Pratt 处理零差，置换方法处理并列秩；6 项统一 Holm 校正。差值为完整系统减去对照。', '', '| 对照 | 预算 | 平均差值 | p | Holm p |', '|---|---|---:|---:|---:|']
    for r in signed:
        lines.append(f"| {r['baseline']} | {r['outcome']} | {r['meanDifference']:.3f} | {r['p']:.6g} | {r['pHolm']:.6g} |")
    lines += ['', '## 解释范围', ''] + ['- '+x for x in result['limitations']] + ['',
        '可确认的是：在这些固定故障条件下，证据路由能否拦截错误、准确追问，以及为此付出的预算。不能由此声称真实大模型在自然题目上的正确率已经提高，也不能把变体数量当作独立样本量。', '',
        '## 复现', '', '```powershell', 'node scripts/run-evidence-benchmark.mjs experiments/evidence-pilot-new', 'python scripts/analyze-evidence-benchmark.py experiments/evidence-pilot-new', '```', '',
        '完整冻结清单见 batch.json、protocol.json；原始轨迹和求解证据见 export-bundle.json；盲评输入见 blind-review.json；逐运行指标见 analysis.jsonl。', '',
        '统计方法参考：[SciPy Wilcoxon](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.wilcoxon.html)、[statsmodels McNemar](https://www.statsmodels.org/stable/generated/statsmodels.stats.contingency_tables.mcnemar.html)。']
    (root / 'report.md').write_text('\n'.join(lines)+'\n', encoding='utf8')
    # Standalone local visualization: no credentials, remote assets, or network.
    def escape(text):
        return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
    overall = [r for r in metrics if r['group'] == 'all']
    body = ''.join(f"<tr><th>{r['method']}</th><td><meter min='0' max='1' value='{r['correctDelivery']}'></meter> {r['correctDelivery']:.1%}</td><td>{r['silentErrorDelivery']:.1%}</td><td>{r['correctFirstDecision']:.1%}</td><td>{r['plannerCalls']:.2f} / {r['solves']:.2f} / {r['interactions']:.2f}</td></tr>" for r in overall)
    (root / 'report.html').write_text("<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>求解证据配对实验</title><style>body{font:16px system-ui;max-width:1100px;margin:48px auto;padding:20px;color:#17232b;background:#fafaf8}h1{font-size:28px}table{width:100%;border-collapse:collapse}td,th{padding:16px;text-align:left;border-bottom:1px solid #ccd3d6}meter{width:110px}p,li{line-height:1.8}.note{padding:16px;background:#e7eeef}</style><h1>求解证据：受控配对实验</h1><p class='note'>固定回答 + 真实 HiGHS 求解。24 道合成题 × 3 个方法。真实模型 API 调用 0 次。此结果检验控制器机制，不能证明真实大模型能力提升。</p><table><tr><th>方法</th><th>正确交付率</th><th>静默错误率</th><th>首次决策正确率</th><th>平均规划 / 求解 / 交互次数</th></tr>"+body+"</table><p>来源：本目录 analysis.jsonl，2026-10-18；统计以 12 个模板家庭配对，防止把参数变体当作独立样本。</p><p><a href='report.md'>完整统计报告</a> · <a href='statistics.json'>机器可读结果</a></p><ul>"+''.join('<li>'+escape(s)+'</li>' for s in result['limitations'])+'</ul></html>', encoding='utf8')
    print(json.dumps({'directory': str(root), 'overall': overall, 'mcnemar': paired, 'wilcoxon': signed}, ensure_ascii=False))


if __name__ == '__main__':
    analyze(sys.argv[1])
