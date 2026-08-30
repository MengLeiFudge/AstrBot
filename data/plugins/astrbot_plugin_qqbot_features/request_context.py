from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

try:
    from astrbot.api.message_components import At, Image, Plain, Reply
    _ASTRBOT_COMPONENTS_AVAILABLE = True
except Exception:  # pragma: no cover - imported by lightweight unit tests.
    At = Image = Plain = Reply = object  # type: ignore[assignment]
    _ASTRBOT_COMPONENTS_AVAILABLE = False


BOT_NAME_MARKERS = ("棉花糖", "云栖", "夜凛", "呼叫棉花糖")


@dataclass(frozen=True, slots=True)
class SourceMessage:
    """One message with its protocol-level sender and nested message children."""

    sender_qq: str = ""
    text: str = ""
    image_sources: tuple[str, ...] = ()
    children: tuple[SourceMessage, ...] = ()
    forward_id: str = ""


@dataclass(frozen=True, slots=True)
class CurrentRequestContext:
    current_text: str
    reply_texts: tuple[str, ...]
    combined_query: str
    named_call: bool
    unresolved_media_context: bool


def build_current_request_context(event: object, prompt: str = "") -> CurrentRequestContext:
    current_text = normalize_space(prompt) or extract_plain_text(event)
    reply_texts = tuple(text for text in extract_reply_texts(event) if text)
    combined_query = compose_query(current_text, reply_texts)
    return CurrentRequestContext(
        current_text=current_text,
        reply_texts=reply_texts,
        combined_query=combined_query,
        named_call=contains_bot_name(current_text),
        unresolved_media_context=has_unresolved_media_context(event),
    )


def compose_query(current_text: str, reply_texts: tuple[str, ...] | list[str]) -> str:
    lines: list[str] = []
    for index, text in enumerate(reply_texts, start=1):
        normalized = normalize_space(text)
        if normalized:
            lines.append(f"被引用消息{index}：{normalized}")
    normalized_current = normalize_space(current_text)
    if normalized_current:
        lines.append(f"当前消息：{normalized_current}")
    return "\n".join(lines).strip()


def extract_plain_text(event: object) -> str:
    parts: list[str] = []
    for segment in safe_get_messages(event):
        if is_plain_segment(segment):
            parts.append(str(getattr(segment, "text", "") or ""))
    text = "".join(parts).strip()
    if text:
        return text
    getter = getattr(event, "get_message_str", None)
    if callable(getter):
        try:
            return str(getter() or "").strip()
        except Exception:
            return ""
    return ""


def extract_reply_texts(event: object) -> list[str]:
    texts = [
        format_source_messages((source,))
        for source in extract_reply_source_messages(event)
    ]
    return dedupe_keep_order([text for text in texts if text])


def extract_reply_source_messages(event: object) -> tuple[SourceMessage, ...]:
    return tuple(
        source_message_from_reply(segment)
        for segment in safe_get_messages(event)
        if is_reply_segment(segment)
    )


def source_message_from_reply(segment: object) -> SourceMessage:
    children, _ = source_messages_from_chain(getattr(segment, "chain", None) or ())
    return SourceMessage(
        sender_qq=normalize_sender_qq(getattr(segment, "sender_id", "")),
        text=reply_segment_text(segment),
        children=children,
    )


def source_messages_from_chain(chain: Iterable[object]) -> tuple[tuple[SourceMessage, ...], str]:
    children: list[SourceMessage] = []
    text_parts: list[str] = []
    for item in chain:
        if is_plain_segment(item):
            text_parts.append(str(getattr(item, "text", "") or ""))
        elif is_node_segment(item):
            children.append(source_message_from_node(item))
        elif is_nodes_segment(item):
            for node in getattr(item, "nodes", None) or ():
                children.append(source_message_from_node(node))
        elif is_forward_segment(item):
            forward_id = normalize_forward_id(getattr(item, "id", ""))
            if forward_id:
                children.append(SourceMessage(forward_id=forward_id))
    return tuple(children), normalize_space("".join(text_parts))


def source_message_from_node(node: object) -> SourceMessage:
    content = getattr(node, "content", None)
    if isinstance(content, str):
        text = normalize_space(content)
        children: tuple[SourceMessage, ...] = ()
    else:
        children, text = source_messages_from_chain(content or ())
    return SourceMessage(
        sender_qq=normalize_sender_qq(getattr(node, "uin", "")),
        text=text,
        children=children,
    )


