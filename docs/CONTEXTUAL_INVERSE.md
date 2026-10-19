# 融合非结构化文本日志与历史人工决策的上下文逆优化

本目录对应 llm4orTT 0.1（内部版本 0.1.0）。研究主线是“文本结构假设 → 逆优化求参 → 稀疏筛选与残差反馈”。应用同时提供普通对话和逆优化工作台；普通对话使用通用助手提示词，支持历史记录，与逆优化的结构生成提示词分离。旧研究结果不当作新方法的证据。

## 直接运行

```powershell
npm run build
npm start
```

顶部选择“逆优化工作台”。点击“运行三步重构”即可用内置排班数据运行真实 HiGHS，不需要大模型密钥。示例是脚本生成的合成数据，历史方案来自求解器，日志来自固定模板，均不冒充真实员工记录或 NLP4LP 数据。

在设置中配置模型，勾选“使用已配置的大模型补充结构假设并自动反馈”，会调用原有多服务商接口。输入任务、日志和训练历史会发送给当前选择的服务商。最多反馈 3 轮；停止按钮会终止请求及子进程。当前版本要求用户提供已知模型骨架及至少一个初始候选特征，LLM 生成/修订其未知目标项和软约束特征，不会从纯文本凭空补齐未提供的业务数据。

结果支持 JSON 导出和历史运行回看，包含输入、候选假设、求得权重、删去的假设、每个样本残差、反事实方案、主问题上下界、求解迭代以及 LLM 反馈轨迹。运行保存在工作区数据目录的 `inverse-runs/` 下。

```powershell
npm run test:inverse
npm run benchmark:inverse
```

`benchmark:inverse` 输出 `outputs/inverse/synthetic-benchmark.json`。默认一颗种子，包含 3 个 K、4 个噪声预算、3 种遮蔽数量、2 种方法，共 72 条评测记录。完整科研实验应使用多颗预先固定的种子，按基础模型聚合并报告不确定性，不能将同一模型的重复上下文当作独立模型。

```powershell
node scripts/inverse.mjs --out outputs/inverse/multiple-seeds.json --seeds 17,29,43
node scripts/inverse.mjs --out outputs/inverse/with-llm.json --guesses data/inverse/llm-guesses.json
```

第二条命令读取独立生成的真实 LLM 猜数结果。该文件以 `seed/K/noise/masked` 为键，例如 `17/5/0/1`；值是全部候选 ID 对应的权重字典。没有实际预测时该基线跳过，绝不以随机数或人工常量冒充大模型结果。

## 数学边界

每个上下文 k 的前向问题写为：

\[
 P_k(\theta)=\min_{x\in X_k}c_{0k}^{\mathsf T}x+\sum_{j=1}^{p}\theta_j\phi_{kj}(x),\qquad 0\le\theta_j\le U_j.
\]

已知硬约束集合 `X_k` 固定。`c0` 是保留的已知成本；候选特征可以是线性目标项，也可以是软约束违反量。不同样本允许具有不同变量数、已知成本、约束和特征系数，同一个假设 ID 的权重在全部上下文间共享。

例如“夜班尽量别超过 1 次”写为 `phi(x)=max(0,a^T x-1)`。自动引入松弛量 `s>=0, s>=a^T x-1`，目标项为 `theta*s`。非负权重保证这种松弛形式与前向惩罚一致。学习负向偏好时，应把方向写入线性特征的系数，不能给软约束一个负惩罚。

逆问题为：

\[
\min_{\theta,\epsilon\ge0}\frac1K\sum_k\epsilon_k+\lambda\|\theta\|_1,
\qquad
\epsilon_k\ge f_k(\hat x_k;\theta)-\min_{x\in X_k}f_k(x;\theta).
\]

初版约束 `theta>=0`，因此 L1 项恰为权重之和。没有同时施加 `sum(theta)=1`，因为那会把 L1 惩罚变成常数。保留已知成本用于固定成本单位；输入拒绝完全缺失已知成本的模型。但非零已知系数不自动保证可识别：已知成本在可行域上可能恒定，候选特征也可能抵消它。结果明确标记“未证明参数唯一性”，不能把零残差直接当作恢复真值。

### 连续 LP：强对偶

将原变量上下界、等式、软约束松弛全部写成 `A_k z >= b_k`，`z` 作为自由变量；成本写成 `c_k(theta)=c0_k+B_k theta`。引入非负对偶变量 `y_k`：

