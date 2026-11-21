from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
from io import BytesIO
import os
from pathlib import Path
import re
import threading
import time
from urllib.error import HTTPError
from urllib.parse import unquote, urlsplit

import httpx
from PIL import Image

from .draw_output import load_generated_image
from .runtime_storage import RuntimeJsonStore
from .runtime_storage import read_json_file


DRAW_BASE_URL = "http://127.0.0.1:8317/v1"
DRAW_USER_AGENT = "QQBot-CPA-Draw/1.0"
DRAW_DEFAULT_MODEL = "gpt-image-2.6"
DRAW_POINT_PRICE_MULTIPLIER = 1000
DRAW_FALLBACK_PRICE = Decimal("0.06")
DRAW_MODEL_PRICES: dict[str, Decimal] = {
    "gpt-image-2.6": Decimal("0.06"),
    "gpt-image-2.6-flare": Decimal("0.15"),
    "gpt-image-2.6-sunburst": Decimal("0.15"),
}
DRAW_FALLBACK_DESCRIPTION = "支持文字生图和参考图生图"
DRAW_MODEL_DESCRIPTIONS: dict[str, str] = {}
DRAW_MODEL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,63}$")
DRAW_IMAGE_MODEL_HINTS = (
    "image",
    "imagen",
    "dall-e",
    "dalle",
    "flux",
    "banana",
    "seedream",
)
DRAW_MODEL_UNAVAILABLE_HINTS = (
    "is not supported on /v1/images/",
    "model_not_found",
    "model not found",
    "model does not exist",
    "unsupported model",
    "no available channel",
)
DRAW_MODEL_CACHE_TTL_SECONDS = 600.0
DRAW_MODEL_ATTEMPT_LIMIT = 4
DRAW_DEFAULT_IMAGE_SIZE = "4096x4096"
DRAW_DEFAULT_LANDSCAPE_SIZE = "4096x2304"
DRAW_DEFAULT_PORTRAIT_SIZE = "2304x4096"
DRAW_IMAGE_SIZE_RE = re.compile(r"^[1-9][0-9]{2,4}x[1-9][0-9]{2,4}$")
DRAW_SIZE_LEVELS: dict[str, dict[str, str]] = {
    "1k": {"square": "1024x1024", "landscape": "1536x1024", "portrait": "1024x1536"},
    "2k": {"square": "2048x2048", "landscape": "2048x1152", "portrait": "1152x2048"},
    "4k": {"square": "4096x4096", "landscape": "4096x2304", "portrait": "2304x4096"},
}
DRAW_COMMAND_PREFIX_RE = re.compile(r"^(文生|图生|头像生)")
DRAW_COMMAND_BASES = {"文生": "文生图", "图生": "图生图", "头像生": "头像生图"}
DRAW_ORIENTATION_CHARS = {"横": "landscape", "竖": "portrait", "动": ""}
DRAW_STRAY_MODE_RE = re.compile(r"(?:^|\s)(横图|竖图|动图|横幅|横版|竖幅|竖版)(?:\s|$)")
DRAW_LEVEL_TOKEN_RE = re.compile(r"(1k|2k|4k)", re.IGNORECASE)
_DRAW_MODEL_VERSION_RE = re.compile(r"(\d+(?:\.\d+)*)")
_DRAW_MODEL_CACHE: dict[tuple[str, str], tuple[float, tuple[str, ...]]] = {}
_DRAW_MODEL_CACHE_LOCK = asyncio.Lock()
FEATURE_MODE_FULL = "full"
_DRAW_POINTS_LOCK = threading.Lock()
_DRAW_POINTS_QUERY_RE = re.compile(
    r"^(?:(?:查|查询|查看|看)(?:一下)?)?(?:我(?:的)?|当前)?(?:生图)?积分(?:余额|情况|多少)?$"
)
_DRAW_POINTS_ENGLISH_QUERY_RE = re.compile(r"^(?:balance|points?)$", re.IGNORECASE)
_DRAW_POINTS_MUTATION_RE = re.compile(
    r"(?:加|增加|扣|扣除|减|减少|改|修改|设置|设定|送|赠|赠送|充值|充).{0,16}积分"
    r"|积分.{0,16}(?:加|增加|扣|扣除|减|减少|改|修改|设置|设定|送|赠|赠送|充值|充)"
)
_DRAW_MODEL_SWITCH_PRIMARY_RE = re.compile(r"^切换\s*生图\s*模型\s*(.*)$", re.IGNORECASE)
_DRAW_MODEL_SWITCH_ALIAS_RE = re.compile(r"^生图\s*模型\s*(.+)$", re.IGNORECASE)
DRAW_DOUDOUYAN_COMMAND = "生成豆豆眼头像"
DRAW_DOUDOUYAN_COMMAND = "生成豆豆眼头像"


@dataclass(frozen=True, slots=True)
class DrawRequest:
    prompt: str
    model: str = DRAW_DEFAULT_MODEL
    image_urls: tuple[str, ...] = ()
    gif: bool = False
    size_level: str = ""
    orientation: str = ""


@dataclass(frozen=True, slots=True)
class DrawCommand:
    """One parsed draw command: mode words, level, orientation, and the prompt."""

    base: str
    prompt: str
    gif: bool = False
    size_level: str = ""
    orientation: str = ""
    base_end: int = 0
    prompt_offset: int = 0

@dataclass(frozen=True, slots=True)
class DrawResult:
    """Validated image bytes for persistence/delivery, with the original CPA source."""

    image_url: str
    total_seconds: float
    image_bytes: bytes = b""
    image_format: str = "png"


@dataclass(frozen=True, slots=True)
class DrawPointBalance:
    user_id: str
    points: int
    model: str
    multiplier: int


