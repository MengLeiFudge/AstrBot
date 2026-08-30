from __future__ import annotations

import re
from collections.abc import Iterable


_STRICT_MARKUP_RE = re.compile(r"&&([^&]+)&&")
_AMP_MARKUP_RE = re.compile(
    r"(?<![A-Za-z0-9_&-])&{1,2}([A-Za-z0-9_-]+)&{0,2}(?![A-Za-z0-9_-])"
)


def extract_wrapped_meme_markups(
    text: str,
    valid_labels: Iterable[str],
) -> tuple[str, list[str]]:
    """提取 LLM 输出中的表情标签，并移除原始标签文本。"""
    canonical = _canonical_label_map(valid_labels)
    emotions: list[str] = []

    def replace_strict(match: re.Match[str]) -> str:
        label = normalize_meme_label(match.group(1), canonical)
        if label:
            emotions.append(label)
        return ""

    cleaned = _STRICT_MARKUP_RE.sub(replace_strict, str(text or ""))

    def replace_amp_markup(match: re.Match[str]) -> str:
        label = normalize_meme_label(match.group(1), canonical)
        if not label:
            return match.group(0)
        emotions.append(label)
        return ""

    cleaned = _AMP_MARKUP_RE.sub(replace_amp_markup, cleaned)
    return _normalize_spaces_after_markup_removal(cleaned), emotions


def clean_meme_markup_text(text: str, valid_labels: Iterable[str]) -> str:
    cleaned, _ = extract_wrapped_meme_markups(text, valid_labels)
    return re.sub(r"&&+", "", cleaned).strip()


def normalize_meme_label(raw_label: str, canonical: dict[str, str]) -> str:
    token = str(raw_label or "").strip()
    if not token:
        return ""

    direct = canonical.get(token) or canonical.get(token.lower())
    if direct:
        return direct

    # 部分模型会把 &&affection_kiss&& 畸形成 &Aaffection_kiss&&。
    if len(token) > 1 and token[0] in {"A", "a"}:
        trimmed = token[1:]
        return canonical.get(trimmed) or canonical.get(trimmed.lower(), "")

    return ""


def _canonical_label_map(valid_labels: Iterable[str]) -> dict[str, str]:
    canonical: dict[str, str] = {}
    for label in valid_labels:
        normalized = str(label or "").strip()
        if not normalized:
            continue
        canonical[normalized] = normalized
        canonical[normalized.lower()] = normalized
    return canonical


def _normalize_spaces_after_markup_removal(text: str) -> str:
    cleaned = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r" *\n *", "\n", cleaned)
    return cleaned.strip()
