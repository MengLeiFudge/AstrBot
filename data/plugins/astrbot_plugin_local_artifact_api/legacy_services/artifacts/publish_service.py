from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any
import zipfile

FE_ARTIFACT_NAME_RE = re.compile(r"^FractionateEverything_\d+(?:\.\d+)*\.zip$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class FeArtifactPublishResult:
    uploaded: list[dict[str, str]]
    deleted: list[str]
    skipped: bool = False
    reason: str = ""


@dataclass(frozen=True, slots=True)
class LocalArtifactPublishFile:
    path: Path
    name: str
    targets: tuple[int, ...]
    sha256: str = ""
    content_sha256: str = ""
    message: str = ""


@dataclass(frozen=True, slots=True)
class LocalArtifactPublishContext:
    project_id: str
    branch: str
    commit_hash: str
    commit_subject: str = ""
    commit_detail: str = ""


@dataclass(frozen=True, slots=True)
class LocalArtifactPublishResult:
    uploaded: list[dict[str, object]]
    deleted: list[dict[str, object]]
    skipped: list[dict[str, object]]


@dataclass(slots=True)
class LocalArtifactPublishNotice:
    reply_message_id: str = ""
    message: str = ""


@dataclass(frozen=True, slots=True)
class CommitSummary:
    short_hash: str
    title: str
    body: str


def normalize_local_path(path: str | Path) -> Path:
    text = str(path).strip()
    if len(text) >= 3 and text[1] == ":":
        return Path(text)
    if text.startswith("/mnt/") and len(text) > 6 and text[6:7] == "/":
        drive = text[5:6].upper()
        rest = text[7:].replace("/", "\\")
        return Path(f"{drive}:\\{rest}")
    return Path(text)


async def publish_fe_artifact(
    bot: Any,
    group_id: int,
    package: str | Path,
    repo_path: str | Path | None = None,
    message: str = "",
    data_root: str | Path | None = None,
) -> FeArtifactPublishResult:
    package_path = normalize_local_path(package)
    package_sha256 = calculate_sha256(package_path)
    if is_same_as_last_published(group_id, package_sha256, data_root=data_root):
        return FeArtifactPublishResult(
            uploaded=[],
            deleted=[],
            skipped=True,
            reason="FE package sha256 unchanged.",
        )
    deleted = await delete_old_fe_group_files(bot, group_id)
    upload_result = await bot.call_api(
        "upload_group_file",
        group_id=group_id,
        file=str(package_path),
        name=package_path.name,
    )
    reply_message_id = _extract_message_id(upload_result)
    if not reply_message_id:
        reply_message_id = await find_uploaded_file_message_id(
            bot,
            group_id,
            package_path.name,
        )
    publish_message = build_publish_message(repo_path, message, reply_message_id=reply_message_id)
    if publish_message:
        await bot.call_api("send_group_msg", group_id=group_id, message=publish_message)
    save_last_published_sha(group_id, package_sha256, data_root=data_root)
    return FeArtifactPublishResult(
        uploaded=[{"file": str(package_path), "name": package_path.name}],
        deleted=deleted,
    )


async def publish_local_artifacts(
    bot: Any,
    files: list[LocalArtifactPublishFile],
    context: LocalArtifactPublishContext,
    data_root: str | Path | None = None,
) -> LocalArtifactPublishResult:
    uploaded: list[dict[str, object]] = []
    deleted: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    notices: dict[int, LocalArtifactPublishNotice] = {}

    for artifact in files:
        package_path = normalize_local_path(artifact.path)
        upload_name = artifact.name.strip() or package_path.name
        expected_sha256 = artifact.sha256.strip().lower()
        actual_sha256 = calculate_sha256(package_path)
        if expected_sha256 and expected_sha256 != actual_sha256:
            raise ValueError(f"Artifact sha256 mismatch: {package_path}")
        server_content_sha256 = calculate_zip_content_sha256(package_path)
        client_content_sha256 = artifact.content_sha256.strip().lower()
        if client_content_sha256 and client_content_sha256 != server_content_sha256:
            raise ValueError(f"Artifact content sha256 mismatch: {package_path}")

        for group_id in artifact.targets:
            if is_same_as_last_local_artifact_published(
                group_id,
                upload_name,
                server_content_sha256,
                data_root=data_root,
            ):
                skipped.append(
                    {
                        "group_id": group_id,
                        "file": str(package_path),
                        "name": upload_name,
                        "sha256": actual_sha256,
                        "content_sha256": server_content_sha256,
                        "reason": "artifact content sha256 unchanged.",
                    }
                )
                continue

            deleted_names = await delete_same_named_group_files_uploaded_by_bot(bot, group_id, upload_name)
            deleted.extend({"group_id": group_id, "name": name} for name in deleted_names)

            upload_result = await bot.call_api(
                "upload_group_file",
                group_id=group_id,
                file=str(package_path),
                name=upload_name,
            )
            reply_message_id = _extract_message_id(upload_result)
            if not reply_message_id:
                reply_message_id = await find_uploaded_file_message_id(bot, group_id, upload_name)
            notice = notices.setdefault(group_id, LocalArtifactPublishNotice())
            notice.reply_message_id = reply_message_id
            if artifact.message.strip():
                notice.message = artifact.message.strip()
            uploaded.append(
                {
                    "group_id": group_id,
                    "file": str(package_path),
                    "name": upload_name,
                    "sha256": actual_sha256,
                    "content_sha256": server_content_sha256,
                }
            )
            save_last_local_artifact_published_sha(
                group_id,
                upload_name,
                server_content_sha256,
                data_root=data_root,
            )
    for group_id, notice in notices.items():
        message = build_local_artifact_publish_message(
            context,
            notice.message,
            reply_message_id=notice.reply_message_id,
        )
        if message:
            await bot.call_api("send_group_msg", group_id=group_id, message=message)
    return LocalArtifactPublishResult(uploaded=uploaded, deleted=deleted, skipped=skipped)


async def delete_old_fe_group_files(bot: Any, group_id: int) -> list[str]:
    payload = await bot.call_api("get_group_root_files", group_id=group_id)
    files = _extract_group_files(payload)
    deleted: list[str] = []
    self_id = str(getattr(bot, "self_id", ""))
    for file_info in files:
        name = _first_text(file_info, "file_name", "name")
        if not FE_ARTIFACT_NAME_RE.fullmatch(name):
            continue
        uploader = _first_text(file_info, "uploader", "uploader_id", "user_id", "sender_id")
        if self_id and uploader and uploader != self_id:
            continue
        file_id = _first_text(file_info, "file_id", "id")
        if not file_id:
            continue
        delete_args: dict[str, object] = {
            "group_id": group_id,
            "file_id": file_id,
        }
        busid = _first_value(file_info, "busid", "bus_id")
        if busid is not None:
            delete_args["busid"] = busid
        await bot.call_api("delete_group_file", **delete_args)
        deleted.append(name)
    return deleted


async def delete_same_named_group_files_uploaded_by_bot(
    bot: Any,
    group_id: int,
    file_name: str,
) -> list[str]:
    payload = await bot.call_api("get_group_root_files", group_id=group_id)
    files = _extract_group_files(payload)
    deleted: list[str] = []
    self_id = str(getattr(bot, "self_id", ""))
    for file_info in files:
        name = _first_text(file_info, "file_name", "name")
        if name != file_name:
            continue
        uploader = _first_text(file_info, "uploader", "uploader_id", "user_id", "sender_id")
        if self_id and uploader and uploader != self_id:
            continue
        file_id = _first_text(file_info, "file_id", "id")
        if not file_id:
            continue
        delete_args: dict[str, object] = {
            "group_id": group_id,
            "file_id": file_id,
        }
        busid = _first_value(file_info, "busid", "bus_id")
        if busid is not None:
            delete_args["busid"] = busid
        await bot.call_api("delete_group_file", **delete_args)
        deleted.append(name)
    return deleted


def is_fe_artifact_path(path: str | Path) -> bool:
    return FE_ARTIFACT_NAME_RE.fullmatch(Path(str(path)).name) is not None


def calculate_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with normalize_local_path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def calculate_zip_content_sha256(path: str | Path) -> str:
    package_path = normalize_local_path(path)
    digest = hashlib.sha256()
    with zipfile.ZipFile(package_path, "r") as archive:
        for info in sorted(archive.infolist(), key=lambda item: item.filename.lower()):
            digest.update(info.filename.encode("utf-8"))
            digest.update(b"\0")
            digest.update(str(info.file_size).encode("utf-8"))
            digest.update(b"\0")
            with archive.open(info, "r") as file:
                for chunk in iter(lambda: file.read(1024 * 1024), b""):
                    digest.update(chunk)
            digest.update(b"\0")
    return digest.hexdigest()


def is_same_as_last_published(
    group_id: int,
    sha256: str,
    *,
    data_root: str | Path | None = None,
) -> bool:
    return bool(sha256) and _load_last_published_sha(group_id, data_root=data_root) == sha256


def save_last_published_sha(
    group_id: int,
    sha256: str,
    *,
    data_root: str | Path | None = None,
) -> None:
    if not sha256:
        return
    path = _last_published_sha_path(group_id, data_root=data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"sha256": sha256}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def is_same_as_last_local_artifact_published(
    group_id: int,
    file_name: str,
    sha256: str,
    *,
    data_root: str | Path | None = None,
) -> bool:
    return bool(sha256) and _load_last_local_artifact_published_sha(
        group_id,
        file_name,
        data_root=data_root,
    ) == sha256


def save_last_local_artifact_published_sha(
    group_id: int,
    file_name: str,
    sha256: str,
    *,
    data_root: str | Path | None = None,
) -> None:
    if not sha256:
        return
    path = _last_local_artifact_published_sha_path(group_id, file_name, data_root=data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"name": file_name, "server_content_sha256": sha256, "content_sha256": sha256},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


async def find_uploaded_file_message_id(
    bot: Any,
    group_id: int,
    file_name: str,
    *,
    retries: int = 5,
    delay_seconds: float = 0.3,
) -> str:
    if not file_name:
        return ""
    for attempt in range(max(1, retries)):
        payload = await _get_recent_group_messages(bot, group_id)
        message_id = _extract_file_message_id_from_history(payload, file_name)
        if message_id:
            return message_id
        if attempt + 1 < retries:
            await asyncio.sleep(delay_seconds)
    return ""


def build_publish_message(
    repo_path: str | Path | None,
    message: str = "",
    reply_message_id: str = "",
) -> str:
    commit = read_latest_commit_summary(repo_path) if repo_path is not None else None
    if commit is None and not message.strip():
        return ""
    reply_prefix = _build_reply_prefix(reply_message_id)
    lines: list[str] = []
    if commit is not None:
        lines.append(f"{reply_prefix}{commit.short_hash} {commit.title}".strip())
    else:
        lines.append(f"{reply_prefix}本次 FE 构建")

    normalized_message = message.strip()
    fields = _parse_publish_summary(normalized_message)
    if not fields and commit is not None and commit.body:
        fields = _parse_publish_summary(commit.body)
    if not fields and normalized_message:
        fields = {"变更内容": [normalized_message]}

    lines.extend(_build_type_sections(_commit_type(commit.title if commit else ""), fields))
    return "\n".join(line for line in lines if line is not None).strip()


def build_local_artifact_publish_message(
    context: LocalArtifactPublishContext,
    message: str = "",
    reply_message_id: str = "",
) -> str:
    reply_prefix = _build_reply_prefix(reply_message_id)
    subject = context.commit_subject.strip()
    commit = context.commit_hash.strip()
    if commit and subject:
        headline = f"{commit[:7]} {subject}"
    elif commit:
        headline = commit[:7]
    else:
        headline = "本次构建"

    lines = [f"{reply_prefix}{headline}".strip()]
    if context.branch.strip():
        lines.extend(["", f"分支：{context.branch.strip()}"])

    detail = (message or context.commit_detail).strip()
    if detail:
        fields = _parse_publish_summary(detail)
        if fields:
            lines.extend(_build_type_sections(_commit_type(subject), fields))
        else:
            lines.extend(["", detail])
    return "\n".join(line for line in lines if line is not None).strip()


def build_latest_commit_message(repo_path: str | Path) -> str:
    commit = read_latest_commit_summary(repo_path)
    if commit is None:
        return ""
    lines = [
        "本次 FE 构建对应提交：",
        f"{commit.short_hash} {commit.title}".strip(),
    ]
    if commit.body:
        lines.extend(["", commit.body])
    return "\n".join(line for line in lines if line is not None).strip()


def read_latest_commit_summary(repo_path: str | Path | None) -> CommitSummary | None:
    if repo_path is None:
        return None
    repo = normalize_local_path(repo_path)
    if not repo.is_dir():
        return None
    summary = _run_git(repo, "log", "-1", "--pretty=format:%h%n%s%n%b")
    if not summary:
        return None
    parts = [part.strip() for part in summary.splitlines()]
    short_hash = parts[0] if parts else ""
    title = parts[1] if len(parts) > 1 else ""
    body = "\n".join(part for part in parts[2:] if part).strip()
    return CommitSummary(short_hash=short_hash, title=title, body=body)


def _build_reply_prefix(message_id: str) -> str:
    return f"[CQ:reply,id={message_id}]" if message_id.isdigit() else ""


def _extract_message_id(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("message_id", "msg_id", "id"):
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    data = payload.get("data")
    if isinstance(data, dict):
        return _extract_message_id(data)
    return ""


async def _get_recent_group_messages(bot: Any, group_id: int) -> Any:
    for api, data in (
        ("get_group_msg_history", {"group_id": group_id, "count": 20}),
        ("get_group_msg_history", {"group_id": group_id}),
    ):
        try:
            return await bot.call_api(api, **data)
        except Exception:
            continue
    return None


def _extract_file_message_id_from_history(payload: Any, file_name: str) -> str:
    target = file_name.strip()
    for message in reversed(_extract_history_messages(payload)):
        if _message_contains_file_name(message, target):
            message_id = _extract_message_id(message)
            if message_id:
                return message_id
    return ""


def _extract_history_messages(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("messages", "message", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _extract_history_messages(value)
            if nested:
                return nested
    return []


def _message_contains_file_name(message: Any, file_name: str) -> bool:
    if not file_name:
        return False
    if isinstance(message, str):
        return file_name in message
    if isinstance(message, list):
        return any(_message_contains_file_name(part, file_name) for part in message)
    if not isinstance(message, dict):
        return False
    for key in ("file", "name", "file_name", "text", "raw_message", "message"):
        value = message.get(key)
        if isinstance(value, str) and file_name in value:
            return True
        if isinstance(value, (dict, list)) and _message_contains_file_name(value, file_name):
            return True
    data = message.get("data")
    return isinstance(data, (dict, list)) and _message_contains_file_name(data, file_name)


def _commit_type(title: str) -> str:
    prefix = title.split("：", 1)[0].strip()
    return prefix if prefix in {"修复", "功能", "重构", "杂项"} else ""


def _parse_publish_summary(message: str) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    current_label = ""
    for raw_line in message.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        label, content = _split_summary_line(line)
        if label:
            current_label = label
            if content:
                fields.setdefault(current_label, []).append(content)
            else:
                fields.setdefault(current_label, [])
            continue
        if current_label:
            fields.setdefault(current_label, []).append(_strip_list_marker(line))
        else:
            fields.setdefault("变更内容", []).append(_strip_list_marker(line))
    return fields


def _split_summary_line(line: str) -> tuple[str, str]:
    for sep in ("：", ":"):
        if sep not in line:
            continue
        raw_label, raw_content = line.split(sep, 1)
        label = _normalize_label(raw_label)
        if label:
            return label, _strip_list_marker(raw_content.strip())
    return "", ""


def _normalize_label(label: str) -> str:
    cleaned = label.strip().strip("[]【】")
    aliases = {
        "原因": "原因",
        "根本原因": "原因",
        "问题": "原因",
        "背景": "原因",
        "修复": "修复",
        "修复方式": "修复方式",
        "怎么修": "修复方式",
        "方式": "修复方式",
        "实现": "修复方式",
        "实现方式": "修复方式",
        "新增": "新增能力",
        "新增能力": "新增能力",
        "功能": "新增能力",
        "使用": "使用方式",
        "用法": "使用方式",
        "使用方式": "使用方式",
        "影响": "影响范围",
        "影响范围": "影响范围",
        "调整": "结构变化",
        "结构": "结构变化",
        "结构变化": "结构变化",
        "行为": "行为影响",
        "行为影响": "行为影响",
        "变更": "变更内容",
        "变更内容": "变更内容",
        "说明": "补充说明",
        "补充": "补充说明",
        "补充说明": "补充说明",
        "验证": "验证",
    }
    return aliases.get(cleaned, "")


def _strip_list_marker(text: str) -> str:
    return re.sub(r"^(?:[-*]\s*|\d+[.)、]\s*)", "", text).strip()


def _build_type_sections(commit_type: str, fields: dict[str, list[str]]) -> list[str]:
    if commit_type == "修复":
        return _sections([
            ("根本原因", _collect(fields, "原因")),
            ("修复方式", _collect(fields, "修复方式", "修复")),
            ("验证", _collect(fields, "验证")),
        ])
    if commit_type == "功能":
        return _sections([
            ("背景原因", _collect(fields, "原因")),
            ("新增能力", _collect(fields, "新增能力", "修复", "变更内容")),
            ("使用方式", _collect(fields, "使用方式", "修复方式")),
            ("影响范围", _collect(fields, "影响范围")),
            ("验证", _collect(fields, "验证")),
        ])
    if commit_type == "重构":
        return _sections([
            ("调整原因", _collect(fields, "原因")),
            ("结构变化", _collect(fields, "结构变化", "修复方式", "变更内容")),
            ("行为影响", _collect(fields, "行为影响", "影响范围")),
            ("验证", _collect(fields, "验证")),
        ])
    return _sections([
        ("变更内容", _collect(fields, "变更内容", "新增能力", "修复")),
        ("补充说明", _collect(fields, "补充说明", "修复方式", "影响范围")),
        ("验证", _collect(fields, "验证")),
    ])


def _collect(fields: dict[str, list[str]], *labels: str) -> list[str]:
    result: list[str] = []
    for label in labels:
        result.extend(item for item in fields.get(label, []) if item)
    return result


def _sections(sections: list[tuple[str, list[str]]]) -> list[str]:
    lines: list[str] = []
    for title, items in sections:
        if not items:
            continue
        lines.extend(["", f"{title}："])
        if len(items) == 1:
            lines.append(items[0])
        else:
            lines.extend(f"{index}.{item}" for index, item in enumerate(items, start=1))
    return lines


def _load_last_published_sha(
    group_id: int,
    *,
    data_root: str | Path | None = None,
) -> str:
    path = _last_published_sha_path(group_id, data_root=data_root)
    if not path.is_file():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    sha256 = payload.get("sha256")
    return sha256.strip().lower() if isinstance(sha256, str) else ""


def _last_published_sha_path(
    group_id: int,
    *,
    data_root: str | Path | None = None,
) -> Path:
    if data_root is None:
        raise ValueError("data_root is required")
    root = normalize_local_path(data_root)
    return root / "fe_artifacts" / f"{group_id}.json"


def _load_last_local_artifact_published_sha(
    group_id: int,
    file_name: str,
    *,
    data_root: str | Path | None = None,
) -> str:
    path = _last_local_artifact_published_sha_path(group_id, file_name, data_root=data_root)
    if not path.is_file():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if payload.get("name") != file_name:
        return ""
    sha256 = payload.get("server_content_sha256") or payload.get("content_sha256") or payload.get("sha256")
    return sha256.strip().lower() if isinstance(sha256, str) else ""


def _last_local_artifact_published_sha_path(
    group_id: int,
    file_name: str,
    *,
    data_root: str | Path | None = None,
) -> Path:
    if data_root is None:
        raise ValueError("data_root is required")
    root = normalize_local_path(data_root)
    name_key = hashlib.sha256(file_name.encode("utf-8")).hexdigest()
    return root / "local_artifacts" / str(group_id) / f"{name_key}.json"


def _run_git(repo_path: Path, *args: str) -> str:
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


def _extract_group_files(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        for key in ("files", "file", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _first_text(file_info: dict[str, Any], *keys: str) -> str:
    value = _first_value(file_info, *keys)
    return "" if value is None else str(value)


def _first_value(file_info: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in file_info:
            return file_info[key]
    return None