\[
A_k^{\mathsf T}y_k=c_k(\theta),\quad y_k\ge0,\quad
\epsilon_k\ge c_k(\theta)^{\mathsf T}\hat z_k-b_k^{\mathsf T}y_k.
\]

这是一个 LP；有限最优解与原始可行性是使用强对偶的前提。求解后再调用前向求解器核对真实残差。

### MILP：前向 Oracle 分离

整数变量不套用连续 LP 的 KKT 条件。主问题中保留权重、残差和已有反例。每轮在当前权重下求解真实前向 MILP，得到 `z*_k`，补上：

\[
\epsilon_k\ge c_k(\theta)^{\mathsf T}(\hat z_k-z_k^*).
\]

每个求解器调用都必须返回 `optimal`，否则停止并报错。没有新的违反割时，当前主问题解同时满足全部残差约束，返回 `optimal`；达到迭代预算时返回 `iteration_limit`，不假称收敛。保存主问题下界与实测目标上界。LP/MILP 混合历史采用同一个主问题，分别使用强对偶和反例割。

### 稀疏筛选和补充假设

仅在逆问题收敛后，将低于阈值、且下界允许为零的权重冻结为零。对真正被阈值截断的非零权重重新拟合，并重新计算残差。大模型只收到训练侧白名单字段与异常样本反事实；不能看到评测真值或测试集，不能改写历史方案和已知成本、硬约束来消除残差。

自动反馈保留训练残差不增加且求解收敛的提案。达到异常阈值、平台期、较差提案或轮数预算就停止。此规则是初版启发式，不保证找到真实遗漏结构；正式实验应增加训练/验证划分，用验证表现控制结构扩张，测试集只做最终评分。

## 数据契约

可直接复制 `examples/inverse/demo.json`。顶层 `schema` 必须为 `contextual-inverse.v1`。

- `description`、`logs`：不完整任务描述与运营日志。
- `hypotheses`：候选 ID、解释、证据原文、权重上下界。
- `samples`：每条包含 `id`、已知 `model`、`decision`、各候选对应的 `features`。
- `model.variables`：`name/type/lower/upper`；类型为 `continuous/integer/binary`。
- `model.objective`：已知成本系数；目前输入统一采用最小化。
- `model.constraints`：`terms/sense/rhs`，支持 `<=`、`>=`、`=`。
- 线性特征：`{"kind":"linear","terms":{"x":1}}`。
- 软约束特征：`{"kind":"soft","terms":{"x":1},"sense":"<=","rhs":3}`。
- `lambda`：默认 0.01；`pruneThreshold`：默认 0.001；`anomalyThreshold`：默认 0.1，均使用输入指定的成本/特征单位。
- `maxIterations`：默认 40；`seconds`：单次求解默认 15 秒。

所有历史方案必须满足已知硬约束与整数性。违反硬约束的观测被拒绝，并返回样本 ID，不能混作“含噪但可行的近优选择”。初版不实现未知硬约束矩阵、右端项与目标权重的联合估计；那通常会产生双线性或非凸逆问题，需要另外设计可识别性假设与算法。

API 为 `GET /api/inverse/demo`、`POST /api/inverse/recover`、`GET /api/inverse/runs`、`GET /api/inverse/runs/:id`，沿用项目原有访问令牌与来源检查。POST 体为 `{"input":完整数据对象,"useLLM":false,"rounds":3}`。

## 遮蔽—恢复评测口径

当前可重复执行的实验是合成排班，不是 NLP4LP 全量实验。真实隐藏权重保存在评测进程中，不进入 UI 样本和 LLM 的 learner view。

1. 固定种子生成已知成本、候选特征和 1–3 个非零隐藏权重，同时设置冗余候选。
2. 求解真实 Oracle 生成最优历史。噪声等级 `rho` 表示选取目标值不超过 `f*+rho*max(1,abs(f*))` 的可行备选，不是“rho 比例样本被污染”。可用备选不足时保留最优方案。
3. 使用 `K=5/10/20` 的嵌套训练前缀，以及固定独立的 20 条测试上下文；噪声随机数与上下文随机数独立。
4. 运行稀疏逆优化和 `lambda=0` 消融；可读入真实 LLM 猜数结果。
5. 输出 MAE、余弦相似度、候选支持集 precision/recall/F1，以及真实 Oracle 目标下的样本外绝对 regret。学习权重全零时余弦返回 null。regret 重新计算软约束违反量，避免零惩罚导致任意松弛量污染评分。

