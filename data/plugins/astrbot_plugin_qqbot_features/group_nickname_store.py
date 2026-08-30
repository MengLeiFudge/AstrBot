from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
import sqlite3

from .runtime_storage import resolve_runtime_db_path


@dataclass(frozen=True, slots=True)
class GroupNicknameRecord:
    group_id: str
    user_id: str
    card: str
    nickname: str
    updated_at: int


class GroupNicknameStore:
    """Resolve a QQ display name from the current group's nickname cache."""

    def __init__(self, runtime_root: Path) -> None:
        self.db_path = resolve_runtime_db_path(Path(runtime_root))

    def record_group_sender(
        self,
        group_id: int | str,
        user_id: int | str,
        *,
        card: str = "",
        nickname: str = "",
        updated_at: int = 0,
    ) -> None:
        group_key = str(group_id or "").strip()
        user_key = str(user_id or "").strip()
        card = normalize_group_nickname(card)
        nickname = normalize_group_nickname(nickname)
        if not group_key or not user_key or not (card or nickname):
            return
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                insert into group_nickname_cache(group_id, user_id, card, nickname, updated_at)
                values (?, ?, ?, ?, ?)
                on conflict(group_id, user_id) do update set
                    card=excluded.card,
                    nickname=excluded.nickname,
                    updated_at=excluded.updated_at
                where excluded.updated_at >= group_nickname_cache.updated_at
                """,
                (group_key, user_key, card, nickname, max(0, int(updated_at))),
            )

    def resolve_display_name(self, group_id: int | str, user_id: int | str) -> str:
        group_key = str(group_id or "").strip()
        user_key = str(user_id or "").strip()
        if not user_key:
            return ""
        with closing(self._connect()) as conn:
            if group_key:
                current = self._find_record(conn, group_key, user_key)
                current_name = pick_current_group_display_name(current)
                if current_name:
                    return current_name
            nickname = self._find_other_group_nickname(conn, group_key, user_key)
        return nickname or user_key

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("pragma busy_timeout=30000")
        conn.execute("pragma journal_mode=delete")
        conn.execute(
            """
            create table if not exists group_nickname_cache (
                group_id text not null,
                user_id text not null,
                card text not null default '',
                nickname text not null default '',
                updated_at integer not null default 0,
                primary key(group_id, user_id)
            )
            """
        )
        conn.execute(
            """
            create index if not exists idx_group_nickname_cache_user_updated
            on group_nickname_cache(user_id, updated_at desc)
            """
        )
        conn.commit()
        return conn

    @staticmethod
    def _find_record(conn: sqlite3.Connection, group_id: str, user_id: str) -> GroupNicknameRecord | None:
        row = conn.execute(
            """
            select group_id, user_id, card, nickname, updated_at
            from group_nickname_cache
            where group_id=? and user_id=?
            """,
            (group_id, user_id),
        ).fetchone()
        return build_group_nickname_record(row)

    @staticmethod
    def _find_other_group_nickname(conn: sqlite3.Connection, group_id: str, user_id: str) -> str:
        if group_id:
            row = conn.execute(
                """
                select nickname
                from group_nickname_cache
                where user_id=? and group_id<>? and nickname<>''
                order by updated_at desc, group_id asc
                limit 1
                """,
                (user_id, group_id),
            ).fetchone()
        else:
            row = conn.execute(
                """
                select nickname
                from group_nickname_cache
                where user_id=? and nickname<>''
                order by updated_at desc, group_id asc
                limit 1
                """,
                (user_id,),
            ).fetchone()
        return normalize_group_nickname(row[0] if row is not None else "")


def build_group_nickname_record(row: tuple[object, ...] | None) -> GroupNicknameRecord | None:
    if row is None:
        return None
    return GroupNicknameRecord(
        group_id=str(row[0] or "").strip(),
        user_id=str(row[1] or "").strip(),
        card=normalize_group_nickname(row[2]),
        nickname=normalize_group_nickname(row[3]),
        updated_at=max(0, int(row[4] or 0)),
    )


def pick_current_group_display_name(record: GroupNicknameRecord | None) -> str:
    if record is None:
        return ""
    return record.card or record.nickname


def normalize_group_nickname(value: object) -> str:
    return " ".join(str(value or "").split())[:64]
