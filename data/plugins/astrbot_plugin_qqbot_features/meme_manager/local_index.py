import hashlib
import json
import logging
import random
import re
import shutil
import time
from pathlib import Path
from typing import Any

from .config import MEMES_DATA_PATH, MEMES_DIR, PLUGIN_DATA_DIR

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp")
MEME_INDEX_PATH = Path(PLUGIN_DATA_DIR) / "meme_index.json"
RECENT_SELECTION_LIMIT = 80
RECENT_SELECTION_TTL_SECONDS = 60 * 60 * 6

_recent_selections: list[tuple[float, str]] = []


def load_meme_index() -> dict[str, Any]:
    if not MEME_INDEX_PATH.is_file():
        index = build_index_from_filesystem()
        save_meme_index(index)
        return index

    try:
        raw = json.loads(MEME_INDEX_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("读取表情索引失败，回退到文件系统扫描: %s", exc)
        raw = {}

    return normalize_index(raw)


def save_meme_index(index: dict[str, Any]) -> None:
    MEME_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    normalized = normalize_index(index)
    MEME_INDEX_PATH.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build_index_from_filesystem() -> dict[str, Any]:
    categories: dict[str, dict[str, Any]] = {}
    images: list[dict[str, Any]] = []
    descriptions = _load_category_descriptions()
    memes_root = Path(MEMES_DIR)

    if not memes_root.is_dir():
        memes_root.mkdir(parents=True, exist_ok=True)

    for category_dir in sorted(path for path in memes_root.iterdir() if path.is_dir()):
        category = category_dir.name
        categories[category] = {
            "label": category,
            "description": descriptions.get(category, ""),
            "use_cases": [],
            "avoid_when": [],
            "auto_send_enabled": True,
        }
        for image_path in sorted(category_dir.iterdir()):
            if not image_path.is_file() or not _is_supported_image(image_path.name):
                continue
            sha256 = _safe_sha256(image_path)
            images.append(
                {
                    "id": _entry_id(category, image_path.name, sha256),
                    "category": category,
                    "filename": image_path.name,
                    "relative_path": f"memes/{category}/{image_path.name}",
                    "title": image_path.stem,
                    "content_caption": "",
                    "use_cases": [],
                    "emotion_tags": [],
                    "intensity": 2,
                    "avoid_when": [],
                    "auto_send_enabled": True,
                    "weight": 1.0,
                    "sha256": sha256,
                }
            )

    return normalize_index(
        {
            "schema_version": 1,
            "source": "meme_manager_filesystem",
            "updated_at": int(time.time()),
            "categories": categories,
            "images": images,
        }
    )


def migrate_mlj_pack_index(source_index_path: Path) -> dict[str, Any]:
    if not source_index_path.is_file():
        raise FileNotFoundError(f"missing mlj_pack index: {source_index_path}")

    source_root = source_index_path.parent
    source = json.loads(source_index_path.read_text(encoding="utf-8"))
    current = load_meme_index()
    categories = current.setdefault("categories", {})
    images = current.setdefault("images", [])
    by_hash = {
        str(entry.get("sha256") or ""): entry
        for entry in images
        if isinstance(entry, dict) and entry.get("sha256")
    }
    by_category_file = {
        (str(entry.get("category") or ""), str(entry.get("filename") or "")): entry
        for entry in images
        if isinstance(entry, dict)
    }

    copied = 0
    updated = 0
    skipped_missing = 0
    source_categories = source.get("categories", {})
    if isinstance(source_categories, dict):
        for category, metadata in source_categories.items():
            if not isinstance(metadata, dict):
                continue
            category_payload = categories.setdefault(str(category), {})
            category_payload.update(
                {
                    "label": str(metadata.get("label") or category),
                    "description": str(metadata.get("description") or ""),
                    "use_cases": _string_list(metadata.get("use_cases")),
                    "avoid_when": _string_list(metadata.get("avoid_when")),
                    "auto_send_enabled": bool(metadata.get("auto_send_enabled", True)),
                }
            )

    for source_entry in source.get("images", []):
        if not isinstance(source_entry, dict):
            continue

        category = str(source_entry.get("category") or "").strip()
        relative_path = str(source_entry.get("relative_path") or "").strip()
        if not category or not relative_path:
            continue

        source_file = source_root / relative_path
        if not source_file.is_file():
            skipped_missing += 1
            continue

        target_dir = Path(MEMES_DIR) / category
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = _available_path(target_dir / source_file.name)
        sha256 = str(source_entry.get("sha256") or "") or _safe_sha256(source_file)
        existing = by_hash.get(sha256)
        if existing is None:
            existing = by_category_file.get((category, source_file.name))

        if existing is None:
            shutil.copy2(source_file, target_path)
            copied += 1
            entry = _entry_from_mlj_pack(source_entry, target_path.name, sha256)
            images.append(entry)
            by_hash[sha256] = entry
            by_category_file[(entry["category"], entry["filename"])] = entry
            continue

        existing_filename = Path(str(existing.get("filename") or source_file.name)).name
        existing_path = Path(MEMES_DIR) / category / existing_filename
        if not existing_path.is_file():
            repaired_path = _available_path(existing_path)
            shutil.copy2(source_file, repaired_path)
            existing_filename = repaired_path.name
            copied += 1

        existing.update(
            _entry_from_mlj_pack(source_entry, existing_filename, sha256)
        )
        updated += 1

    normalized = normalize_index(current)
    normalized["source"] = "meme_manager_migrated_mlj_pack"
    normalized["updated_at"] = int(time.time())
    normalized["migration"] = {
        "source_index": str(source_index_path),
        "copied": copied,
        "updated": updated,
        "skipped_missing": skipped_missing,
    }
    save_meme_index(normalized)
    sync_category_descriptions_from_index(normalized)
    return normalized["migration"]


def sync_category_descriptions_from_index(index: dict[str, Any] | None = None) -> None:
    index = index or load_meme_index()
    descriptions: dict[str, str] = {}
    for category, metadata in index.get("categories", {}).items():
        if not isinstance(metadata, dict):
            continue
        description = str(metadata.get("description") or "").strip()
        use_cases = "、".join(_string_list(metadata.get("use_cases")))
        avoid_when = "、".join(_string_list(metadata.get("avoid_when")))
        label = str(metadata.get("label") or category)
        parts = [f"{label}：{description}" if description else label]
        if use_cases:
            parts.append(f"适用：{use_cases}")
        if avoid_when:
            parts.append(f"避免：{avoid_when}")
        descriptions[str(category)] = "。".join(parts)

    Path(MEMES_DATA_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(MEMES_DATA_PATH).write_text(
        json.dumps(descriptions, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def upsert_image_metadata(category: str, filename: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    index = load_meme_index()
    _ensure_category_payload(index, category)
    entry = _find_entry(index, category, filename)
    image_path = Path(MEMES_DIR) / category / Path(filename).name
    if entry is None:
        sha256 = _safe_sha256(image_path) if image_path.is_file() else ""
        entry = {
            "id": _entry_id(category, filename, sha256),
            "category": category,
            "filename": Path(filename).name,
            "relative_path": f"memes/{category}/{Path(filename).name}",
            "title": Path(filename).stem,
            "content_caption": "",
            "use_cases": [],
            "emotion_tags": [],
            "intensity": 2,
            "avoid_when": [],
            "auto_send_enabled": True,
            "weight": 1.0,
            "sha256": sha256,
        }
        index.setdefault("images", []).append(entry)

    if metadata:
        for key in (
            "title",
            "content_caption",
            "use_cases",
            "emotion_tags",
            "avoid_when",
            "auto_send_enabled",
            "weight",
        ):
            if key not in metadata:
                continue
            if key in {"use_cases", "emotion_tags", "avoid_when"}:
                entry[key] = _string_list(metadata[key])
            elif key == "auto_send_enabled":
                entry[key] = bool(metadata[key])
            elif key == "weight":
                entry[key] = _safe_float(metadata[key], 1.0)
            else:
                entry[key] = str(metadata[key] or "").strip()
        if "intensity" in metadata:
            entry["intensity"] = max(1, min(5, int(_safe_float(metadata["intensity"], 2))))

    entry["category"] = category
    entry["filename"] = Path(filename).name
    entry["relative_path"] = f"memes/{category}/{Path(filename).name}"
    save_meme_index(index)
    return entry


def remove_image_metadata(category: str, filename: str) -> None:
    index = load_meme_index()
    filename = Path(filename).name
    index["images"] = [
        entry
        for entry in index.get("images", [])
        if not (
            isinstance(entry, dict)
            and entry.get("category") == category
            and entry.get("filename") == filename
        )
    ]
    save_meme_index(index)


def move_image_metadata(source_category: str, filename: str, target_category: str, target_filename: str | None = None) -> None:
    index = load_meme_index()
    entry = _find_entry(index, source_category, filename)
    if entry is None:
        return
    _ensure_category_payload(index, target_category)
    final_filename = Path(target_filename or filename).name
    entry["category"] = target_category
    entry["filename"] = final_filename
    entry["relative_path"] = f"memes/{target_category}/{final_filename}"
    save_meme_index(index)


def rename_category_metadata(old_name: str, new_name: str) -> None:
    index = load_meme_index()
    categories = index.setdefault("categories", {})
    if old_name in categories:
        categories[new_name] = categories.pop(old_name)
    for entry in index.get("images", []):
        if isinstance(entry, dict) and entry.get("category") == old_name:
            entry["category"] = new_name
            entry["relative_path"] = f"memes/{new_name}/{entry.get('filename', '')}"
    save_meme_index(index)


def delete_category_metadata(category: str) -> None:
    index = load_meme_index()
    index.setdefault("categories", {}).pop(category, None)
    index["images"] = [
        entry
        for entry in index.get("images", [])
        if not (isinstance(entry, dict) and entry.get("category") == category)
    ]
    save_meme_index(index)


def ensure_category_metadata(category: str, description: str = "") -> None:
    index = load_meme_index()
    payload = _ensure_category_payload(index, category)
    if description and not str(payload.get("description") or "").strip():
        payload["description"] = description
    save_meme_index(index)


def update_category_metadata(category: str, metadata: dict[str, Any]) -> None:
    index = load_meme_index()
    payload = _ensure_category_payload(index, category)
    for key in ("label", "description", "use_cases", "avoid_when", "auto_send_enabled"):
        if key not in metadata:
            continue
        if key in {"use_cases", "avoid_when"}:
            payload[key] = _string_list(metadata[key])
        elif key == "auto_send_enabled":
            payload[key] = bool(metadata[key])
        else:
            payload[key] = str(metadata[key] or "").strip()
    save_meme_index(index)
    sync_category_descriptions_from_index(index)


def export_index_for_api() -> dict[str, Any]:
    index = load_meme_index()
    return normalize_index(index)


def select_meme_for_emotion(emotion: str, context_text: str = "") -> Path | None:
    index = load_meme_index()
    category_meta = index.get("categories", {}).get(emotion, {})
    if isinstance(category_meta, dict) and category_meta.get("auto_send_enabled") is False:
        return None

    candidates = [
        entry
        for entry in index.get("images", [])
        if isinstance(entry, dict)
        and entry.get("category") == emotion
        and entry.get("auto_send_enabled", True) is True
    ]
    candidates = [
        entry
        for entry in candidates
        if (Path(MEMES_DIR) / emotion / str(entry.get("filename") or "")).is_file()
    ]
    if not candidates:
        return None

    _prune_recent()
    scored = [(max(0.1, _score_entry(entry, context_text)), entry) for entry in candidates]
    fresh_scored = [
        pair
        for pair in scored
        if _recent_key(pair[1]) not in {recent_key for _, recent_key in _recent_selections[-20:]}
    ]
    if fresh_scored:
        scored = fresh_scored

    selected = _weighted_choice(scored)
    if selected is None:
        return None
    _remember_recent(selected)
    return Path(MEMES_DIR) / emotion / str(selected.get("filename") or "")


def normalize_index(raw: dict[str, Any]) -> dict[str, Any]:
    categories = raw.get("categories")
    if not isinstance(categories, dict):
        categories = {}
    images = raw.get("images")
    if not isinstance(images, list):
        images = []

    normalized_images = []
    for entry in images:
        if not isinstance(entry, dict):
            continue
        category = str(entry.get("category") or "").strip()
        filename = Path(str(entry.get("filename") or Path(str(entry.get("relative_path") or "")).name)).name
        if not category or not filename:
            continue
        normalized = dict(entry)
        normalized["category"] = category
        normalized["filename"] = filename
        normalized["relative_path"] = f"memes/{category}/{filename}"
        normalized["title"] = str(normalized.get("title") or Path(filename).stem)
        normalized["content_caption"] = str(normalized.get("content_caption") or "")
        normalized["use_cases"] = _string_list(normalized.get("use_cases"))
        normalized["emotion_tags"] = _string_list(normalized.get("emotion_tags"))
        normalized["avoid_when"] = _string_list(normalized.get("avoid_when"))
        normalized["auto_send_enabled"] = bool(normalized.get("auto_send_enabled", True))
        normalized["weight"] = _safe_float(normalized.get("weight"), 1.0)
        normalized["intensity"] = max(1, min(5, int(_safe_float(normalized.get("intensity"), 2))))
        normalized["sha256"] = str(normalized.get("sha256") or "")
        normalized["id"] = str(normalized.get("id") or _entry_id(category, filename, normalized["sha256"]))
        normalized_images.append(normalized)
        categories.setdefault(
            category,
            {
                "label": category,
                "description": "",
                "use_cases": [],
                "avoid_when": [],
                "auto_send_enabled": True,
            },
        )

    for category, metadata in list(categories.items()):
        if not isinstance(metadata, dict):
            categories[category] = {
                "label": str(category),
                "description": "",
                "use_cases": [],
                "avoid_when": [],
                "auto_send_enabled": True,
            }
            continue
        metadata.setdefault("label", str(category))
        metadata.setdefault("description", "")
        metadata["use_cases"] = _string_list(metadata.get("use_cases"))
        metadata["avoid_when"] = _string_list(metadata.get("avoid_when"))
        metadata["auto_send_enabled"] = bool(metadata.get("auto_send_enabled", True))

    return {
        **raw,
        "schema_version": 1,
        "updated_at": int(time.time()),
        "categories": dict(sorted(categories.items())),
        "images": sorted(
            normalized_images,
            key=lambda item: (str(item.get("category")), str(item.get("filename"))),
        ),
    }


def _load_category_descriptions() -> dict[str, str]:
    path = Path(MEMES_DATA_PATH)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items()}


def _entry_from_mlj_pack(source_entry: dict[str, Any], filename: str, sha256: str) -> dict[str, Any]:
    category = str(source_entry.get("category") or "")
    return {
        "id": str(source_entry.get("id") or _entry_id(category, filename, sha256)),
        "category": category,
        "filename": Path(filename).name,
        "relative_path": f"memes/{category}/{Path(filename).name}",
        "title": str(source_entry.get("title") or Path(filename).stem),
        "content_caption": str(source_entry.get("content_caption") or ""),
        "use_cases": _string_list(source_entry.get("use_cases")),
        "emotion_tags": _string_list(source_entry.get("emotion_tags")),
        "intensity": max(1, min(5, int(_safe_float(source_entry.get("intensity"), 2)))),
        "avoid_when": _string_list(source_entry.get("avoid_when")),
        "auto_send_enabled": bool(source_entry.get("auto_send_enabled", True)),
        "weight": _safe_float(source_entry.get("weight"), 1.0),
        "sha256": sha256,
        "source_folder": str(source_entry.get("source_folder") or ""),
        "source_file": str(source_entry.get("source_file") or ""),
        "source_path": str(source_entry.get("source_path") or ""),
        "source_windows_path": str(source_entry.get("source_windows_path") or ""),
        "classification_basis": str(source_entry.get("classification_basis") or ""),
    }


def _find_entry(index: dict[str, Any], category: str, filename: str) -> dict[str, Any] | None:
    filename = Path(filename).name
    for entry in index.get("images", []):
        if (
            isinstance(entry, dict)
            and entry.get("category") == category
            and entry.get("filename") == filename
        ):
            return entry
    return None


def _ensure_category_payload(index: dict[str, Any], category: str) -> dict[str, Any]:
    categories = index.setdefault("categories", {})
    payload = categories.setdefault(
        category,
        {
            "label": category,
            "description": "",
            "use_cases": [],
            "avoid_when": [],
            "auto_send_enabled": True,
        },
    )
    if not isinstance(payload, dict):
        payload = {
            "label": category,
            "description": "",
            "use_cases": [],
            "avoid_when": [],
            "auto_send_enabled": True,
        }
        categories[category] = payload
    payload.setdefault("label", category)
    payload.setdefault("description", "")
    payload["use_cases"] = _string_list(payload.get("use_cases"))
    payload["avoid_when"] = _string_list(payload.get("avoid_when"))
    payload["auto_send_enabled"] = bool(payload.get("auto_send_enabled", True))
    return payload


def _score_entry(entry: dict[str, Any], context_text: str) -> float:
    context = _tokenize(context_text)
    score = _safe_float(entry.get("weight"), 1.0)
    fields = []
    fields.extend(_string_list(entry.get("emotion_tags")))
    fields.extend(_string_list(entry.get("use_cases")))
    fields.append(str(entry.get("title") or ""))
    fields.append(str(entry.get("content_caption") or ""))
    haystack = " ".join(fields).lower()

    for token in context:
        if token and token in haystack:
            score += 2.0

    avoid_text = " ".join(_string_list(entry.get("avoid_when"))).lower()
    for token in context:
        if token and token in avoid_text:
            score -= 3.0

    intensity = max(1, min(5, int(_safe_float(entry.get("intensity"), 2))))
    if len(context_text) <= 12 and intensity <= 3:
        score += 0.6
    if len(context_text) > 80 and intensity >= 4:
        score -= 0.8
    return max(0.1, score)


def _tokenize(text: str) -> set[str]:
    normalized = str(text or "").lower()
    tokens = set(re.findall(r"[a-z0-9_\-]{2,}|[\u4e00-\u9fff]{1,4}", normalized))
    return {token.strip() for token in tokens if token.strip()}


def _weighted_choice(scored_entries: list[tuple[float, dict[str, Any]]]) -> dict[str, Any] | None:
    if not scored_entries:
        return None
    total = sum(score for score, _ in scored_entries)
    marker = random.uniform(0, total)
    current = 0.0
    for score, entry in scored_entries:
        current += score
        if current >= marker:
            return entry
    return scored_entries[-1][1]


def _remember_recent(entry: dict[str, Any]) -> None:
    _recent_selections.append((time.time(), _recent_key(entry)))
    del _recent_selections[:-RECENT_SELECTION_LIMIT]


def _prune_recent() -> None:
    now = time.time()
    _recent_selections[:] = [
        item for item in _recent_selections if now - item[0] <= RECENT_SELECTION_TTL_SECONDS
    ]


def _recent_key(entry: dict[str, Any]) -> str:
    return f"{entry.get('category')}::{entry.get('filename')}"


def _is_supported_image(filename: str) -> bool:
    return filename.lower().endswith(IMAGE_EXTENSIONS)


def _safe_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _available_path(path: Path) -> Path:
    if not path.exists():
        return path
    suffix = path.suffix
    stem = path.stem
    index = 1
    while True:
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def _entry_id(category: str, filename: str, sha256: str) -> str:
    digest = (
        sha256[:8]
        if sha256
        else hashlib.sha256(f"{category}/{filename}".encode()).hexdigest()[:8]
    )
    return f"{category}-{Path(filename).stem}-{digest}"


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,，;；、\n]", value) if part.strip()]
    return []


def _safe_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
