from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
from typing import Any

from aiohttp import web
from astrbot.api import logger
from astrbot.api.star import Context, Star, register


LOCAL_ARTIFACT_PUBLISH_MAX_AGE_SECONDS = 5 * 60
HOST = "127.0.0.1"
PORT = 8080


@dataclass(frozen=True, slots=True)
class HttpError(Exception):
    status: int
    detail: str


@register(
    "astrbot_plugin_local_artifact_api",
    "MengLei",
    "本机 localhost 构建产物发布兼容接口。",
    "0.1.1",
)
class LocalArtifactApiPlugin(Star):
    """Serve Yunqi's artifact API at the fixed localhost deployment address."""

    def __init__(self, context: Context) -> None:
        """Initialize listener state without configurable network endpoints.

        Args:
            context: AstrBot services providing the active OneBot platform.
        """
        super().__init__(context)
        self._context = context
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    async def initialize(self) -> None:
        app = web.Application()
        app.router.add_post("/admin/api/artifacts/publish-local", self._publish_local)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, HOST, PORT)
        try:
            await self._site.start()
        except OSError as exc:
            logger.warning(
                "[LocalArtifactApi] failed to listen on %s:%s: %s",
                HOST,
                PORT,
                exc,
            )
            await self._runner.cleanup()
            self._runner = None
            self._site = None
            return
        logger.info("[LocalArtifactApi] listening on http://%s:%s", HOST, PORT)

    async def terminate(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
        self._runner = None
        self._site = None

    async def _publish_local(self, request: web.Request) -> web.Response:
        if request.remote not in {"127.0.0.1", "::1", "localhost"}:
            return web.json_response({"detail": "Local request required."}, status=403)
        try:
            payload = await request.json()
            result = await publish_local_artifact_payload(payload, self._get_onebot_api())
        except HttpError as exc:
            return web.json_response({"detail": exc.detail}, status=exc.status)
        except Exception as exc:
            logger.exception("[LocalArtifactApi] publish-local failed: %s", exc)
            return web.json_response({"detail": str(exc)}, status=500)
        return web.json_response(result)

    def _get_onebot_api(self) -> "AstrBotPlatformOneBotApi":
        self_id = str(os.environ.get("QQBOT_ASTRBOT_ACCOUNT") or "").strip()
        if not self_id:
            raise HttpError(503, "Cannot determine AstrBot OneBot self id.")
        for platform in getattr(self._context.platform_manager, "platform_insts", []):
            if getattr(platform.meta(), "name", "") != "aiocqhttp":
                continue
            bot = getattr(platform, "bot", None)
            if bot is not None:
                return AstrBotPlatformOneBotApi(bot, self_id)
        raise HttpError(503, "No connected OneBot bot.")


class AstrBotPlatformOneBotApi:
    def __init__(self, bot: Any, self_id: str) -> None:
        self._bot = bot
        self.self_id = self_id

    async def call_api(self, action: str, **kwargs):
        return await self._bot.call_action(action, **kwargs)


async def publish_local_artifact_payload(payload: dict[str, Any], bot: AstrBotPlatformOneBotApi) -> dict[str, object]:
    from .legacy_services.artifacts.publish_service import (
        LocalArtifactPublishContext,
        publish_local_artifacts,
    )

    if not isinstance(payload, dict):
        raise HttpError(400, "Invalid JSON payload.")
    files_payload = payload.get("files")
    if not isinstance(files_payload, list) or not files_payload:
        raise HttpError(400, "No artifact files to publish.")
    _validate_publish_timestamp(str(payload.get("timestamp") or ""))
    _validate_publish_metadata(payload)

    repo_path = _infer_publish_repo_path(files_payload)
    _validate_publish_git_context(payload, repo_path)
    files = [_build_local_artifact_publish_file(item, repo_path) for item in files_payload]
    context = LocalArtifactPublishContext(
        project_id=str(payload.get("project_id") or ""),
        branch=str(payload.get("branch") or "").strip(),
        commit_hash=str(payload.get("commit_hash") or "").strip(),
        commit_subject=str(payload.get("commit_subject") or "").strip(),
        commit_detail=str(payload.get("commit_detail") or "").strip(),
    )
    try:
        result = await publish_local_artifacts(bot, files, context, data_root=get_qqbot_runtime_root())
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return {
        "ok": True,
        "uploaded": result.uploaded,
        "deleted": result.deleted,
        "skipped": result.skipped,
    }


def _build_local_artifact_publish_file(payload: dict[str, Any], repo_path: Path):
    from .legacy_services.artifacts.publish_service import LocalArtifactPublishFile

    if not isinstance(payload, dict):
        raise HttpError(400, "Invalid artifact file payload.")
    targets: list[int] = []
    for raw_group_id in payload.get("targets", []):
        try:
            group_id = int(raw_group_id)
        except (TypeError, ValueError) as exc:
            raise HttpError(400, "Artifact targets must be integer group ids.") from exc
        if group_id > 0:
            targets.append(group_id)
    if not targets:
        raise HttpError(400, "Artifact targets must include at least one valid group id.")
    artifact = _validate_generic_local_artifact_path(str(payload.get("path") or ""), repo_path)
    return LocalArtifactPublishFile(
        path=artifact,
        name=str(payload.get("name") or "").strip() or artifact.name,
        targets=tuple(targets),
        sha256=str(payload.get("sha256") or "").strip(),
        content_sha256=str(payload.get("content_sha256") or "").strip(),
        message=str(payload.get("message") or "").strip(),
    )


def _validate_generic_local_artifact_path(raw_path: str, repo_path: Path) -> Path:
    from .legacy_services.artifacts.publish_service import normalize_local_path

    artifact = normalize_local_path(raw_path)
    if artifact.suffix.lower() != ".zip":
        raise HttpError(400, "Only zip artifacts can be uploaded.")
    if not artifact.is_file():
        raise HttpError(404, "Artifact file does not exist.")
    try:
        artifact.resolve().relative_to(repo_path.resolve())
    except ValueError as exc:
        raise HttpError(400, "Artifact must be inside project repository.") from exc
    return artifact


def _infer_publish_repo_path(files: list[Any]) -> Path:
    from .legacy_services.artifacts.publish_service import normalize_local_path

    first = files[0] if isinstance(files[0], dict) else {}
    first_path = normalize_local_path(str(first.get("path") or ""))
    repo_path = _find_git_repo_root(first_path.parent)
    if repo_path is None:
        raise HttpError(400, "Cannot infer project git repository from artifact path.")
    for item in files:
        if not isinstance(item, dict):
            raise HttpError(400, "Invalid artifact file payload.")
        artifact = normalize_local_path(str(item.get("path") or ""))
        try:
            artifact.resolve().relative_to(repo_path.resolve())
        except ValueError as exc:
            raise HttpError(400, "All artifacts must be inside the same project repository.") from exc
    return repo_path


def _find_git_repo_root(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _validate_publish_timestamp(timestamp: str) -> None:
    text = timestamp.strip()
    if not text:
        raise HttpError(400, "Publish timestamp is required.")
    try:
        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        published_at = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise HttpError(400, "Invalid publish timestamp.") from exc
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age_seconds = abs((datetime.now(timezone.utc) - published_at.astimezone(timezone.utc)).total_seconds())
    if age_seconds > LOCAL_ARTIFACT_PUBLISH_MAX_AGE_SECONDS:
        raise HttpError(400, "Publish request timestamp is stale.")


def _validate_publish_metadata(payload: dict[str, Any]) -> None:
    if not str(payload.get("branch") or "").strip():
        raise HttpError(400, "Publish branch is required.")
    if not str(payload.get("commit_hash") or "").strip():
        raise HttpError(400, "Publish commit hash is required.")
    files = payload.get("files")
    file_messages: list[str] = []
    if isinstance(files, list):
        for item in files:
            if isinstance(item, dict):
                file_messages.append(str(item.get("message") or "").strip())
    if not str(payload.get("commit_detail") or "").strip() and not any(file_messages):
        raise HttpError(400, "Publish commit detail or file message is required.")


def _validate_publish_git_context(payload: dict[str, Any], repo_path: Path) -> None:
    current_branch = _read_git_output(repo_path, "branch", "--show-current")
    if not current_branch:
        raise HttpError(400, "Cannot read project git branch.")
    if current_branch != str(payload.get("branch") or "").strip():
        raise HttpError(400, "Publish branch does not match project checkout.")
    current_commit = _read_git_output(repo_path, "rev-parse", "HEAD")
    if not current_commit:
        raise HttpError(400, "Cannot read project git commit.")
    requested_commit = str(payload.get("commit_hash") or "").strip().lower()
    if not current_commit.lower().startswith(requested_commit):
        raise HttpError(400, "Publish commit does not match project checkout.")


def _read_git_output(repo_path: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_path,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def get_astrbot_data_root() -> Path:
    astrbot_root = Path(os.environ.get("ASTRBOT_ROOT") or Path(__file__).resolve().parents[3])
    return astrbot_root.resolve() / "data"


def get_qqbot_runtime_root() -> Path:
    return get_astrbot_data_root() / "plugin_data" / "qqbot_features_runtime"
