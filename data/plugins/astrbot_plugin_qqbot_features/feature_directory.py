from __future__ import annotations

import re
from dataclasses import dataclass

from .menu_catalog import MENU_SECTIONS, MenuSection
from .draw_catalog import DRAW_COMMAND_FACTS


FEATURE_INDEX_TITLE = "【当前 bot 的功能目录】"
FEATURE_DETAIL_TITLE = "【命中的功能详情】"
FEATURE_RULES_TITLE = "【目录使用要求】"
FEATURE_RULES: tuple[str, ...] = (
    "用户询问功能、用法、价格或怎么操作时，按这份目录回答，并给出可以直接发送的指令原文。",
    "目录只列用户可以直接发送的指令；理解图片、视频、引用消息和长文是对话能力，不在这份清单里，不要因为没列出来就否认。",
    "目录里没有的能力不要编造指令名，可以引导用户发送“菜单”查看分类。",
    "目录里列出的都是本 bot 已启用的功能；用户问能不能用、怎么用时照实说明，不要以“没有这个功能”为由拒接。",
)
FEATURE_INDEX_MAX_CHARS = 1200
FEATURE_DETAIL_MAX_ENTRIES = 3
FEATURE_DETAIL_MAX_CHARS = 1800
FEATURE_ALIAS_MIN_CHARS = 2


@dataclass(frozen=True, slots=True)
class FeatureEntry:
    """One user-facing capability with its exact commands and limits."""

    name: str
    hint: str
    aliases: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    priority: int = 0


COMMAND_FEATURE_ENTRIES: tuple[FeatureEntry, ...] = (
    FeatureEntry(
        name="菜单",
        hint="菜单 / 帮助 / 指令；菜单<分类名>",
        aliases=("菜单", "帮助", "指令", "分类"),
        commands=(
            "菜单 / 帮助 / 指令：发送功能分类总览图片。",
            "菜单<分类名>：发送该分类的详情图片，例如 菜单棉花糖互动、菜单Arcaea。",
        ),
        priority=10,
    ),
    FeatureEntry(
        name="生图",
        hint="文生图 / 图生图 / 头像生图 / 生动图；也可以直接说“画只猫”",
        aliases=("文生图", "图生图", "头像生图", "生动图", "画图", "画个", "画只", "来一张", "生成图片"),
        commands=DRAW_COMMAND_FACTS,
        notes=(
            "群里不 @ 机器人的自然语言画图不触发；私聊或 @ 机器人时可以直接说“画只猫”。",
            "不再支持“生成”“棉花糖生图”“棉花生图”前缀。",
            "普通生图一张 60 积分（0.06 元）起，flare / sunburst 变体 150 积分（0.15 元）；全部失败会退回本次扣分。",
        ),
        priority=10,
    ),
    FeatureEntry(
        name="生图模型",
        hint="生图模型 / 生图价格；切换生图模型 <模型名>",
        aliases=(
            "生图模型",
            "生图价格",
            "切换生图模型",
            "切换模型",
            "换模型",
            "画图模型",
            "gpt-image",
            "nano-banana",
        ),
        commands=(
            "生图模型 / 生图价格：查看当前模型、CPA 当前可用的生图模型列表、人民币价格与积分消耗。",
            "切换生图模型 <模型名>：切换自己保存的生图模型，例如 切换生图模型 gpt-image-2.6。",
            "生图模型 <模型名>：与上面等价的旧写法。",
        ),
        notes=(
            "切换只接受 CPA 当前注册的模型名；名字不在列表时回复可用模型，不扣积分也不改设置。",
            "生图指令里不能临时指定模型，例如“文生图 gpt-image-2.6 一只猫”会被拒绝。",
            "默认按 CPA 注册列表自动挑选（版本从新到旧、基础名优先于变体）；保存的模型不可用时下次生图自动改用可用模型。",
            "切换指令不在菜单里展示，但可以直接发送。",
        ),
        priority=10,
    ),
    FeatureEntry(
        name="生图积分",
        hint="查看积分 / balance / points；积分排行",
        aliases=("查看积分", "积分排行", "积分", "balance", "points"),
        commands=(
            "查看积分 / balance / points：查询自己的生图积分、当前模型和该模型单次消耗。",
            "积分排行 / 积分排行榜：跨群累计积分最高的前 10 名。",
        ),
        notes=("群消息会持续累计积分；每次生图按模型价格扣分。",),
        priority=10,
    ),
    FeatureEntry(
        name="豆豆眼头像",
        hint="生成豆豆眼头像；头像生图 豆豆眼",
        aliases=("豆豆眼",),
        commands=(
            "生成豆豆眼头像：把发送者本人头像转成豆豆眼，韩文 v1、中文 v3 各两张，四张并行后全部发送。",
            "头像生图 豆豆眼 / 图生图 豆豆眼：在原有入口上套用同一预设。",
        ),
        notes=(
            "固定静态四张，不支持动图；四张共用一次扣分，部分失败仍交付成功的成品。",
            "自然语言如“帮我把头像改成豆豆眼”在识别为改图请求后走同一流程。",
        ),
        priority=10,
    ),
    FeatureEntry(
        name="用量",
        hint="用量；额度与 CodexRadar 榜单",
        aliases=("用量", "额度", "codexradar", "sub2api"),
        commands=(
            "用量：发送两张图片，第一张按账号展示 5h / 7d 额度卡、该账号 7d 消费榜和全账号消费榜，第二张是 CodexRadar 智力效率榜。",
        ),
        notes=("群里只读缓存，不实时请求上游；首次缓存还没成功时可能只有用量图。",),
        priority=10,
    ),
    FeatureEntry(
        name="表情管理",
        hint="表情管理；添加表情 / 清空指定类型",
        aliases=("表情管理", "添加表情", "表情"),
        commands=(
            "表情管理：查看当前图库分类。",
            "表情管理 添加表情 [类别]：进入 30 秒图片上传等待状态。",
            "表情管理 清空指定类型 [类别] / 删除类型本身 [类别] / 清空全部：执行前需同一发送者二次确认。",
            "表情管理 开启管理后台：私聊启动本地图库 WebUI。",
        ),
        notes=(
            "除查看分类外都限主人或机器人自身。",
            "自动收藏在后台筛选当前消息附件并按图片内容去重，图库达到 1000 张后停止自动收集。",
        ),
        priority=10,
    ),
    FeatureEntry(
        name="JM漫画",
        hint="jm<作品ID>；好友限定，成品私聊发密码压缩包",
        aliases=("jm漫画", "jm", "漫画", "pdf", "禁漫"),
        commands=(
            "jm<作品ID>：例如 jm422389。好友限定，群聊或私聊发送都可以。",
            "下载完成后成品通过私聊以密码压缩包发送，先收到标题、切片数和密码；状态消息不带引用。",
        ),
        notes=("这是本 bot 已启用的功能，用户问能不能下载或怎么用时照实说明用法。",),
        priority=10,
    ),
)


