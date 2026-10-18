# 程序化求解证据与配对实验

完整方法 `full` 新增确定性证据；`no_evidence` 保留此前的完整流程作为消融，仅出现在实验配置中，中文名称为“完整方法 · 关闭程序证据（消融）”；`structure` 是相同结构协议与相同本地求解器的基础对照。当前方法版本为 `0.7.8-evidence-2`，修正了 evidence-1 的指标口径并增加 audit 降级。旧记录不迁移为新结论。导出协议继续使用原有版本，只增加证据与决策字段。

## 入口与预算

- `solver/evidence.py` 从实际 Pyomo 表达式的标准表示中读取目标方向、变量类型、全部非零常数、约束行与边界。
- `SolverService.audit` 只构造和检查模型，不调用优化器、不消耗模型调用或求解额度。支持现有求解后再次检查。
- audit 接口缺失、进程失败、空结果或 `diagnostic_error` 会记录 `task.evidenceDisabled`，本题退回无程序证据流程，保留语义审核和数值核验。后续求解关闭证据和辅助求解，不消耗额外交互预算。取消操作原样传播，不当成降级；明确发现的建模错误也不当成诊断故障绕过。
- `server/evidence-routing.mjs` 共用确定性决策逻辑；`executeV07` 把证据放进语义审核和定向修模输入，记录 `evidenceDecisions`。
- 新三元路由用于 `final_task`。既有 `budget_threshold_base` 阈值特例保留原预算门控及已验证证据复用，避免把故意暂未写入的预算区间误判成漏建约束；其求解记录仍可包含程序化证据，但不由新路由覆盖预算结论。
- 修模仍需可用调用及求解预算。模型代码错误不能改道消耗交互预算；预算不足时保留未验证结果，不能标成正确交付。
- 诊断求解预留额度，再按实际执行数结算；中断或响应不可信时保守保留预留额度。失败的辅助求解也计数。
- 不可行诊断最小化非负人工松弛量之和，保留变量边界和整数域。等式通过正负两侧共用绝对松弛处理。结果是一个最小 L1 松弛方案，**不是 IIS，也不是允许放宽用户条件的授权**。整数域或变量边界冲突可能无法靠行松弛消除。
- 双向微扰固定选择首个非零 RHS 的不等式，分别乘 0.9、1.1，检查可行域包含关系要求的单调性。需要额外两次求解。现有每题两次总求解预算通常不够，所以明确记录跳过；单独求解服务调用可显式提供两次诊断额度。运行时长受原有每次时限约束，不能保证任意 MILP 都在毫秒内完成。

## 数字对账的解释边界

数字集合不是自然语言语义证明。它不能检测所有“相同数字写在错误位置”的错误；行等比例缩放、指标计数、变量消元也可能使数字合法消失。原始 `missing_prompt_numbers` 及差异仍完整记录；不能定位到明确代数 RHS 的单独缺失标记作为歧义提示交给语义审核，不自动认定漏约束。带未定义常数、整数域或目标方向不符的明确异常仍进入修模。

单位换算只支持可明确识别的万元/元、吨/千克、千克/克、小时/分钟。通用自由文本、汉字数量和复杂单位推导不能靠此检查器保证识别。全体变量的整数/二元要求以及显式命名变量的整数/二元要求可以检查；复杂混合域描述仍需语义审核。

系数跨度超过 10000、零目标/全零方案、大上界贴边均是筛查信号，不必然代表业务错误。公开题面明确给出的极大上限不会直接标记为人为边界。无界变量列表是候选定位，不是无界射线证书。

## 无人值守

新建实验默认 `unattended: true`。已有模拟环境能回答的问题按原机制回答；无法回答时保存问题与 `UNATTENDED_CLARIFICATION_RECORDED`，该运行结算为 `partial`，继续其他配对运行。显式 `unattended: false` 保留人工补答模式。没有补充答案的正确追问不计为正确最终交付。

## 复现初步实验

