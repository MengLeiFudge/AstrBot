"""Per-category plan for the local meme library: quotas, merges and archiving."""

from __future__ import annotations

import io
import json
import re
import shutil
import time
import uuid
from pathlib import Path

from PIL import Image as PILImage

from astrbot.api import logger

from .config import MEMES_DATA_PATH, MEMES_DIR, PLUGIN_DATA_DIR
from .local_index import load_meme_index, record_image_score, save_meme_index, upsert_image_metadata

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp")
ARCHIVE_DIR = Path(PLUGIN_DATA_DIR) / "archive"
_STAMP_SUFFIX = re.compile(r"(?:-\d{10})+$")


def _unique_target(directory: Path, name: str) -> Path:
    """Pick a free file name inside one directory without stacking timestamp suffixes."""
    stem = _STAMP_SUFFIX.sub("", Path(name).stem) or Path(name).stem
    suffix = Path(name).suffix
    candidate = directory / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    for _ in range(20):
        candidate = directory / f"{stem}-{uuid.uuid4().hex[:6]}{suffix}"
        if not candidate.exists():
            return candidate
    return directory / f"{stem}-{uuid.uuid4().hex}{suffix}"
ARCHIVE_MANIFEST_NAME = "archive.json"
# 风控不合格的图不归档，单独进审核队列等人工定夺
REVIEW_DIR = Path(PLUGIN_DATA_DIR) / "review_queue"
REVIEW_MANIFEST_NAME = "review.json"
REVIEW_RULES = (
    "gore",
    "real_person",
    "screenshot",
    "personal_info",
    "ad",
    "watermark",
    "unrecognizable",
)
SCORE_VERSION = 1
DEFAULT_QUOTA = 12
TIE_MARGIN = 5.0
MIN_ENTRY_TOTAL = 55
CAPTION_SIMILARITY = 0.7
PHASH_MAX_DISTANCE = 6
# 私密分类：只能在跟主人聊天时发，云栖不往群里自动发；和普通分类一样受配额约束
PRIVATE_RULE_CATEGORY: dict[str, str] = {
    "sexual_suggestive": "private_flirt",
    "undress_meme": "private_intimate",
    "sexual_explicit": "private_explicit",
}
PRIVATE_CATEGORIES = tuple(dict.fromkeys(PRIVATE_RULE_CATEGORY.values()))
PRIVATE_CATEGORY = PRIVATE_CATEGORIES[0]
PRIVATE_LABELS: dict[str, tuple[str, str]] = {
    "private_flirt": ("暧昧调情", "调情、眼神、贴身但没露的图，适合发给对象；只能在跟主人聊天时发。"),
    "private_intimate": ("亲密接触", "睡衣、躺床、贴很近、脱衣梗这类亲密图；只能在跟主人聊天时发。"),
    "private_explicit": ("露点裸露", "明确露点或裸露；只能在跟主人聊天时发。"),
}

# 归档/归零分的具体原因，模型必须给出一条，人工审核页面按此分类
ARCHIVE_RULES: dict[str, str] = {
    "sexual_explicit": "露点或裸露",
    "sexual_suggestive": "性行为或强性暗示",
    "undress_meme": "脱衣、内衣或暴露梗",
    "gore": "恐怖血腥",
    "real_person": "真人照片",
    "screenshot": "聊天、评论或工作界面截图",
    "personal_info": "个人资料、证件或二维码",
    "ad": "广告或引流",
    "watermark": "水印盖住主体",
    "unrecognizable": "看不出情绪或糊到认不出",
    "low_quality": "画质低或压缩糊",
    "wrong_category": "分类不合适或不像表情包",
    "duplicate": "与库里已有图重复",
    "mockery": "嘲讽、阴阳怪气或内涵他人，不适合机器人用",
}
PRIVATE_RULES = ("sexual_explicit", "sexual_suggestive", "undress_meme")

CATEGORY_QUOTAS: dict[str, int] = {
    # 主力情绪
    "happy_cheer": 20,
    "angry_dislike": 20,
    "sad_cry": 20,
    "confused_stunned": 20,
    "awkward_silence": 20,
    "affection_kiss": 20,
    "see": 20,
    # 一般
    "confused_question": 12,
    "shocked_surprise": 12,
    "shy_flirt": 12,
    "fear_panic": 12,
    "disgust": 12,
    "tired_defeated": 12,
    "reject_no": 12,
    "agreement_yes": 12,
    # 冷门
    "boss_worship": 6,
    "apology_sorry": 6,
    # 私密分类：不自动发群，只在跟主人聊天时可用，同样按配额换图
    "private_flirt": 20,
    "private_intimate": 20,
    "private_explicit": 20,
}

