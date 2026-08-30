from __future__ import annotations

from dataclasses import dataclass
import inspect
from typing import Any

from astrbot.core.message.components import Forward as CoreForward
from astrbot.core.message.components import Node as CoreNode
from astrbot.core.message.components import Nodes as CoreNodes
from astrbot.core.message.components import Plain as CorePlain

from .reply_style_guard_logic import should_fold_long_reply
from .reply_style_guard_logic import split_forward_text
from .request_context import SourceMessage
from .request_context import format_source_messages
from .request_context import looks_like_image_source
from .request_context import normalize_forward_id
from .request_context import normalize_sender_qq
from .request_context import source_message_from_reply


@dataclass(frozen=True, slots=True)
class FoldedReplyChain:
    chain: list[object]
    text_chars: int
    node_count: int


def build_folded_reply_chain(
    text: str,
    *,
    threshold: int,
    uin: str,
    name: str,
) -> FoldedReplyChain | None:
    if not should_fold_long_reply(text, threshold=threshold):
        return None
    chunks = split_forward_text(text)
    if not chunks:
        return None
    node_name = str(name or "").strip() or "棉花糖"
    node_uin = str(uin or "10000").strip() or "10000"
    chain = [
        CoreNodes(
            [
                CoreNode(
                    uin=node_uin,
                    name=node_name,
                    content=[CorePlain(chunk)],
                )
                for chunk in chunks
            ]
        )
    ]
    return FoldedReplyChain(chain=chain, text_chars=len(str(text or "")), node_count=len(chunks))


def has_forward_message(event: object) -> bool:
    return bool(_forward_ids_from_segments(_safe_get_messages(event)))


async def extract_onebot_source_tree(
    event: object,
    *,
    max_fetch: int = 6,
) -> tuple[SourceMessage, ...]:
    """Return Reply and top-level Forward roots with Forward children expanded in place."""

    roots: list[SourceMessage] = []
    for segment in _safe_get_messages(event):
        segment_type = segment.__class__.__name__.lower()
        if segment_type == "reply":
            roots.append(source_message_from_reply(segment))
        elif isinstance(segment, CoreForward) or segment_type == "forward":
            forward_id = normalize_forward_id(getattr(segment, "id", ""))
            if forward_id:
                roots.append(SourceMessage(forward_id=forward_id))
    return await _expand_forward_references(
        tuple(roots),
        call_action=_resolve_onebot_call_action(event),
        max_fetch=max_fetch,
    )


async def extract_onebot_forward_sources(
    event: object,
    *,
    max_fetch: int = 6,
) -> tuple[SourceMessage, ...]:
    """Compatibility view containing only expanded Forward roots."""

    forward_ids = _forward_ids_from_segments(_safe_get_messages(event))
    call_action = _resolve_onebot_call_action(event)
    if not forward_ids or call_action is None:
        return ()
    roots = tuple(SourceMessage(forward_id=forward_id) for forward_id in forward_ids)
    return await _expand_forward_references(
        roots,
        call_action=call_action,
        max_fetch=max_fetch,
    )


