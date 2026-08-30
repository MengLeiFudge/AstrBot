from __future__ import annotations

import random
from pathlib import Path

from astrbot.api.message_components import BaseMessageComponent, ComponentType, Image


IMAGE_SUMMARY_POOL = (
    "我爱你",
    "今天也很喜欢你",
    "有一点点想你",
    "你超~~可爱！",
    "给你一颗糖",
    "抱一下再看",
    "只给你偷偷看",
    "请签收今日份可爱",
    "我什么都没发",
    "不许装作没看见",
    "被你发现啦",
    "点开会变可爱",
    "看完不许笑我",
    "嗯？你看到了",
    "这次真的不是广告",
    "图片正在看着你",
    "猜猜里面是什么",
    "嘘，偷偷看",
    "这是一个小秘密",
    "别眨眼",
    "有东西掉出来了",
    "前方糖分超标",
    "点开就知道啦",
    "我先藏在这里",
    "给你看个好东西",
    "图片来啦",
    "新鲜出炉",
    "这张有点厉害",
    "一小份快乐",
    "棉花糖掉落了",
    "快收下",
    "好东西要一起看",
)


def choose_image_summary() -> str:
    """为一张插件图片随机选择 QQ 外层预览摘要。"""
    return random.choice(IMAGE_SUMMARY_POOL)


class _OneBotImageSummarySegment(BaseMessageComponent):
    """最终发送前使用的原始 OneBot 图片段，避免 Core 丢弃 summary。"""

    type: ComponentType = ComponentType.Image
    file: str
    summary: str
    sub_type: int | None = None

    def __init__(
        self,
        *,
        file: str,
        summary: str,
        sub_type: int | None = None,
    ) -> None:
        super().__init__(file=file, summary=summary, sub_type=sub_type)

    def toDict(self) -> dict:
        data: dict[str, object] = {
            "file": self.file,
            "summary": self.summary,
        }
        if self.sub_type is not None:
            data["sub_type"] = self.sub_type
        return {"type": "image", "data": data}


def random_summary_image_from_file(path: str | Path) -> Image:
    file_path = Path(path).resolve(strict=False)
    return _image_with_summary(file=file_path.as_uri(), path=str(file_path))


def random_summary_image_from_url(url: str) -> Image:
    if not url.startswith(("http://", "https://")):
        raise ValueError("image URL must use http:// or https://")
    return _image_with_summary(file=url)


def _image_with_summary(*, file: str, path: str = "") -> Image:
    """Keep the exact AstrBot Image type so RespondStage does not drop it as empty."""
    image = Image(file=file, path=path)
    image.__dict__["summary"] = choose_image_summary()
    return image


async def prepare_onebot_image_summary_chain(message_chain):
    """把带摘要的标准 Image 转成 NapCat 可识别的 OneBot 图片段。"""
    converted = []
    changed = False
    for segment in message_chain.chain:
        summary = str(getattr(segment, "summary", "") or "").strip()
        if not isinstance(segment, Image) or not summary:
            converted.append(segment)
            continue
        image_base64 = await segment.convert_to_base64()
        converted.append(
            _OneBotImageSummarySegment(
                file=f"base64://{image_base64}",
                summary=summary,
                sub_type=getattr(segment, "sub_type", None),
            )
        )
        changed = True
    return message_chain.derive(converted) if changed else message_chain
