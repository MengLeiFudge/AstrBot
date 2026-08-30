from __future__ import annotations

YUNQI_BOT_QQ = "1443944862"
KNOWN_SISTER_BOT_QQ_IDS = frozenset(
    {YUNQI_BOT_QQ, "2629227874", "3056830689", "3109326090"}
)
GROUP_MEMBER_WELCOME_EXPRESSIONS = (
    "群地位-1",
    "群地位--",
    "群地位=群地位-1",
    "群地位+=-1",
    "群地位-=1",
    "群地位=群地位+(-1)",
    "群地位=群地位+i²",
    "群地位+=i²",
    "群地位-=-i²",
    "群地位(t+1)=群地位(t)-1",
    "群地位=群地位+e^(iπ)",
    "群地位+=e^(iπ)",
    "群地位-=(-e^(iπ))",
    "群地位=群地位+cos(π)",
    "群地位+=cos(π)",
)


def format_self_join_private_notice(group_name: str | None, group_id: str | int) -> str:
    normalized_name = str(group_name or "").strip() or "未知群聊"
    normalized_group_id = str(group_id or "").strip() or "未知群号"
    return f"棉花糖已经加入群聊{normalized_name}（{normalized_group_id}）了喵！"


def should_send_member_welcome(
    *,
    user_id: str,
    self_id: str,
    known_bot_ids: frozenset[str] = KNOWN_SISTER_BOT_QQ_IDS,
) -> bool:
    if not user_id or user_id == self_id:
        return False
    if user_id in known_bot_ids:
        return False
    return self_id == YUNQI_BOT_QQ


def format_group_member_welcome(self_id: str, expression: str) -> str:
    normalized_self_id = str(self_id or "").strip()
    normalized_expression = str(expression or "").strip() or GROUP_MEMBER_WELCOME_EXPRESSIONS[0]
    if normalized_self_id == YUNQI_BOT_QQ:
        return f" 欢迎大佬喵！{normalized_expression}"
    return f" 欢迎大佬，{normalized_expression}"