def format_source_messages(
    messages: Iterable[SourceMessage],
    *,
    max_depth: int = 8,
    max_chars: int = 12000,
) -> str:
    """Format a bounded source tree without inventing missing sender identities."""

    if max_chars <= 0:
        return ""
    lines: list[str] = []
    remaining = max_chars

    def append_line(line: str) -> None:
        nonlocal remaining
        if remaining <= 0:
            return
        separator_size = 1 if lines else 0
        if remaining <= separator_size:
            remaining = 0
            return
        value = line[: remaining - separator_size]
        lines.append(value)
        remaining -= separator_size + len(value)

    def append_message(message: SourceMessage, depth: int) -> None:
        if depth > max(0, max_depth) or remaining <= 0:
            return
        indent = "  " * depth
        if message.sender_qq:
            append_line(f"{indent}发送者 QQ：{message.sender_qq}")
        if message.text:
            message_text = str(message.text).strip()
            for line in message_text.splitlines():
                append_line(f"{indent}{line}")
        for child in message.children:
            append_message(child, depth + 1)

    for message in messages:
        append_message(message, 0)
    return "\n".join(lines).strip()


def collect_source_image_sources(
    messages: Iterable[SourceMessage],
    *,
    max_images: int = 12,
) -> tuple[str, ...]:
    """Collect direct images before deeper forwarded images, with a request-size bound."""

    if max_images <= 0:
        return ()
    sources: list[str] = []
    pending = list(messages)
    while pending and len(sources) < max_images:
        message = pending.pop(0)
        for source in message.image_sources:
            if source not in sources:
                sources.append(source)
                if len(sources) >= max_images:
                    break
        pending.extend(message.children)
    return tuple(sources)


def remove_empty_assistant_contexts(contexts: list[dict]) -> int:
    """Drop assistant history entries rejected by strict OpenAI-compatible APIs."""

    cleaned: list[dict] = []
    removed = 0
    for context in contexts:
        if not isinstance(context, dict) or context.get("role") != "assistant":
            cleaned.append(context)
            continue
        content = context.get("content")
        has_content = content not in (None, "", [])
        if has_content or context.get("tool_calls") or context.get("reasoning_content"):
            cleaned.append(context)
            continue
        removed += 1
    if removed:
        contexts[:] = cleaned
    return removed


def reply_segment_text(segment: object) -> str:
    for attr in ("message_str", "text"):
        text = normalize_space(getattr(segment, attr, "") or "")
        if text and not is_media_placeholder_text(text):
            return text
    chain = getattr(segment, "chain", None)
    if not chain:
        return ""
    parts: list[str] = []
    for item in chain:
        if is_plain_segment(item):
            parts.append(str(getattr(item, "text", "") or ""))
    text = normalize_space("".join(parts))
    return "" if is_media_placeholder_text(text) else text


def canonical_event_claim_key(event: object, *, purpose: str, include_private_self_id: bool = False) -> str:
    group_id = safe_call(event, "get_group_id")
    if not group_id:
        self_id = safe_call(event, "get_self_id") if include_private_self_id else ""
        group_id = f"private:{self_id}" if self_id else "private"
    sender_id = safe_call(event, "get_sender_id") or "unknown"
    text = re.sub(r"\s+", "", extract_plain_text(event))[:160]
    at_ids = ",".join(sorted(extract_at_ids(event)))
    reply_key = canonical_reply_key(event)
    bucket = event_time_bucket(event)
    if text or at_ids or reply_key:
        return f"canonical:{purpose}:{group_id}:{sender_id}:{bucket}:{at_ids}:{reply_key}:{text}"
    message_id = event_message_id(event)
    if message_id:
        return f"message:{purpose}:{message_id}"
    return f"fallback:{purpose}:{group_id}:{sender_id}:{bucket}"


def canonical_reply_key(event: object) -> str:
    reply_texts = tuple(
        re.sub(r"\s+", "", text)[:160]
        for text in extract_reply_texts(event)
        if text
    )
    if reply_texts:
        return "text:" + "|".join(reply_texts)
    reply_ids = extract_reply_ids(event)
    return "id:" + ",".join(reply_ids) if reply_ids else ""


def extract_at_ids(event: object) -> tuple[str, ...]:
    ids: list[str] = []
    for segment in safe_get_messages(event):
        if is_at_segment(segment):
            qq = str(getattr(segment, "qq", "") or "").strip()
            if qq:
                ids.append(qq)
    return tuple(ids)


def extract_image_sources(event: object) -> tuple[str, ...]:
    sources: list[str] = []
    for segment in safe_get_messages(event):
        sources.extend(image_sources_from_segment(segment))
    return tuple(dedupe_keep_order(sources))


def image_sources_from_segment(segment: object) -> list[str]:
    if is_image_segment(segment):
        return image_segment_sources(segment)
    if not is_reply_segment(segment):
        return []
    sources: list[str] = []
    for item in getattr(segment, "chain", None) or []:
        if is_image_segment(item):
            sources.extend(image_segment_sources(item))
    return sources


