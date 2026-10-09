"""Validate CPA image results and persist completed PNGs before delivery."""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime
from io import BytesIO
import os
from pathlib import Path
import uuid

import httpx
from PIL import Image


MAX_OUTPUT_BYTES = 32 * 1024 * 1024


async def load_generated_image(source: str, client: httpx.AsyncClient) -> bytes:
    """Read a valid generated image and normalize its format to PNG.

    Args:
        source: CPA's Base64 data URL or remote result URL.
        client: Request client without default authorization headers.

    Returns:
        Validated PNG bytes, reusable for both persistence and delivery.

    Raises:
        ValueError: If the response is empty or exceeds the size limit.
    """
    if source.startswith("data:image/"):
        header, _, encoded = source.partition(",")
        if ";base64" not in header or len(encoded) > (MAX_OUTPUT_BYTES + 2) // 3 * 4:
            raise ValueError("生图结果格式无效或超过 32 MiB")
        image = base64.b64decode(encoded, validate=True)
    elif source.startswith(("http://", "https://")):
        content = bytearray()
        async with client.stream("GET", source, follow_redirects=True) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > MAX_OUTPUT_BYTES:
                    raise ValueError("生图结果超过 32 MiB")
        image = bytes(content)
    else:
        raise ValueError("生图服务没有返回可读取的图片")
    if not image or len(image) > MAX_OUTPUT_BYTES:
        raise ValueError("生图结果为空或超过 32 MiB")
    return await asyncio.to_thread(_normalize_generated_png, image)


def _normalize_generated_png(image: bytes) -> bytes:
    """Keep valid PNG bytes or encode another image format without resizing.

    Args:
        image: Bounded provider response, which may differ from requested settings.

    Returns:
        A PNG suitable for the shared output path and delivery fallback.
    """
    with Image.open(BytesIO(image)) as result:
        if result.format == "PNG":
            result.verify()
            return image
        with result.convert("RGBA") as converted:
            output = BytesIO()
            converted.save(output, format="PNG")
            image = output.getvalue()
    if len(image) > MAX_OUTPUT_BYTES:
        raise ValueError("生图结果转换为 PNG 后超过 32 MiB")
    return image


def save_generated_image(image: bytes, data_root: Path) -> Path:
    """Atomically publish a generated image under the plugin's output directory.

    Args:
        image: Validated PNG bytes from the CPA client.
        data_root: This framework's existing plugin runtime data root.

    Returns:
        The completed PNG path; partial files never appear as finished results.
    """
    now = datetime.now()
    directory = data_root / "draw" / "outputs" / now.strftime("%Y%m%d")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{now:%H%M%S_%f}_{uuid.uuid4().hex}.png"
    partial = path.with_suffix(".part")
    try:
        with partial.open("xb") as stream:
            stream.write(image)
            stream.flush()
            os.fsync(stream.fileno())
        partial.replace(path)
    finally:
        partial.unlink(missing_ok=True)
    return path
