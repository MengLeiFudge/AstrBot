from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ...runtime_storage import RuntimeJsonStore
from ...runtime_storage import infer_runtime_root_from_path
from ...runtime_storage import read_json_file
from .arcaea_record_apk_downloader import ArcaeaRecordApkDownloader


@dataclass(slots=True)
class ArcApkUpdateStatus:
    state: str = "idle"
    version: str = ""
    progress: str = ""
    path: Path | None = None
    error: str = ""


class ArcApkUpdateManager:
    def __init__(
        self,
        state_path: Path,
        version_fetcher: Callable[[], str],
        downloader: ArcaeaRecordApkDownloader,
        timezone_name: str = "Asia/Shanghai",
    ) -> None:
        self.state_path = Path(state_path)
        self.version_fetcher = version_fetcher
        self.downloader = downloader
        self.zone = self._resolve_zone(timezone_name)
        self.status = ArcApkUpdateStatus()
        self._task: asyncio.Task | None = None
        self.runtime_root = infer_runtime_root_from_path(self.state_path)
        self.legacy_state_path = self.runtime_root / "data" / "arc" / self.state_path.name
        self.store = RuntimeJsonStore(self.runtime_root)

    async def query_and_update(self) -> str:
        if self._task is not None and not self._task.done():
            return self.render_status()
        latest_version = await asyncio.to_thread(self.version_fetcher)
        self._record_checked_version(latest_version)
        if self._load_raw_state().get("version_last_downloaded") == latest_version:
            self.status = ArcApkUpdateStatus(
                state="completed",
                version=latest_version,
                progress="100%",
            )
            return f"当前官网版本：{latest_version}\n安装包已经下载过。"
        self.status = ArcApkUpdateStatus(
            state="downloading",
            version=latest_version,
            progress="准备下载",
        )
        self._task = asyncio.create_task(self._download(latest_version))
        return f"当前官网版本：{latest_version}\n已开始下载，发送 xz 或 arcxz 可查看进度。"

    def render_status(self) -> str:
        if self.status.state == "downloading":
            return f"Arcaea {self.status.version} 安装包正在下载。\n当前进度：{self.status.progress}"
        if self.status.state == "completed":
            if self.status.path is not None:
                return f"Arcaea {self.status.version} 安装包已下载完毕：{self.status.path}"
            return f"Arcaea {self.status.version} 安装包已下载完毕。"
        if self.status.state == "failed":
            return f"Arcaea {self.status.version} 安装包下载失败：{self.status.error}"
        return "当前没有进行中的 Arcaea 安装包下载。"

    async def _download(self, version: str) -> None:
        def update_progress(progress: str) -> None:
            self.status.progress = progress

        try:
            result = await asyncio.to_thread(
                self.downloader.download_latest_apk,
                version,
                update_progress,
            )
        except Exception as exc:
            self.status = ArcApkUpdateStatus(
                state="failed",
                version=version,
                progress=self.status.progress,
                error=str(exc),
            )
            return
        self.status = ArcApkUpdateStatus(
            state="completed",
            version=version,
            progress="100%",
            path=result.path,
        )
        self._record_downloaded_version(version)

    def _record_checked_version(self, version: str) -> None:
        raw = self._load_raw_state()
        raw["version_last_checked_at"] = datetime.now(self.zone).isoformat()
        raw["version_last_seen"] = version
        self._save_raw_state(raw)

    def _record_downloaded_version(self, version: str) -> None:
        raw = self._load_raw_state()
        raw["version_last_downloaded"] = version
        self._save_raw_state(raw)

    def _load_raw_state(self) -> dict:
        return self.store.read_with_legacy(
            "arc.background_state",
            {},
            lambda: self._load_legacy_state(),
        )

    def _save_raw_state(self, raw: dict) -> None:
        self.store.write("arc.background_state", raw)

    def _load_legacy_state(self) -> dict | None:
        for path in (self.state_path, self.legacy_state_path):
            if path.exists():
                return read_json_file(path, {})
        return None

    @staticmethod
    def _resolve_zone(timezone_name: str):
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            if timezone_name == "Asia/Shanghai":
                return timezone(timedelta(hours=8), name=timezone_name)
            if timezone_name == "UTC":
                return timezone.utc
            return datetime.now().astimezone().tzinfo or timezone.utc
