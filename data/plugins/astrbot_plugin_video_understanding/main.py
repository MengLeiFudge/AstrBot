"""Attach DSH storyboard images and time evidence to normal AstrBot chat."""

from __future__ import annotations

import base64
import json

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Json, Plain, Video
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, StarTools, register

from .video_reader import VIDEO_CAPABILITY, VideoError, VideoOverview, VideoReader, VideoSource, find_video_sources


@register("astrbot_plugin_video_understanding", "MengLei", "用DSH分镜图和时间清单理解视频。", "1.1.0")
class VideoUnderstandingPlugin(Star):
    """Give the main chat model actual frames through public request hooks."""

    def __init__(self, context: Context, config=None) -> None:
        """Own bounded video jobs in this plugin's data directory.

        Args:
            context: Public framework context.
            config: Plugin settings containing the boolean enabled flag.
        """
        super().__init__(context)
        enabled = (config or {}).get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("Video plugin enabled must be a boolean")
        self._enabled = enabled
        self._reader = VideoReader(StarTools.get_data_dir("astrbot_plugin_video_understanding"))
        logger.info("[VideoUnderstanding] DSH enabled=%s tools_ready=%s", enabled, self._reader.tools_ready)

    async def terminate(self) -> None:
        """Cancel the current process tree and clear the image cache."""
        await self._reader.close()

    @filter.event_message_type(filter.EventMessageType.ALL, priority=1100, desc="保留当前视频来源，由插件处理有界下载和分镜。")
    async def prepare_video_attachments(self, event: AstrMessageEvent) -> None:
        """Retain sources before the framework's attachment downloader runs.

        Args:
            event: Message whose video components become text placeholders.
        """
        if not self._enabled or str(event.get_sender_id()) == str(event.get_self_id()):
            return
        sources = []
        components = event.get_messages()
        replaced = False
        for index, component in enumerate(components):
            if not isinstance(component, Video):
                continue
            url = str(component.url or component.file or "").strip()
            if url.startswith(("http://", "https://")):
                sources.append(VideoSource(url, direct=True))
            components[index] = Plain("[视频]")
            replaced = True
        if replaced:
            if not sources:
                event.set_extra("qqbot_video_result", "[视频未读取] 当前附件没有可用下载地址，请改发视频链接或重新发送原视频。不能声称已经看过。")
            event.set_extra("qqbot_video_native_sources", sources)
            event.message_str = (event.message_str + "\n[视频]").strip()
            event.message_obj.message_str = event.message_str

    @filter.on_llm_request(priority=-100, desc="把当前视频的DSH分镜原图和时间清单附给聊天模型。")
    async def enrich_video(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        """Attach frames after chat routing and its image gating have completed.

        Args:
            event: Incoming message and retained native video sources.
            req: Actual main-model request receiving the images and manifest.
        """
        if not self._enabled or str(event.get_sender_id()) == str(event.get_self_id()) or event.is_stopped():
            return
        if self._reader.tools_ready and VIDEO_CAPABILITY not in (req.system_prompt or ""):
            req.system_prompt = (req.system_prompt or "") + "\n" + VIDEO_CAPABILITY
        stored = event.get_extra("qqbot_video_native_sources")
        sources = [source for source in stored if isinstance(source, VideoSource)] if isinstance(stored, list) else []
        text = []
        for component in event.get_messages():
            if isinstance(component, Plain):
                text.append(component.text)
            elif isinstance(component, Json):
                text.append(json.dumps(component.data, ensure_ascii=False))
        if not sources:
            sources = find_video_sources("\n".join(text))
        result = event.get_extra("qqbot_video_result")
        if result is None and not sources:
            return
        if result is None:
            try:
                result = await self._reader.analyze(sources[0])
            except VideoError as exc:
                result = f"[视频未读取] {exc}。请明确说明尚未看到视频，不能根据标题或其他图片编造内容。"
                logger.warning("[VideoUnderstanding] video unavailable: %s", exc)
            except Exception as exc:
                result = "[视频未读取] 视频下载或DSH分镜处理失败，请重发可访问的短视频；不能声称已经看过。"
                logger.warning("[VideoUnderstanding] analysis failed: error_type=%s", type(exc).__name__)
            event.set_extra("qqbot_video_result", result)
        if isinstance(result, VideoOverview):
            for image in result.images:
                encoded = "data:image/png;base64," + base64.b64encode(image).decode("ascii")
                if encoded not in req.image_urls:
                    req.image_urls.append(encoded)
            req.prompt = (req.prompt or "") + "\n\n" + result.prompt
            logger.info("[VideoUnderstanding] main request attached: images=%s cells=%s duration=%.2fs", len(result.images), result.evidence["cells_total"], result.duration)
        elif isinstance(result, str):
            req.prompt = (req.prompt or "") + "\n\n" + result
