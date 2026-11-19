"""Per-category plan for the local meme library: quotas, merges and archiving."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from astrbot.api import logger

from .config import MEMES_DATA_PATH, MEMES_DIR, PLUGIN_DATA_DIR
from .local_index import load_meme_index, save_meme_index, upsert_image_metadata

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp")
ARCHIVE_DIR = Path(PLUGIN_DATA_DIR) / "archive"
ARCHIVE_MANIFEST_NAME = "archive.json"
SCORE_VERSION = 1
DEFAULT_QUOTA = 12
TIE_MARGIN = 5.0

CATEGORY_QUOTAS: dict[str, int] = {
    # 主力情绪
    "affection_kiss": 20,
    "shy_flirt": 20,
    "confused_question": 20,
    "sad_cry": 20,
    "angry_dislike": 20,
    "happy_cheer": 20,
    "shocked_surprise": 20,
    "funny_laugh": 20,
    "tired_defeated": 20,
    "troll_funny": 20,
    "awkward_silence": 20,
    "cute_begging_trade": 20,
    # 一般
    "see": 12,
    "reject_no": 12,
    "sleep_rest": 12,
    "boss_worship": 12,
    "touch_rua": 12,
    "food_eat": 12,
    "fear_panic": 12,
    "slap_warning": 12,
    "self_noob": 12,
    "rhythm_game_pressure": 12,
    # 冷门
    "agreement_yes": 6,
    "apology_sorry": 6,
    "polite_awkward_smile": 6,
    "no_need": 6,
    "game_invite": 6,
}

CATEGORY_MERGES: dict[str, str] = {
    "angry": "angry_dislike",
    "confused": "confused_question",
    "surprised": "shocked_surprise",
    "sad": "sad_cry",
    "happy": "happy_cheer",
    "sigh": "tired_defeated",
    "shy": "shy_flirt",
    "sleep": "sleep_rest",
    "morning": "sleep_rest",
    "meow": "cute_begging_trade",
    "like": "affection_kiss",
    "fool": "self_noob",
    "baka": "self_noob",
    "boss_feed": "boss_worship",
    "hug_comfort": "touch_rua",
    "cpu": "confused_question",
}

CATEGORY_ARCHIVE_ALL: tuple[str, ...] = (
    "misc_review",
    "suggestive_warning",
    "sensitive_payment_do_not_send",
    "color",
    "givemoney",
    "reply",
)


def quota_of(category: str) -> int:
    """Return the image quota of one category.

    Args:
        category: Category directory name.

    Returns:
        Configured quota, or the default quota for unlisted categories.
    """
    return CATEGORY_QUOTAS.get(category, DEFAULT_QUOTA)


def recency_bonus(entry: dict) -> float:
    """Return the freshness bonus that lets new memes compete with old ones.

    Args:
        entry: Library index entry.

    Returns:
        Bonus added to the stored score; it fades out as the image ages.
    """
    added_at = float(entry.get("added_at") or 0)
    if not added_at:
        return 0.0
    age_days = max(0.0, (time.time() - added_at) / 86400)
    if age_days < 7:
        return 10.0
    if age_days < 30:
        return 5.0
    return 0.0


def rank_of(entry: dict) -> float:
    """Return the ranking value used to compare memes inside one category.

    Args:
        entry: Library index entry.

    Returns:
        Stored total score plus freshness bonus; unscored entries rank lowest.
    """
    score = entry.get("score")
    total = float(score.get("total") or 0) if isinstance(score, dict) else 0.0
    return total + recency_bonus(entry)


def archive_image(category: str, filename: str, *, reason: str, note: str = "") -> bool:
    """Move one image out of the library into the per-category archive.

    Args:
        category: Category the image currently belongs to.
        filename: Image file name inside that category.
        reason: Short tag recorded in the archive manifest.
        note: Optional extra explanation.

    Returns:
        True when the file was moved and its index entry removed.
    """
    name = Path(filename).name
    source = Path(MEMES_DIR) / category / name
    target_dir = ARCHIVE_DIR / category
    record = _archive_record(category, name, reason, note)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        if source.is_file():
            target = target_dir / name
            if target.exists():
                target = target_dir / f"{Path(name).stem}-{int(time.time())}{Path(name).suffix}"
            shutil.move(str(source), str(target))
            record["filename"] = target.name
    except Exception as exc:
        logger.warning("[MemeArchive] archive failed: error_type=%s", type(exc).__name__)
        return False
    _append_manifest(target_dir, record)
    _drop_index_entry(category, name)
    logger.info("[MemeArchive] archived: category=%s filename=%s reason=%s", category, name, reason)
    return True


def trim_category(category: str) -> int:
    """Archive the lowest ranked images until one category fits its quota.

    Args:
        category: Category directory name.

    Returns:
        Number of archived images.
    """
    quota = quota_of(category)
    index = load_meme_index()
    members = [
        entry
        for entry in index.get("images", [])
        if isinstance(entry, dict) and entry.get("category") == category
    ]
    excess = len(members) - quota
    if excess <= 0:
        return 0
    scored = [entry for entry in members if isinstance(entry.get("score"), dict)]
    if not scored:
        return 0
    scored.sort(key=rank_of)
    archived = 0
    for entry in scored[:excess]:
        if archive_image(category, str(entry.get("filename") or ""), reason="over_quota"):
            archived += 1
    return archived


def apply_category_plan() -> dict[str, int]:
    """Apply category merges and retire categories that must leave the library.

    Returns:
        Counts of retired, merged and duplicate images.
    """
    stats = {"retired": 0, "merged": 0, "duplicate": 0}
    memes_root = Path(MEMES_DIR)
    index = load_meme_index()
    entries = {
        (str(entry.get("category")), str(entry.get("filename"))): entry
        for entry in index.get("images", [])
        if isinstance(entry, dict)
    }
    removed_keys: set[tuple[str, str]] = set()

    for category in CATEGORY_ARCHIVE_ALL:
        category_dir = memes_root / category
        if not category_dir.is_dir():
            continue
        for path in sorted(category_dir.iterdir()):
            if not path.is_file() or not _is_supported(path.name):
                continue
            if _move_to_archive(category, path.name, entries.get((category, path.name)), "category_retired"):
                removed_keys.add((category, path.name))
                stats["retired"] += 1
        _remove_empty_dir(category_dir)

    for source, target in CATEGORY_MERGES.items():
        source_dir = memes_root / source
        if not source_dir.is_dir():
            continue
        target_dir = memes_root / target
        target_dir.mkdir(parents=True, exist_ok=True)
        for path in sorted(source_dir.iterdir()):
            if not path.is_file() or not _is_supported(path.name):
                continue
            if (target_dir / path.name).exists():
                if _move_to_archive(source, path.name, entries.get((source, path.name)), "duplicate_after_merge"):
                    removed_keys.add((source, path.name))
                    stats["duplicate"] += 1
                continue
            shutil.move(str(path), str(target_dir / path.name))
            entry = entries.get((source, path.name))
            if entry is not None:
                entry["category"] = target
                entry["relative_path"] = f"memes/{target}/{path.name}"
            stats["merged"] += 1
        _remove_empty_dir(source_dir)

    if removed_keys:
        index["images"] = [
            entry
            for entry in index.get("images", [])
            if not (
                isinstance(entry, dict)
                and (str(entry.get("category")), str(entry.get("filename"))) in removed_keys
            )
        ]
    if removed_keys or stats["merged"]:
        save_meme_index(index)
    _prune_retired_metadata(set(CATEGORY_ARCHIVE_ALL) | set(CATEGORY_MERGES))
    _resync_missing_entries()
    if any(stats.values()):
        logger.info(
            "[MemeArchive] category plan applied: retired=%s merged=%s duplicate=%s",
            stats["retired"], stats["merged"], stats["duplicate"],
        )
    return stats


def _prune_retired_metadata(retired: set[str]) -> None:
    """Drop retired categories from the index and from the tag descriptions."""
    index = load_meme_index()
    live = {str(entry.get("category")) for entry in index.get("images", []) if isinstance(entry, dict)}
    categories = index.get("categories")
    if isinstance(categories, dict):
        stale = [name for name in categories if name in retired and name not in live]
        for name in stale:
            categories.pop(name, None)
        if stale:
            save_meme_index(index)

    path = Path(MEMES_DATA_PATH)
    if not path.is_file():
        return
    try:
        descriptions = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(descriptions, dict):
        return
    changed = False
    for name in list(descriptions):
        if name in retired and name not in live:
            descriptions.pop(name, None)
            changed = True
    if changed:
        path.write_text(json.dumps(descriptions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _resync_missing_entries() -> int:
    """Re-add files that exist on disk but lost their index entry."""
    index = load_meme_index()
    known = {
        (str(entry.get("category")), str(entry.get("filename")))
        for entry in index.get("images", [])
        if isinstance(entry, dict)
    }
    missing: list[tuple[str, str]] = []
    for category_dir in sorted(Path(MEMES_DIR).iterdir()):
        if not category_dir.is_dir():
            continue
        for path in sorted(category_dir.iterdir()):
            if not path.is_file() or not _is_supported(path.name):
                continue
            if (category_dir.name, path.name) not in known:
                missing.append((category_dir.name, path.name))
    for category, filename in missing:
        upsert_image_metadata(category, filename)
    if missing:
        logger.info("[MemeArchive] re-added %s untracked images to the index", len(missing))
    return len(missing)


def _move_to_archive(category: str, filename: str, entry: dict | None, reason: str) -> bool:
    """Move one file into the archive without touching the index."""
    source = Path(MEMES_DIR) / category / filename
    target_dir = ARCHIVE_DIR / category
    record = _archive_record(category, filename, reason, "")
    if isinstance(entry, dict):
        record["score"] = entry.get("score")
        record["title"] = entry.get("title")
        record["added_at"] = entry.get("added_at")
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / filename
        if target.exists():
            target = target_dir / f"{Path(filename).stem}-{int(time.time())}{Path(filename).suffix}"
        shutil.move(str(source), str(target))
        record["filename"] = target.name
    except Exception as exc:
        logger.warning("[MemeArchive] archive failed: error_type=%s", type(exc).__name__)
        return False
    _append_manifest(target_dir, record)
    return True


def _archive_record(category: str, filename: str, reason: str, note: str) -> dict:
    """Build one archive manifest record."""
    record = {
        "filename": Path(filename).name,
        "category": category,
        "reason": reason,
        "archived_at": int(time.time()),
    }
    if note:
        record["note"] = note
    return record


def _append_manifest(target_dir: Path, record: dict) -> None:
    """Append one record to the archive manifest of a category."""
    path = target_dir / ARCHIVE_MANIFEST_NAME
    records: list = []
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                records = loaded
        except Exception:
            records = []
    records.append(record)
    try:
        path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        logger.warning("[MemeArchive] manifest write failed: error_type=%s", type(exc).__name__)


def _drop_index_entry(category: str, filename: str) -> None:
    """Remove one image entry from the library index."""
    index = load_meme_index()
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


def _is_supported(filename: str) -> bool:
    """Return whether the file name is a supported image."""
    return Path(filename).suffix.lower() in IMAGE_EXTENSIONS


def _remove_empty_dir(path: Path) -> None:
    """Remove a category directory when nothing is left in it."""
    try:
        path.rmdir()
    except OSError:
        pass
