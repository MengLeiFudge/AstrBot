from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
from pathlib import Path
import time

try:
    from astrbot.core.utils.astrbot_path import get_astrbot_temp_path
except Exception:
    get_astrbot_temp_path = None

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def resolve_astrbot_temp_root(*, fallback_data_root: Path) -> Path:
    """Return AstrBot Core temp root so plugin images join Core size-based cleanup."""
    if get_astrbot_temp_path is not None:
        try:
            return Path(get_astrbot_temp_path()).resolve()
        except Exception:
            pass
    return (fallback_data_root / "temp").resolve()


def resolve_plugin_temp_dir(*, fallback_data_root: Path, name: str) -> Path:
    safe_name = name.strip().replace("\\", "/").strip("/")
    if not safe_name or ".." in Path(safe_name).parts:
        raise ValueError(f"invalid temp dir name: {name!r}")
    return resolve_astrbot_temp_root(fallback_data_root=fallback_data_root) / "qqbot_features" / safe_name


@dataclass(frozen=True, slots=True)
class TempDedupeConfig:
    enabled: bool = True
    interval_seconds: int = 6 * 60 * 60
    min_file_age_seconds: int = 10 * 60
    max_files_per_run: int = 5000


@dataclass(frozen=True, slots=True)
class TempDedupeResult:
    scanned_files: int
    duplicate_files_removed: int
    bytes_removed: int
    skipped_files: int


class TempDuplicateCleaner:
    """Remove duplicate temp files while leaving AstrBot Core retention policy in charge."""

    def __init__(self, temp_root: Path, config: TempDedupeConfig | None = None) -> None:
        self.temp_root = temp_root.resolve()
        self.config = config or TempDedupeConfig()
        self._stop_event = asyncio.Event()

    def cleanup_once(self) -> TempDedupeResult:
        if not self.config.enabled:
            return TempDedupeResult(0, 0, 0, 0)
        if not self.temp_root.exists():
            return TempDedupeResult(0, 0, 0, 0)

        now = time.time()
        candidates_by_size: dict[int, list[Path]] = {}
        scanned = 0
        skipped = 0

        for path in self._iter_candidate_files():
            if scanned >= self.config.max_files_per_run:
                skipped += 1
                continue
            try:
                stat = path.stat()
            except OSError:
                skipped += 1
                continue
            if stat.st_size <= 0 or now - stat.st_mtime < self.config.min_file_age_seconds:
                skipped += 1
                continue
            candidates_by_size.setdefault(stat.st_size, []).append(path)
            scanned += 1

        removed = 0
        bytes_removed = 0
        for paths in candidates_by_size.values():
            if len(paths) < 2:
                continue
            seen: dict[str, Path] = {}
            for path in sorted(paths, key=lambda item: _safe_mtime(item)):
                digest = _sha256_file(path)
                if digest is None:
                    skipped += 1
                    continue
                if digest not in seen:
                    seen[digest] = path
                    continue
                try:
                    size = path.stat().st_size
                    path.unlink()
                except OSError:
                    skipped += 1
                    continue
                removed += 1
                bytes_removed += size

        return TempDedupeResult(
            scanned_files=scanned,
            duplicate_files_removed=removed,
            bytes_removed=bytes_removed,
            skipped_files=skipped,
        )

    async def run(self, *, logger=None) -> None:
        while not self._stop_event.is_set():
            try:
                result = await asyncio.to_thread(self.cleanup_once)
                if result.duplicate_files_removed and logger is not None:
                    logger.info(
                        "[QQBotFeatures] temp duplicate cleanup removed %s files, released %s bytes, scanned=%s skipped=%s",
                        result.duplicate_files_removed,
                        result.bytes_removed,
                        result.scanned_files,
                        result.skipped_files,
                    )
            except Exception as exc:
                if logger is not None:
                    logger.warning("[QQBotFeatures] temp duplicate cleanup failed: %r", exc)

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=max(self.config.interval_seconds, 60),
                )
            except asyncio.TimeoutError:
                continue

    async def stop(self) -> None:
        self._stop_event.set()

    def _iter_candidate_files(self):
        for path in self.temp_root.rglob("*"):
            if not path.is_file():
                continue
            if path.is_symlink():
                continue
            if path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            if not _is_managed_temp_image(self.temp_root, path):
                continue
            yield path


def load_temp_dedupe_config(config) -> TempDedupeConfig:
    return TempDedupeConfig(
        enabled=_read_bool(config, "temp_dedupe_enabled", True),
        interval_seconds=_read_int(
            config,
            "temp_dedupe_interval_seconds",
            default=6 * 60 * 60,
            minimum=60,
            maximum=7 * 24 * 60 * 60,
        ),
        min_file_age_seconds=_read_int(
            config,
            "temp_dedupe_min_file_age_seconds",
            default=10 * 60,
            minimum=60,
            maximum=24 * 60 * 60,
        ),
        max_files_per_run=_read_int(
            config,
            "temp_dedupe_max_files_per_run",
            default=5000,
            minimum=100,
            maximum=100000,
        ),
    )


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return float("inf")


def _sha256_file(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _is_managed_temp_image(temp_root: Path, path: Path) -> bool:
    if path.name.startswith("io_temp_img_"):
        return True
    try:
        relative_parts = path.relative_to(temp_root).parts
    except ValueError:
        return False
    return len(relative_parts) >= 2 and relative_parts[0] == "qqbot_features"


def _read_bool(config, key: str, default: bool) -> bool:
    value = _get_config_value(config, key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "启用", "开启"}:
            return True
        if normalized in {"0", "false", "no", "off", "禁用", "关闭"}:
            return False
    return default


def _read_int(config, key: str, *, default: int, minimum: int, maximum: int) -> int:
    value = _get_config_value(config, key, default)
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _get_config_value(config, key: str, default):
    if config is None:
        return default
    getter = getattr(config, "get", None)
    if callable(getter):
        try:
            return getter(key, default)
        except TypeError:
            try:
                return getter(key)
            except Exception:
                return default
    return default
