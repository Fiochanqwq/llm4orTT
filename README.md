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

密钥、聊天、实验输出、模型文件、运行时与安装包不进入 Git；安装包通过 Releases 分发。启用大模型会把当前任务数据发送到所选接口。离线复算需单独归档的实验数据，见 [复现说明](research/REPRODUCE.txt)。

实现边界与实验协议见 [研究说明](docs/CONTEXTUAL_INVERSE.md)。当前内置评测是合成排班数据，不代表已完成 NLP4LP 全量评测。新方向代码位于 `server/inverse.mjs`、`solver/inverse.py` 和 `src/Inverse.tsx`。

新增独立的 MAMO 公开数据实验管线：固定审计40道配餐题，39道重构模型与公开答案一致；使用受控生成的日志和历史做遮蔽恢复、少样本噪声与消融比较。数据来源、数学公式、排除记录和复算方法见 [MAMO复现说明](research/REPRODUCE_MAMO.txt)。这是一类问题的探索性实验，不能替代跨领域评测或真实人工决策验证。`npm run test:mamo` 不需要下载研究数据；`npm run experiment:mamo` 需要归档的冻结数据和模型回答。

原始代码保留全部权利，见 [LICENSE](LICENSE)。第三方依赖许可见 [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt)。

### MAMO事后审计（2026-10-20）

已公开的完整证据包在 [research/artifacts](research/artifacts/README.txt)。下载其中 ZIP，解压后打开“审计报告.html”，可以查看逐题数据、旧报告、复算脚本和结论处置记录。

旧实验分数和测试集保持不变。审计发现：主比较中2号、39号题占本方法总损失的86.50%；零价格导致最优解不唯一，改变变量排列会改变决策遗憾；25/62个隐藏价格从未被训练历史激活。文本、稀疏以及相对固定报10的额外收益均未证实，不能将当前结果写成真实参数恢复或一般隐式约束发现的证明。

`npm run audit:mamo` 从归档证据执行本地审计；`npm run audit:mamo -- --recompute` 在新的独立输出目录从零重算。两者都不调用付费模型。结果包含原始报告副本、全部方法对照、参数范围、最优解退化证书、逐题下载及结论处置账本；`npm run qa:mamo-audit` 检查报告。审计数学与证据核验在 `research/mamo_audit.py` 和 `research/mamo_audit_verify.py`，绘图在 `research/mamo_audit_report.py`。
