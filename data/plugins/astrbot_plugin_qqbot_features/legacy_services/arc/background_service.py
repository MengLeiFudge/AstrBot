from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ...runtime_storage import RuntimeJsonStore
from ...runtime_storage import infer_runtime_root_from_path
from ...runtime_storage import read_json_file
from ..feature_catalog import FeatureDefinition
from ..settings_store import SettingsStore

logger = logging.getLogger(__name__)


async def call_split_text_api(
    bot: Any,
    api: str,
    *,
    message: Any,
    group_interval_sleep: Callable[[float], Any] | None = None,
    **data: object,
) -> None:
    text = str(message)
    chunks = [text[index : index + 1000] for index in range(0, len(text), 1000)] or [""]
    for chunk in chunks:
        if api == "send_group_msg" and group_interval_sleep is not None:
            await group_interval_sleep(0)
        await bot.call_api(api, **data, message=chunk)


@dataclass(slots=True)
class ArcBackgroundState:
    alias_last_synced_at: str = ""
    constants_last_synced_at: str = ""
    version_last_checked_at: str = ""
    version_last_seen: str = ""
    version_last_notified: str = ""
    version_last_downloaded: str = ""
    group_last_reminded_on: dict[str, str] = field(default_factory=dict)


class ArcBackgroundService:
    def __init__(
        self,
        state_path: Path,
        settings_store: SettingsStore,
        arc_feature: FeatureDefinition | None,
        author_qq: int,
        version_fetcher: Callable[[], str],
        event_service: Any,
        alias_service: Any,
        guess_service: Any | None = None,
        constant_service: Any | None = None,
        constant_song_loader: Callable[[], list[dict[str, str]]] | None = None,
        timezone_name: str = "Asia/Shanghai",
        sleep_func: Callable[[float], Any] | None = None,
    ) -> None:
        self.state_path = Path(state_path)
        self.settings_store = settings_store
        self.arc_feature = arc_feature
        self.author_qq = author_qq
        self.version_fetcher = version_fetcher
        self.event_service = event_service
        self.alias_service = alias_service
        self.guess_service = guess_service
        self.constant_service = constant_service
        self.constant_song_loader = constant_song_loader
        self.zone = self._resolve_zone(timezone_name)
        self.sleep_func = sleep_func or asyncio.sleep
        self.runtime_root = infer_runtime_root_from_path(self.state_path)
        self.legacy_state_path = self.runtime_root / "data" / "arc" / self.state_path.name
        self.store = RuntimeJsonStore(self.runtime_root)
        self.state = self._load()

    async def run_once(self, bot, now: datetime | None = None) -> None:
        current = self._coerce_now(now)
        if self.should_run_alias_sync(current):
            try:
                await asyncio.to_thread(self.alias_service.sync_alias_cache, now=current)
                self.state.alias_last_synced_at = current.isoformat()
                self._save()
            except Exception:
                logger.exception("Arc alias cache sync failed")
        if self.should_run_constants_sync(current):
            try:
                if self.constant_service is not None and self.constant_song_loader is not None:
                    songs = await asyncio.to_thread(self.constant_song_loader)
                    await asyncio.to_thread(
                        self.constant_service.sync_missing_constants,
                        songs=songs,
                        now=current,
                    )
                    self.state.constants_last_synced_at = current.isoformat()
                    self._save()
            except Exception:
                logger.exception("Arc constants sync failed")
        if self.should_run_version_check(current):
            await self.check_version_and_notify(bot, now=current)
        await self.expire_arc_guess_sessions(bot, now=current)
        await self.send_activity_reminders(bot, now=current)

    def should_run_alias_sync(self, now: datetime) -> bool:
        last_synced_at = self._parse_dt(self.state.alias_last_synced_at)
        if last_synced_at is None:
            return True
        return now - last_synced_at >= timedelta(hours=24)

    def should_run_constants_sync(self, now: datetime) -> bool:
        last_synced_at = self._parse_dt(self.state.constants_last_synced_at)
        if last_synced_at is None:
            return True
        return now - last_synced_at >= timedelta(hours=24)

    def should_run_version_check(self, now: datetime) -> bool:
        last_checked_at = self._parse_dt(self.state.version_last_checked_at)
        if last_checked_at is None:
            return True
        if now - last_checked_at >= timedelta(hours=24):
            return True
        for hour in (8, 20):
            scheduled_at = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            if last_checked_at < scheduled_at <= now:
                return True
        return False

    async def check_version_and_notify(self, bot, now: datetime | None = None) -> None:
        current = self._coerce_now(now)
        latest_version = await asyncio.to_thread(self.version_fetcher)
        self.state.version_last_checked_at = current.isoformat()
        self.state.version_last_seen = latest_version
        self._save()

    async def send_activity_reminders(self, bot, now: datetime | None = None) -> None:
        current = self._coerce_now(now)
        today = current.date().isoformat()
        pending_group_ids = [
            group_id
            for group_id in await self._list_arc_enabled_groups(bot)
            if self.state.group_last_reminded_on.get(str(group_id)) != today
        ]
        if not pending_group_ids:
            return
        try:
            events = self.event_service.fetch_active_events(now=current)
            messages = self.event_service.render_event_messages(events, now=current)
        except Exception:
            logger.exception("Arc activity reminder fetch/render failed")
            return
        if messages == ["当前没有活动梯子。"]:
            return
        for group_id in pending_group_ids:
            try:
                for message in messages:
                    await call_split_text_api(
                        bot,
                        "send_group_msg",
                        group_id=group_id,
                        message=message,
                        group_interval_sleep=self.sleep_func,
                    )
            except Exception:
                logger.exception("Arc activity reminder send failed: group_id=%s", group_id)
                continue
            self.state.group_last_reminded_on[str(group_id)] = today
            self._save()

    async def expire_arc_guess_sessions(self, bot, now: datetime | None = None) -> None:
        if self.guess_service is None:
            return
        current = self._coerce_now(now)
        for group_id, message in self.guess_service.collect_expired_sessions(now=current):
            await call_split_text_api(
                bot,
                "send_group_msg",
                group_id=group_id,
                message=message.text,
                group_interval_sleep=self.sleep_func,
            )

    async def _list_arc_enabled_groups(self, bot) -> list[int]:
        if self.arc_feature is None or not self.settings_store.get_group_feature_state(0, self.arc_feature):
            return []
        try:
            groups = await bot.call_api("get_group_list")
        except Exception:
            logger.exception("Arc activity reminder group list fetch failed")
            return []
        group_ids = []
        for group in groups or []:
            group_id = group.get("group_id") if isinstance(group, dict) else None
            if group_id is None:
                continue
            group_ids.append(int(group_id))
        return sorted(group_ids)

    def _coerce_now(self, now: datetime | None) -> datetime:
        if now is None:
            return datetime.now(self.zone)
        if now.tzinfo is None:
            return now.replace(tzinfo=self.zone)
        return now.astimezone(self.zone)

    def _parse_dt(self, raw: str) -> datetime | None:
        if not raw:
            return None
        return datetime.fromisoformat(raw).astimezone(self.zone)

    def _load(self) -> ArcBackgroundState:
        raw = self.store.read_with_legacy(
            "arc.background_state",
            {},
            lambda: self._load_legacy_state(),
        )
        return ArcBackgroundState(
            alias_last_synced_at=str(raw.get("alias_last_synced_at", "")),
            constants_last_synced_at=str(raw.get("constants_last_synced_at", "")),
            version_last_checked_at=str(raw.get("version_last_checked_at", "")),
            version_last_seen=str(raw.get("version_last_seen", "")),
            version_last_notified=str(raw.get("version_last_notified", "")),
            version_last_downloaded=str(raw.get("version_last_downloaded", "")),
            group_last_reminded_on=dict(raw.get("group_last_reminded_on", {})),
        )

    def _save(self) -> None:
        self.store.write("arc.background_state", asdict(self.state))

    def _load_legacy_state(self) -> dict | None:
        for path in (self.state_path, self.legacy_state_path):
            if path.exists():
                return read_json_file(path, {})
        return None

    def _resolve_zone(self, timezone_name: str):
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            if timezone_name == "Asia/Shanghai":
                return timezone(timedelta(hours=8), name=timezone_name)
            if timezone_name == "UTC":
                return timezone.utc
            return datetime.now().astimezone().tzinfo or timezone.utc