def _section_hint(section: MenuSection) -> str:
    """Build a short index hint from the leading command names of one menu section."""

    names: list[str] = []
    for line in section.lines:
        name = line.split("：", 1)[0].strip()
        if name and name not in names:
            names.append(name)
    if names:
        return " / ".join(names[:3])
    return " / ".join(section.aliases[:3]) or section.name


def _section_feature_entries() -> tuple[FeatureEntry, ...]:
    entries: list[FeatureEntry] = []
    covered_names = {entry.name for entry in COMMAND_FEATURE_ENTRIES}
    for section in MENU_SECTIONS:
        if section.name in covered_names:
            continue
        hint = _section_hint(section)
        entries.append(
            FeatureEntry(
                name=section.name,
                hint=hint,
                aliases=(section.name, *section.aliases),
                commands=section.lines,
                notes=(f"发送“菜单{section.name}”可查看该分类的详情图片。",),
            )
        )
    return tuple(entries)


FEATURE_ENTRIES: tuple[FeatureEntry, ...] = COMMAND_FEATURE_ENTRIES + _section_feature_entries()


def normalize_feature_query(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").strip().casefold())


def match_features(query: str, *, limit: int = FEATURE_DETAIL_MAX_ENTRIES) -> tuple[FeatureEntry, ...]:
    """Return the features whose aliases appear in the query, most specific first."""

    normalized = normalize_feature_query(query)
    if not normalized:
        return ()
    scored: list[tuple[int, int, str, FeatureEntry]] = []
    for entry in FEATURE_ENTRIES:
        matched_alias = ""
        for alias in entry.aliases:
            alias_key = normalize_feature_query(alias)
            if len(alias_key) < FEATURE_ALIAS_MIN_CHARS:
                continue
            if alias_key in normalized and len(alias_key) > len(matched_alias):
                matched_alias = alias_key
        if matched_alias:
            scored.append((len(matched_alias), entry.priority, matched_alias, entry))
    # A shorter alias already covered by a longer one (生图 under 生图模型) would repeat the same answer.
    matched_aliases = [item[2] for item in scored]
    scored = [
        item
        for item in scored
        if not any(item[2] != other and item[2] in other for other in matched_aliases)
    ]
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return tuple(item[3] for item in scored[: max(1, limit)])


def format_feature_index() -> str:
    lines = [FEATURE_INDEX_TITLE]
    used = len(FEATURE_INDEX_TITLE)
    for entry in FEATURE_ENTRIES:
        line = f"- {entry.name}：{entry.hint}"
        if used + len(line) + 1 > FEATURE_INDEX_MAX_CHARS:
            continue
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


def format_feature_detail(entry: FeatureEntry) -> str:
    lines = [f"【{entry.name}】"]
    if entry.commands:
        lines.append("可用指令：")
        lines.extend(f"- {item}" for item in entry.commands)
    if entry.notes:
        lines.append("限制：")
        lines.extend(f"- {item}" for item in entry.notes)
    return "\n".join(lines)


def format_feature_details(entries: tuple[FeatureEntry, ...] | list[FeatureEntry]) -> str:
    blocks: list[str] = []
    used = 0
    for entry in entries:
        block = format_feature_detail(entry)
        if blocks and used + len(block) > FEATURE_DETAIL_MAX_CHARS:
            break
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)


def format_feature_directory_injection(query: str) -> str:
    parts = [format_feature_index()]
    details = format_feature_details(match_features(query))
    if details:
        parts.append(f"{FEATURE_DETAIL_TITLE}\n{details}")
    parts.append(FEATURE_RULES_TITLE + "\n" + "\n".join(f"- {rule}" for rule in FEATURE_RULES))
    return "\n\n".join(parts)
