from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PluginSpec:
    id: str
    name: str
    version: str = "1.0"
    aliases: tuple[str, ...] = ()
    menu_lines: tuple[str, ...] = ()
    menu_keys: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ("group", "private")
    requires_direct_at: bool = True
    ai_capabilities: tuple[str, ...] = ()
    visible: bool = True
    admin_only: bool = False


PLUGIN_SPECS: tuple[PluginSpec, ...] = (
    PluginSpec(
        id="group_assistant",
        name="群管助手",
        aliases=("群管", "群管理", "群功能", "QQ助手", "qq助手"),
        menu_lines=(
            "通知清理文件：统计超过一周的外层群文件并按大小禁言上传者",
        ),
        commands=(
            "通知清理文件",
        ),
        scopes=("group",),
        admin_only=True,
    ),
    PluginSpec(
        id="social_requests",
        name="好友邀请处理",
        aliases=("好友申请", "邀请入群", "自动同意", "社交事件"),
        menu_lines=(
            "自动处理好友申请和邀请入群；机器人入群后通知邀请者已加入群聊",
        ),
        commands=("好友申请", "邀请入群"),
        scopes=("group", "private"),
        visible=True,
        admin_only=True,
    ),
    PluginSpec(
        id="group_welcome",
        name="入群欢迎",
        aliases=("欢迎", "新人欢迎", "社交事件"),
        menu_lines=(
            "新成员入群时发送欢迎消息；机器人自身入群时发送自我介绍",
        ),
        commands=("入群欢迎",),
        scopes=("group",),
        requires_direct_at=False,
    ),
    PluginSpec(
        id="reread",
        name="复读",
        aliases=("随机复读",),
        menu_lines=(
            "群里连续出现相同文字消息时概率复读；连续次数越多概率越高，复读后短时间内不重复同一内容",
        ),
        commands=("复读",),
        scopes=("group",),
        requires_direct_at=False,
    ),
    PluginSpec(
        id="lolicon",
        name="Lolicon美图",
        aliases=("Lolicon", "美图", "色图"),
        commands=("来点色图", "美图", "开群色图", "关群色图"),
        scopes=("group", "private"),
    ),
    PluginSpec(
        id="ai",
        name="AI测试",
        commands=("ai",),
        scopes=("private",),
        ai_capabilities=("chat",),
        visible=False,
    ),
    PluginSpec(
        id="kun",
        name="养鲲",
        aliases=("鲲",),
        commands=(
            "摸鲲",
            "养鲲",
            "抓鲲",
            "属性",
            "签到",
            "背包",
            "商城",
            "boss",
            "挑战",
        ),
        menu_lines=(
            "摸鲲 / 养鲲 / 抓鲲 / 捕鲲：私聊创建或获取鲲",
            "属性：私聊查看自己的鲲",
            "查看 @对方：查看对方的鲲",
            "洗练攻击10 / 洗练防御10 / 洗练血量10：消耗洗练卡强化属性",
            "签到：领取萌泪币",
            "背包 / 道具：私聊查看道具",
            "商城：私聊查看商品",
            "购买改名卡1 / 出售改名卡1：买卖道具",
            "命名新名字：私聊改名",
            "boss / 查看boss：私聊查看 Boss",
            "挑战：私聊挑战 Boss",
            "等级排行 / 财富排行：查看排行榜",
            "进击 @对方：攻击对方",
            "赠送 @对方 100：赠送萌泪币",
            "开新赛季提示 / 关新赛季提示：私聊切换提示",
        ),
    ),
    PluginSpec(
        id="sakura",
        name="落樱之都",
        aliases=("樱花", "落樱"),
        commands=("注册樱花勇者", "个人信息", "加经验", "加力量", "恢复"),
        scopes=("group", "private"),
    ),
    PluginSpec(
        id="arc",
        name="Arc",
        aliases=("Arc查询", "Arc狼人杀", "Arc吃鸡", "arcaea"),
        menu_lines=(
            "arctj10.5：按 PTT 推荐谱面",
            "zm：开始字符猜歌",
            "开*：开一个非空格字符",
            "10曲名：猜第 10 题",
            "arcqh：开始/继续曲绘猜歌",
            "jx：公布当前 Arc 猜歌答案",
            "archd：查看当前活动梯子",
            "xz / arcxz：查询并下载最新 c 版安装包",
        ),
        menu_keys=("arc", "arcaea"),
        commands=("arctj", "zm", "arczm", "arcqh", "jx", "archd", "xz", "arcxz"),
        scopes=("group", "private"),
        ai_capabilities=("explain",),
    ),
    PluginSpec(
        id="factorio",
        name="Factorio",
        aliases=("异星工厂", "太空时代", "Space Age", "spaceage"),
        menu_lines=(
            "Factorio下载链接 / 异星下载链接：获取 Space Age Windows 安装包下载链接",
        ),
        menu_keys=("factorio", "spaceage"),
        commands=("Factorio下载链接", "异星下载链接", "太空时代下载链接"),
        scopes=("group", "private"),
    ),
    PluginSpec(
        id="shapez",
        name="异形工厂",
        aliases=("shapez",),
        commands=("i", "view", "chart", "chart1", "chart2", "path", "path1", "path2", "p", "puzzle"),
        scopes=("group", "private"),
        ai_capabilities=("render",),
    ),
)


def validate_plugin_specs(specs: tuple[PluginSpec, ...] = PLUGIN_SPECS) -> None:
    ids = [spec.id for spec in specs]
    if len(ids) != len(set(ids)):
        raise ValueError("插件 id 不能重复")


def list_visible_plugin_specs() -> list[PluginSpec]:
    validate_plugin_specs()
    return sorted(
        (spec for spec in PLUGIN_SPECS if spec.visible),
        key=lambda spec: spec.name.casefold(),
    )


def get_plugin_spec_by_id(plugin_id: str) -> PluginSpec | None:
    normalized = plugin_id.strip().lower()
    for spec in PLUGIN_SPECS:
        if spec.id == normalized:
            return spec
    return None


def get_plugin_spec_by_menu_key(key: str) -> PluginSpec | None:
    normalized = key.strip().lower()
    if not normalized or normalized.isdigit():
        return None

    for spec in list_visible_plugin_specs():
        names = (
            spec.name,
            spec.id,
            *spec.aliases,
            *spec.menu_keys,
        )
        normalized_names = [name.lower() for name in names]
        if normalized in normalized_names:
            return spec
        if any(normalized in name or name in normalized for name in normalized_names):
            return spec
    return None