CATEGORY_MERGES: dict[str, str] = {
    "angry": "angry_dislike",
    "confused": "confused_question",
    "surprised": "shocked_surprise",
    "sad": "sad_cry",
    "happy": "happy_cheer",
    "sigh": "tired_defeated",
    "shy": "shy_flirt",
    "sleep": "tired_defeated",
    "morning": "tired_defeated",
    "sleep_rest": "tired_defeated",
    "rest": "tired_defeated",
    "meow": "affection_kiss",
    "cute_begging_trade": "affection_kiss",
    "touch_rua": "affection_kiss",
    "polite_awkward_smile": "awkward_silence",
    "rhythm_game_pressure": "tired_defeated",
    "slap_warning": "angry_dislike",
    "food_eat": "see",
    "funny_laugh": "happy_cheer",
    "troll_funny": "happy_cheer",
    "fool": "happy_cheer",
    "no_need": "reject_no",
    "game_invite": "see",
    "self_noob": "see",
    "fear": "fear_panic",
    "angry_sulk": "angry_dislike",
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


def canonical_category(category: str) -> str:
    """Map a retired category to the one that took its place.

    Args:
        category: Category directory name, possibly retired.

    Returns:
        Current category name, falling back to the catch-all category.
    """
    seen = set()
    name = category
    while name in CATEGORY_MERGES and name not in seen:
        seen.add(name)
        name = CATEGORY_MERGES[name]
    if name in CATEGORY_QUOTAS:
        return name
    return "see" if "see" in CATEGORY_QUOTAS else name


def recency_bonus(entry: dict) -> float:
    """Return the freshness bonus: 15 points on day one, losing 0.5 a day until zero."""
    added_at = float(entry.get("added_at") or 0)
    if not added_at:
        return 0.0
    age_days = max(0.0, (time.time() - added_at) / 86400)
    return round(max(0.0, 15.0 - 0.5 * age_days), 1)


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


def total_of(entry: dict) -> int:
    """Return the stored total score of one entry, or 0 when it has none."""
    score = entry.get("score")
    return int(score.get("total") or 0) if isinstance(score, dict) else 0


def image_phash(content: bytes) -> str:
    """Return a 64-bit difference hash of the first frame, or empty when unreadable."""
    try:
        with PILImage.open(io.BytesIO(content)) as image:
            with image.convert("L").resize((9, 8)) as small:
                pixels = list(small.getdata())
    except Exception:
        return ""
    bits = 0
    for row in range(8):
        for column in range(8):
            bits = (bits << 1) | (1 if pixels[row * 9 + column] > pixels[row * 9 + column + 1] else 0)
    return f"{bits:016x}"


def phash_distance(left: str, right: str) -> int:
    """Return the Hamming distance of two stored hashes, or 64 when unusable."""
    try:
        return bin(int(left, 16) ^ int(right, 16)).count("1")
    except (TypeError, ValueError):
        return 64


def find_similar_caption(category: str, caption: str, entries: list[dict]) -> dict | None:
    """Return a same-category entry whose caption reads like the same joke."""
    grams = _caption_grams(caption)
    if not grams:
        return None
    for entry in entries:
        if not isinstance(entry, dict) or str(entry.get("category") or "") != category:
            continue
        other = _caption_grams(entry.get("title") or entry.get("content_caption") or "")
        if not other:
            continue
        if len(grams & other) / len(grams | other) >= CAPTION_SIMILARITY:
            return entry
    return None


def _caption_grams(caption: str) -> set[str]:
    """Split a caption into character bigrams so wording noise is tolerated."""
    text = re.sub(r"\s+", "", str(caption or ""))
    if len(text) < 4:
        return set()
    return {text[index:index + 2] for index in range(len(text) - 1)}


def archive_image(category: str, filename: str, *, reason: str, note: str = "", rule: str = "") -> bool:
    """Move one image out of the library into the per-category archive.

    Args:
        category: Category the image currently belongs to.
        filename: Image file name inside that category.
        reason: Short tag recorded in the archive manifest.
        note: Optional extra explanation.
        rule: Specific rule id from ``ARCHIVE_RULES``; the reviewer needs it to know why.

    Returns:
        True when the file was moved and its index entry removed.
    """
    name = Path(filename).name
    source = Path(MEMES_DIR) / category / name
    target_dir = ARCHIVE_DIR / category
    record = _archive_record(category, name, reason, note, rule)
    if not source.is_file():
        # 文件已经不在了：只清掉指向它的索引条目，不写归档清单
        logger.warning("[MemeArchive] source missing: category=%s filename=%s", category, name)
        _drop_index_entry(category, name)
        return False
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target = _unique_target(target_dir, name)
        shutil.move(str(source), str(target))
        record["filename"] = target.name
    except Exception as exc:
        logger.warning("[MemeArchive] archive failed: error_type=%s", type(exc).__name__)
        return False
    dropped = _drop_index_entry(category, name)
    if isinstance(dropped, dict):
        # 归档记录带上描述和分数，以后需要恢复时不用重读图
        record["title"] = dropped.get("title")
        record["score"] = dropped.get("score")
        record["added_at"] = dropped.get("added_at")
    _append_manifest(target_dir, record)
    logger.info("[MemeArchive] archived: category=%s filename=%s reason=%s", category, name, reason)
    return True


def send_to_review(category: str, filename: str, *, rule: str, note: str = "") -> bool:
    """Move a risk-flagged image into the review queue; the archive is only for low scores."""
    name = Path(filename).name
    source = Path(MEMES_DIR) / category / name
    target_dir = REVIEW_DIR / category
    if not source.is_file():
        logger.warning("[MemeReview] source missing: category=%s filename=%s", category, name)
        _drop_index_entry(category, name)
        return False
    record = _archive_record(category, name, "risk", note, rule)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target = _unique_target(target_dir, name)
        shutil.move(str(source), str(target))
        record["filename"] = target.name
    except Exception as exc:
        logger.warning("[MemeReview] queue failed: error_type=%s", type(exc).__name__)
        return False
    dropped = _drop_index_entry(category, name)
    if isinstance(dropped, dict):
        record["title"] = dropped.get("title")
        record["score"] = dropped.get("score")
        record["added_at"] = dropped.get("added_at")
    _append_manifest(target_dir, record, manifest=REVIEW_MANIFEST_NAME)
    logger.info("[MemeReview] queued: category=%s filename=%s rule=%s", category, name, rule)
    return True


def delete_image(category: str, filename: str) -> bool:
    """Delete a duplicate image outright; neither archive nor review queue keeps a copy."""
    name = Path(filename).name
    path = Path(MEMES_DIR) / category / name
    try:
        path.unlink(missing_ok=True)
    except Exception as exc:
        logger.warning("[MemeDelete] delete failed: error_type=%s", type(exc).__name__)
        return False
    _drop_index_entry(category, name)
    logger.info("[MemeDelete] deleted: category=%s filename=%s", category, name)
    return True


def ensure_private_category() -> None:
    """Make sure every private category exists and never auto-sends from Cloud."""
    index = load_meme_index()
    changed = False
    for name in PRIVATE_CATEGORIES:
        payload = index.setdefault("categories", {}).setdefault(name, {})
        if not isinstance(payload, dict):
            payload = {}
            index["categories"][name] = payload
        before = dict(payload)
        label, description = PRIVATE_LABELS[name]
        payload.update({
            "label": label,
            "description": description,
            "use_cases": [],
            "avoid_when": ["群聊", "云栖自动发送"],
            "audience": "owner_only",
            "auto_send_enabled": False,
        })
        changed = changed or before != payload
    if changed:
        save_meme_index(index)


def move_to_private_category(source_category: str, filename: str, *, rule: str = "") -> bool:
    """Move one image into the private category that is never auto-sent.

    Args:
        source_category: Category or archive folder the image currently sits in.
        filename: Image file name.
        rule: Rule id that triggered the move, kept in the index for review.

    Returns:
        True when the file was moved and re-indexed as private.
    """
    name = Path(filename).name
    target_category = PRIVATE_RULE_CATEGORY.get(rule) or PRIVATE_CATEGORY
    if source_category == target_category:
        return True
    candidates = (
        Path(MEMES_DIR) / source_category / name,
        ARCHIVE_DIR / source_category / name,
    )
    source = next((path for path in candidates if path.is_file()), None)
    if source is None:
        logger.warning("[MemeArchive] private move skipped, file missing: %s/%s", source_category, name)
        return False
    target_dir = Path(MEMES_DIR) / target_category
    target = target_dir / name
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target = target_dir / f"{Path(name).stem}-{int(time.time())}{Path(name).suffix}"
        shutil.move(str(source), str(target))
    except Exception as exc:
        logger.warning("[MemeArchive] private move failed: error_type=%s", type(exc).__name__)
        return False

    index = load_meme_index()
    images = [entry for entry in index.get("images", []) if isinstance(entry, dict)]
    dropped = next(
        (
            entry
            for entry in images
            if entry.get("category") == source_category and entry.get("filename") == name
        ),
        None,
    )
    if dropped is not None:
        images.remove(dropped)
    entry = dict(dropped) if dropped else {}
    entry.update({
        "category": target_category,
        "filename": target.name,
        "relative_path": f"memes/{target_category}/{target.name}",
        "auto_send_enabled": False,
    })
    entry.setdefault("title", Path(name).stem)
    entry.setdefault("content_caption", "")
    entry["private_from"] = source_category
    if rule:
        entry["private_rule"] = rule
    images.append(entry)
    index["images"] = images
    payload = index.setdefault("categories", {}).setdefault(target_category, {})
    label, description = PRIVATE_LABELS[target_category]
    payload.update({
        "label": label,
        "description": description,
        "use_cases": [],
        "avoid_when": ["群聊", "云栖自动发送"],
        "audience": "owner_only",
        "auto_send_enabled": False,
    })
    save_meme_index(index)
    _drop_manifest_entry(source_category, name)
    logger.info(
        "[MemeArchive] moved to private: from=%s to=%s filename=%s rule=%s",
        source_category,
        target_category,
        name,
        rule,
    )
    return True


def _drop_manifest_entry(category: str, filename: str) -> None:
    """Remove one record from an archive manifest after the file left the archive."""
    path = ARCHIVE_DIR / category / ARCHIVE_MANIFEST_NAME
    if not path.is_file():
        return
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(records, list):
        return
    kept = [
        record
        for record in records
        if not (isinstance(record, dict) and record.get("filename") == filename)
    ]
    if len(kept) == len(records):
        return
    try:
        path.write_text(json.dumps(kept, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass


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
    if len(members) - len(scored) >= excess:
        # 没打分的图数量已经够超额数，等它们打完再裁，否则可能误删好图
        return 0
    scored.sort(key=rank_of)
    archived = 0
    for entry in scored[:excess]:
        if archive_image(category, str(entry.get("filename") or ""), reason="over_quota"):
            archived += 1
    return archived


def enforce_quotas() -> dict[str, int]:
    """Trim every category above its quota; pure rule, no model involved."""
    index = load_meme_index()
    counts: dict[str, int] = {}
    for entry in index.get("images", []):
        if isinstance(entry, dict):
            category = str(entry.get("category") or "")
            counts[category] = counts.get(category, 0) + 1
    trimmed: dict[str, int] = {}
    for category, count in sorted(counts.items()):
        if count <= quota_of(category):
            continue
        moved = trim_category(category)
        if moved:
            trimmed[category] = moved
    if trimmed:
        logger.info("[MemeArchive] quota sweep: %s", trimmed)
    return trimmed


def restore_image(category: str, filename: str, *, target_category: str = "") -> bool:
    """Move one archived image back into the library, keeping its description and score."""
    name = Path(filename).name
    source = ARCHIVE_DIR / category / name
    target = target_category or canonical_category(category)
    target_dir = Path(MEMES_DIR) / target
    if not source.is_file():
        logger.warning("[MemeArchive] archived file missing: category=%s filename=%s", category, name)
        return False
    record = _pop_manifest_record(category, name)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        destination = _unique_target(target_dir, name)
        shutil.move(str(source), str(destination))
    except Exception as exc:
        logger.warning("[MemeArchive] restore failed: error_type=%s", type(exc).__name__)
        return False
    title = str(record.get("title") or Path(name).stem)[:80]
    upsert_image_metadata(target, destination.name, {
        "title": title,
        "content_caption": str(record.get("title") or title)[:300],
        "emotion_tags": [target],
        "auto_send_enabled": True,
    })
    score = record.get("score")
    if isinstance(score, dict) and score.get("total"):
        record_image_score(
            target,
            destination.name,
            cute=int(score.get("cute") or 0),
            expressive=int(score.get("expressive") or 0),
            quality=int(score.get("quality") or 0),
            usable=int(score.get("usable") or 0),
            version=int(score.get("version") or SCORE_VERSION),
            caption=title,
        )
    logger.info("[MemeArchive] restored: category=%s filename=%s", category, name)
    return True


def rebalance_category(category: str) -> int:
    """Swap in an archived image when it clearly outscores the weakest library member."""
    index = load_meme_index()
    members = [
        entry
        for entry in index.get("images", [])
        if isinstance(entry, dict)
        and entry.get("category") == category
        and isinstance(entry.get("score"), dict)
    ]
    if not members:
        return 0
    scored = [
        record
        for record in _read_manifest(category)
        if isinstance(record.get("score"), dict) and record["score"].get("total")
    ]
    if not scored:
        return 0
    weakest = min(members, key=rank_of)
    best = max(scored, key=rank_of)
    if rank_of(best) <= rank_of(weakest):
        return 0
    if not archive_image(category, str(weakest.get("filename") or ""), reason="over_quota"):
        return 0
    if not restore_image(category, str(best.get("filename") or "")):
        return 0
    logger.info(
        "[MemeArchive] rebalanced: category=%s in=%s out=%s",
        category, best.get("filename"), weakest.get("filename"),
    )
    return 1


def rebalance_quotas() -> dict[str, int]:
    """Bring archived images back when they outscore what is currently in the library."""
    index = load_meme_index()
    categories = {
        str(entry.get("category") or "")
        for entry in index.get("images", [])
        if isinstance(entry, dict)
    }
    swapped: dict[str, int] = {}
    for category in sorted(categories):
        moved = rebalance_category(category)
        if moved:
            swapped[category] = moved
    if swapped:
        logger.info("[MemeArchive] rebalance sweep: %s", swapped)
    return swapped


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

    see_dir = memes_root / "see"
    for category in CATEGORY_ARCHIVE_ALL:
        category_dir = memes_root / category
        if not category_dir.is_dir():
            continue
        for path in sorted(category_dir.iterdir()):
            if not path.is_file() or not _is_supported(path.name):
                continue
            # 退休分类的图不打包归档，统一并进通用分类，交给配额和打分决定去留
            see_dir.mkdir(parents=True, exist_ok=True)
            target = _unique_target(see_dir, path.name)
            shutil.move(str(path), str(target))
            entry = entries.get((category, path.name))
            if entry is not None:
                entry["category"] = "see"
                entry["relative_path"] = f"memes/see/{target.name}"
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
                # 目标分类已有同名同内容文件，重复的直接删，不进归档
                path.unlink(missing_ok=True)
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
        target = _unique_target(target_dir, filename)
        shutil.move(str(source), str(target))
        record["filename"] = target.name
    except Exception as exc:
        logger.warning("[MemeArchive] archive failed: error_type=%s", type(exc).__name__)
        return False
    _append_manifest(target_dir, record)
    return True


def _archive_record(category: str, filename: str, reason: str, note: str, rule: str = "") -> dict:
    """Build one archive manifest record."""
    record = {
        "filename": Path(filename).name,
        "category": category,
        "reason": reason,
        "archived_at": int(time.time()),
    }
    if rule:
        record["rule"] = rule
    if note:
        record["note"] = note
    return record


def _append_manifest(target_dir: Path, record: dict, *, manifest: str = ARCHIVE_MANIFEST_NAME) -> None:
    """Append one record to the archive or review manifest of a category."""
    path = target_dir / manifest
    records: list = []
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                records = loaded
        except Exception:
            records = []
    records.append(record)
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    except Exception as exc:
        logger.warning("[MemeArchive] manifest write failed: error_type=%s", type(exc).__name__)


def _drop_index_entry(category: str, filename: str) -> dict | None:
    """Remove one image entry from the library index and return it."""
    index = load_meme_index()
    dropped = None
    kept = []
    for entry in index.get("images", []):
        if (
            isinstance(entry, dict)
            and entry.get("category") == category
            and entry.get("filename") == filename
        ):
            dropped = entry
            continue
        kept.append(entry)
    index["images"] = kept
    save_meme_index(index)
    return dropped


def _is_supported(filename: str) -> bool:
    """Return whether the file name is a supported image."""
    return Path(filename).suffix.lower() in IMAGE_EXTENSIONS


def _remove_empty_dir(path: Path) -> None:
    """Remove a category directory when nothing is left in it."""
    try:
        path.rmdir()
    except OSError:
        pass


def _read_manifest(category: str) -> list[dict]:
    """Return the archive records of one category."""
    manifest = ARCHIVE_DIR / category / ARCHIVE_MANIFEST_NAME
    if not manifest.is_file():
        return []
    try:
        records = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


def _pop_manifest_record(category: str, filename: str) -> dict:
    """Remove and return one record from a category archive manifest."""
    manifest = ARCHIVE_DIR / category / ARCHIVE_MANIFEST_NAME
    if not manifest.is_file():
        return {}
    try:
        records = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(records, list):
        return {}
    found: dict = {}
    kept: list = []
    for record in records:
        if isinstance(record, dict) and record.get("filename") == filename and not found:
            found = record
            continue
        kept.append(record)
    if found:
        manifest.write_text(json.dumps(kept, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return found
