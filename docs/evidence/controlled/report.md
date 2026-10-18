# 程序证据：当前动作日志的受控配对检验

**固定脚本故障注入实验，外部模型调用为零；不是真实大模型能力评测。**

数据：72 条运行，12 个 baseId，每个方法每个 baseId 两个变体。两个变体均成功才记该配对单位成功。

动作版本：`controller-actions-2`。
输入：[controlled-results.jsonl](controlled-results.jsonl)，SHA256：`0b9d54b22c091f72a13b6c1116a96de4cb65f4dda4583fb131f28513beffd402`。
机器可读结果：[statistics.json](statistics.json)；冻结协议：[protocol.json](protocol.json)。

## 结论

主指标 correctDelivery：structure：不显著（Holm p=0.25）；no_evidence：不显著（Holm p=0.25）。
次指标 correctFirstDecision：structure：显著（Holm p=0.03125）；no_evidence：显著（Holm p=0.03125）。
判断阈值为 0.05；两个对照、两个指标共四项检验统一 Holm 校正。不显著不等于无效果；次指标不能代替主指标。

## 实际运行计数

| 方法 | 运行数 | complete | partial | 正确交付 | 首次决策正确 | 静默错误交付 |
|---|---:|---:|---:|---:|---:|---:|
| structure | 24 | 24 | 0 | 8 | 8 | 16 |
| no_evidence | 24 | 24 | 0 | 8 | 8 | 16 |
| full | 24 | 16 | 8 | 16 | 24 | 0 |

## 双侧精确 McNemar 检验

改善/退步指同一 baseId 从对照到 full 的成败变化。成功率差是 full 减对照，以 baseId 为分母。

| 对照 | 指标 | 改善 | 退步 | 成功率差 | 精确 p | Holm p | 校正后显著 |
|---|---|---:|---:|---:|---:|---:|---|
| structure | correctDelivery | 4 | 0 | 33.33% | 0.125 | 0.25 | 否 |
| structure | correctFirstDecision | 8 | 0 | 66.67% | 0.0078125 | 0.03125 | 是 |
| no_evidence | correctDelivery | 4 | 0 | 33.33% | 0.125 | 0.25 | 否 |
| no_evidence | correctFirstDecision | 8 | 0 | 66.67% | 0.0078125 | 0.03125 | 是 |

计算：给定不一致配对数 n=改善+退步，双侧 p=min(1, 2×P[Binomial(n, 0.5)≤min(改善,退步)])。全部一致时 p=1。

## 边界与复现

- Hand-built template families are not a random sample; p-values describe this controlled mechanism check, not real-world superiority.
- Candidates, reviews and repairs are scripted; external model calls are zero.
- Two variants share a baseId and are combined, not counted as independent pairs.
- A correct clarification without an answer is partial, not a correct final delivery.
- Historical actions are not reconstructed; missing or inconsistent event logs fail validation.
- Number coverage is not a proof of semantic completeness.

校验已提交的报告：`npm run verify:evidence:published`。
重新执行测试、求解、统计并发布：`npm run verify:evidence -- qa/evidence-fresh --publish docs/evidence/controlled`，输出目录必须不存在。

本报告由当前 JSONL 自动计算；生成和核验不依赖额外 Python 统计包。预算 Wilcoxon 与描述性 bootstrap 可用独立的 Python 扩展分析生成，不属于本报告。