@dataclass(frozen=True, slots=True)
class DrawQuotaResult:
    allowed: bool
    user_id: str
    model: str
    cost_points: int
    balance_before: int
    balance_after: int
    multiplier: int
    price: str


@dataclass(frozen=True, slots=True)
class DrawImageSizes:
    """Requested output sizes; CPA hands them to the channel that renders the image."""

    square: str = DRAW_DEFAULT_IMAGE_SIZE
    landscape: str = DRAW_DEFAULT_LANDSCAPE_SIZE
    portrait: str = DRAW_DEFAULT_PORTRAIT_SIZE

    def resolve(self, level: str = "", orientation: str = "") -> str:
        """Pick the requested size for one image call.

        Args:
            level: Explicit 1k / 2k / 4k wording from the command, if any.
            orientation: "square", "landscape", or "portrait".

        Returns:
            The size preset for that level and orientation, or the configured default.
        """

        chosen = orientation or "square"
        preset = DRAW_SIZE_LEVELS.get(level)
        if preset is not None:
            return preset[chosen]
        return getattr(self, chosen)

@dataclass(frozen=True, slots=True)
class DrawConfig:
    feature_mode: str
    data_root: Path
    api_key: str
    point_multiplier: int
    draw_timeout_seconds: float
    base_url: str = DRAW_BASE_URL
    image_sizes: DrawImageSizes = field(default_factory=DrawImageSizes)


class DrawTimeoutError(TimeoutError):
    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        super().__init__(f"生图超过 {timeout_seconds:.0f} 秒未返回")


class DrawModelUnavailableError(RuntimeError):
    """Raised when CPA does not register the requested model for the Images API."""

    def __init__(self, model: str) -> None:
        self.model = model
        super().__init__(f"CPA 尚未将 {model} 注册为图片模型")


