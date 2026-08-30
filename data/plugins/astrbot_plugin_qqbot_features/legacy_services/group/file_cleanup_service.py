from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import json
import logging
import math
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ...runtime_storage import RuntimeJsonStore
from ...runtime_storage import infer_runtime_root_from_path
from ...runtime_storage import read_json_file


logger = logging.getLogger(__name__)

SHAPEZ_GROUP_ID = "1163635014"
DEFAULT_OLD_FILE_GRACE_DAYS = 7
DEFAULT_GROUP_FILE_FETCH_COUNT = 10000
DEFAULT_GROUP_CLEANUP_SUMMARY_CHUNK_SIZE = 10
DEFAULT_MUTE_BYTES_PER_MINUTE = 1_000_000
DEFAULT_GROUP_MESSAGE_INTERVAL_SECONDS = 1.0
DEFAULT_GROUP_MESSAGE_RETRY_COUNT = 2


@dataclass(frozen=True, slots=True)
class GroupFileInfo:
    file_id: str
    name: str
    size: int
    uploaded_at: int
    uploader_id: str
    busid: str = ""
    parent_folder_id: str = ""


@dataclass(frozen=True, slots=True)
class GroupFolderInfo:
    folder_id: str
    name: str
    total_file_count: int = 0


@dataclass(frozen=True, slots=True)
class GroupFileSnapshot:
    root_files: tuple[GroupFileInfo, ...]
    folders: tuple[GroupFolderInfo, ...]
    inner_files: tuple[GroupFileInfo, ...]


@dataclass(frozen=True, slots=True)
class GroupFileCleanupSummary:
    user_id: str
    files: tuple[GroupFileInfo, ...]
    file_count: int
    total_size: int
    mute_duration_seconds: int


@dataclass(frozen=True, slots=True)
class ShapezPendingCleanup:
    user_id: str
    group_id: str
    file_ids: tuple[str, ...]
    file_names: tuple[str, ...]
    first_detected_at: int
    last_checked_at: int
    muted_until: int
    notice_sent_at: int
    status: str = "pending"
    deleted_at: int = 0


@dataclass(slots=True)
class ShapezGroupFileCleanupState:
    last_scan_date: str = ""
    last_scan_at: int = 0
    pending: dict[str, ShapezPendingCleanup] = field(default_factory=dict)


class ShapezGroupFileCleanupStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.runtime_root = infer_runtime_root_from_path(self.path)
        self.legacy_path = self.runtime_root / "data" / self.path.name
        self.store = RuntimeJsonStore(self.runtime_root)

    def load(self) -> ShapezGroupFileCleanupState:
        try:
            raw = self.store.read_with_legacy(
                "shapez.file_cleanup_state",
                {},
                lambda: self._load_legacy_state(),
            )
        except (OSError, json.JSONDecodeError, TypeError):
            return ShapezGroupFileCleanupState()
        pending: dict[str, ShapezPendingCleanup] = {}
        raw_pending = raw.get("pending", {})
        if isinstance(raw_pending, dict):
            for user_id, item in raw_pending.items():
                if not isinstance(item, dict):
                    continue
                pending[str(user_id)] = ShapezPendingCleanup(
                    user_id=str(item.get("user_id", user_id)),
                    group_id=str(item.get("group_id", SHAPEZ_GROUP_ID)),
                    file_ids=tuple(str(value) for value in item.get("file_ids", ())),
                    file_names=tuple(str(value) for value in item.get("file_names", ())),
                    first_detected_at=int(item.get("first_detected_at", 0) or 0),
                    last_checked_at=int(item.get("last_checked_at", 0) or 0),
                    muted_until=int(item.get("muted_until", 0) or 0),
                    notice_sent_at=int(item.get("notice_sent_at", 0) or 0),
                    status=str(item.get("status", "pending")),
                    deleted_at=int(item.get("deleted_at", 0) or 0),
                )
        return ShapezGroupFileCleanupState(
            last_scan_date=str(raw.get("last_scan_date", "")),
            last_scan_at=int(raw.get("last_scan_at", 0) or 0),
            pending=pending,
        )

    def save(self, state: ShapezGroupFileCleanupState) -> None:
        payload = {
            "last_scan_date": state.last_scan_date,
            "last_scan_at": state.last_scan_at,
            "pending": {
                user_id: {
                    **asdict(item),
                    "file_ids": list(item.file_ids),
                    "file_names": list(item.file_names),
                }
                for user_id, item in state.pending.items()
            },
        }
        self.store.write("shapez.file_cleanup_state", payload)

    def _load_legacy_state(self) -> dict | None:
        for path in (self.path, self.legacy_path):
            if path.exists():
                return read_json_file(path, {})
        return None


