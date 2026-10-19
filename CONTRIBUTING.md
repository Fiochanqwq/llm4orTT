# 贡献指南

先阅读 README 与研究边界。项目代码保留全部权利，协作不自动授予再分发许可。

使用 Node.js 24，执行 `npm ci` 和 `npm run solver:prepare`。提交前运行 `npm run build`、`npm test`、`npm run test:inverse`、`npm run test:research`。改动桌面或打包时，在 Windows 运行 `npm run package` 与 `npm run qa:desktop`。

PR 描述具体问题、改后行为及实际验证。使用不含私人数据的最小例子，研究结论需区分合成数据、真实数据与模型生成内容。

不要提交密钥、聊天、原始实验回答、个人路径、模型权重、运行时或构建输出。文件使用 UTF-8，脚本使用 LF。更新依赖时同步锁文件和第三方许可。

发布时同步 package.json、锁文件根信息、打包目录与 CHANGELOG。标签 v0.1 对应内部 0.1.0，后续可用完整语义标签。Release 工作流先验证，再上传 Windows ZIP 与 SHA256SUMS.txt。不要移动已发布标签。