class DrawClient:
    """Send image requests through CPA, which owns upstream selection and retries."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DRAW_BASE_URL,
        timeout_seconds: float = 240.0,
        image_sizes: DrawImageSizes | None = None,
    ) -> None:
        """Configure the client without opening a persistent HTTP session.

        Args:
            api_key: CPA client credential, never an upstream channel credential.
            base_url: OpenAI-compatible API root including /v1.
            timeout_seconds: Total deadline, including reference image downloads.
            image_sizes: Requested output sizes; defaults keep the 4K square preset.
        """
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.image_sizes = image_sizes or DrawImageSizes()

    async def draw_batch(
        self, requests: tuple[DrawRequest, ...],
    ) -> tuple[DrawResult | BaseException, ...]:
        """Await all one-image calls concurrently without discarding partial success.

        Args:
            requests: One ordinary request or four prepared preset requests.

        Returns:
            Results or failures in request order; each call has this client's deadline.

        Raises:
            ValueError: If the batch size is unsupported.
            asyncio.CancelledError: If the caller cancels; all children are awaited.
        """
        if len(requests) not in (1, 4):
            raise ValueError("生图批次必须包含一张或四张")
        tasks = [asyncio.create_task(self.draw(request)) for request in requests]
        try:
            return tuple(await asyncio.gather(*tasks, return_exceptions=True))
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def draw(self, request: DrawRequest) -> DrawResult:
        """Generate one image, falling back to other registered image models."""

        if not self.api_key:
            raise ValueError("缺少 CPA 生图 API Key")
        preferred = str(request.model or "").strip().lower()
        if not DRAW_MODEL_NAME_RE.fullmatch(preferred):
            raise ValueError(f"不支持的生图模型: {request.model}")
        candidates = await self._model_candidates(preferred)
        attempted: list[str] = []
        refreshed = False
        index = 0
        while index < len(candidates) and len(attempted) < DRAW_MODEL_ATTEMPT_LIMIT:
            model = candidates[index]
            index += 1
            if model in attempted:
                continue
            attempted.append(model)
            try:
                return await self._draw_with_model(
                    request, model, self.image_sizes.resolve(request.size_level, request.orientation)
                )
            except DrawModelUnavailableError:
                if refreshed:
                    continue
                refreshed = True
                invalidate_draw_models(api_key=self.api_key, base_url=self.base_url)
                for extra in await self._model_candidates(preferred, refresh=True):
                    if extra not in candidates:
                        candidates.append(extra)
        tried = "、".join(attempted) or preferred
        raise RuntimeError(f"CPA 没有可用的生图模型（已尝试 {tried}），请检查渠道模型的 image 配置")

    async def _model_candidates(self, preferred: str, *, refresh: bool = False) -> list[str]:
        """Return the preferred model first, then other image models registered in CPA."""

        try:
            models = await fetch_draw_models(
                api_key=self.api_key, base_url=self.base_url, preferred=preferred, refresh=refresh,
            )
        except (httpx.HTTPError, ValueError):
            return [preferred]
        return list(models) or [preferred]

    async def _draw_with_model(self, request: DrawRequest, model: str, size: str) -> DrawResult:
        """Generate one image, uploading references through the Images edits API.

        Args:
            request: Prompt and optional reference image sources.
            model: Image model that CPA registered for the Images API.
            size: Requested output size; the channel renders exactly this ratio.

        Returns:
            The original source, validated PNG bytes, and total elapsed seconds.

        Raises:
            DrawModelUnavailableError: If CPA does not register the model.
            DrawTimeoutError: If the total deadline expires.
            RuntimeError: If CPA returns an error or no image.
        """
        started = time.perf_counter()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": DRAW_USER_AGENT,
        }
        payload = {
            "model": model,
            "prompt": request.prompt,
            "n": 1,
            "size": size,
            "response_format": "b64_json",
            "output_format": "gif" if request.gif else "png",
        }
        try:
            async with asyncio.timeout(self.timeout_seconds):
                async with httpx.AsyncClient(timeout=self.timeout_seconds, trust_env=False) as client:
                    if request.image_urls:
                        # Use the single-file field for one reference; arrays are for multi-image edits.
                        field = "image" if len(request.image_urls) == 1 else "image[]"
                        files = []
                        for index, source in enumerate(request.image_urls):
                            image, mime = await load_draw_reference_image(source, client)
                            files.append((field, (f"reference-{index}.{mime.split('/')[-1]}", image, mime)))
                        response = await client.post(
                            f"{self.base_url}/images/edits",
                            headers=headers,
                            data={key: str(value) for key, value in payload.items()},
                            files=files,
                        )
                    else:
                        response = await client.post(
                            f"{self.base_url}/images/generations",
                            headers=headers,
                            json=payload,
                        )
                    response.raise_for_status()
                    data = response.json()
                    image_url = extract_image_url_from_object(data)
                    if not image_url:
                        raise RuntimeError(extract_draw_task_error(data) or "生图服务没有返回图片")
                    image_bytes, image_format = await load_generated_image(image_url, client)
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise DrawTimeoutError(self.timeout_seconds) from exc
        except httpx.HTTPStatusError as exc:
            try:
                detail = extract_draw_task_error(exc.response.json())
            except (ValueError, httpx.ResponseNotRead):
                detail = ""
            detail = re.sub(r"\s+", " ", detail).replace(self.api_key, "[redacted]")
            detail = re.sub(r"\b(?:sk-|Bearer\s+)[A-Za-z0-9._-]+", "[redacted]", detail, flags=re.IGNORECASE)[:300]
            if is_draw_model_unavailable(exc.response.status_code, detail):
                raise DrawModelUnavailableError(model) from exc
            message = f"生图服务返回 HTTP {exc.response.status_code}"
            if detail:
                message += f"：{detail}"
            raise RuntimeError(message) from exc
        return DrawResult(
            image_url=image_url, image_bytes=image_bytes, image_format=image_format,
            total_seconds=time.perf_counter() - started,
        )


async def load_draw_reference_image(source: str, client: httpx.AsyncClient) -> tuple[bytes, str]:
    """Load a reference for multipart upload without sending CPA credentials to its host.

    Args:
        source: An HTTP URL, local path, file URL, or Base64 image source.
        client: The request-scoped HTTP client without default authorization headers.

    Returns:
        At most 20 MiB of image bytes and their detected MIME type.

    Raises:
        ValueError: If the reference is empty, too large, or not a supported image.
    """
    limit = 20 * 1024 * 1024
    if source.startswith(("data:image/", "base64://")):
        if source.startswith("data:image/"):
            header, separator, encoded = source.partition(",")
            if not separator or ";base64" not in header.lower():
                raise ValueError("参考图必须是 Base64 data URL")
        else:
            encoded = source.removeprefix("base64://")
        encoded = re.sub(r"\s+", "", encoded)
        if len(encoded) > (limit + 2) // 3 * 4:
            raise ValueError("参考图不能超过 20 MiB")
        image = base64.b64decode(encoded, validate=True)
    elif source.startswith(("http://", "https://")):
        content = bytearray()
        async with client.stream("GET", source, follow_redirects=True) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > limit:
                    raise ValueError("参考图不能超过 20 MiB")
        image = bytes(content)
    else:
        path = source
        if source.startswith("file://"):
            path = unquote(urlsplit(source).path)
            if re.match(r"^/[A-Za-z]:", path):
                path = path[1:]
        with Path(path).open("rb") as stream:
            image = stream.read(limit + 1)
    if not image or len(image) > limit:
        raise ValueError("参考图不能为空或超过 20 MiB")
    with Image.open(BytesIO(image)) as reference:
        mime = Image.MIME.get(reference.format or "", "")
        if mime not in {"image/png", "image/jpeg", "image/webp"}:
            converted = BytesIO()
            reference.convert("RGBA").save(converted, format="PNG")
            image, mime = converted.getvalue(), "image/png"
        else:
            reference.verify()
    if len(image) > limit:
        raise ValueError("参考图转换后不能超过 20 MiB")
    return image, mime


def is_draw_model_unavailable(status_code: int, detail: str) -> bool:
    """Tell whether a CPA failure means the model is not usable for images."""

    if status_code == 404:
        return True
    lowered = detail.lower()
    return any(hint in lowered for hint in DRAW_MODEL_UNAVAILABLE_HINTS)


def rank_draw_models(models: tuple[str, ...] | list[str], *, preferred: str = "") -> tuple[str, ...]:
    """Rank registered image models with the preferred one first.

    Args:
        models: Model identifiers reported by CPA.
        preferred: Model to put first when it is still registered.

    Returns:
        Deduplicated image model names; newer base names precede their variants.
    """
    candidates = [
        name
        for name in (str(raw or "").strip().lower() for raw in models)
        if DRAW_MODEL_NAME_RE.fullmatch(name)
        and any(hint in name for hint in DRAW_IMAGE_MODEL_HINTS)
    ]
    ordered = sorted(dict.fromkeys(candidates), key=_draw_model_sort_key)
    preferred_key = str(preferred or "").strip().lower()
    if preferred_key in ordered:
        ordered.remove(preferred_key)
        ordered.insert(0, preferred_key)
    return tuple(ordered)


def _draw_model_sort_key(model: str) -> tuple[tuple[int, ...], int, str]:
    """Sort newer versions first and keep a base name ahead of its variants."""
    match = _DRAW_MODEL_VERSION_RE.search(model)
    version = tuple(-int(part) for part in match.group(1).split(".")) if match else (1,)
    return (version, model.count("-"), model)


def _draw_model_cache_key(api_key: str, base_url: str) -> tuple[str, str]:
    return (base_url.rstrip("/"), api_key)


def invalidate_draw_models(*, api_key: str, base_url: str) -> None:
    """Drop the cached model list so the next call rediscovers CPA registrations."""
    _DRAW_MODEL_CACHE.pop(_draw_model_cache_key(api_key, base_url), None)


async def fetch_draw_models(
    *,
    api_key: str,
    base_url: str,
    preferred: str = "",
    refresh: bool = False,
) -> tuple[str, ...]:
    """Read the image models CPA currently registers, cached for a short while.

    Args:
        api_key: CPA client credential.
        base_url: OpenAI-compatible API root including /v1.
        preferred: Model to put first when it is still registered.
        refresh: Ignore the cached model list.

    Returns:
        Ranked image model names; empty when CPA registers none.

    Raises:
        httpx.HTTPError: If the model list request fails.
        ValueError: If the response is not JSON.
    """
    cache_key = _draw_model_cache_key(api_key, base_url)
    if not refresh:
        cached = _DRAW_MODEL_CACHE.get(cache_key)
        if cached is not None and time.monotonic() - cached[0] < DRAW_MODEL_CACHE_TTL_SECONDS:
            return rank_draw_models(cached[1], preferred=preferred)
    async with _DRAW_MODEL_CACHE_LOCK:
        cached = None if refresh else _DRAW_MODEL_CACHE.get(cache_key)
        if cached is not None and time.monotonic() - cached[0] < DRAW_MODEL_CACHE_TTL_SECONDS:
            return rank_draw_models(cached[1], preferred=preferred)
        models = await request_draw_models(api_key=api_key, base_url=base_url)
        _DRAW_MODEL_CACHE[cache_key] = (time.monotonic(), models)
    return rank_draw_models(models, preferred=preferred)


async def request_draw_models(*, api_key: str, base_url: str) -> tuple[str, ...]:
    """List every model identifier CPA reports through the OpenAI models endpoint."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": DRAW_USER_AGENT,
    }
    async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
        response = await client.get(f"{base_url.rstrip('/')}/models", headers=headers)
        response.raise_for_status()
        data = response.json()
    entries = data.get("data") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        return ()
    names = []
    for entry in entries:
        value = entry.get("id") if isinstance(entry, dict) else entry
        name = str(value or "").strip().lower()
        if name:
            names.append(name)
    return tuple(dict.fromkeys(names))


