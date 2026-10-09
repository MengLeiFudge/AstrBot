# AstrBot local config templates

本目录只放可提交的本机配置示例，不放真实运行数据。

可用以下命令从当前运行态重新导出示例：

```bash
python3 scripts/qqbot-maintenance/export-astrbot-config-examples.py
```

导出内容包括 `cmd_config.example.json`、`personas.example.json` 和 `plugins/*.example.json`。脚本会剔除 LLM provider/model/provider_sources/provider_settings/fallback/image-caption/embedding 路由，并脱敏 key、token、secret、password、cookie、authorization 等字段。

真实 AstrBot 运行数据位于本项目的 `data/`，由项目 `.gitignore` 排除；只有四个本地插件源码纳入版本控制。常见敏感项包括：

- Dashboard 密码、JWT secret、TOTP secret。
- Provider API key。
- OneBot / 平台 token。
- HAPI connector access token、Cloudflare Access client secret。
- 插件数据库、长期记忆、会话数据和未脱敏运行态数据。

初始化新机器时，先启动 AstrBot 生成默认配置，再参考本目录的示例补充本机值。

云栖人格文本从 AstrBot WebUI 人格配置导出为 `personas.example.json`。夜凛、星遥和月澄只在云栖人格中作为静态姐妹关系，不配置为 AstrBot persona 或平台。

图片按需处理：保持 `provider_ltm_settings.image_caption = false`，普通群图片不做背景描述；点名云栖并附图/引用图时，才由原生视觉请求处理。

DSP 六个大型模组的唯一向量库由 `astrbot_plugin_dsp_knowledge` 从 `D:/project/dsp` 自动增量维护。新机器还需配置 `openai_embedding`（`qwen3.7-text-embedding`）与 `bailian_rerank`（`qwen3-rerank`）两个 provider；API key 只放真实运行配置。插件只在 `127.0.0.1:8081` 提供共享检索，夜凛不会保存第二份索引。

DeepSeek Responses 默认模型 `deepseek-responses/deepseek-flash` 保持自定义请求体 `{"reasoning":{"effort":"none"}}`，供普通续聊候选、拍一拍、命名意图判断、空回复纠错和上下文压缩使用。在同一 provider source 下另建 ID 为 `deepseek-responses/deepseek-flash-reply` 的模型配置，实际模型仍是 `deepseek-flash`，能力列表与默认模型一致，自定义请求体填写 `{"reasoning":{"effort":"low"},"max_output_tokens":4096}`，无需复制 API key。

`topic_concentration` 仅为私聊和非拍一拍的显式呼叫选择该回复模型，且只在会话原本使用上述默认模型、事件没有选择其他 provider 时生效；会话默认模型保持不变。4096 为单次推理和正文共享的总输出上限。模型路由不会导出到示例，需在本机 WebUI 中配置这两个模型；缺少回复模型时沿用默认模型。
