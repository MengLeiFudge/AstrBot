from __future__ import annotations

import re


RIGHTCODES_DRAW_CATALOG_TEXT = """RightCodes 生图接口知识库：
资料来源：Right Code 官方文档 https://docs.right.codes/docs/rc_draw/ ，最近核对 2026-08-03。

基础信息：
- 绘图基础地址：https://www.rightapi.ai/draw
- 任务查询地址：https://www.rightapi.ai/v1/tasks/{task_id}，查询接口不带 /draw。
- 统一鉴权头：Authorization: Bearer sk-xxxxx
- 所有绘图请求统一使用异步流程：提交时固定带 async=true，取得 task_id 后轮询任务查询接口。

/v1/images/generations：
- 用途：OpenAI Images 兼容的异步文生图和参考图生图接口。
- 方法：POST https://www.rightapi.ai/draw/v1/images/generations
- 字段：model、prompt、async=true 必填；n、size、imageSize、image 可选。
- size 支持 1:1、16:9、9:16、4:3，或 1024x1024 这类像素串；imageSize 仅支持 1K、2K、4K。
- image 参考图必须是 data URL 数组，不是普通图片 URL。
- 示例 body：
{
  "model": "gpt-image-2",
  "prompt": "一只白猫",
  "n": 1,
  "size": "1:1",
  "imageSize": "1K",
  "async": true
}

/v1beta/models/{model}:generateContent：
- 用途：Gemini generateContent 兼容的异步生图接口。
- 方法：POST https://www.rightapi.ai/draw/v1beta/models/{model}:generateContent
- 请求体固定带 async=true；提示词放在 contents[].parts[].text。
- 比例和分辨率分别放在 generationConfig.imageConfig.aspectRatio 与 imageSize。
- 参考图使用 contents[].parts[].inline_data，包含 mime_type 和 base64 data。

/v1/tasks/{task_id}：
- 方法：GET https://www.rightapi.ai/v1/tasks/{task_id}
- queued / in_progress 表示继续轮询，completed 从 data 或 candidates 取图，failed 查看 error.message。
- 实际 Images 完成响应也可能直接返回 created 和 data，不带 status；此时从 data 取图。

当前经真实 Images 接口生成验证可用的模型：
- gpt-image-2：$0.04/次，OpenAI 画图模型，支持 1K。
- gpt-image-2-vip：$0.13/次，OpenAI 官方直连，当前支持 1K；官方已停止 2K、4K。
- nano-banana-2-lite：$0.05/次，即 gemini-3.1-flash-lite-image，支持 1K。
- nano-banana-pro：$0.18/次，即 gemini-3-pro-image-preview，支持 1K、2K、4K。

回答风格要求：
- 回答 RightCodes 生图接口问题时，明确说明当前是异步提交加任务轮询，不要再推荐旧域名或同步等待方式。
- 允许输出保留缩进的 JSON 示例；这是 QQ 纯文本，不要包 Markdown 代码块，不要加 ```。
- 如用户问“body 里写什么”，直接给可复制 JSON。"""


_RIGHTCODES_DRAW_CATALOG_KEYWORDS = (
    "rightcodes",
    "right code",
    "right.codes",
    "docs.right.codes",
    "gpt-image-2",
    "gpt-image-2-vip",
    "nano-banana",
    "nano banana",
    "画图接口",
    "生图接口",
    "图片生成",
    "图像生成",
    "images/generations",
    "generatecontent",
    "v1/tasks",
    "1024x1024",
    "2048x2048",
    "4096x4096",
)


def should_inject_rightcodes_draw_catalog(query: str) -> bool:
    normalized = normalize_catalog_query(query)
    if not normalized:
        return False
    if any(keyword in normalized for keyword in _RIGHTCODES_DRAW_CATALOG_KEYWORDS):
        return True
    if "size" in normalized and any(term in normalized for term in ("body", "json", "prompt", "model")):
        return True
    if re.search(r"\b(?:1k|2k|4k)\b", normalized) and any(
        term in normalized for term in ("生图", "画图", "图片", "图像", "draw")
    ):
        return True
    return False


def normalize_catalog_query(query: str) -> str:
    return re.sub(r"\s+", " ", str(query or "").strip().lower())


def format_rightcodes_draw_catalog_injection(query: str) -> str:
    return f"{RIGHTCODES_DRAW_CATALOG_TEXT}\n\n用户当前问题：{str(query or '').strip()}"
