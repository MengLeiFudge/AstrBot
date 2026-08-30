import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MemeManagerCommand:
    action: str
    argument: str = ""
    primary_text: str = ""
    admin_only: bool = False


MEME_MANAGER_COMMAND_ALIASES: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    ("start_webui", ("开启管理后台", "打开管理后台", "启动管理后台"), True),
    ("stop_webui", ("关闭管理后台", "停止管理后台"), True),
    ("list_emotions", ("查看图库", "图库", "查看表情"), False),
    ("upload_meme", ("添加表情", "上传表情"), True),
    ("restore_default_memes", ("恢复默认表情包", "恢复默认表情"), True),
    ("clear_category", ("清空指定类型", "清空类型"), True),
    ("clear_all", ("清空全部", "清空全部表情"), True),
    ("delete_category", ("删除类型本身", "删除类型"), True),
    ("sync_status", ("同步状态",), False),
    ("sync_to_remote", ("同步到云端",), True),
    ("library_stats", ("图库统计", "表情统计"), False),
    ("sync_from_remote", ("从云端同步",), True),
    ("overwrite_to_remote", ("覆盖到云端",), True),
    ("overwrite_from_remote", ("从云端覆盖",), True),
)

MEME_MANAGER_PRIMARY_COMMANDS = tuple(
    aliases[0] for _, aliases, _ in MEME_MANAGER_COMMAND_ALIASES
)
MEME_MANAGER_COMMAND_PATTERN = r"^表情管理(?:\s+|\s*)(\S[\s\S]*)?$"


def parse_meme_manager_command(text: str) -> MemeManagerCommand | None:
    match = re.match(MEME_MANAGER_COMMAND_PATTERN, str(text or "").strip())
    if match is None:
        return None
    rest = re.sub(r"\s+", " ", str(match.group(1) or "").strip())
    if not rest:
        return MemeManagerCommand(
            action="list_emotions",
            primary_text="查看图库",
        )
    compact_rest = re.sub(r"\s+", "", rest)
    for action, aliases, admin_only in MEME_MANAGER_COMMAND_ALIASES:
        primary = aliases[0]
        for alias in aliases:
            compact_alias = re.sub(r"\s+", "", alias)
            if compact_rest == compact_alias:
                return MemeManagerCommand(action, "", primary, admin_only)
            if compact_rest.startswith(compact_alias):
                argument = rest[len(alias) :].strip()
                return MemeManagerCommand(action, argument, primary, admin_only)
    return None


def looks_like_meme_manager_command(text: str) -> bool:
    return parse_meme_manager_command(text) is not None
