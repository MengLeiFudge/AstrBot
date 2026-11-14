from __future__ import annotations

import asyncio
import math
import random
import re
import time

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import At, BaseMessageComponent, Image, Node, Plain, Record, Reply
from astrbot.api.star import Context


STARTED_AT_EXTRA = "qqbot_reply_started_at"
FIRST_DELIVERY_EXTRA = "qqbot_reply_first_delivery"
DELIVERED_CHAIN_EXTRA = "qqbot_reply_delivered_chain"


def component_delay(component: BaseMessageComponent, config: dict) -> float:
    """Use the configured native interval for an outgoing component.

    Args:
        component: Text or media component about to be sent.
        config: Existing segmented-reply settings.

    Returns:
        The full native interval before first-message credit.
    """
    if config.get("interval_method", "log") == "log":
        if isinstance(component, Plain):
            text = component.text
            count = len(text.split()) if text.isascii() else sum(char.isalnum() for char in text)
            delay = math.log(count + 1, float(config.get("log_base", 2.6)))
            return random.uniform(delay, delay + 0.5)
        return random.uniform(1.0, 1.75)
    lower, upper = (float(value) for value in str(config.get("interval", "1.5,3.5")).split(","))
    return random.uniform(lower, upper)


def split_chain(chain: list[BaseMessageComponent], config: dict) -> list[BaseMessageComponent]:
    """Preserve native text segmentation and non-text components.

    Args:
        chain: Decorated result before native text splitting.
        config: Existing text splitting and cleanup settings.

    Returns:
        Ordered text and media components.
    """
    output = []
    threshold = int(config.get("words_count_threshold", 150))
    if config.get("split_mode", "regex") == "words":
        words = sorted((re.escape(word) for word in config.get("split_words", [])), key=len, reverse=True)
        pattern = f".*?(?:{'|'.join(words)})|.+$" if words else r".+"
    else:
        pattern = config.get("regex", r".*?[。？！~…]+|.+$")
    for component in chain:
        if not isinstance(component, Plain) or len(component.text) > threshold:
            output.append(component)
            continue
        segments = re.findall(pattern, component.text, re.DOTALL | re.MULTILINE)
        if not segments:
            output.append(component)
            continue
        for segment in segments:
            cleanup = config.get("content_cleanup_rule", "")
            text = re.sub(cleanup, "", segment).strip() if cleanup else segment.strip()
            if text:
                output.append(Plain(text))
    return output


async def deliver_segmented_result(event: AstrMessageEvent, context: Context) -> None:
    """Deliver through the public API while preserving native post-send hooks.

    Args:
        event: Current reply event with a recorded processing start time.
        context: Plugin context providing request-scoped configuration.
    """
    result = event.get_result()
    if result is None or not result.chain or not result.is_model_result():
        return
    config = context.get_config(event.unified_msg_origin)
    settings = config["platform_settings"]
    segmented = settings["segmented_reply"]
    if not segmented.get("enable") or event.get_platform_name() != "aiocqhttp":
        return
    # Voice conversion has its own native result processing. The deployed chat
    # profile uses text output; do not bypass a subsequently enabled converter.
    if config.get("provider_tts_settings", {}).get("enable") or result.async_stream is not None:
        return
    if any(not isinstance(component, (Plain, Image, At, Reply, Node, Record)) for component in result.chain):
        return
    started_at = event.get_extra(STARTED_AT_EXTRA)
    if not isinstance(started_at, (int, float)):
        return
    original = list(result.chain)
    prefix = settings.get("reply_prefix", "")
    if prefix:
        original = [Plain(component.text) if isinstance(component, Plain) else component for component in original]
        for component in original:
            if isinstance(component, Plain):
                component.text = prefix + component.text
                break
    components = split_chain(original, segmented)
    threshold = int(settings.get("forward_threshold", 1500))
    if threshold > 0 and sum(len(component.text) for component in components if isinstance(component, Plain)) > threshold:
        components[:] = [Node(uin=event.get_self_id(), name="AstrBot", content=list(components))]
    if all(isinstance(component, (Plain, Image)) for component in components):
        if settings.get("reply_with_mention") and not event.is_private_chat():
            components.insert(0, At(qq=event.get_sender_id()))
            if len(components) > 1 and isinstance(components[1], Plain):
                components[1].text = "\n" + components[1].text
        if settings.get("reply_with_quote"):
            components.insert(0, Reply(id=event.message_obj.message_id))
    headers = [component for component in components if isinstance(component, (At, Reply))]
    body = [component for component in components if not isinstance(component, (At, Reply))]
    if not body:
        return
    # Reserve before network I/O. An exception or cancellation must never make
    # the native pipeline resend a possibly delivered chain.
    result.chain = []
    delivered = []
    event.set_extra(DELIVERED_CHAIN_EXTRA, delivered)
    for component in body:
        if event.is_stopped():
            break
        delay = component_delay(component, segmented)
        first = not event.get_extra(FIRST_DELIVERY_EXTRA, False)
        if first:
            delay = max(0.0, delay - max(0.0, time.monotonic() - started_at))
            event.set_extra(FIRST_DELIVERY_EXTRA, True)
        if delay:
            await asyncio.sleep(delay)
        if event.is_stopped():
            break
        chain = [component] if isinstance(component, Record) else [*headers, component]
        try:
            await event.send(result.derive(chain))
        except Exception as exc:
            logger.error("[QQBotFeatures] reply segment delivery unconfirmed: error_type=%s", type(exc).__name__)
            continue
        delivered.extend(chain)
        if not isinstance(component, Record):
            headers.clear()


def restore_delivered_result(event: AstrMessageEvent) -> None:
    """Restore confirmed content for the existing activation and meme callbacks.

    Args:
        event: Reply event passed to the native post-send hook.
    """
    result = event.get_result()
    delivered = event.get_extra(DELIVERED_CHAIN_EXTRA)
    if isinstance(delivered, list):
        if result is not None:
            result.chain = delivered
        event.set_extra(DELIVERED_CHAIN_EXTRA, None)
    if result is not None and result.chain:
        event.set_extra(FIRST_DELIVERY_EXTRA, True)