def image_segment_sources(segment: object) -> list[str]:
    return [
        value
        for value in (
            getattr(segment, "url", ""),
            getattr(segment, "file", ""),
            getattr(segment, "path", ""),
        )
        if looks_like_image_source(value)
    ]


def looks_like_image_source(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return (
        text.startswith("http://")
        or text.startswith("https://")
        or text.startswith("file:///")
        or text.startswith("/")
        or re.match(r"^[A-Za-z]:[\\/]", text) is not None
    )


def extract_reply_ids(event: object) -> tuple[str, ...]:
    ids: list[str] = []
    for segment in safe_get_messages(event):
        if is_reply_segment(segment):
            reply_id = str(getattr(segment, "id", "") or "").strip()
            if reply_id:
                ids.append(reply_id)
    return tuple(ids)


def event_message_id(event: object) -> str:
    return str(getattr(getattr(event, "message_obj", None), "message_id", "") or "").strip()


def event_time_bucket(event: object, *, seconds: int = 10) -> str:
    message_obj = getattr(event, "message_obj", None)
    raw = getattr(message_obj, "timestamp", None) or getattr(message_obj, "time", None)
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return ""
    return str(value // max(1, seconds))


def contains_bot_name(text: str) -> bool:
    normalized = str(text or "")
    return any(marker in normalized for marker in BOT_NAME_MARKERS)


def has_unresolved_media_context(event: object) -> bool:
    return any(segment_has_unresolved_media(segment) for segment in safe_get_messages(event))


def segment_has_unresolved_media(segment: object) -> bool:
    if is_plain_segment(segment):
        return is_media_placeholder_text(getattr(segment, "text", "") or "")
    if is_media_segment(segment):
        return True
    if not is_reply_segment(segment):
        return False
    for attr in ("message_str", "text"):
        text = normalize_space(getattr(segment, attr, "") or "")
        if is_media_placeholder_text(text):
            return True
    chain = getattr(segment, "chain", None)
    if not chain:
        return False
    has_media = False
    has_text = False
    for item in chain:
        if is_media_segment(item):
            has_media = True
        elif is_plain_segment(item):
            text = normalize_space(getattr(item, "text", "") or "")
            if text and not is_media_placeholder_text(text):
                has_text = True
    return has_media and not has_text


def is_media_placeholder_text(text: object) -> bool:
    normalized = normalize_space(text)
    if not normalized:
        return False
    return re.fullmatch(r"\[(?:图片|表情|视频|语音|文件|卡片消息|转发消息)(?:[^\]]*)\]", normalized) is not None


def normalize_sender_qq(value: object) -> str:
    text = str(value or "").strip()
    return text if text.isdigit() and int(text) > 0 else ""


def normalize_forward_id(value: object) -> str:
    return str(value or "").strip()


def normalize_space(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def safe_get_messages(event: object) -> tuple[object, ...]:
    getter = getattr(event, "get_messages", None)
    if not callable(getter):
        return ()
    try:
        return tuple(getter() or ())
    except Exception:
        return ()


def safe_call(event: object, method_name: str) -> str:
    method = getattr(event, method_name, None)
    if not callable(method):
        return ""
    try:
        return str(method() or "").strip()
    except Exception:
        return ""


def is_plain_segment(segment: object) -> bool:
    return (_ASTRBOT_COMPONENTS_AVAILABLE and isinstance(segment, Plain)) or segment.__class__.__name__.lower() == "plain"


def is_at_segment(segment: object) -> bool:
    return (_ASTRBOT_COMPONENTS_AVAILABLE and isinstance(segment, At)) or segment.__class__.__name__.lower() == "at"


def is_media_segment(segment: object) -> bool:
    return segment.__class__.__name__.lower() in {
        "image",
        "video",
        "record",
        "file",
        "face",
        "node",
        "xml",
        "json",
    }


def is_image_segment(segment: object) -> bool:
    return (_ASTRBOT_COMPONENTS_AVAILABLE and isinstance(segment, Image)) or segment.__class__.__name__.lower() == "image"


def is_reply_segment(segment: object) -> bool:
    return (_ASTRBOT_COMPONENTS_AVAILABLE and isinstance(segment, Reply)) or segment.__class__.__name__.lower() == "reply"


def is_node_segment(segment: object) -> bool:
    return segment.__class__.__name__.lower() == "node"


def is_nodes_segment(segment: object) -> bool:
    return segment.__class__.__name__.lower() == "nodes"


def is_forward_segment(segment: object) -> bool:
    return segment.__class__.__name__.lower() == "forward"


def dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = normalize_space(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result
