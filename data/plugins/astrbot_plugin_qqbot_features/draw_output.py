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


async def load_generated_image(source: str, client: httpx.AsyncClient) -> tuple[bytes, str]:
    """Read a valid generated image, keeping animated GIFs intact.

    Args:
        source: CPA's Base64 data URL or remote result URL.
        client: Request client without default authorization headers.

    Returns:
        Validated image bytes and their format, either "png" or "gif".

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
    return await asyncio.to_thread(_normalize_generated_image, image)


def _normalize_generated_image(image: bytes) -> tuple[bytes, str]:
    """Keep PNG and animated GIF bytes, or encode another format without resizing.

    Args:
        image: Bounded provider response, which may differ from requested settings.

    Returns:
        Image bytes and their format; a requested animation may arrive as one PNG frame.
    """
    with Image.open(BytesIO(image)) as result:
        if result.format == "PNG":
            result.verify()
            return image, "png"
        if result.format == "GIF":
            for index in range(getattr(result, "n_frames", 1)):
                result.seek(index)
                result.load()
            return image, "gif"
        with result.convert("RGBA") as converted:
            output = BytesIO()
            converted.save(output, format="PNG")
            image = output.getvalue()
    if len(image) > MAX_OUTPUT_BYTES:
        raise ValueError("生图结果转换为 PNG 后超过 32 MiB")
    return image, "png"


def save_generated_image(image: bytes, data_root: Path, *, image_format: str = "png") -> Path:
    """Atomically publish a generated image under the plugin's output directory.

    Args:
        image: Validated image bytes from the CPA client.
        data_root: This framework's existing plugin runtime data root.
        image_format: Kept format, either "png" or "gif".

    Returns:
        The completed image path; partial files never appear as finished results.
    """
    suffix = "gif" if image_format == "gif" else "png"
    now = datetime.now()
    directory = data_root / "draw" / "outputs" / now.strftime("%Y%m%d")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{now:%H%M%S_%f}_{uuid.uuid4().hex}.{suffix}"
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