class ShapezGroupFileCleanupService:
    def __init__(
        self,
        *,
        store: ShapezGroupFileCleanupStore,
        group_id: str = SHAPEZ_GROUP_ID,
        old_file_grace_days: int = DEFAULT_OLD_FILE_GRACE_DAYS,
        group_message_interval_seconds: float = DEFAULT_GROUP_MESSAGE_INTERVAL_SECONDS,
        group_message_retry_count: int = DEFAULT_GROUP_MESSAGE_RETRY_COUNT,
        timezone_name: str = "Asia/Shanghai",
        now_func: Callable[[], datetime] | None = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self.store = store
        self.group_id = str(group_id)
        self.old_file_grace_days = max(0, int(old_file_grace_days))
        self.group_message_interval_seconds = max(0.0, float(group_message_interval_seconds))
        self.group_message_retry_count = max(0, int(group_message_retry_count))
        self.zone = _resolve_zone(timezone_name)
        self.now_func = now_func
        self.sleep = sleep

    async def fetch_snapshot(self, bot: Any) -> GroupFileSnapshot:
        root_payload = await bot.call_api(
            "get_group_root_files",
            group_id=int(self.group_id),
            file_count=DEFAULT_GROUP_FILE_FETCH_COUNT,
        )
        root_files = tuple(_parse_files(_extract_list(root_payload, "files", "file", "items")))
        folders = tuple(_parse_folders(_extract_list(root_payload, "folders", "folder")))
        inner_files: list[GroupFileInfo] = []
        for folder in folders:
            folder_payload = await bot.call_api(
                "get_group_files_by_folder",
                group_id=int(self.group_id),
                folder_id=folder.folder_id,
                file_count=max(DEFAULT_GROUP_FILE_FETCH_COUNT, folder.total_file_count),
            )
            inner_files.extend(
                _parse_files(
                    _extract_list(folder_payload, "files", "file", "items"),
                    parent_folder_id=folder.folder_id,
                )
            )
        return GroupFileSnapshot(root_files=root_files, folders=folders, inner_files=tuple(inner_files))

    def find_violations(self, snapshot: GroupFileSnapshot, *, now: datetime | None = None) -> dict[str, tuple[GroupFileInfo, ...]]:
        current = self._coerce_now(now)
        cutoff = int((current - timedelta(days=self.old_file_grace_days)).timestamp())
        grouped: dict[str, list[GroupFileInfo]] = {}
        for file_info in snapshot.root_files:
            if not file_info.uploader_id:
                continue
            if file_info.uploaded_at <= 0 or file_info.uploaded_at > cutoff:
                continue
            grouped.setdefault(file_info.uploader_id, []).append(file_info)
        return {user_id: tuple(files) for user_id, files in grouped.items()}

    async def scan_and_notify_group(self, bot: Any, *, now: datetime | None = None) -> dict[str, object]:
        current = self._coerce_now(now)
        snapshot = await self.fetch_snapshot(bot)
        violations = self.find_violations(snapshot, now=current)
        summaries = build_group_file_cleanup_summaries(violations)
        if not summaries:
            return {
                "root_file_count": len(snapshot.root_files),
                "folder_count": len(snapshot.folders),
                "inner_file_count": len(snapshot.inner_files),
                "violating_user_count": 0,
                "violating_file_count": 0,
                "violating_total_size": 0,
                "muted_user_count": 0,
                "failed_mute_count": 0,
                "skipped_mute_count": 0,
                "group_message_count": 0,
                "failed_group_message_count": 0,
            }

        failed_group_messages = 0
        group_message_count = 1
        intro_sent = await self._send_group_cleanup_message(
            bot,
            message=build_group_cleanup_intro_message(),
            message_index=1,
        )
        if not intro_sent:
            failed_group_messages += 1

        if not intro_sent:
            return {
                "root_file_count": len(snapshot.root_files),
                "folder_count": len(snapshot.folders),
                "inner_file_count": len(snapshot.inner_files),
                "violating_user_count": len(summaries),
                "violating_file_count": sum(summary.file_count for summary in summaries),
                "violating_total_size": sum(summary.total_size for summary in summaries),
                "muted_user_count": 0,
                "failed_mute_count": 0,
                "skipped_mute_count": len(tuple(summary for summary in summaries if summary.mute_duration_seconds < 60)),
                "group_message_count": group_message_count,
                "failed_group_message_count": failed_group_messages,
            }

        state = self.store.load()
        muted = 0
        failed_mutes = 0
        skipped_mutes = 0
        summary_chunks = tuple(
            summaries[index : index + DEFAULT_GROUP_CLEANUP_SUMMARY_CHUNK_SIZE]
            for index in range(0, len(summaries), DEFAULT_GROUP_CLEANUP_SUMMARY_CHUNK_SIZE)
        )
        for chunk_index, chunk in enumerate(summary_chunks, start=1):
            if self.group_message_interval_seconds > 0:
                await self.sleep(self.group_message_interval_seconds)
            group_message_count += 1
            message = build_group_cleanup_summary_message(chunk, chunk_index=chunk_index, chunk_count=len(summary_chunks))
            sent = await self._send_group_cleanup_message(
                bot,
                message=message,
                message_index=group_message_count,
            )
            if not sent:
                failed_group_messages += 1
                continue
            chunk_result = await self._mute_summaries(bot, state=state, summaries=chunk, now=current)
            muted += chunk_result["muted"]
            failed_mutes += chunk_result["failed"]
            skipped_mutes += chunk_result["skipped"]
        self.store.save(state)
        return {
            "root_file_count": len(snapshot.root_files),
            "folder_count": len(snapshot.folders),
            "inner_file_count": len(snapshot.inner_files),
            "violating_user_count": len(summaries),
            "violating_file_count": sum(summary.file_count for summary in summaries),
            "violating_total_size": sum(summary.total_size for summary in summaries),
            "muted_user_count": muted,
            "failed_mute_count": failed_mutes,
            "skipped_mute_count": skipped_mutes,
            "group_message_count": group_message_count,
            "failed_group_message_count": failed_group_messages,
        }

    async def _mute_summaries(
        self,
        bot: Any,
        *,
        state: ShapezGroupFileCleanupState,
        summaries: tuple[GroupFileCleanupSummary, ...],
        now: datetime,
    ) -> dict[str, int]:
        muted = 0
        failed = 0
        skipped = 0
        for summary in summaries:
            if summary.mute_duration_seconds < 60:
                skipped += 1
                continue
            previous = state.pending.get(summary.user_id)
            muted_until = int(now.timestamp()) + summary.mute_duration_seconds
            try:
                await bot.call_api(
                    "set_group_ban",
                    group_id=int(self.group_id),
                    user_id=int(summary.user_id),
                    duration=summary.mute_duration_seconds,
                )
            except Exception as exc:
                failed += 1
                logger.warning("Group file cleanup mute failed for group_id=%s user_id=%s: %r", self.group_id, summary.user_id, exc)
                continue
            muted += 1
            state.pending[summary.user_id] = ShapezPendingCleanup(
                user_id=summary.user_id,
                group_id=self.group_id,
                file_ids=tuple(file_info.file_id for file_info in summary.files),
                file_names=tuple(file_info.name for file_info in summary.files),
                first_detected_at=previous.first_detected_at if previous else int(now.timestamp()),
                last_checked_at=int(now.timestamp()),
                muted_until=muted_until,
                notice_sent_at=int(now.timestamp()),
                status="pending",
                deleted_at=0,
            )
        return {"muted": muted, "failed": failed, "skipped": skipped}

    async def _send_group_cleanup_message(self, bot: Any, *, message: str, message_index: int) -> bool:
        for attempt in range(self.group_message_retry_count + 1):
            try:
                await bot.call_api("send_group_msg", group_id=int(self.group_id), message=message)
                return True
            except Exception as exc:
                logger.warning(
                    "Group file cleanup message failed for group_id=%s index=%s attempt=%s: %r",
                    self.group_id,
                    message_index,
                    attempt + 1,
                    exc,
                )
                if attempt < self.group_message_retry_count and self.group_message_interval_seconds > 0:
                    await self.sleep(self.group_message_interval_seconds)
        return False

    def _coerce_now(self, now: datetime | None) -> datetime:
        if now is None:
            if self.now_func is not None:
                return self._coerce_now(self.now_func())
            return datetime.now(self.zone)
        if now.tzinfo is None:
            return now.replace(tzinfo=self.zone)
        return now.astimezone(self.zone)


def build_group_file_cleanup_summaries(
    violations: dict[str, tuple[GroupFileInfo, ...]]
) -> tuple[GroupFileCleanupSummary, ...]:
    summaries: list[GroupFileCleanupSummary] = []
    for user_id, files in violations.items():
        sorted_files = _sort_files_by_size_desc(files)
        total_size = sum(file_info.size for file_info in sorted_files)
        summaries.append(
            GroupFileCleanupSummary(
                user_id=user_id,
                files=sorted_files,
                file_count=len(sorted_files),
                total_size=total_size,
                mute_duration_seconds=_calculate_size_based_mute_duration(total_size),
            )
        )
    return tuple(sorted(summaries, key=lambda summary: (-summary.total_size, summary.user_id)))


def build_group_cleanup_intro_message() -> str:
    return (
        "该清理文件了喵！\n"
        "以下只统计超过一周、未归类到文件夹内的文件喵。\n"
        "请将自己的文件删除或移动到合适的文件夹喵！"
    )


def build_group_cleanup_summary_messages(
    summaries: tuple[GroupFileCleanupSummary, ...],
    *,
    chunk_size: int = DEFAULT_GROUP_CLEANUP_SUMMARY_CHUNK_SIZE,
) -> tuple[str, ...]:
    size = max(1, int(chunk_size))
    chunks = tuple(summaries[index : index + size] for index in range(0, len(summaries), size))
    return tuple(
        build_group_cleanup_summary_message(chunk, chunk_index=chunk_index, chunk_count=len(chunks))
        for chunk_index, chunk in enumerate(chunks, start=1)
    )


def build_group_cleanup_summary_message(
    summaries: tuple[GroupFileCleanupSummary, ...],
    *,
    chunk_index: int,
    chunk_count: int,
) -> str:
    lines = [
        f"[CQ:at,qq={summary.user_id}] {summary.file_count} 个，{_format_decimal_mb(summary.total_size)}"
        for summary in summaries
    ]
    if chunk_count > 1:
        lines.append(f"第 {chunk_index}/{chunk_count} 条")
    return "\n".join(lines)


def _sort_files_by_size_desc(files: tuple[GroupFileInfo, ...]) -> tuple[GroupFileInfo, ...]:
    return tuple(sorted(files, key=lambda file_info: (-file_info.size, file_info.name)))


def _format_decimal_mb(size: int) -> str:
    return f"{max(0, int(size)) / DEFAULT_MUTE_BYTES_PER_MINUTE:.1f} MB"


def _calculate_size_based_mute_duration(size: int) -> int:
    if size <= 0:
        return 0
    raw_seconds = int(size) * 60 / DEFAULT_MUTE_BYTES_PER_MINUTE
    if raw_seconds < 60:
        return 0
    return math.ceil(raw_seconds)


def _extract_list(payload: object, *keys: str) -> tuple[dict[str, object], ...]:
    if not isinstance(payload, dict):
        return ()
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return tuple(item for item in value if isinstance(item, dict))
        if isinstance(value, dict):
            nested = _extract_list(value, *keys)
            if nested:
                return nested
    return ()


def _parse_files(raw_files: tuple[dict[str, object], ...], *, parent_folder_id: str = "") -> tuple[GroupFileInfo, ...]:
    files: list[GroupFileInfo] = []
    for item in raw_files:
        file_id = _first_text(item, "file_id", "id")
        name = _first_text(item, "file_name", "name")
        uploader_id = _first_text(item, "uploader", "uploader_id", "user_id", "sender_id")
        if not file_id or not name:
            continue
        files.append(
            GroupFileInfo(
                file_id=file_id,
                name=name,
                size=_first_int(item, "file_size", "size"),
                uploaded_at=_normalize_unix_seconds(
                    _first_positive_int(item, "upload_time", "uploaded_at", "create_time", "modify_time")
                ),
                uploader_id=uploader_id,
                busid=_first_text(item, "busid", "bus_id"),
                parent_folder_id=parent_folder_id,
            )
        )
    return tuple(files)


def _parse_folders(raw_folders: tuple[dict[str, object], ...]) -> tuple[GroupFolderInfo, ...]:
    folders: list[GroupFolderInfo] = []
    for item in raw_folders:
        folder_id = _first_text(item, "folder_id", "id")
        name = _first_text(item, "folder_name", "name")
        if folder_id:
            folders.append(
                GroupFolderInfo(
                    folder_id=folder_id,
                    name=name or folder_id,
                    total_file_count=_first_int(item, "total_file_count", "file_count"),
                )
            )
    return tuple(folders)


def _first_text(item: dict[str, object], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _first_int(item: dict[str, object], *keys: str) -> int:
    text = _first_text(item, *keys)
    if not text:
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def _first_positive_int(item: dict[str, object], *keys: str) -> int:
    for key in keys:
        value = _first_int(item, key)
        if value > 0:
            return value
    return 0


def _normalize_unix_seconds(value: int) -> int:
    normalized = int(value)
    while normalized > 10_000_000_000:
        normalized //= 1000
    return normalized


def _resolve_zone(timezone_name: str):
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        if timezone_name == "Asia/Shanghai":
            return timezone(timedelta(hours=8), name=timezone_name)
        if timezone_name == "UTC":
            return timezone.utc
        return datetime.now().astimezone().tzinfo or timezone.utc
