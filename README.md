# llm4orTT

[![CI](https://github.com/Fiochanqwq/llm4orTT/actions/workflows/ci.yml/badge.svg)](https://github.com/Fiochanqwq/llm4orTT/actions/workflows/ci.yml)

**0.1** · 普通对话与上下文逆优化工作台。程序与 npm 元数据使用标准版本号 `0.1.0`。

从运营日志和历史决策中恢复优化模型的隐藏权重，用稀疏正则化筛选候选假设。内置示例可在本地运行，无需 API 密钥。

## Windows 使用

从 [Releases](https://github.com/Fiochanqwq/llm4orTT/releases) 下载 Windows x64 压缩包，完整解压后运行 `llm4orTT.exe`。`Browser.cmd` 可打开浏览器界面。请保留随包提供的 `resources` 目录。

默认进入普通对话，支持多轮上下文、历史记录、停止、重试、搜索、重命名、复制、文本附件和导出。在“设置”中选择服务商并保存密钥。顶部“逆优化工作台”中的“运行三步重构”运行真实本地求解器。原有本地配置与聊天仍可读取。

## DeepSeek 新旧版本

默认使用最新官方入口 `deepseek-flash`。内置 V4 Pro、V4 兼容别名、历史 Chat/Reasoner/Coder、V2、V2.5、V3、R1、V3.1、V3.2 系列候选 ID，同时允许手填任何前缀、日期快照和新型号。

在设置中选择 DeepSeek、填写密钥，点击“刷新可用模型”，再选择模型并“测试连接”。旧模型或自部署服务可在高级设置中填写提供该型号的 OpenAI Chat Completions 兼容 HTTPS 地址。程序按代际适配参数，不会自动替换模型。

预设 ID 只是填写提示；可用性以接口实际提供的模型为准。官方已下线的版本需要仍托管它的服务，官方兼容别名也可能被路由到新模型。详情见 [兼容说明](docs/DEEPSEEK_COMPATIBILITY.md)。

## 源码运行与验证

需要 Node.js 24 或更新版本。Windows 脚本会下载固定的嵌入式 Python；Linux/macOS 还需要 Python 3.13 和 venv 支持。首次安装需要联网。

```sh
npm ci
npm run solver:prepare
npm run build
npm start
npm test
npm run test:inverse
npm run test:research
npm run benchmark:inverse
```

Windows 桌面使用 `npm run desktop` 或 `Start-Desktop.cmd`；开发前端使用 `npm run dev`。Windows 打包：`npm run package`，输出 `release/0.1.0/win-unpacked/llm4orTT.exe`。浏览器与桌面验收：`npm run qa:browser`、`npm run qa:desktop`。

GitHub Actions 对推送与 PR 执行构建、接口和真实求解器测试。版本标签 `v0.1` 会额外构建 Windows 包、验证打包后程序，并发布 ZIP 和 SHA256 校验文件。见 [贡献指南](CONTRIBUTING.md) 和 [发布记录](CHANGELOG.md)。

## 数据与研究边界

密钥、聊天、未整理的实验输出、模型文件和运行时不进入 Git；安装包通过 Releases 分发。经过核验的公开研究证据包单独放在 `research/artifacts`，不含用户聊天或密钥。启用大模型会把当前任务数据发送到所选接口。离线复算需归档的实验数据，见 [复现说明](research/REPRODUCE.txt)。

实现边界与实验协议见 [研究说明](docs/CONTEXTUAL_INVERSE.md)。当前内置评测是合成排班数据，不代表已完成 NLP4LP 全量评测。新方向代码位于 `server/inverse.mjs`、`solver/inverse.py` 和 `src/Inverse.tsx`。

新增独立的 MAMO 公开数据实验管线：固定审计40道配餐题，39道重构模型与公开答案一致；使用受控生成的日志和历史做遮蔽恢复、少样本噪声与消融比较。数据来源、数学公式、排除记录和复算方法见 [MAMO复现说明](research/REPRODUCE_MAMO.txt)。这是一类问题的探索性实验，不能替代跨领域评测或真实人工决策验证。`npm run test:mamo` 不需要下载研究数据；`npm run experiment:mamo` 需要归档的冻结数据和模型回答。

原始代码保留全部权利，见 [LICENSE](LICENSE)。第三方依赖许可见 [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt)。

### 多公开基准压力测试（2026-10-20）

新增 NETLIB、OR-Library 和 TSPLIB95 三个公开基准集合：预列 14 个实例，13 个通过公开最优值核验，一个来源不可用并保留。固定三次种子、九种方法，包含全零、常见价格、固定中点和随机报数四个不学习对照。全部排程、失败、最优面诊断、参数范围和资源账进入独立证据包；旧 MAMO 证据不替换。

AFIRO 已给出明确反例：隐藏价格误差达到 100%，决策费用损失仍可为零；无噪声且取消稀疏惩罚也可能出现。不能用“方案分高”证明“真实价格恢复正确”。文本候选仍是受控模板，历史仍是生成数据，不宣称完成自由文本或真实人工决策验证。

主条件下，背包平均费用损失为 1.026%，常见价格对照为 10.945%，但隐藏价格误差仍为 51.496%；连续规划反而较差，0.286% 对 0.035%。路线库有一组共享历史生成失败，不能报告完整队列胜利。共 1,368 条完成、108 条来源不可用、36 条受共享管线阻断；97 次额外最坏最优面检查超时。稀疏和文本候选筛选的稳定额外优势尚未证实。所有计算在本地完成，付费 API 调用为零。

运行与数学口径见 [压力测试复现说明](research/REPRODUCE_STRESS.txt)；完整结果在 [公开证据目录](research/artifacts/README.txt)。`npm run test:stress` 执行无需下载数据的数学测试；`npm run experiment:stress` 使用公开源文件执行冻结实验。中断和重复调度事故也归档，受影响任务用同一输入重算，未隐瞒为零成本。

### MAMO事后审计（2026-10-20）

已公开的完整证据包在 [research/artifacts](research/artifacts/README.txt)。下载其中 ZIP，解压后打开“审计报告.html”，可以查看逐题数据、旧报告、复算脚本和结论处置记录。

旧实验分数和测试集保持不变。审计发现：主比较中2号、39号题占本方法总损失的86.50%；零价格导致最优解不唯一，改变变量排列会改变决策遗憾；25/62个隐藏价格从未被训练历史激活。文本、稀疏以及相对固定报10的额外收益均未证实，不能将当前结果写成真实参数恢复或一般隐式约束发现的证明。

`npm run audit:mamo` 从归档证据执行本地审计；`npm run audit:mamo -- --recompute` 在新的独立输出目录从零重算。两者都不调用付费模型。结果包含原始报告副本、全部方法对照、参数范围、最优解退化证书、逐题下载及结论处置账本；`npm run qa:mamo-audit` 检查报告。审计数学与证据核验在 `research/mamo_audit.py` 和 `research/mamo_audit_verify.py`，绘图在 `research/mamo_audit_report.py`。

### 冻结跨题型扩展（2026-10-20）

新增调运与闭环路线两类模型，审计 59 道候选题，准入 19 道；其中 16 道测试题、3 道开发题。5 次重复、8 种本地方法、2 个历史数量和 2 个噪声上限，共 3,040 条结果，新增付费调用为 0。

路线题主条件平均遗憾从固定中点的 4.271% 降到文本候选稀疏逆优化的 0.764%，但仅有 5 道准入测试题。调运题的相对收益区间仍跨零，且估计最优方案之间有严重费用歧义；这些反例全部保留。受控文本不代表已验证真实日志理解，当前结果也不代表 CCF A 投稿已就绪。

[完整证据包](research/artifacts/README.txt)包含逐题五次最好／中间／最差、所有对照、独立模型核验和论文草稿。[复现说明](research/REPRODUCE_MULTIFAMILY.txt)。`npm run test:multifamily` 运行无数据依赖的数学测试，`npm run experiment:multifamily -- --recompute` 在新目录重算全套实验，保留原档。普通聊天功能和软件版本 `0.1.0` 保持不变。
