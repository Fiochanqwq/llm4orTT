llm4orOvO 0.7.8 · 交互式优化与实验工作台
整理日期：2026-10-18

从空白开始
1. 从托盘退出以前运行的程序。
2. 双击 Start-Desktop.cmd（桌面）或 Start-Browser.cmd（浏览器）。
3. 在设置中重新填写厂商、模型与 API Key，选择 HiGHS，开启自动求解。
4. 每个新问题新建对话；批量实验从实验台创建新清单。

这两个入口使用本工程 .local/workspace-clean 中的新工作区，首次无会话、实验或密钥。
之后启动会继续保存和读取你的新数据，并非每次清空。
原来的 %LOCALAPPDATA%/FYPPPPP/workspace 保留，不自动导入。
直接 npm start / npm run desktop 仍沿用程序默认数据目录；从空白使用请优先双击上述入口。
现有 dist 和运行依赖已保留，可直接启动。修改前端后执行 npm run build。

能力与边界
自然语言需求 → 必要澄清 → LP/MILP 建模 → HiGHS 本地求解 → 数值检查 → 结果交付。
generic/full 对照、冻结批次、人工答复、暂停/继续、轨迹和评分导出均已提供。
每题最多4次模型请求、2次求解、2轮澄清，每轮最多3问；求解时限30秒。
失败和协议纠正占请求额度；建模输出默认4096 tokens，有效上限为 min(maxTokens, modelingTokens)。
请求次数和 token 上限不是金额硬限额。软件不保证人民币费用上限，消费限制需在提供商侧设置。
求解器 optimal 只证明提交模型的求解状态，不证明原题理解或最终答案正确。
非预算澄清和部分评分需人工处理；未知用量保持未知。
Gurobi 需额外环境与许可。软件支持线性/混合整数模型，不支持任意非线性问题。

文档入口
- docs/PROGRAM_OVERVIEW.txt：当前能力、目录和数据安全说明。
- docs/实验使用说明.txt：从创建批次到导出结果。
- docs/版本与历史说明.txt：当前版本、保留历史和验证证据。

目录
src/server/shared/solver/electron/public/assets：当前代码和资源。
scripts/test：维护命令与回归测试；带旧版本号的测试是兼容性测试，非旧程序入口。
experiments：保留的题库、参考答案和回归材料，不会自动加载成新工作区的运行记录。
baselines：必要的历史源码与回归依赖。
archive/20261018：旧说明、工作记录、实验审查、交付文件、重要旧安装包。
node_modules/runtime/dist：启动所需依赖、Python求解环境和前端构建。

维护
npm test：完整回归，会生成新的 qa 文件，并执行本地求解。
npm run build：类型检查和前端构建。
npm run package：构建当前0.7.8安装目录，输出 release/0.7.8。
本次整理未重新打包0.7.8，也未启动付费实验。
历史记录保留原始版本号；研究方法/协议版本不与应用版本强行同步。
