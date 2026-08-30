from __future__ import annotations


YUNQI_QQ = "1443944862"
KNOWN_SISTER_BOT_QQ_IDS = frozenset(
    {
        YUNQI_QQ,
        "2629227874",  # 夜凛
        "3056830689",  # 星遥
        "3109326090",  # 月澄
    }
)
YUNQI_IDENTITY_FACT = (
    "身份事实：你是云栖（QQ 1443944862），四姐妹中的大姐。"
    "夜凛（QQ 2629227874）是二妹，星遥（QQ 3056830689）是三妹，月澄（QQ 3109326090）是四妹。"
    "其他姐妹只是静态关系事实，不是当前 AstrBot worker；你只能代表云栖回答，不能冒充或替她们发言。"
)


def is_known_bot_sender_id(sender_id: object) -> bool:
    return str(sender_id or "").strip() in KNOWN_SISTER_BOT_QQ_IDS
