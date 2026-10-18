# 可复现的程序证据验证

`controlled/` 只保存由合成题生成的紧凑逐运行结果、协议及验证清单，纳入 Git。完整运行轨迹和测试日志由 CI 的 `evidence-verification-<commit SHA>` artifact 保存。

生成命令（输出目录必须是新目录）：

```powershell
npm run verify:evidence -- qa/evidence-new --publish docs/evidence/controlled
```

`verification.json` 由脚本实际执行检查后生成，`passed` 是这次本地执行的结果，不等同于远端 CI 状态。远端状态必须以对应提交的 GitHub Actions 运行记录为准。源码版本以 `sourceSnapshot` 中逐文件 SHA256 为准。

这里验证的是固定候选回答下的控制器机制。外部模型调用数为零，不证明真实模型能力提升。真实模型无注入前导实验及扩样本属于后续研究，不能用这里的合成结果替代。
