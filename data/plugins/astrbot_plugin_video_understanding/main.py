"""Enrich normal AstrBot chat with descriptions of video contact sheets."""

from __future__ import annotations

import base64
import json

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Json, Plain, Video
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, StarTools, register

from .video_reader import VideoError, VideoOverview, VideoReader, VideoSource, find_video_sources


@register("astrbot_plugin_video_understanding", "MengLei", "下载视频、抽帧拼图并补充视频内容。", "1.0.0")
class VideoUnderstandingPlugin(Star):
    """Use public request hooks and the configured image provider for video vision."""

    def __init__(self, context: Context, config=None) -> None:
        """Create one reader whose temporary files belong to this plugin.

        Args:
            context: Public framework context used for model selection and calls.
            config: Plugin settings containing the boolean enabled flag.
        """
        super().__init__(context)
        self._context = context
        enabled = (config or {}).get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("Video plugin enabled must be a boolean")
        self._enabled = enabled
        self._reader = VideoReader(StarTools.get_data_dir("astrbot_plugin_video_understanding"))
        logger.info("[VideoUnderstanding] enabled=%s tools_ready=%s", enabled, self._reader.tools_ready)

    async def terminate(self) -> None:
        """Cancel the current download and release the description cache."""
        await self._reader.close()

    async def _describe(self, overview: VideoOverview, umo: str) -> str:
        """Reuse the session's image provider without persisting chat history.

        Args:
            overview: Contact sheet and verified video metadata.
            umo: Current session origin used to select its configured provider.

        Returns:
            Model description of the supplied video frames.
        """
        settings = self._context.get_config(umo).get("provider_settings", {})
        provider = str(settings.get("default_image_caption_provider_id") or "")
        if not provider:
            provider = await self._context.get_current_chat_provider_id(umo)
        response = await self._context.llm_generate(
            chat_provider_id=provider, prompt=overview.prompt,
            system_prompt="根据分镜图提供可信的视频画面描述，明确区分实际画面与未提供的声音信息。",
            image_urls=["data:image/jpeg;base64," + base64.b64encode(overview.image).decode("ascii")],
            contexts=[], persist=False,
        )
        return response.completion_text

    @filter.event_message_type(filter.EventMessageType.ALL, priority=1100, desc="保留当前视频来源，由插件处理有界下载和分镜。")
    async def prepare_video_attachments(self, event: AstrMessageEvent) -> None:
        """Retain video sources before the framework's attachment downloader runs.

        Args:
            event: Current message whose video components become text placeholders.
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
                event.set_extra("qqbot_video_description", "[视频未读取] 当前附件没有可用下载地址，请改发视频链接或重新发送原视频。不能声称已经看过。")
            event.set_extra("qqbot_video_native_sources", sources)
            event.message_str = (event.message_str + "\n[视频]").strip()
            event.message_obj.message_str = event.message_str

    @filter.on_llm_request(desc="在普通聊天请求中补充当前视频链接或附件的分镜描述。")
    async def enrich_video(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        """Describe current-message video sources while preserving chat routing.

        Args:
            event: Incoming message and its retained native video sources.
            req: Existing chat request enriched with the video description.
        """
        if not self._enabled or str(event.get_sender_id()) == str(event.get_self_id()):
            return
        stored_sources = event.get_extra("qqbot_video_native_sources")
        sources = [source for source in stored_sources if isinstance(source, VideoSource)] if isinstance(stored_sources, list) else []
        text = []
        for component in event.get_messages():
            if isinstance(component, Video):
                url = str(component.url or component.file or "").strip()
                if url.startswith(("http://", "https://")):
                    sources.append(VideoSource(url, direct=True))
            elif isinstance(component, Plain):
                text.append(component.text)
            elif isinstance(component, Json):
                text.append(json.dumps(component.data, ensure_ascii=False))
        if not sources:
            sources = find_video_sources("\n".join(text))
        cached = event.get_extra("qqbot_video_description")
        if not sources and not isinstance(cached, str):
            return
        if isinstance(cached, str):
            description = cached
        else:
            try:
                description = await self._reader.analyze(
                    sources[0], lambda overview: self._describe(overview, event.unified_msg_origin),
                )
                logger.info("[VideoUnderstanding] video description ready")
            except VideoError as exc:
                description = f"[视频未读取] {exc}。请明确说明尚未看到视频，不能根据标题或其他图片编造内容。"
                logger.warning("[VideoUnderstanding] video unavailable: %s", exc)
            except Exception as exc:
                description = "[视频未读取] 下载、抽帧或视觉模型调用失败，请重发可访问的短视频；不能声称已经看过。"
                logger.warning("[VideoUnderstanding] analysis failed: error_type=%s", type(exc).__name__)
            event.set_extra("qqbot_video_description", description)
        req.prompt = (req.prompt or "") + "\n\n" + description