class DrawQuotaStore:
    def __init__(
        self,
        data_root: Path,
        *,
        multiplier: int = DRAW_POINT_PRICE_MULTIPLIER,
    ) -> None:
        self.data_root = Path(data_root)
        self.multiplier = max(1, int(multiplier))
        self.path = self.data_root / "ai" / "draw_points.json"
        self.store = RuntimeJsonStore(self.data_root)

    def record_group_message(self, user_id: int | str, *, amount: int = 1) -> int:
        user_key = str(user_id).strip()
        if not user_key or amount <= 0:
            return 0
        with _DRAW_POINTS_LOCK:
            payload = self._read()
            users = get_users_payload(payload)
            user_payload = get_user_payload(users, user_key)
            points = int(user_payload.get("points", 0) or 0) + int(amount)
            user_payload["points"] = points
            users[user_key] = user_payload
            payload["users"] = users
            self._write(payload)
            return points

    def get_balance(self, user_id: int | str) -> DrawPointBalance:
        user_key = str(user_id).strip()
        if not user_key:
            return DrawPointBalance("", 0, DRAW_DEFAULT_MODEL, self.multiplier)
        with _DRAW_POINTS_LOCK:
            payload = self._read()
            users = get_users_payload(payload)
            user_payload = get_user_payload(users, user_key)
        return DrawPointBalance(
            user_id=user_key,
            points=int(user_payload.get("points", 0) or 0),
            model=normalize_draw_model(user_payload.get("model")),
            multiplier=self.multiplier,
        )

    def set_model(self, user_id: int | str, model: str) -> DrawPointBalance:
        user_key = str(user_id).strip()
        model_key = str(model or "").strip().lower()
        if not user_key:
            raise ValueError("缺少 QQ 用户 ID")
        if not DRAW_MODEL_NAME_RE.fullmatch(model_key):
            raise ValueError(f"不支持的生图模型: {model}")
        with _DRAW_POINTS_LOCK:
            payload = self._read()
            users = get_users_payload(payload)
            user_payload = get_user_payload(users, user_key)
            user_payload["model"] = model_key
            users[user_key] = user_payload
            payload["users"] = users
            self._write(payload)
            return DrawPointBalance(
                user_id=user_key,
                points=int(user_payload.get("points", 0) or 0),
                model=model_key,
                multiplier=self.multiplier,
            )

    def get_points_ranking(self, *, limit: int = 10) -> tuple[DrawPointBalance, ...]:
        with _DRAW_POINTS_LOCK:
            payload = self._read()
            users = get_users_payload(payload)
        balances = [
            DrawPointBalance(
                user_id=user_id,
                points=int(user_payload.get("points", 0) or 0),
                model=normalize_draw_model(user_payload.get("model")),
                multiplier=self.multiplier,
            )
            for user_id, user_payload in users.items()
        ]
        balances.sort(key=lambda item: (-item.points, sortable_user_id(item.user_id)))
        return tuple(balances[: max(0, int(limit))])

    def reserve(
        self,
        user_id: int | str,
        *,
        model: str = DRAW_DEFAULT_MODEL,
    ) -> DrawQuotaResult:
        user_key = str(user_id).strip()
        model = normalize_draw_model(model)
        cost_points = calculate_draw_model_points(model, multiplier=self.multiplier)
        price = format_draw_model_price(model)
        if not user_key:
            return DrawQuotaResult(False, "", model, cost_points, 0, 0, self.multiplier, price)
        with _DRAW_POINTS_LOCK:
            payload = self._read()
            users = get_users_payload(payload)
            user_payload = get_user_payload(users, user_key)
            balance = int(user_payload.get("points", 0) or 0)
            if balance < cost_points:
                return DrawQuotaResult(
                    False, user_key, model, cost_points, balance, balance, self.multiplier, price
                )
            user_payload["points"] = balance - cost_points
            users[user_key] = user_payload
            payload["users"] = users
            self._write(payload)
            return DrawQuotaResult(
                True,
                user_key,
                model,
                cost_points,
                balance,
                balance - cost_points,
                self.multiplier,
                price,
            )

    def refund(self, reservation: DrawQuotaResult) -> None:
        if not reservation.allowed or not reservation.user_id:
            return
        with _DRAW_POINTS_LOCK:
            payload = self._read()
            users = get_users_payload(payload)
            user_payload = get_user_payload(users, reservation.user_id)
            if reservation.cost_points > 0:
                points = int(user_payload.get("points", 0) or 0)
                user_payload["points"] = points + reservation.cost_points
            users[reservation.user_id] = user_payload
            payload["users"] = users
            self._write(payload)

    def _read(self) -> dict[str, object]:
        raw = self.store.read("draw.points", {"schema_version": 2, "users": {}})
        if not isinstance(raw, dict):
            raw = {"schema_version": 2, "users": {}}
        normalized = normalize_draw_points_payload(raw)
        if normalized != raw:
            self.store.write("draw.points", normalized)
        raw = normalized
        if not self.path.exists():
            return raw
        fingerprint = fingerprint_file(self.path)
        imports = self.store.read("draw.points_legacy_imports", {"files": {}})
        imported_files = imports.get("files") if isinstance(imports, dict) else {}
        if isinstance(imported_files, dict) and imported_files.get(str(self.path)) == fingerprint:
            return raw
        legacy_raw = read_json_file(self.path, {"schema_version": 1, "users": {}})
        merged = merge_draw_points_payload(raw, legacy_raw)
        if merged != raw:
            self.store.write("draw.points", merged)
        if not isinstance(imported_files, dict):
            imported_files = {}
        imported_files[str(self.path)] = fingerprint
        self.store.write("draw.points_legacy_imports", {"files": imported_files})
        return merged

    def _write(self, payload: dict[str, object]) -> None:
        payload = normalize_draw_points_payload(payload)
        self.store.write("draw.points", payload)


