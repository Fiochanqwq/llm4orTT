# llm4orTT

[![CI](https://github.com/Fiochanqwq/llm4orTT/actions/workflows/ci.yml/badge.svg)](https://github.com/Fiochanqwq/llm4orTT/actions/workflows/ci.yml)

**从文字日志和历史选择中学习偏好，让优化方案有依据、可检查。**

llm4orTT 是一个上下文逆优化工作台，提供 Windows 桌面应用和本地浏览器界面。当前源码版本为 **0.1.2**，集成偏好权重估计、候选规则筛选、参数范围分析和条件风险检查，也提供独立的普通对话功能。

例如：历史排班经常避开夜班和跨区支援，系统可以根据已有模型与候选规则，估计这些安排的隐性代价，再展示哪些规则被保留、哪些历史难以解释，以及推荐方案在声明条件下的最坏额外费用。

[下载已发布版本](https://github.com/Fiochanqwq/llm4orTT/releases) · [数学与实现说明](docs/CONTEXTUAL_INVERSE.md) · [公开研究证据](research/artifacts/README.txt) · [当前任务板](任务.md)

## 核心流程

```text
任务描述、文字日志、历史决策与候选模型
                  ↓
         本地逆优化：估计共享偏好权重
                  ↓
       稀疏筛选、残差分析与参数范围检查
                  ↓
          条件风险检查、结果展示与导出
```

启用模型辅助后，大模型可补充候选规则；数值拟合与数学检查由本地求解器完成。

- **偏好学习**：结合已知成本与历史选择，估计候选特征的共享权重；支持线性特征和软约束惩罚。
- **本地分析**：选择正则化强度，展示拟合残差、异常样本和能够解释历史的参数范围。
- **条件风险检查**：在声明的历史误差预算和参数范围下，计算方案损失上下界；提供风险见证和误差预算敏感性结果。
- **过程追溯**：回看历史运行，导出输入、权重、残差、求解轨迹及模型调用用量。
- **模型辅助**：按需请求候选规则，复用相同请求的缓存；工作台单次运行最多发起 1 次模型请求。
- **普通对话**：支持多轮上下文、停止、重试、搜索、重命名、文本附件和导出。

## 快速上手

### 使用 Windows 应用

1. 在 [Releases](https://github.com/Fiochanqwq/llm4orTT/releases) 选择已发布的 Windows x64 压缩包，完整解压。
2. 运行 `llm4orTT.exe`；也可通过包内的 `Browser.cmd` 打开浏览器界面。运行时请保留完整的 `resources/` 目录。
3. 进入顶部的“逆优化工作台”，载入排班示例，点击“运行三步重构”。
4. 查看恢复结果、本地数学检查与风险结果，点击“导出证据”保存 JSON。

**内置排班示例可在本地运行，无需 API 密钥。** 安装包的版本以对应 Release 标签为准。

### 从源码启动

环境要求：Node.js 24 或更新版本。Windows 安装脚本会下载固定版本的嵌入式 Python；Linux/macOS 需要 Python 3.13 及 venv 支持。首次安装需要联网。

在项目根目录执行：

```sh
npm ci
npm run solver:prepare
npm run build
npm start
```

`npm start` 启动本地服务并打开浏览器。Windows 桌面模式使用：

```sh
npm run desktop
```

完成依赖与求解器安装后，开发模式使用 `npm run dev`，打开终端给出的本地地址。

### 配置模型辅助与对话

在“设置”中选择服务商、保存密钥，刷新可用模型后测试连接。逆优化工作台需勾选“需要时请大模型补充规则”才会使用模型辅助；普通对话使用单独的对话流程。

DeepSeek 默认配置为 `deepseek-flash`，支持预设候选、接口发现与手动填写模型 ID。旧型号和自部署服务可填写兼容的 HTTPS 接口地址，程序按型号适配参数。候选 ID 的实际可用性由所选接口决定，配置细节见 [DeepSeek 兼容说明](docs/DEEPSEEK_COMPATIBILITY.md)。

启用模型功能时，任务文本及相应上下文会发送到所选服务商。密钥、聊天记录和运行缓存保存在本机，提交代码时由忽略规则排除。

## 验证与打包

基础回归检查：

```sh
npm run build
npm test
npm run test:inverse
npm run test:research
npm run test:certification
```

公开基准相关的离线数学测试：

```sh
npm run test:mamo
npm run test:multifamily
npm run test:stress
```

上述测试入口不需要付费模型调用。浏览器与打包后桌面验收分别使用 `npm run qa:browser`、`npm run qa:desktop`。

Windows 打包：

```sh
npm run package
```

输出位于 `release/0.1.2/win-unpacked/`。修改 `src/` 或 `solver/` 后重新构建；发布包中的求解器由维护源码同步生成。

推送和拉取请求触发 [CI](.github/workflows/ci.yml)。与项目版本匹配的 `v*` 标签触发 [Windows 发布流程](.github/workflows/release.yml)，完成打包、桌面验收和 ZIP 校验文件发布。协作与版本规则见 [贡献指南](CONTRIBUTING.md) 和 [更新记录](CHANGELOG.md)。

## 研究资料与复现

**应用演示、离线测试和完整实验各有独立入口。** 完整实验依赖对应的冻结数据、归档响应及运行环境；先阅读各批次复现说明，再按[任务板](任务.md)执行预算和冻结规则。

- [基础逆优化实验](research/REPRODUCE.txt)：合成排班、偏好恢复与消融评测。
- [MAMO 配餐实验](research/REPRODUCE_MAMO.txt)：公开题重构、遮蔽恢复和事后审计。
- [跨题型实验](research/REPRODUCE_MULTIFAMILY.txt)：调运、路线模型及方法对照。
- [公开基准压力测试](research/REPRODUCE_STRESS.txt)：NETLIB、OR-Library、TSPLIB95，以及参数误差与决策损失的区别。
- [真实模型文本闭环](research/REPRODUCE_LLM_GROUNDING.txt)：真实模型响应、文本消融、反馈和失败记录。
- [条件风险证书研究](research/REPRODUCE_PUBLICATION.txt)：方法比较、精确核验、误差预算敏感性及报告生成。

公开证据包统一收录在 [research/artifacts/](research/artifacts/README.txt)，包含逐题结果、原始失败、核验材料和数据许可。该目录同时记录已有实验中的负面结果：文本候选与稀疏筛选的相对收益随题型变化，闭环反馈在完整配对样本上没有改善结果。

本地完整实验资料位于 `实验/`，入口为 `实验/先看这里.txt`；该目录受忽略规则排除，克隆仓库后需另行取得对应归档。决策契约批次的逐题分析以本地 `实验/决策契约研究_2026-10-21_01/案例簿.md` 为事实来源，后续工作见[任务板](任务.md)。

### 适用范围

- 输入包含已知模型骨架、历史决策与候选特征；离线流程直接使用已有候选进行拟合。
- 参数范围描述经验损失约束下的可行取值，统计置信区间需另行估计。低残差与参数唯一恢复是不同指标。
- 桌面风险证书面向能够完整枚举的小型有界整数问题；计算不足时返回未决状态。连续规划基础求解与二维几何研究模块使用各自的实现入口。
- 风险结果依赖输入的误差预算、特征和可行域。内置排班与多批历史日志采用合成或受控生成数据，数据构造和逐批结论见对应复现材料。

## 代码导航

```text
src/                 前端界面、逆优化工作台与风险结果展示
server/              本地服务、模型接口、运行记录与求解器调用
solver/              逆优化、条件风险证书与敏感性分析的维护源码
research/            实验方法、分析、复现说明与公开证据包
scripts/             开发、构建、打包和实验入口
test/                应用与既有研究回归测试
tests/               证书、几何与实验完整性测试
docs/                数学说明、接口兼容与环境锁定
```

## 许可

项目原始代码和美术资源保留全部权利，使用与再分发按 [LICENSE](LICENSE) 执行。第三方组件遵循各自许可，见 [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt)；研究数据许可随对应证据包提供。
