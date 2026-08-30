from __future__ import annotations


async def is_onebot_friend(api, user_id: int) -> bool:
    """Return whether the current OneBot account lists the user as a friend."""
    result = await api.call_api("get_friend_list", no_cache=False)
    records = result
    if isinstance(result, dict):
        records = result.get("data", result.get("friends", []))
    if not isinstance(records, list):
        return False
    target = str(int(user_id))
    return any(
        isinstance(record, dict) and str(record.get("user_id") or "") == target
        for record in records
    )