def load_draw_config(config=None) -> DrawConfig:
    feature_mode = read_feature_mode(config)
    data_root_raw = get_config_value(config, "data_root", "")
    data_root = Path(str(data_root_raw)).expanduser() if str(data_root_raw or "").strip() else resolve_default_data_root()
    return DrawConfig(
        feature_mode=feature_mode,
        data_root=data_root,
        api_key=str(get_config_value(config, "api_key", "") or "").strip(),
        base_url=str(get_config_value(config, "base_url", DRAW_BASE_URL) or DRAW_BASE_URL).strip(),
        point_multiplier=max(1, safe_int(get_config_value(config, "point_multiplier", 1000), 1000)),
        draw_timeout_seconds=max(
            30.0,
            float(safe_int(get_config_value(config, "draw_timeout_seconds", 240), 240)),
        ),
        image_sizes=DrawImageSizes(
            square=_normalize_image_size(
                get_config_value(config, "draw_image_size_square", DRAW_DEFAULT_IMAGE_SIZE),
                DRAW_DEFAULT_IMAGE_SIZE,
            ),
            landscape=_normalize_image_size(
                get_config_value(config, "draw_image_size_landscape", DRAW_DEFAULT_LANDSCAPE_SIZE),
                DRAW_DEFAULT_LANDSCAPE_SIZE,
            ),
            portrait=_normalize_image_size(
                get_config_value(config, "draw_image_size_portrait", DRAW_DEFAULT_PORTRAIT_SIZE),
                DRAW_DEFAULT_PORTRAIT_SIZE,
            ),
        ),
    )


def _normalize_image_size(value, default: str) -> str:
    """Fall back to the preset size when the configured value is not WIDTHxHEIGHT."""
    candidate = str(value or "").strip().lower()
    return candidate if DRAW_IMAGE_SIZE_RE.fullmatch(candidate) else default


def read_feature_mode(config=None) -> str:
    del config
    return FEATURE_MODE_FULL


def should_record_passive_group_points(
    *,
    feature_mode: str,
    legacy_runtime_online: bool = False,
) -> bool:
    return True


def parse_draw_command(text: str) -> DrawRequest | None:
    normalized = text.strip()
    if normalized == DRAW_DOUDOUYAN_COMMAND:
        return DrawRequest(prompt="豆豆眼头像")
    command = parse_draw_command_text(normalized)
    if command is None or not command.prompt:
        return None
    if extract_removed_draw_temporary_model(normalized) is not None:
        return None
    return DrawRequest(
        prompt=command.prompt,
        gif=command.gif,
        size_level=command.size_level,
        orientation=command.orientation,
    )


def looks_like_draw_invocation(text: str) -> bool:
    normalized = text.strip()
    if normalized == DRAW_DOUDOUYAN_COMMAND:
        return True
    try:
        return parse_draw_command_text(normalized) is not None
    except ValueError:
        return True


