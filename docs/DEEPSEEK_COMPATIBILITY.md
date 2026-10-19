# DeepSeek 兼容说明

核对日期：2026-10-19。

默认入口 `deepseek-flash` 当前由 DeepSeek-V4.1-Flash-1017 提供；`deepseek-v4-pro` 仍提供服务。`deepseek-v4-flash` 和 `deepseek-v4-flash-vision-exp` 是由官方路由到新 Flash 的兼容名称，不能用来冻结历史权重。

参考：[官方入口](https://api-docs.deepseek.com/)、[模型查询](https://api-docs.deepseek.com/api/list-models/)、[思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)、[版本历史](https://api-docs.deepseek.com/updates/)。

## 历史与自部署模型

预设含历史 API 名称和 V2、Coder V2、V2.5、V3、V3-0324、R1、R1-0528、V3.1、V3.1-Terminus、V3.2-Exp、V3.2、V3.2-Speciale 的仓库名称。不同服务可能采用不同大小写、前缀或后缀，模型输入框允许任意 ID，程序不按版本过滤。预设只是填写提示，不证明任何接口仍提供该模型。

使用旧模型时，填写实际托管该版本的 HTTPS Chat Completions 地址和对应密钥。官方已下线的型号、别名与限时端点无法由客户端恢复。失败时不会自动换型号，也不会自动重试产生额外模型请求。

## 请求行为

- Flash、V4 系列标准命名：启用思考、`reasoning_effort=high` 和流式用量。
- Reasoner、R1 及其前缀/日期变体：使用原生推理，不发送新版 thinking、reasoning_effort 或 stream_options 字段。
- Chat、Coder、V2/V3 与未知自定义 ID：仅使用标准 Chat Completions 字段，保留服务端默认能力。
- 老 Chat/Coder/V2/V3 保守限制为 4096 输出 token；R1/Reasoner 为 65536；现代系列为 393216。较小请求保持原值，未知模型保持用户设置。限额可能使长回答提前结束，界面会提示。
- 只将最终 content 作为回答，推理片段不混入正文；多轮发送用户和助手正文。缺少正常结束标记、异常结束和取消均不会冒充成功。

“刷新可用模型”查询当前地址 `/models`，保存返回的全部 ID，预设和手填仍保留。模型列表不保证每项均有生成权限，“测试连接”才实际调用当前型号。

测试通过 SDK 与模拟 HTTP/SSE 验证旧版、最新版、自定义 ID、用量、截断、取消与错误。这不等于每个第三方服务的付费实测。
