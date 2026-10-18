# llm4orOvO

自然语言优化建模、聊天与实验工作台。源码仓库保持私有。

## 在 GitHub 打开使用，无需本地下载

**[点击创建在线工作区](https://codespaces.new/Fiochanqwq/llm4orOvO?quickstart=1)**

1. 登录拥有此仓库访问权限的 GitHub 账号，点击上面的链接并创建 Codespace。也可以从 **Code → Codespaces → Create codespace on main** 进入。
2. 等待首次环境准备完成：自动安装依赖、Python/HiGHS 并构建网页，通常需要几分钟。
3. 打开启动任务的终端，点击输出的完整 `https://…app.github.dev/#token=…` 链接。若没有看到链接，在终端输入 **`npm run codespace`**；重复执行会连接已运行的服务。
4. 在网页设置里填写自己的模型 API Key，选择 HiGHS，即可开始使用。

Ports 面板中的 **43127 端口保持 Private**。从 Ports 直接打开的地址不带应用访问令牌，请使用终端输出的完整链接；不要分享这个链接。若旧链接失效，再运行 `npm run codespace` 获取当前链接。

下次从 [你的 Codespaces 列表](https://github.com/codespaces) 打开已有工作区，不需要重新创建。停止后重新打开会启动服务。使用完可在该列表停止环境；Codespaces 的可用额度和计费以你的 GitHub 账户为准。

## 数据与密钥

- 在线环境从空白开始，不包含本机实验数据、baseline 或历史对话。
- 云端新数据保存在 `.local/codespace-workspace/`，已被 Git 忽略，不随提交上传。
- API Key 使用 AES-256-GCM 加密，保护密钥文件仅允许工作区用户读写。它保护落盘文件，不隔离拥有该 Codespace 完整权限的人。
- 停止并重开同一个 Codespace 会保留工作区文件；删除 Codespace 会丢失其中未另行备份的数据。重要结果请使用应用导出功能备份。
- Windows 桌面版继续使用原来的 DPAPI 密钥保护。云端默认提供 HiGHS；Gurobi 需要另行安装和许可。

## 本地运行与验证

Windows 现有工程入口见 [README.txt](README.txt)。新克隆的工程先执行 `npm ci`、`npm run build`，求解环境需单独准备。

`npm run test:ci` 运行不依赖研究数据的测试。CI 同时检查 Windows 构建和 Linux 在线环境，Linux 作业还运行真实 HiGHS 求解与启动入口检查。

`npm test` 是完整本地回归，其中部分测试需要未上传的实验材料和历史 baseline。更多说明见 [GitHub 配置说明](docs/GITHUB_SETUP.txt)。

程序化求解证据、预算路由与无人值守分层配对实验见 [程序化证据说明](docs/PROGRAMMATIC_EVIDENCE.md)。
