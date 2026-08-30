from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import re
from typing import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


MEDIAWIKI_API_URL = "https://arcaea.fandom.com/api.php"

EVENT_BLOCK_RE = re.compile(
    r"(?:\}\})?\{\{#ifeq:\{\{\{1\|(?P<title>[^}]+)\}\}\}\|(?P=title)\|(?P<body>.*?)(?=(?:\}\}\{\{#ifeq:)|(?:\n\[\[Category:)|\Z)",
    re.S,
)
PLAYABLE_RANGE_RE = re.compile(r"(\d{4}-\d{2}-\d{2}) to (\d{4}-\d{2}-\d{2})")
LIST_ITEM_RE = re.compile(r"<li>(.*?)</li>", re.S)
REWARD_LINE_RE = re.compile(r"^\|\s*[^|]*\|\s*[^|]*\|\s*(.+)$")
WIKI_LINK_RE = re.compile(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]")
TAG_RE = re.compile(r"<[^>]+>")
RESOURCE_RE = re.compile(r"(?i)^(?P<count>\d+)\s+(?P<name>Fragments?|Ether Drop|Memory Archive Ticket|World Extend Ticket|Core.*)$")


@dataclass(frozen=True, slots=True)
class ArcWorldEvent:
    title: str
    started_at: datetime
    ends_at: datetime
    key_rewards: tuple[str, ...]


def _fetch_wiki_page_wikitext(title: str) -> str:
    query = urlencode(
        {
            "action": "parse",
            "page": title,
            "prop": "wikitext",
            "formatversion": "2",
            "format": "json",
        }
    )
    request = Request(
        f"{MEDIAWIKI_API_URL}?{query}",
        headers={"User-Agent": "qqbot/0.1"},
    )
    with urlopen(request, timeout=20) as response:
        payload = response.read().decode("utf-8")
    match = re.search(r'"wikitext":"(.*)"\}\}$', payload)
    if match is not None:
        # parse 接口内容是 JSON 字符串，直接交给正则吃不稳；这里保留一个兜底。
        pass
    import json

    return json.loads(payload)["parse"]["wikitext"]


def _fetch_latest_arc_version() -> str:
    query = urlencode({"format": "json"})
    request = Request(
        "https://webapi.lowiro.com/webapi/serve/static/bin/arcaea/apk",
        headers={"User-Agent": "qqbot/0.1"},
    )
    with urlopen(request, timeout=20) as response:
        import json

        payload = json.loads(response.read().decode("utf-8"))
    return str(payload["value"]["version"])


