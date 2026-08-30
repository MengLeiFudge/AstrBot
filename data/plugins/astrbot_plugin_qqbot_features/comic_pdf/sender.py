from __future__ import annotations

from collections.abc import Iterable

from .models import ComicPdfArtifact, ComicPdfError


async def send_private_pdfs_with_password(
    api,
    user_id: int,
    album_id: str,
    artifacts: Iterable[ComicPdfArtifact],
    *,
    title: str,
    author: str,
    tags: Iterable[str] = (),
) -> int:
    """Announce one encrypted delivery, send every part, then confirm completion."""
    password = str(album_id or "").strip()
    if not password.isdigit():
        raise ComicPdfError("JM PDF 密码无法由作品 ID 生成。")
    parts = tuple(artifacts)
    if not parts:
        raise ComicPdfError("待发送 PDF 不存在，任务已终止。")
    paths = tuple(_validated_pdf_path(artifact) for artifact in parts)
    tag_text = "、".join(
        dict.fromkeys(
            text
            for item in tags
            if (text := str(item or "").strip())
        )
    ) or "未提供"
    summary = (
        f"JM{password} 加密完成，准备发送。\n"
        f"名称：JM{password}\n"
        f"标题：{str(title or '').strip() or f'JM{password}'}\n"
        f"作者：{str(author or '').strip() or '未知作者'}\n"
        f"标签：{tag_text}\n"
        f"文件切片：共 {len(paths)} 份\n"
        f"密码：{password}"
    )
    await _send_text(api, user_id, summary)

    sent = 0
    for path in paths:
        await api.call_api(
            "send_private_msg",
            user_id=int(user_id),
            message=[
                {
                    "type": "file",
                    "data": {"file": str(path), "name": path.name},
                }
            ],
        )
        sent += 1

    await _send_text(api, user_id, f"JM{password}发送完成")
    return sent


def _validated_pdf_path(artifact: ComicPdfArtifact):
    path = artifact.path.resolve()
    if not path.is_file() or path.suffix.lower() != ".pdf":
        raise ComicPdfError("待发送 PDF 不存在，任务已终止。")
    return path


async def _send_text(api, user_id: int, text: str) -> None:
    await api.call_api(
        "send_private_msg",
        user_id=int(user_id),
        message=[{"type": "text", "data": {"text": text}}],
    )