def looks_like_draw_feature_request(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    return (
        looks_like_draw_invocation(normalized)
        or looks_like_draw_points_mutation_request(normalized)
        or looks_like_draw_points_query(normalized)
        or looks_like_draw_points_ranking(normalized)
        or looks_like_draw_help_command(normalized)
        or looks_like_draw_model_switch(normalized)
    )


def parse_draw_command_text(text: str) -> DrawCommand | None:
    """Parse one draw command written as 文生图 / 文生竖图2k / 文生动图 [提示词].

    Args:
        text: Message text without surrounding whitespace or mention components.

    Returns:
        The parsed command, or None when the text does not start with a draw command.

    Raises:
        ValueError: For a level token glued to the prompt, or a mode word in the wrong place.
    """
    normalized = text.strip()
    if normalized == DRAW_DOUDOUYAN_COMMAND:
        return DrawCommand(base="头像生图", prompt="豆豆眼头像")
    prefix_match = DRAW_COMMAND_PREFIX_RE.match(normalized)
    if prefix_match is None:
        return None
    position = prefix_match.end()
    orientation = ""
    gif = False
    mode_char = normalized[position : position + 1]
    if mode_char in DRAW_ORIENTATION_CHARS and normalized.startswith("图", position + 1):
        orientation = DRAW_ORIENTATION_CHARS[mode_char]
        gif = mode_char == "动"
        position += 2
    elif normalized.startswith("图", position):
        position += 1
    else:
        return None
    command_end = position
    spaced_before = position < len(normalized) and normalized[position].isspace()
    while position < len(normalized) and normalized[position].isspace():
        position += 1
    level = ""
    level_match = DRAW_LEVEL_TOKEN_RE.match(normalized[position:])
    if level_match is not None:
        token = level_match.group(1).lower()
        after_token = position + level_match.end()
        glued_after = after_token < len(normalized) and not normalized[after_token].isspace()
        if glued_after and not spaced_before:
            raise ValueError(
                f"“{token}”后面要空一格再写提示词，例如“文生图 {token} 一只白猫”"
            )
        if not glued_after:
            level = token
            position = after_token
    prompt = normalized[position:].strip()
    if DRAW_STRAY_MODE_RE.search(prompt) is not None:
        raise ValueError(
            "画幅词要写在“生”和“图”之间，例如“文生竖图2k 一只白猫”“图生横图 换成水彩”；动图写成“文生动图 提示词”"
        )
    return DrawCommand(
        base=DRAW_COMMAND_BASES[prefix_match.group(1)],
        prompt=prompt,
        gif=gif,
        size_level=level,
        orientation=orientation,
        base_end=command_end,
        prompt_offset=position,
    )


def extract_removed_draw_temporary_model(text: str) -> str | None:
    if text.lstrip().startswith(("文生图", "图生图", "头像生图")):
        return None
    try:
        command = parse_draw_command_text(text.strip())
    except ValueError:
        return None
    rest = command.prompt if command is not None else ""
    if not rest:
        return None
    bracket_match = re.match(r"^\[([^\]]+)\](?:\s+|$)", rest)
    if bracket_match is not None:
        candidate = bracket_match.group(1).strip().lower()
    else:
        candidate = rest.split(maxsplit=1)[0].strip().lower()
    # Keep recognizing retired temporary selectors so they cannot become billable prompts.
    return candidate if re.fullmatch(r"gpt-image-2(?:\.5|-vip)?|nano-banana(?:-2(?:-lite)?|-pro)?", candidate) else None


def looks_like_draw_command(text: str) -> bool:
    return parse_draw_command(text) is not None


def format_draw_missing_prompt_message() -> str:
    return (
        "请填写提示词。用法：文生图 提示词；图生图 提示词（附图或引用图）；头像生图 [@某人] 提示词。"
        "档位紧跟指令写：文生图4k 一只白猫；画幅把“图”写成“竖图/横图”：文生竖图2k 一只白猫；动图：文生动图 提示词。"
    )


def format_draw_temporary_model_removed(model: str) -> str:
    return (
        f"生图命令不再支持临时指定模型 {model}，本次没有扣积分。"
        "生图模型由 CPA 当前注册的图片模型自动选择，请直接发送“文生图 提示词”。"
    )


def looks_like_draw_help_command(text: str) -> bool:
    normalized = re.sub(r"\s+", "", text.strip())
    return normalized in {
        "生图模型说明",
        "生图模型",
        "生图价格",
        "画图模型说明",
        "画图模型",
        "画图价格",
        "棉花糖生图模型说明",
        "棉花糖生图模型",
        "棉花糖生图价格",
        "棉花生图模型说明",
        "棉花生图模型",
        "棉花生图价格",
    }


def looks_like_draw_points_query(text: str) -> bool:
    normalized = text.strip()
    if not normalized:
        return False
    if _DRAW_POINTS_ENGLISH_QUERY_RE.fullmatch(normalized):
        return True
    compact = re.sub(r"\s+", "", normalized)
    return _DRAW_POINTS_QUERY_RE.fullmatch(compact) is not None


def looks_like_draw_points_ranking(text: str) -> bool:
    compact = re.sub(r"\s+", "", text.strip())
    return compact in {"积分排行", "积分排行榜"}


def looks_like_draw_points_mutation_request(text: str) -> bool:
    compact = re.sub(r"\s+", "", text.strip())
    if not compact or "积分" not in compact:
        return False
    return _DRAW_POINTS_MUTATION_RE.search(compact) is not None


def extract_draw_model_switch(text: str) -> str | None:
    normalized = text.strip()
    match = _DRAW_MODEL_SWITCH_PRIMARY_RE.fullmatch(normalized)
    if match is not None:
        return match.group(1).strip()
    match = _DRAW_MODEL_SWITCH_ALIAS_RE.fullmatch(normalized)
    if match is not None:
        return match.group(1).strip()
    return None


def looks_like_draw_model_switch(text: str) -> bool:
    return extract_draw_model_switch(text) is not None


def parse_draw_model_switch(text: str) -> str | None:
    candidate = extract_draw_model_switch(text)
    if candidate is None:
        return None
    model = candidate.strip().lower()
    return model if DRAW_MODEL_NAME_RE.fullmatch(model) else None


def format_draw_model_help(
    current_model: str = DRAW_DEFAULT_MODEL,
    *,
    multiplier: int = DRAW_POINT_PRICE_MULTIPLIER,
    available_models: tuple[str, ...] = (),
) -> str:
    current_model = normalize_draw_model(current_model)
    models = tuple(dict.fromkeys(available_models)) or (current_model,)
    lines = [f"当前生图模型：{current_model}", "可用模型："]
    for model in models:
        description = get_draw_model_description(model)
        price = format_draw_model_price(model)
        current_mark = "（当前）" if model == current_model else ""
        lines.append(
            f"· {model}{current_mark}：{price} 元/次，"
            f"{calculate_draw_model_points(model, multiplier=multiplier)} 积分。{description}"
        )
    if current_model not in models:
        lines.append(f"当前保存的 {current_model} 已不可用，下次生图会自动改用上面的可用模型。")
    lines.extend(
        [
            "",
            "生图指令：文生图 提示词；图生图 提示词（附图或引用）；头像生图 [@某人] 提示词",
            "动图指令：把上面的“生图”换成“生动图”，即 文生动图 / 图生动图 / 头像生动图",
            "私聊或 @机器人 时也可以直接说“画只猫”“生成一只白猫”，由 AI 判断后调用同一个生图功能",
        ]
    )
    return "\n".join(lines)


def format_draw_points_status(balance: DrawPointBalance) -> str:
    cost_points = calculate_draw_model_points(balance.model, multiplier=balance.multiplier)
    return "\n".join(
        [
            f"当前生图积分：{balance.points}",
            f"当前生图模型：{balance.model}",
            f"当前模型消耗：{cost_points} 积分/次",
            "",
            "查看模型与价格：生图模型",
        ]
    )


def format_draw_points_ranking(
    ranking: tuple[DrawPointBalance, ...],
    *,
    resolve_display_name: Callable[[str], str] | None = None,
) -> str:
    if not ranking:
        return "全群还没有生图积分记录。"
    lines = ["全群生图积分排行榜："]
    for index, balance in enumerate(ranking, start=1):
        display_name = resolve_display_name(balance.user_id) if resolve_display_name is not None else balance.user_id
        identity = display_name if display_name != balance.user_id else f"QQ {mask_qq_user_id(balance.user_id)}"
        lines.append(f"{index}. {identity}：{balance.points} 积分")
    return "\n".join(lines)


def format_draw_model_switch_success(balance: DrawPointBalance) -> str:
    cost_points = calculate_draw_model_points(balance.model, multiplier=balance.multiplier)
    description = get_draw_model_description(balance.model)
    return "\n".join(
        [
            f"已切换生图模型：{balance.model}",
            f"单次消耗：{cost_points} 积分",
            description,
            "之后发送“文生图 提示词”或“图生图 提示词”就会使用这个模型。",
        ]
    )


def format_draw_model_switch_invalid(
    candidate: str,
    *,
    available_models: tuple[str, ...] = (),
) -> str:
    candidate = str(candidate or "").strip()
    first_line = f"不支持这个生图模型：{candidate}" if candidate else "请填写要切换的生图模型。"
    available_line = (
        f"当前可用：{'、'.join(available_models)}" if available_models
        else "暂时查不到 CPA 当前可用的生图模型。"
    )
    return "\n".join(
        [
            first_line,
            available_line,
            "生图用法：文生图 提示词；图生图 提示词（附图或引用）；动图用 文生动图 / 图生动图",
        ]
    )


def format_draw_points_mutation_denied() -> str:
    return "生图积分只能通过群消息自动累计，并在生图时自动扣除；普通聊天不能手动加分或改分。"


def format_draw_start_message(quota: DrawQuotaResult) -> str:
    return (
        "收到，棉花糖开始生图任务啦！"
        f"本次使用 {quota.model}，扣 {quota.cost_points} 积分，"
        f"剩余 {quota.balance_after} 积分。"
    )


def format_draw_quota_exceeded_message(quota: DrawQuotaResult) -> str:
    return (
        f"积分不够啦：{quota.model} 需要 {quota.cost_points} 积分"
        f"（价格 {quota.price} 元），"
        f"你现在有 {quota.balance_before} 积分。"
        "可发送“查看积分”查询余额，通过群消息继续累计积分。"
    )


def format_draw_success(
    result: DrawResult,
    *,
    model: str,
    image_count: int = 1,
) -> str:
    unit = "张动图" if result.image_format == "gif" else "张"
    return (
        "✨ 生成成功！\n"
        f"📊 耗时: {result.total_seconds:.2f}s\n"
        f"🖼️ 数量: {image_count}{unit}\n"
        f"🤖 模型: {model}"
    )


def format_draw_failure(exc: Exception) -> str:
    return (
        f"❌ 生成失败: {extract_draw_error_message(exc)}。"
        "本次扣除的积分已退回，请稍后重试。"
    )


def format_draw_timeout(timeout_seconds: float) -> str:
    return (
        f"❌ 生成失败: 生图超过 {timeout_seconds:.0f} 秒还没返回，"
        "本次扣除的积分已退回，请稍后重试。"
    )


def extract_draw_error_message(exc: Exception) -> str:
    if isinstance(exc, DrawTimeoutError):
        return f"生图超过 {exc.timeout_seconds:.0f} 秒未返回"
    if isinstance(exc, TimeoutError):
        return "生图请求超时"
    if isinstance(exc, HTTPError):
        detail = read_http_error_detail(exc)
        return detail or f"上游返回 HTTP {exc.code}"
    message = str(exc).strip()
    return message or type(exc).__name__


def calculate_draw_model_points(
    model: str,
    *,
    multiplier: int = DRAW_POINT_PRICE_MULTIPLIER,
) -> int:
    points = get_draw_model_price(model) * Decimal(str(multiplier))
    return int(points.to_integral_value(rounding=ROUND_CEILING))


def get_draw_model_price(model: str) -> Decimal:
    return DRAW_MODEL_PRICES.get(
        normalize_draw_model(model), DRAW_FALLBACK_PRICE,
    )


def get_draw_model_description(model: str) -> str:
    return DRAW_MODEL_DESCRIPTIONS.get(
        normalize_draw_model(model), DRAW_FALLBACK_DESCRIPTION,
    )


def format_draw_model_price(model: str) -> str:
    return f"{get_draw_model_price(model):.2f}"


def read_http_error_detail(exc: HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except Exception:
        return ""
    if not body:
        return ""
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return body[:200]
    for path in (("error", "message"), ("message",), ("detail",)):
        value: object = data
        for key in path:
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return body[:200]


def extract_draw_task_error(data: object) -> str:
    if not isinstance(data, dict):
        return ""
    error = data.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    message = data.get("message")
    return message.strip() if isinstance(message, str) else ""


def extract_image_url_from_object(data: object) -> str:
    if isinstance(data, dict):
        value = data.get("b64_json")
        if isinstance(value, str) and value.strip():
            mime = str(data.get("mime_type") or "").strip().lower()
            if not re.fullmatch(r"image/[a-z0-9.+-]+", mime):
                mime = "image/png"
            return f"data:{mime};base64,{value.strip()}"
        value = data.get("url")
        if isinstance(value, str):
            extracted = extract_image_url(value)
            if extracted:
                return extracted
        for child in data.values():
            extracted = extract_image_url_from_object(child)
            if extracted:
                return extracted
    elif isinstance(data, list):
        for item in data:
            extracted = extract_image_url_from_object(item)
            if extracted:
                return extracted
    return ""


def extract_image_url(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith(("http://", "https://", "data:image/")):
        return stripped
    match = re.search(r"(https?://\S+)", stripped)
    if match:
        return match.group(1).rstrip("，,。)")
    return ""


def resolve_default_data_root() -> Path:
    return resolve_astrbot_data_root() / "plugin_data" / "qqbot_features_runtime"


def resolve_astrbot_data_root() -> Path:
    astrbot_root = Path(os.environ.get("ASTRBOT_ROOT") or Path(__file__).resolve().parents[3])
    return astrbot_root.resolve() / "data"


def get_users_payload(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    raw = payload.get("users")
    if not isinstance(raw, dict):
        return {}
    users: dict[str, dict[str, object]] = {}
    for user_id, value in raw.items():
        if str(user_id).strip() and isinstance(value, dict):
            users[str(user_id)] = dict(value)
    return users


def get_user_payload(users: dict[str, dict[str, object]], user_key: str) -> dict[str, object]:
    raw = users.get(user_key)
    if not isinstance(raw, dict):
        return {"points": 0, "model": DRAW_DEFAULT_MODEL}
    payload: dict[str, object] = {
        "points": safe_int(raw.get("points"), 0),
        "model": normalize_draw_model(raw.get("model")),
    }
    return payload


def normalize_draw_points_payload(payload: dict[str, object]) -> dict[str, object]:
    normalized: dict[str, object] = {
        "schema_version": max(2, safe_int(payload.get("schema_version"), 2)),
        "users": {},
    }
    users: dict[str, dict[str, object]] = {}
    for user_id, raw_user in get_users_payload(payload).items():
        users[user_id] = get_user_payload({user_id: raw_user}, user_id)
    normalized["users"] = users
    return normalized


def merge_draw_points_payload(current: dict[str, object], legacy: dict[str, object]) -> dict[str, object]:
    merged = normalize_draw_points_payload(current)
    users = get_users_payload(merged)
    for user_id, legacy_user in get_users_payload(normalize_draw_points_payload(legacy)).items():
        current_exists = user_id in users
        current_user = get_user_payload(users, user_id)
        legacy_payload = get_user_payload({user_id: legacy_user}, user_id)
        current_points = safe_int(current_user.get("points"), 0)
        legacy_points = safe_int(legacy_payload.get("points"), 0)
        if legacy_points > current_points:
            current_user["points"] = legacy_points
        if not current_exists:
            current_user["model"] = normalize_draw_model(legacy_payload.get("model"))
        users[user_id] = current_user
    merged["users"] = users
    return merged


def fingerprint_file(path: Path) -> str:
    stat = path.stat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"{stat.st_size}:{stat.st_mtime_ns}:{digest}"


def get_config_value(config, key: str, default):
    if config is None:
        return default
    try:
        return config.get(key, default)
    except Exception:
        return default


def safe_int(value: object, default: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def normalize_draw_model(model: object) -> str:
    candidate = str(model or "").strip().lower()
    return candidate if DRAW_MODEL_NAME_RE.fullmatch(candidate) else DRAW_DEFAULT_MODEL


def mask_qq_user_id(user_id: object) -> str:
    value = str(user_id or "").strip()
    if len(value) <= 6:
        return "*" * max(1, len(value))
    return f"{value[:3]}{'*' * (len(value) - 6)}{value[-3:]}"


def sortable_user_id(user_id: str) -> tuple[int, int | str]:
    user_key = str(user_id or "").strip()
    if user_key.isdigit():
        return (0, int(user_key))
    return (1, user_key)
