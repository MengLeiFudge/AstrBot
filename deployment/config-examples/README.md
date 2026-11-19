# AstrBot local config templates

本目录只放可提交的本机配置示例，不放真实运行数据。

可用以下命令从当前运行态重新导出示例：

```bash
python3 scripts/qqbot-maintenance/export-astrbot-config-examples.py
```

导出内容包括 `cmd_config.example.json`、`personas.example.json` 和 `plugins/*.example.json`。脚本会剔除 LLM provider/model/provider_sources/provider_settings/fallback/image-caption/embedding 路由，并脱敏 key、token、secret、password、cookie、authorization 等字段。

真实 AstrBot 运行数据位于本项目的 `data/`，由项目 `.gitignore` 排除；维护的本地插件源码按目录白名单纳入版本控制。常见敏感项包括：

- Dashboard 密码、JWT secret、TOTP secret。
- Provider API key。
- OneBot / 平台 token。
- HAPI connector access token、Cloudflare Access client secret。
- 插件数据库、长期记忆、会话数据和未脱敏运行态数据。

初始化新机器时，先启动 AstrBot 生成默认配置，再参考本目录的示例补充本机值。

云栖人格文本从 AstrBot WebUI 人格配置导出为 `personas.example.json`。夜凛、星遥和月澄只在云栖人格中作为静态姐妹关系，不配置为 AstrBot persona 或平台。

图片按需处理：保持 `provider_ltm_settings.image_caption = false`，普通群图片不做背景描述；点名云栖并附图/引用图时，才由原生视觉请求处理。

DSP 六个大型模组的唯一向量库由 `astrbot_plugin_dsp_knowledge` 从 `D:/project/dsp` 自动增量维护。新机器还需配置 `openai_embedding`（`qwen3.7-text-embedding`）与 `bailian_rerank`（`qwen3-rerank`）两个 provider；API key 只放真实运行配置。插件只在 `127.0.0.1:8081` 提供共享检索，夜凛不会保存第二份索引。嵌入与重排序保持原百炼接口，CPA 提供兼容入口前不替换这两个 provider。

DeepSeek Responses 默认模型 `deepseek-responses/deepseek-flash` 与直接对话模型 `deepseek-responses/deepseek-flash-reply` 统一使用自定义请求体 `{"reasoning":{"effort":"high"},"max_output_tokens":8192}`。两者在同一 provider source 下请求支持视觉的 `qqbot-deepseek-flash`，能力列表一致；source 的 `api_base` 为 `http://127.0.0.1:8317/v1`，`key` 填写 CPA 客户端密钥。启用 [CPA 会话透传插件](../../data/plugins/astrbot_plugin_cpa_session/README.md)，将该 source 的 `type` 设为 `cpa_responses` 后完整重启，以便向 CPA 发送真实会话标识。保留 source ID、provider ID 与其余参数。普通续聊候选、拍一拍、命名意图判断、空回复纠错和上下文压缩沿用默认模型。

`topic_concentration` 仅为私聊和非拍一拍的显式呼叫选择回复模型，且只在会话原本使用上述默认模型、事件没有选择其他 provider 时生效；会话默认模型保持不变。两条路径均使用 high 思考，8192 为单次推理和正文共享的总输出上限，source 请求超时保持 120 秒。模型路由不会导出到示例，需在本机 WebUI 中配置这两个模型；缺少回复模型时沿用默认模型。

回复节奏由本地聊天插件管理：新直接呼叫停止同会话旧拍一拍或候选请求；首条分段等待扣除已经经过的处理时间，后续分段保持原速度。设置 `provider_settings.buffer_intermediate_messages=false`，让有用且已确认的公开阶段结论及时发送；保留 `display_reasoning_text=false` 和原模型参数。该 provider section 不进入脱敏示例，需在本机配置。普通文字的完整行为见[群聊路由插件](../../data/plugins/astrbot_plugin_topic_concentration/README.md)和[功能合集](../../data/plugins/astrbot_plugin_qqbot_features/README.md)。