当前 F1 衡量候选特征支持集，不证明两组数学公式的语义等价，也不能直接标为“未知硬约束恢复率”。当前无正则消融不等于“无文本先验的全矩阵逆优化”；尚未实现的基线不输出伪造数据。正式对照需分别控制候选字典、文本先验、正则化与结构修订，不应把几个因素的效果混在一起。

正式 NLP4LP 实验还需：锁定数据集版本和许可、构造经过独立验证的参数化 Oracle、对可遮蔽的模型做筛选清单、真实 LLM 口语日志生成与数字泄漏检查、LLM 猜数基线、限定参数域的无文本逆优化基线、多种子及按原模型聚类的区间估计。目前没有完成这组研究结论所需的实测。

## 参考文献核对（2026-10-19）

以下核对了所给 arXiv 条目的标题和摘要；OptiMUS 另核对 HTML 正文中的数据集规模。未将摘要核验写成逐条定理验证。

1. [Inverse Optimization: A Survey — 2109.03920](https://arxiv.org/abs/2109.03920)：逆优化问题分类与方法背景。
2. [Data-driven Inverse Optimization with Imperfect Information — 1512.05489](https://arxiv.org/abs/1512.05489)：含噪/不完备信息与次优性损失。初版只实现经验残差，不冒称实现其分布鲁棒保证。
3. [Exact Solution to Data-Driven Inverse Optimization of MILPs in Finite Time via Gradient-Based Methods — 2405.14273](https://arxiv.org/abs/2405.14273)：当前 v8 与早期版本不同，使用时要固定版本。本文实现 Oracle 割法，并非复现该文梯度算法。
4. [Explicit Iteration Complexity of Exact Data-Driven Inverse Optimization for Integer Linear Programs — 2607.22263](https://arxiv.org/abs/2607.22263)：讨论求解所需迭代次数。**迭代复杂度不等于统计样本复杂度，不能据此断言少量历史能唯一恢复真值。**
5. [OptiMUS — 2402.10172](https://arxiv.org/abs/2402.10172)：[v1 正文](https://arxiv.org/html/2402.10172v1)列出 NLP4LP 为 **67 个问题，其中 13 个 MILP**，不能将此版本说成 100 个标准模型。100 应保留为待确认版本或扩充后的实验目标。
6. [Mamo: a Mathematical Modeling Benchmark with Solvers — 2405.13144v2](https://arxiv.org/abs/2405.13144v2)：可作为备选母本；特定下载版本是否含完整决策向量，需逐记录检查，不能由“带求解器”自动推断。
7. [OptMATH — 2502.11102](https://arxiv.org/abs/2502.11102)：双向合成思路；初版模板日志不冒称真实运行了其合成流程。
8. [ORLM — 2405.17743](https://arxiv.org/abs/2405.17743)：自动建模训练与 IndustryOR 背景。
9. [LLMOPT — 2410.13213](https://arxiv.org/abs/2410.13213)：五元素建模表示的参考。
10. [EquivaMap — 2502.14760](https://arxiv.org/abs/2502.14760)：模型等价性评估参考；初版未运行 EquivaMap，支持集 F1 不替代等价性证明。
11. [“I Want It That Way” — 2312.06908](https://arxiv.org/abs/2312.06908)：LLM 与约束规划的交互决策支持，用于界定对话偏好提取的相关工作。
12. [Decision Information Meets Large Language Models: The Future of Explainable Operations Research — 2502.09994](https://arxiv.org/abs/2502.09994)：EOR 解释思路；初版输出“日志证据—数学特征—权重—残差”，不声称已完成其评估。
13. [A Survey of Optimization Modeling Meets LLMs: Progress and Future Directions — 2508.10047](https://arxiv.org/abs/2508.10047)：建模综述；“所有数据集均完全显式给出参数”过于绝对，正式写作需数据集级证据。
14. [Large Language Models for Operations Research: A Comprehensive Survey — 2605.20849](https://arxiv.org/abs/2605.20849)：LLM4OR 研究背景与挑战，不作为本方法性能的实验证明。

## 用大白话理解

把系统想成学习老师傅排班的学徒。运营日志让学徒猜测“老师傅是不是特别怕夜班太多、交接太频繁”。历史排班让数学求解器算出：这些顾虑各值多少成本，才能解释以前为什么那样安排。稀疏惩罚像给每条猜测收一点“复杂度费用”：解释不了更多历史的多余规则，会被删掉。

但同一张排班表可能被不同想法解释。学徒说“我能解释这十次安排”，不等于已经完全读懂师傅。因此还要给他新的排班任务，用真实成本检查是否选得好；这就是样本外遗憾值的作用。
