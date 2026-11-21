from __future__ import annotations

import re


DRAW_COMMAND_FACTS: tuple[str, ...] = (
    "标准生图指令：文生图 提示词；图生图 提示词（同条附图或引用图片）；头像生图 [@某人] 提示词。",
    "动图版：把“生图”换成“生动图”，即文生动图 / 图生动图 / 头像生动图。",
    "无头像目标时使用发送者头像；真实艾特须紧跟头像生图。",
    "查询模型与价格：生图模型 / 生图价格；查询积分：查看积分；排行榜：积分排行。",
    "切换自己保存的生图模型：切换生图模型 <模型名>，只接受 CPA 当前注册的模型名；菜单不展示这条指令。",
    "出图尺寸：默认 4K 方图；档位紧跟指令写：文生图4k 一只白猫（1k / 2k / 4k）；画幅把“图”写成“竖图/横图”：文生竖图2k 一只白猫；动图：文生动图 提示词。档位后面要空一格再写提示词。",
)


DRAW_CATALOG_TEXT = """生图接口知识库：

当前 bot 生图功能：
- 生图模型按 CPA 当前注册的图片模型自动选择，原模型不可用时自动改用其他可用模型；普通生图每次一张，价格人民币 0.06 元（60 积分），带 flare / sunburst 的变体模型 0.15 元（150 积分），豆豆眼四张组也只扣一次。
""" + "\n".join(f"- {line}" for line in DRAW_COMMAND_FACTS) + """
- 动图版在请求里带 output_format: gif；动图保留原始 GIF 字节并按动图发送，上游可能回退成静态 PNG，回退时成品消息会注明。实测动图为 9 帧、每帧 200ms、约 2048 像素，尺寸和帧数由上游决定。豆豆眼预设是静态四张，不支持动图。
- 不再支持“生成”“棉花糖生图”“棉花生图”前缀。群里不 @ 的“生成一只白猫”不会触发生图；私聊或 @机器人 时说“生成一只白猫”“画个动图”由 AI 判定后调用同一条生图链路。
- 旧用户保存的模型若已不在 CPA 注册列表里，会自动改用当前可用的生图模型，积分余额不变。
- 群消息继续累计积分；从首次请求开始扣费，全部生成失败或超时原额退款；部分成功交付全部已有成品，不自动重生。
- 普通标准指令原样提交提示词，不调用聊天模型改写。图生图使用单张原图，当前附件优先于引用图片；原图获取失败不扣积分。自然语言入口仍保留条件改写与最多3张参考图。
- 生成豆豆眼头像：固定将发送者本人的头像转为豆豆眼，使用完整韩文v1、中文v3各生成两张，四个独立请求并行，完成后全部发送。原有生图入口及自然语言改图请求含“豆豆眼”并指定头像或图片时，也完全换用该预设，不改写、不拼接。自然语言仍须识别为实际绘图意图，来源不明确先询问。
- 所有开工通知都会明确提示词来源：用户话语（无预设），或豆豆眼预设（完整固定原文）。
- 私聊或明确唤醒后的自然语言请求（如“画只猫”“帮我把我的头像改成水彩”“画个动图”）会先解析为文生图/图生图/动图；完整请求直接开工并回显提示词和来源，歧义先询问，不扣积分。
- 普通聊天回复只能介绍用法或引导明确指令，不得声称已开始绘图、已扣分或已交付；实际执行由生图插件负责。
- 成品统一先保存再发送；保存失败仍尝试交付，并提示未保存。全部图片均未保存且发送失败时退积分，不重复生成。

仅在用户询问接口时说明以下技术信息：
- bot 使用本机 CPA 的 OpenAI Images 接口，API 根地址为 http://127.0.0.1:8317/v1。
- 鉴权使用 CPA 客户端 API Key；HC/RC 渠道选择与优先级由 CPA 配置管理，各渠道的图片模型记录需要 image: true 才能使用 Images 接口；bot 从 /v1/models 返回里挑选图片模型。
- 文生图：POST /images/generations，JSON body 示例：
{
  "model": "gpt-image-2.6",
  "prompt": "一只白猫",
  "n": 1,
  "size": "4096x4096",
  "response_format": "b64_json",
  "output_format": "png"
}
- 参考图：POST /images/edits，multipart/form-data 单张使用 image 文件字段，多张使用 image[] 文件字段，其余文本参数与文生图相同。
- 同一次 CPA 请求等待最终图片，不使用任务轮询。
- 从返回 data[].b64_json 或 data[].url 取得图片；size 决定成品尺寸，实测 4096x4096、4096x2304、2304x4096、2048x2048 都按原尺寸返回，auto 会得到 1024x1536 竖图。档位对应尺寸：1k 1024x1024（横 1536x1024 / 竖 1024x1536），2k 2048x2048（横 2048x1152 / 竖 1152x2048），4k 4096x4096（横 4096x2304 / 竖 2304x4096）。请求体把 output_format 设为 gif 即可要动图，返回可能是 GIF 也可能是静态 PNG。

回答风格要求：
- 模型、价格和用法问题只回答当前 bot 的功能；说明价格时使用人民币“元”。
- 接口 body 问题直接给可复制 JSON，保留缩进，不使用 Markdown 代码围栏。"""


_DRAW_CATALOG_KEYWORDS = (
    "生图尺寸",
    "竖图",
    "横图",
    "nano-banana",
    "nano banana",
    "画图接口",
    "画", "生图", "绘图", "头像", "改图",
    "生图接口",
    "图片生成",
    "图像生成",
    "images/generations",
    "images/edits",
    "generatecontent",
    "v1/tasks",
    "1024x1024",
    "2048x2048",
    "4096x4096",
    "4096x2304",
    "2304x4096",
)


def should_inject_draw_catalog(query: str) -> bool:
    normalized = normalize_catalog_query(query)
    if not normalized:
        return False
    if any(keyword in normalized for keyword in _DRAW_CATALOG_KEYWORDS):
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


def format_draw_catalog_injection(query: str) -> str:
    return f"{DRAW_CATALOG_TEXT}\n\n用户当前问题：{str(query or '').strip()}"
