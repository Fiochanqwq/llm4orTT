# 可复现的程序证据验证

`controlled/` 保存由合成题生成的紧凑逐运行结果、协议、验证清单，以及当前动作日志自动计算的 [统计报告](controlled/report.md) 和 [机器可读统计](controlled/statistics.json)，全部纳入 Git。完整运行轨迹、测试及 JavaScript 覆盖率日志由 CI 的 `evidence-verification-<commit SHA>` artifact 保存。

生成命令（输出目录必须不存在；即使目录只有失败运行的残留文件也不能复用）：

```powershell
npm run verify:evidence -- qa/evidence-new --publish docs/evidence/controlled
```

验证流程依次执行 CI 回归、证据 JavaScript 覆盖率、真实求解证据测试、类型检查、构建和 72 条合成轨迹，然后生成统计报告并重新核算报告内容、输入与输出哈希。任一步失败均保存 `passed:false`，不会发布新报告。仅复制公开合成摘要，不复制完整对话、凭据或本地研究目录。覆盖率日志明确限定所测 JavaScript 文件，不表示 Python 或整个项目覆盖率为 100%。

独立检查已提交的报告、冻结源码和验证驱动是否仍与当前代码一致：

```powershell
npm run verify:evidence:published
```

该检查在 Windows 与 Linux CI 都执行。源码、测试或验证驱动变化后，必须重新生成证据再提交；旧报告不能继续冒充当前版本的通过结果。`.gitattributes` 固定被哈希源码的行尾，并保持发布数据原始字节，避免跨平台换行导致哈希漂移。

单独重新计算某份合成摘要的正确性统计（不会生成测试通过证明）：

```powershell
npm run analyze:evidence -- qa/evidence-new
```

统计分析使用 Node 内置功能，不需要安装额外 Python 统计库；它检查冻结题目清单、所有方法的两个配对变体、动作日志顺序、修模分类和预算。McNemar 采用双侧精确检验，两个指标与两个对照共四项统一 Holm 校正。报告分别判断主指标 `correctDelivery` 和次指标 `correctFirstDecision`，不能用次指标显著代替主指标。

`verification.json` 由脚本实际执行检查后生成，`passed` 是这次本地执行的结果，不等同于远端 CI 状态。远端状态必须以对应提交的 GitHub Actions 运行记录为准。源码版本以 `sourceSnapshot` 中逐文件 SHA256 为准。

这里验证的是固定候选回答下的控制器机制。外部模型调用数为零，不证明真实模型能力提升。真实模型无注入前导实验及扩样本属于后续研究，不能用这里的合成结果替代。