async def _expand_forward_references(
    roots: tuple[SourceMessage, ...],
    *,
    call_action,
    max_fetch: int,
) -> tuple[SourceMessage, ...]:
    cache: dict[str, tuple[SourceMessage, ...]] = {}
    active: set[str] = set()
    fetch_count = 0

    async def resolve_forward(forward_id: str) -> tuple[SourceMessage, ...]:
        nonlocal fetch_count
        if not forward_id:
            return ()
        if forward_id in cache:
            return cache[forward_id]
        if forward_id in active or call_action is None or fetch_count >= max(0, max_fetch):
            return (SourceMessage(forward_id=forward_id),)

        active.add(forward_id)
        fetch_count += 1
        try:
            payload = await _call_onebot_action_compat(
                call_action,
                "get_forward_msg",
                forward_id,
            )
            if not isinstance(payload, dict):
                result = (SourceMessage(forward_id=forward_id),)
            else:
                expanded: list[SourceMessage] = []
                for source in _source_messages_from_onebot_payload(payload):
                    expanded.extend(await expand_nested(source))
                result = tuple(expanded) or (SourceMessage(forward_id=forward_id),)
        finally:
            active.remove(forward_id)
        cache[forward_id] = result
        return result

    async def expand_nested(source: SourceMessage) -> tuple[SourceMessage, ...]:
        if source.forward_id:
            return await resolve_forward(source.forward_id)
        children: list[SourceMessage] = []
        for child in source.children:
            children.extend(await expand_nested(child))
        return (
            SourceMessage(
                sender_qq=source.sender_qq,
                text=source.text,
                image_sources=source.image_sources,
                children=tuple(children),
            ),
        )

    result: list[SourceMessage] = []
    for root in roots:
        result.extend(await expand_nested(root))
    return tuple(result)


async def extract_onebot_forward_text(event: object, *, max_fetch: int = 6) -> str:
    """Compatibility text view; keep the historical breadth-first fetch order."""

    forward_ids = list(_forward_ids_from_segments(_safe_get_messages(event)))
    call_action = _resolve_onebot_call_action(event)
    if not forward_ids or call_action is None:
        return ""
    texts: list[str] = []
    pending = list(forward_ids)
    seen: set[str] = set()
    fetch_count = 0
    while pending and fetch_count < max(0, max_fetch):
        forward_id = pending.pop(0)
        if not forward_id or forward_id in seen:
            continue
        seen.add(forward_id)
        fetch_count += 1
        payload = await _call_onebot_action_compat(call_action, "get_forward_msg", forward_id)
        if not isinstance(payload, dict):
            continue
        direct_sources: list[SourceMessage] = []
        for source in _source_messages_from_onebot_payload(payload):
            direct, nested_ids = _without_forward_references(source)
            direct_sources.append(direct)
            pending.extend(nested_id for nested_id in nested_ids if nested_id not in seen)
        text = format_source_messages(direct_sources)
        if text:
            texts.append(text)
    return "\n".join(texts).strip()


def _without_forward_references(source: SourceMessage) -> tuple[SourceMessage, tuple[str, ...]]:
    nested_ids: list[str] = []
    children: list[SourceMessage] = []
    for child in source.children:
        if child.forward_id:
            nested_ids.append(child.forward_id)
            continue
        direct_child, child_ids = _without_forward_references(child)
        children.append(direct_child)
        nested_ids.extend(child_ids)
    return (
        SourceMessage(
            sender_qq=source.sender_qq,
            text=source.text,
            image_sources=source.image_sources,
            children=tuple(children),
        ),
        tuple(nested_ids),
    )


def _forward_ids_from_segments(segments) -> tuple[str, ...]:
    ids: list[str] = []
    for segment in segments:
        if isinstance(segment, CoreForward) or segment.__class__.__name__.lower() == "forward":
            forward_id = normalize_forward_id(getattr(segment, "id", ""))
            if forward_id:
                ids.append(forward_id)
            continue
        if segment.__class__.__name__.lower() == "reply":
            ids.extend(_forward_ids_from_segments(getattr(segment, "chain", None) or ()))
        elif segment.__class__.__name__.lower() == "nodes":
            ids.extend(_forward_ids_from_segments(getattr(segment, "nodes", None) or ()))
        elif segment.__class__.__name__.lower() == "node":
            content = getattr(segment, "content", None)
            if not isinstance(content, str):
                ids.extend(_forward_ids_from_segments(content or ()))
    return tuple(ids)


