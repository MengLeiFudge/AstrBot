# CPA 会话透传

本地插件注册 `cpa_responses` Provider，复用 AstrBot 原生 Responses 的工具、图像、推理、重试和流式处理。

把目标生成 provider source 的 `type` 改为 `cpa_responses`，保留 source ID、provider ID、模型名、地址、密钥与生成参数，然后完整重启 AstrBot。该 Provider 类型需要本插件先加载，不使用插件热重载切换类型。

每次请求发送：

- `x-opencode-session`：已有 `session_id` 的 UTF-8 百分号编码，保留 ASCII 冒号；同一会话和请求重试复用该值。
- `User-Agent`：`QQBot/AstrBot-cpa-session/0.1.0`。

没有会话 ID 的独立调用生成一次 UUID，并在该调用的重试中复用。请求头只保存在本次请求的 payload 中，不修改共享 HTTP 客户端或会话历史。

CPA 的 Go 渠道透传客户端的 `x-opencode-session` 与 `User-Agent`。模型别名、优先级和同名渠道兜底仍由 CPA 管理。跨框架路由要求见根工作区的 [模型 API 路由](../../../../docs/model-routing.md#opencode-go)。