```powershell
node --test test/evidence.test.mjs
npm run test:ci
npm run verify:evidence -- qa/evidence-new --publish docs/evidence/controlled
node scripts/run-evidence-benchmark.mjs experiments/evidence-pilot-new
python scripts/analyze-evidence-benchmark.py experiments/evidence-pilot-new
npm test
npm run build
```

求解使用项目已有 `runtime/python` 中的 Pyomo/HiGHS。服务和证据测试共用平台探测：Windows 查找嵌入式 `python.exe` 或虚拟环境 `Scripts/python.exe`，Linux/macOS 查找 `bin/python` 或 `bin/python3`。缺少依赖会明确失败，不跳过测试。分析使用独立 Python 环境中的 NumPy、SciPy、statsmodels；实际版本写入 `statistics.json`，不向求解环境安装统计库。

`test:ci` 包含不依赖 Python 的路由、指标、降级回归，在 Windows/Linux 都运行。Linux CI 通过已有 Codespaces 设置脚本安装锁定版本的求解依赖，再运行真实证据测试和 `verify:evidence`。CI 上传 `evidence-verification-<commit SHA>` 产物，包含日志、逐运行指标、完整导出和机器生成的 `verification.json`。

`verify:evidence` 使用新目录，执行 CI 测试、真实证据测试、构建与 72 条合成轨迹；逐项核验源码/驱动哈希、导出清单、动作指标及预算。检查失败会保存 `passed:false` 并非零退出。`--publish` 仅复制合成摘要与溯源清单到受版本控制的 `docs/evidence/controlled`，不复制用户对话、密钥或本地研究数据。`experiments/` 和 `qa/` 仍保留忽略规则。旧手工汇总文件不视为本版本的验证证据。

## 动作指标口径

新记录带 `decisionMetricsVersion: controller-actions-2`。`task.decisionEvents` 在动作实际发生时顺序追加，`firstDecision` 取第一个动作：`repair`、`clarify`、`deliver` 或 `fallback`。静态检查的 `continue`、暂时公布的求解结果和证据模块的降级提示都不是终结动作；只有通过后续检查的交付才记 `deliver`。先追问、后修模的轨迹首次动作仍为 `clarify`，不再从最终计数倒推。

修模按成功预留请求额度的次数统计，失败或取消的请求仍计入成本。`semanticRepairs` 只计语义审核诊断触发的请求；`programmaticRepairs` 计程序证据触发的请求；`toolRepairs` 计数值/工具复核触发的请求。协议格式纠正另计 `protocolCorrections`，不能冒充语义修模。只有内部修模标志而没有发出请求时不增加修模指标。导出与实验评分共用相同计算函数；缺少新动作日志的旧记录返回 `null`，不猜测历史顺序。

该基准有 24 个实例，A/B/C 各 8 个，12 个基础题型，每题型两个参数变体。A 注入数字遗漏/更改、整数域遗漏、方向反转和单位错误；B 包含单变量无界、耦合无界、冲突、缺最低需求导致零方案；C 包含生产、覆盖、等式和二元模型。可交付题的真值独立枚举顶点或整数点，不用被测求解结果充当答案。

这是**冻结脚本回答的控制器故障注入实验**。三个方法收到相同候选；固定审核回答未发现注入错误，只有真实触发修模后才提供修正候选。请求次数是实际执行的脚本规划请求，真实外部 API 调用为零。它验证错误拦截和决策机制，不估计真实模型犯错/修复的概率，也不构成真实任务上的优越性证明。

使用现有 ExperimentService 的随机排程、冻结快照、盲评接口、原任务评分器和 ExportService 导出。`batch.json` 冻结执行代码及预算，`driver-source-hashes.json` 冻结驱动/分析/题目脚本，`protocol.json` 冻结数据注入哈希与分析约定。输出包括完整 bundle、逐条 JSONL、盲评输入、CSV、JSON、Markdown 与本地 HTML 报告。

McNemar 按基础题型“两个变体均成功”配对做双侧精确检验；Wilcoxon 对题型内预算均值做 Pratt 零差处理的配对置换检验。分别对四项正确性检验和六项预算检验做 Holm 校正。模板非随机抽样、离散差值不对称，p 值只能作为本次受控机制实验的描述性证据。
