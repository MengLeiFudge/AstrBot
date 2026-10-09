from __future__ import annotations

from pathlib import Path
from typing import Any
import asyncio
import json

from aiohttp import web
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain, Reply
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, register
from astrbot.core.agent.message import TextPart
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from .indexer import KnowledgeIndexUnavailableError, SharedDspKnowledgeIndex


HOST = "127.0.0.1"
DEFAULT_PORT = 8081
SEARCH_PATH = "/v1/knowledge/dsp/search"
HEALTH_PATH = "/v1/knowledge/dsp/health"
EVIDENCE_MARKER = "<mlj.shared-dsp-knowledge:v1>"
EVIDENCE_END_MARKER = "</mlj.shared-dsp-knowledge:v1>"


@register(
    "astrbot_plugin_dsp_knowledge",
    "MengLei",
    "Shared vector knowledge for six major Dyson Sphere Program mods.",
    "0.1.0",
)
class DspKnowledgePlugin(Star):
    """Maintain one DSP vector corpus and serve evidence to both local bots."""

    def __init__(self, context: Context, config=None) -> None:
        """Initialize immutable configuration and owned runtime resources.

        Args:
            context: AstrBot services, including the native knowledge-base manager.
            config: Plugin configuration loaded by AstrBot.
        """

        super().__init__(context, config)
        source_root = Path(str(_config_value(config, "source_root", "D:/project/dsp")))
        knowledge_base_name = str(
            _config_value(config, "knowledge_base_name", "dsp-major-mods")
        ).strip()
        embedding_provider_id = str(
            _config_value(config, "embedding_provider_id", "openai_embedding")
        ).strip()
        rerank_provider_id = str(
            _config_value(config, "rerank_provider_id", "bailian_rerank")
        ).strip()
        self._sync_interval_seconds = max(
            60,
            int(_config_value(config, "sync_interval_seconds", 600)),
        )
        self._port = int(_config_value(config, "api_port", DEFAULT_PORT))
        if not 1_024 <= self._port <= 65_535:
            raise ValueError("DSP knowledge api_port must be between 1024 and 65535")
        if not knowledge_base_name or not embedding_provider_id or not rerank_provider_id:
            raise ValueError("DSP knowledge base and provider IDs must not be empty")

        state_root = Path(get_astrbot_plugin_data_path()) / "astrbot_plugin_dsp_knowledge"
        self._index = SharedDspKnowledgeIndex(
            context=context,
            source_root=source_root,
            manifest_path=state_root / "index_manifest.json",
            knowledge_base_name=knowledge_base_name,
            embedding_provider_id=embedding_provider_id,
            rerank_provider_id=rerank_provider_id,
            max_results=int(_config_value(config, "max_results", 4)),
            max_evidence_chars=int(_config_value(config, "max_evidence_chars", 6_000)),
        )
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._sync_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def initialize(self) -> None:
        """Start the loopback API before scheduling the initial synchronization."""

        app = web.Application(client_max_size=32 * 1_024)
        app.router.add_get(HEALTH_PATH, self._health)
        app.router.add_post(SEARCH_PATH, self._search)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, HOST, self._port)
        try:
            await self._site.start()
        except Exception:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
            raise
        self._sync_task = asyncio.create_task(
            self._synchronization_loop(),
            name="dsp-knowledge-sync",
        )
        logger.info(
            "[DSPKnowledge] loopback retrieval API listening on http://%s:%s%s",
            HOST,
            self._port,
            SEARCH_PATH,
        )

    async def terminate(self) -> None:
        """Stop periodic synchronization and release the loopback listener."""

        self._stop_event.set()
        if self._sync_task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._sync_task), timeout=30)
            except asyncio.TimeoutError:
                self._sync_task.cancel()
                try:
                    await self._sync_task
                except asyncio.CancelledError:
                    pass
            self._sync_task = None
        if self._runner is not None:
            await self._runner.cleanup()
        self._runner = None
        self._site = None

    @filter.on_llm_request(
        desc="Retrieve reranked evidence from the shared DSP vector knowledge base."
    )
    async def inject_dsp_knowledge(
        self,
        event: AstrMessageEvent,
        req: ProviderRequest,
    ) -> None:
        """Inject shared DSP evidence into Yunqi's current model request."""

        query = _effective_query(event, str(req.prompt or ""))
        if not query:
            return
        try:
            result = await self._index.search(query, str(event.get_group_id() or ""))
        except KnowledgeIndexUnavailableError:
            logger.debug("[DSPKnowledge] Yunqi retrieval skipped because the index is unavailable")
            return
        except Exception as exc:
            logger.warning(
                "[DSPKnowledge] Yunqi retrieval failed: error_type=%s",
                type(exc).__name__,
            )
            return
        if not result.matched or not result.evidence:
            return
        req.extra_user_content_parts.append(
            TextPart(
                text=(
                    f"{EVIDENCE_MARKER}\n"
                    f"{result.evidence}\n"
                    f"{EVIDENCE_END_MARKER}"
                )
            ).mark_as_temp()
        )
        logger.info(
            "[DSPKnowledge] injected Yunqi evidence: hits=%s chars=%s",
            result.hit_count,
            len(result.evidence),
        )

    async def _synchronization_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._wait_for_knowledge_base_manager()
                if self._stop_event.is_set():
                    break
                await self._index.synchronize()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "[DSPKnowledge] synchronization pass will retry: error_type=%s",
                    type(exc).__name__,
                )
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._sync_interval_seconds,
                )
            except asyncio.TimeoutError:
                continue

    async def _wait_for_knowledge_base_manager(self) -> None:
        """Wait until AstrBot finishes initializing native KB storage and retrieval."""

        manager = self.context.kb_manager
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 30
        while loop.time() < deadline:
            if hasattr(manager, "kb_db") and hasattr(manager, "retrieval_manager"):
                return
            if self._stop_event.is_set():
                return
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=0.25)
            except asyncio.TimeoutError:
                continue
        raise RuntimeError("AstrBot knowledge base manager did not initialize within 30 seconds")

    async def _health(self, request: web.Request) -> web.Response:
        if not _is_loopback_request(request):
            return web.json_response({"ok": False, "error": "loopback_required"}, status=403)
        status = self._index.status()
        return web.json_response(
            {"ok": bool(status["ready"] and not status["syncing"]), "status": status}
        )

    async def _search(self, request: web.Request) -> web.Response:
        if not _is_loopback_request(request):
            return web.json_response({"ok": False, "error": "loopback_required"}, status=403)
        try:
            payload = await request.json()
        except (json.JSONDecodeError, TypeError, ValueError):
            return web.json_response({"ok": False, "error": "invalid_json"}, status=400)
        if not isinstance(payload, dict):
            return web.json_response({"ok": False, "error": "invalid_payload"}, status=400)
        query = str(payload.get("query", "") or "").strip()
        group_id = str(payload.get("group_id", "") or "").strip()
        if not query or len(query) > 4_000 or len(group_id) > 64:
            return web.json_response({"ok": False, "error": "invalid_query"}, status=400)
        try:
            result = await asyncio.wait_for(
                self._index.search(query, group_id),
                timeout=20,
            )
        except KnowledgeIndexUnavailableError:
            return web.json_response(
                {
                    "ok": False,
                    "matched": True,
                    "error": "index_unavailable",
                    "status": self._index.status(),
                },
                status=503,
            )
        except asyncio.TimeoutError:
            return web.json_response({"ok": False, "error": "retrieval_timeout"}, status=504)
        except Exception as exc:
            logger.warning(
                "[DSPKnowledge] shared API retrieval failed: error_type=%s",
                type(exc).__name__,
            )
            return web.json_response({"ok": False, "error": "retrieval_failed"}, status=500)
        return web.json_response(
            {
                "ok": True,
                "matched": result.matched,
                "evidence": result.evidence,
                "hit_count": result.hit_count,
            }
        )


def _effective_query(event: AstrMessageEvent, prompt: str) -> str:
    """Combine the current prompt with bounded text from quoted messages."""

    current = str(prompt or "").strip()
    if not current:
        try:
            current = str(event.get_message_str() or "").strip()
        except Exception:
            current = ""
    quoted: list[str] = []
    try:
        messages = event.get_messages()
    except Exception:
        messages = []
    for segment in messages:
        if not isinstance(segment, Reply):
            continue
        text = str(segment.message_str or segment.text or "").strip()
        if not text and segment.chain:
            text = "".join(
                str(item.text or "")
                for item in segment.chain
                if isinstance(item, Plain)
            ).strip()
        if text and text not in {"[图片]", "[image]"}:
            quoted.append(text)
    parts = [f"被引用消息：{text}" for text in quoted]
    if current:
        parts.append(f"当前消息：{current}")
    return "\n".join(parts)[:4_000].strip()


def _config_value(config: Any, key: str, default: Any) -> Any:
    if config is None:
        return default
    getter = getattr(config, "get", None)
    if not callable(getter):
        return default
    value = getter(key, default)
    return default if value is None else value


def _is_loopback_request(request: web.Request) -> bool:
    return request.remote in {"127.0.0.1", "::1", "localhost"}