class ArcEventService:
    def __init__(
        self,
        wiki_page_fetcher: Callable[[str], str] | None = None,
        version_fetcher: Callable[[], str] | None = None,
        timezone: str = "Asia/Shanghai",
    ) -> None:
        self.wiki_page_fetcher = wiki_page_fetcher or _fetch_wiki_page_wikitext
        self.version_fetcher = version_fetcher or _fetch_latest_arc_version
        self.zone = self._resolve_zone(timezone)

    def fetch_active_events(self, now: datetime | None = None) -> list[ArcWorldEvent]:
        current = self._coerce_now(now)
        wikitext = self.wiki_page_fetcher("World Mode Data Past Events")
        if not wikitext:
            return []
        current_version = self.version_fetcher()
        events: list[ArcWorldEvent] = []
        for match in EVENT_BLOCK_RE.finditer(wikitext):
            raw_title = match.group("title")
            body = match.group("body")
            active_range = self._pick_active_range(body, current)
            if active_range is None:
                continue
            rewards = self._extract_reward_lines(body)
            enriched_rewards = tuple(
                self._describe_reward(reward, current_version) for reward in rewards[:4]
            )
            events.append(
                ArcWorldEvent(
                    title=self._normalize_event_title(raw_title),
                    started_at=active_range[0],
                    ends_at=active_range[1],
                    key_rewards=enriched_rewards,
                )
            )
        return sorted(events, key=lambda event: event.ends_at)

    def render_event_messages(
        self,
        events: list[ArcWorldEvent],
        now: datetime | None = None,
    ) -> list[str]:
        current = self._coerce_now(now)
        if not events:
            return ["当前没有活动梯子。"]
        messages = []
        for event in events:
            rewards = "、".join(event.key_rewards) if event.key_rewards else "暂无关键奖励信息"
            messages.append(
                "\n".join(
                    [
                        f"限时：{event.title}",
                        f"剩余时间：{self._format_remaining(event.ends_at - current)}",
                        f"关键奖励：{rewards}",
                    ]
                )
            )
        return messages

    def _pick_active_range(
        self,
        body: str,
        now: datetime,
    ) -> tuple[datetime, datetime] | None:
        ranges = []
        for start_text, end_text in PLAYABLE_RANGE_RE.findall(body):
            start_dt = datetime.fromisoformat(start_text).replace(tzinfo=timezone.utc)
            end_dt = datetime.fromisoformat(end_text).replace(tzinfo=timezone.utc) + timedelta(
                hours=15
            )
            ranges.append((start_dt.astimezone(self.zone), end_dt.astimezone(self.zone)))
        for started_at, ends_at in sorted(ranges, key=lambda item: item[1], reverse=True):
            if started_at <= now <= ends_at:
                return started_at, ends_at
        return None

    def _extract_reward_lines(self, body: str) -> list[str]:
        total_rewards = [self._clean_markup(item) for item in LIST_ITEM_RE.findall(body)]
        if total_rewards:
            return [reward for reward in total_rewards if reward]

        item_rewards: list[str] = []
        resource_totals: dict[str, int] = {}
        for line in body.splitlines():
            match = REWARD_LINE_RE.match(line.strip())
            if match is None:
                continue
            reward = self._clean_markup(match.group(1))
            if not reward or reward == "-":
                continue
            resource_match = RESOURCE_RE.match(reward)
            if resource_match is not None:
                name = resource_match.group("name")
                resource_totals[name] = resource_totals.get(name, 0) + int(
                    resource_match.group("count")
                )
                continue
            if reward not in item_rewards:
                item_rewards.append(reward)
        for name, count in resource_totals.items():
            item_rewards.append(f"{name} x{count}")
        return item_rewards

    def _describe_reward(self, reward: str, current_version: str) -> str:
        if reward.startswith("Fragments") or reward.startswith("Ether Drop"):
            return reward
        if reward.endswith("Fragments"):
            return reward.replace(" Fragments", " Fragments")
        try:
            page = self._get_reward_page(reward)
        except Exception:
            return reward
        if "{{Song" in page:
            pack = self._match_first(page, r"\|Mobile Pack\s*=\s*(.+)")
            if pack:
                return f"{reward}（曲目 / {pack}）"
            return f"{reward}（曲目）"
        if "{{PartnerInfobox" in page:
            version_added = self._match_first(page, r"\|version_added\s*=\s*([0-9.]+)")
            partner_type = "新搭档" if version_added == self._normalize_version(current_version) else "复刻搭档"
            return f"{reward}（搭档 / {partner_type}）"
        return reward

    @lru_cache(maxsize=128)
    def _get_reward_page(self, title: str) -> str:
        return self.wiki_page_fetcher(title)

    def _coerce_now(self, now: datetime | None) -> datetime:
        if now is None:
            return datetime.now(self.zone)
        if now.tzinfo is None:
            return now.replace(tzinfo=self.zone)
        return now.astimezone(self.zone)

    def _normalize_event_title(self, raw_title: str) -> str:
        normalized = raw_title.replace("0-LE ", "").replace("0-WE ", "").strip()
        if " / " in normalized:
            normalized = normalized.split(" / ", 1)[0].strip()
        return normalized.removesuffix(" Event").strip()

    def _clean_markup(self, text: str) -> str:
        cleaned = text.replace("&times;", "x")
        cleaned = cleaned.replace("'''", "")
        cleaned = WIKI_LINK_RE.sub(r"\1", cleaned)
        cleaned = TAG_RE.sub("", cleaned)
        cleaned = cleaned.replace("&nbsp;", " ")
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = re.sub(r"\bx\s+(\d+)", r"x\1", cleaned)
        return cleaned.strip()

    def _format_remaining(self, delta: timedelta) -> str:
        total_seconds = max(0, int(delta.total_seconds()))
        days, remain = divmod(total_seconds, 86400)
        hours, remain = divmod(remain, 3600)
        minutes, _seconds = divmod(remain, 60)
        parts = []
        if days:
            parts.append(f"{days}天")
        if hours or days:
            parts.append(f"{hours}小时")
        parts.append(f"{minutes}分钟")
        return " ".join(parts)

    def _match_first(self, text: str, pattern: str) -> str | None:
        match = re.search(pattern, text)
        if match is None:
            return None
        return self._clean_markup(match.group(1))

    def _normalize_version(self, version: str) -> str:
        return re.sub(r"[^0-9.].*$", "", version)

    def _resolve_zone(self, timezone_name: str):
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            if timezone_name == "Asia/Shanghai":
                return timezone(timedelta(hours=8), name=timezone_name)
            if timezone_name == "UTC":
                return timezone.utc
            return datetime.now().astimezone().tzinfo or timezone.utc