def _source_messages_from_onebot_payload(payload: dict[str, object]) -> tuple[SourceMessage, ...]:
    body = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(body, dict):
        return ()
    raw_nodes: list[object] | tuple[object, ...] | None = None
    for container_name in ("messages", "message", "nodes", "nodeList"):
        container = body.get(container_name)
        if isinstance(container, (list, tuple)):
            raw_nodes = container
            break
        if isinstance(container, dict):
            raw_nodes = (container,)
            break
    if raw_nodes is not None:
        return tuple(
            source
            for raw in raw_nodes
            if isinstance(raw, dict)
            for source in (_source_message_from_onebot_node(raw),)
        )

    # Keep compatibility with adapters returning the Core parser's compact shape.
    text = str(body.get("text", "") or "").strip()
    children = tuple(
        SourceMessage(forward_id=normalize_forward_id(forward_id))
        for forward_id in body.get("forward_ids", [])
        if normalize_forward_id(forward_id)
    ) if isinstance(body.get("forward_ids"), (list, tuple)) else ()
    return (SourceMessage(text=text, children=children),) if text or children else ()


def _source_message_from_onebot_node(raw: dict[str, object]) -> SourceMessage:
    sender = raw.get("sender") if isinstance(raw.get("sender"), dict) else {}
    sender_qq = normalize_sender_qq(sender.get("user_id", ""))
    if not sender_qq:
        sender_qq = normalize_sender_qq(raw.get("user_id", raw.get("uin", "")))
    text, image_sources, children = _source_content_from_onebot(
        raw.get("content", raw.get("message", []))
    )
    return SourceMessage(
        sender_qq=sender_qq,
        text=text,
        image_sources=image_sources,
        children=children,
    )


def _source_content_from_onebot(
    content: object,
) -> tuple[str, tuple[str, ...], tuple[SourceMessage, ...]]:
    if isinstance(content, str):
        return content.strip(), (), ()
    if not isinstance(content, list):
        return "", (), ()
    text_parts: list[str] = []
    image_sources: list[str] = []
    children: list[SourceMessage] = []
    for segment in content:
        if isinstance(segment, str):
            text_parts.append(segment)
            continue
        if not isinstance(segment, dict):
            continue
        segment_type = str(segment.get("type", "") or "").lower()
        data = segment.get("data") if isinstance(segment.get("data"), dict) else {}
        if segment_type == "text":
            text_parts.append(str(data.get("text", "") or ""))
        elif segment_type == "image":
            for key in ("url", "file", "path"):
                source = str(data.get(key, "") or "").strip()
                if looks_like_image_source(source) and source not in image_sources:
                    image_sources.append(source)
        elif segment_type == "forward":
            forward_id = normalize_forward_id(data.get("id", data.get("message_id", "")))
            if forward_id:
                children.append(SourceMessage(forward_id=forward_id))
        elif segment_type == "node":
            node_raw = dict(data)
            if "content" not in node_raw and "message" in node_raw:
                node_raw["content"] = node_raw["message"]
            children.append(_source_message_from_onebot_node(node_raw))
    return "".join(text_parts).strip(), tuple(image_sources), tuple(children)


def _safe_get_messages(event: object) -> tuple[object, ...]:
    getter = getattr(event, "get_messages", None)
    if not callable(getter):
        return ()
    try:
        return tuple(getter() or ())
    except Exception:
        return ()


def _resolve_onebot_call_action(event: object):
    bot = getattr(event, "bot", None)
    for candidate in (getattr(bot, "api", None), bot):
        call_action = getattr(candidate, "call_action", None)
        if callable(call_action):
            return call_action
    return None


async def _call_maybe_async(call_action, action: str, **params: Any):
    result = call_action(action, **params)
    if inspect.isawaitable(result):
        return await result
    return result


async def _call_onebot_action_compat(call_action, action: str, message_id: str):
    params_list: list[dict[str, object]] = [{"message_id": message_id}, {"id": message_id}]
    if str(message_id).isdigit():
        int_id = int(message_id)
        params_list.extend([{"message_id": int_id}, {"id": int_id}])
    for params in params_list:
        try:
            return await _call_maybe_async(call_action, action, **params)
        except Exception:
            continue
    return None
