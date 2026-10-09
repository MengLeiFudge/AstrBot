from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MenuSection:
    name: str
    aliases: tuple[str, ...] = ()
    status: str = "已移植"
    lines: tuple[str, ...] = ()


MENU_SECTIONS: tuple[MenuSection, ...] = (
    MenuSection(
        name="群务管理",
        aliases=("群务", "群管理", "群管", "欢迎", "好友邀请"),
        lines=(
            "通知清理文件：统计超期外层群文件并按大小禁言上传者",
            "好友申请 / 邀请入群：按配置自动同意；自身入群后私聊通知邀请者",
            "入群欢迎：云栖欢迎新成员；已知姐妹机器人账号不会触发欢迎",
        ),
    ),
    MenuSection(
        name="棉花糖互动",
        aliases=("互动", "聊天", "AI", "生图", "美图"),
        status="混合功能",
        lines=(
            "AI对话：显式呼叫后按群激活 3 分钟，由主模型挑选后续消息并可主动静默",
            "生图：文生图 提示词 / 图生图 提示词（附图或引用）；头像生图 [@某人] 提示词；40积分/次；查看积分 / 积分排行",
            "豆豆眼：生成豆豆眼头像（本人头像）；图生图 豆豆眼（附图或引用）；开工会标明无预设或豆豆眼预设",
            "Sub2API用量：用量 按账号展示额度和各自当前7d周期用户榜，底部展示全账号消费，并附 CodexRadar 智力效率缓存图",
            "Lolicon美图：来点美图 / 色图 / 混合；作者可开关 R18 和图片显示",
            "复读：群里连续出现相同纯文本时概率复读并冷却",
        ),
    ),
    MenuSection(
        name="养鲲",
        aliases=("鲲",),
        lines=(
            "摸鲲 / 养鲲 / 抓鲲 / 捕鲲：私聊创建或获取鲲",
            "属性 / 背包 / 商城 / 签到 / 挑战 / 排行 / 进击 / 赠送：使用 AstrBot 迁移后的存档与状态机",
        ),
    ),
    MenuSection(
        name="落樱之都",
        aliases=("樱花", "落樱"),
        status="基础玩法已移植",
        lines=("落樱之都 / 注册 / 改名 / 个人信息 / 加经验 / 嘤 / 加点 / 恢复：使用 AstrBot 迁移后的存档",),
    ),
    MenuSection(
        name="Arcaea",
        aliases=("Arc", "Arc查询", "Arc狼人杀", "Arc吃鸡", "arcaea"),
        status="已移植",
        lines=(
            "arctj10.5：按 PTT 推荐谱面，使用本地曲库和定数缓存",
            "archd / arctz：查看当前活动梯子",
            "zm / arczm：字母猜歌；qh / arcqh：曲绘猜歌；jx / arcjx：揭晓",
            "xz / arcxz：作者限定，查询并下载最新 c 版安装包",
            "后台同步别名、定数缓存、猜歌过期会话和每日活动提醒",
        ),
    ),
    MenuSection(
        name="JM漫画",
        aliases=("JM", "漫画", "PDF"),
        lines=("JM作品ID：好友可在群聊或私聊请求；状态不引用，私聊先发信息、总切片数和密码，再发全部切片",),
    ),
    MenuSection(
        name="Factorio",
        aliases=("异星工厂", "太空时代", "Space Age", "spaceage"),
        lines=("Factorio下载链接 / 异星下载链接：获取 Space Age Windows 安装包下载链接",),
    ),
    MenuSection(
        name="异形工厂",
        aliases=("shapez", "Shapez"),
        lines=("i/view/chart/path：渲染 shapez 短代码图片；p/puzzle 在线谜题仍提示未配置 token",),
    ),
)


def find_menu_section(key: str) -> MenuSection | None:
    normalized = key.strip().casefold()
    if not normalized:
        return None
    for section in MENU_SECTIONS:
        names = (section.name, *section.aliases)
        if any(normalized == item.casefold() for item in names):
            return section
    return None
