from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ...runtime_storage import infer_runtime_root_from_path


class LoliconMode(Enum):
    NON_R18 = 0
    R18 = 1
    MIXED = 2


@dataclass(frozen=True, slots=True)
class LoliconCommand:
    mode: LoliconMode
    num: int
    tags: list[str]


@dataclass(frozen=True, slots=True)
class LoliconImageItem:
    title: str
    pid: int
    page: int
    author: str
    uid: int
    url: str
    r18: bool
    width: int
    height: int
    tags: tuple[str, ...]
    ext: str
    ai_type: int
    upload_date: int
    local_path: Path | None = None


LOLICON_API_URL = "https://api.lolicon.app/setu/v2"
LOLICON_USER_AGENT = "qqbot-lolicon/1.0"
LOLICON_MAX_NUM = 20


def parse_lolicon_command(text: str) -> LoliconCommand | None:
    normalized = text.strip()
    if normalized.startswith("来点"):
        normalized = normalized[2:].strip()
    if len(normalized) < 2:
        return None

    prefix = normalized[:2]
    if prefix == "美图":
        mode = LoliconMode.NON_R18
    elif prefix in {"色图", "涩图", "蛇图"}:
        mode = LoliconMode.R18
    elif prefix == "混合":
        mode = LoliconMode.MIXED
    else:
        return None

    payload = normalized[2:].strip()
    if not payload:
        return LoliconCommand(mode=mode, num=1, tags=[])
    if payload.isdigit():
        return LoliconCommand(mode=mode, num=int(payload), tags=[])

    parts = payload.split()
    num = 5
    if parts[-1].isdigit():
        num = int(parts[-1])
        parts = parts[:-1]
    return LoliconCommand(mode=mode, num=num, tags=parts)


def parse_lolicon_response(payload: dict) -> list[LoliconImageItem]:
    if payload.get("error"):
        return []
    items: list[LoliconImageItem] = []
    for raw in payload.get("data", []):
        urls = raw.get("urls", {})
        original_url = urls.get("original")
        if not isinstance(original_url, str) or not original_url.strip():
            continue
        items.append(
            LoliconImageItem(
                title=str(raw.get("title", "")),
                pid=int(raw.get("pid", 0)),
                page=int(raw.get("p", 0)),
                author=str(raw.get("author", "")),
                uid=int(raw["uid"]),
                url=original_url.strip(),
                r18=bool(raw.get("r18", False)),
                width=int(raw.get("width", 0) or 0),
                height=int(raw.get("height", 0) or 0),
                tags=tuple(str(tag) for tag in raw.get("tags", []) if str(tag).strip()),
                ext=str(raw.get("ext", "") or Path(original_url).suffix.lstrip(".") or "jpg"),
                ai_type=int(raw.get("aiType", 0) or 0),
                upload_date=int(raw.get("uploadDate", 0) or 0),
            )
        )
    return items


def fetch_lolicon_items(mode: LoliconMode, num: int, tags: list[str]) -> list[LoliconImageItem]:
    query: dict[str, object] = {
        "r18": mode.value,
        "num": min(max(num, 1), LOLICON_MAX_NUM),
        "size": "original",
    }
    if tags:
        query["tag"] = tags
    url = f"{LOLICON_API_URL}?{urlencode(query, doseq=True)}"
    request = Request(url, headers={"User-Agent": LOLICON_USER_AGENT})
    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return parse_lolicon_response(payload)


class LoliconImageStore:
    def __init__(self, data_root: Path) -> None:
        self.data_root = Path(data_root)
        runtime_root = infer_runtime_root_from_path(self.data_root)
        self.legacy_root = runtime_root / "data" / "lolicon"
        self.db_path = runtime_root / "db" / "lolicon.sqlite3"

    def prepare_item(self, item: LoliconImageItem) -> LoliconImageItem:
        self.upsert_metadata(item)
        return item

    def upsert_metadata(self, item: LoliconImageItem) -> None:
        self._ensure_schema()
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                """
                insert into images (
                    pid, page, uid, title, author, r18, width, height, tags, ext,
                    ai_type, upload_date, url
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(pid, page) do update set
                    uid=excluded.uid,
                    title=excluded.title,
                    author=excluded.author,
                    r18=excluded.r18,
                    width=excluded.width,
                    height=excluded.height,
                    tags=excluded.tags,
                    ext=excluded.ext,
                    ai_type=excluded.ai_type,
                    upload_date=excluded.upload_date,
                    url=excluded.url,
                    updated_at=datetime('now')
                """,
                (
                    item.pid,
                    item.page,
                    item.uid,
                    item.title,
                    item.author,
                    int(item.r18),
                    item.width,
                    item.height,
                    json.dumps(list(item.tags), ensure_ascii=False),
                    item.ext,
                    item.ai_type,
                    item.upload_date,
                    item.url,
                ),
            )

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                """
                create table if not exists images (
                    pid integer not null,
                    page integer not null,
                    uid integer not null,
                    title text not null,
                    author text not null,
                    r18 integer not null,
                    width integer not null,
                    height integer not null,
                    tags text not null,
                    ext text not null,
                    ai_type integer not null,
                    upload_date integer not null,
                    url text not null,
                    local_path text not null default '',
                    created_at text not null default (datetime('now')),
                    updated_at text not null default (datetime('now')),
                    primary key (pid, page)
                )
                """
            )
