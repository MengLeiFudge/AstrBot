from __future__ import annotations


class OneBotCallApiAdapter:
    def __init__(self, bot) -> None:
        self._bot = bot

    async def call_api(self, action: str, **kwargs):
        return await self._bot.call_action(action, **kwargs)
