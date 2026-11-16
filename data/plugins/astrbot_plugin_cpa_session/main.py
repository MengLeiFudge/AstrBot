"""Forward AstrBot conversation identities through CPA's Responses API route."""

from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from astrbot.api.star import Star, register
from astrbot.core.provider.entities import LLMResponse
from astrbot.core.provider.register import register_provider_adapter
from astrbot.core.provider.sources.openai_responses_source import ProviderOpenAIResponses


@register_provider_adapter(
    "cpa_responses",
    "CPA Responses with per-conversation session headers",
    provider_display_name="CPA Responses",
)
class CPASessionProvider(ProviderOpenAIResponses):
    """Reuse the Responses adapter with headers owned by each request."""

    async def _prepare_chat_payload(self, *args: Any, **kwargs: Any) -> tuple[dict, list]:
        """Add the caller's ASCII session identity to this request's payload.

        Args:
            *args: Native adapter payload arguments.
            **kwargs: Native options and the identity supplied by the entry point.

        Returns:
            The native payload and context with request-local HTTP headers.
        """
        session_id = kwargs.pop("_cpa_session_id")
        payload, context = await super()._prepare_chat_payload(*args, **kwargs)
        # Platform instance names may contain Chinese; HTTP headers require ASCII.
        payload["extra_headers"] = {
            **{
                key: value for key, value in payload.get("extra_headers", {}).items()
                if key.lower() not in {"x-client-request-id", "x-opencode-session", "user-agent"}
            },
            "x-opencode-session": quote(str(session_id), safe=":"),
            "User-Agent": "QQBot/AstrBot-cpa-session/0.1.0",
        }
        return payload, context

    async def text_chat(
        self, prompt: Any = None, session_id: str | None = None, *args: Any, **kwargs: Any
    ) -> LLMResponse:
        """Forward a non-streaming request without sharing mutable session state.

        Args:
            prompt: Native chat prompt.
            session_id: Existing conversation identity, when available.
            *args: Remaining native positional arguments.
            **kwargs: Remaining native request options.

        Returns:
            The native Responses adapter result.
        """
        return await super().text_chat(
            prompt, session_id, *args,
            _cpa_session_id=session_id or str(uuid4()), **kwargs,
        )

    async def text_chat_stream(
        self, prompt: Any = None, session_id: str | None = None, *args: Any, **kwargs: Any
    ) -> AsyncGenerator[LLMResponse, None]:
        """Forward a stream with one identity for its retries and complete lifetime.

        Args:
            prompt: Native chat prompt.
            session_id: Existing conversation identity, when available.
            *args: Remaining native positional arguments.
            **kwargs: Remaining native request options.

        Yields:
            Native Responses adapter chunks.
        """
        async with aclosing(super().text_chat_stream(
            prompt, session_id, *args,
            _cpa_session_id=session_id or str(uuid4()), **kwargs,
        )) as stream:
            async for response in stream:
                yield response


@register("cpa_session", "MLJ", "CPA conversation session forwarding", "0.1.0")
class CPASessionPlugin(Star):
    """Load the provider adapter before configured providers are initialized."""
