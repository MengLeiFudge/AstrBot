"""Durable group batches; network retries never repeat a completed summary."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path

RETENTION_MS = 7 * 86400 * 1000


class Queue:
    """Own the plugin's SQLite spool on the single event-loop thread."""

    def __init__(self, path: Path, binding: str, max_bytes: int):
        """Open the spool and reject accidental rebinding of existing data."""
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.max_bytes = max_bytes
        try:
            self.db.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=FULL;
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS batches (
                    id TEXT PRIMARY KEY,group_id TEXT NOT NULL,summary TEXT,
                    attempted_at INTEGER NOT NULL DEFAULT 0,state TEXT NOT NULL DEFAULT 'pending'
                );
                CREATE TABLE IF NOT EXISTS items (
                    group_id TEXT NOT NULL,message_id TEXT NOT NULL,sender_id TEXT NOT NULL,
                    received_at INTEGER NOT NULL,body TEXT,batch_id TEXT,
                    PRIMARY KEY(group_id,message_id)
                );
                CREATE TABLE IF NOT EXISTS budget (day TEXT PRIMARY KEY,attempts INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS sent (id TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS replies (id TEXT PRIMARY KEY,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS summary_requests (batch_id TEXT PRIMARY KEY);
            """)
            with self.db:
                old = self.db.execute("SELECT value FROM settings WHERE key='binding'").fetchone()
                if old and old[0] != binding:
                    raise ValueError("Bridge binding changed; archive the old spool before rebinding")
                self.db.execute("INSERT OR IGNORE INTO settings VALUES('binding',?)", (binding,))
        except BaseException:
            self.db.close()
            raise

    def close(self):
        """Close only this plugin instance's connection."""
        self.db.close()

    def expire(self) -> int:
        """Remove expired raw text without deleting summary or audit identifiers."""
        cutoff = int(time.time() * 1000) - RETENTION_MS
        with self.db:
            self.db.execute("UPDATE batches SET state='expired' WHERE state='pending' AND id IN (SELECT batch_id FROM items WHERE received_at<=?)", (cutoff,))
            count = self.db.execute("UPDATE items SET body=NULL WHERE body IS NOT NULL AND received_at<=?", (cutoff,)).rowcount
            # Dedupe identifiers can outlive raw text but should not grow without bound locally.
            self.db.execute("DELETE FROM items WHERE body IS NULL AND received_at<?", (cutoff - RETENTION_MS,))
            self.db.execute("DELETE FROM summary_requests WHERE batch_id IN (SELECT id FROM batches WHERE state<>'pending')")
        return count

    def enqueue(self, group: str, message: str, sender: str, body: str) -> bool:
        """Persist direct text mentioning the bot; reject overflow before changing the queue."""
        if not body.strip() or len(body.encode()) > 8192:
            raise ValueError("Text must contain 1–8192 UTF-8 bytes")
        if not group.isdecimal() or not sender.isdecimal() or not message or len(message) > 128:
            raise ValueError("Invalid source identifiers")
        with self.db:
            if self.db.execute("SELECT 1 FROM items WHERE group_id=? AND message_id=?", (group, message)).fetchone():
                return False
            used, count = self.db.execute("SELECT coalesce(sum(length(CAST(body AS BLOB))),0),count(*) FROM items WHERE body IS NOT NULL").fetchone()
            if used + len(body.encode()) > self.max_bytes or count >= 10000:
                raise ValueError("Raw text queue is full; this message was not accepted")
            self.db.execute("INSERT INTO items VALUES(?,?,?,?,?,NULL)", (group, message, sender, int(time.time() * 1000), body))
        return True

    def _freeze(self, group: str) -> str:
        """Freeze at most fifty current source rows inside the caller's transaction."""
        batch_id = str(uuid.uuid4())
        self.db.execute("INSERT INTO batches(id,group_id) VALUES(?,?)", (batch_id, group))
        self.db.execute("UPDATE items SET batch_id=? WHERE group_id=? AND message_id IN (SELECT message_id FROM items WHERE group_id=? AND batch_id IS NULL AND body IS NOT NULL ORDER BY received_at,message_id LIMIT 50)", (batch_id, group, group))
        return batch_id

    def budget_available(self, limit: int) -> bool:
        """Read the UTC daily budget without reserving another model attempt."""
        day = time.strftime("%Y-%m-%d", time.gmtime())
        row = self.db.execute("SELECT attempts FROM budget WHERE day=?", (day,)).fetchone()
        return not row or row[0] < limit

    def request_summary(self, group: str | None, limit: int) -> str:
        """Freeze the owner's current group/all-group backlog without bypassing budget or retry delays."""
        self.expire()
        with self.db:
            groups = self.db.execute("SELECT group_id FROM items WHERE batch_id IS NULL AND body IS NOT NULL AND (? IS NULL OR group_id=?) UNION SELECT group_id FROM batches WHERE state='pending' AND (? IS NULL OR group_id=?)", (group, group, group, group)).fetchall()
            if not groups:
                return "empty"
            if not self.budget_available(limit):
                return "limited"
            for row in groups:
                while self.db.execute("SELECT 1 FROM items WHERE group_id=? AND batch_id IS NULL AND body IS NOT NULL LIMIT 1", (row[0],)).fetchone():
                    self._freeze(row[0])
                self.db.execute("INSERT OR IGNORE INTO summary_requests SELECT id FROM batches WHERE group_id=? AND state='pending'", (row[0],))
        return "queued"

    def requested_ready(self, limit: int) -> bool:
        """Continue requested batches promptly only when their retry delay and model budget allow it."""
        return self.db.execute("SELECT 1 FROM batches b JOIN summary_requests r ON r.batch_id=b.id WHERE b.state='pending' AND (b.summary IS NOT NULL OR (b.attempted_at<=? AND ?)) LIMIT 1", (int(time.time() * 1000) - 1800000, self.budget_available(limit))).fetchone() is not None

    def next_batch(self, threshold: int, delay_ms: int) -> dict | None:
        """Freeze one group at a time; keep its UUID and source set across retries."""
        now = int(time.time() * 1000)
        with self.db:
            row = self.db.execute("SELECT * FROM batches WHERE state='pending' AND (summary IS NOT NULL OR attempted_at<=?) ORDER BY (summary IS NOT NULL) DESC,(id IN (SELECT batch_id FROM summary_requests)) DESC,attempted_at,id LIMIT 1", (now - 1800000,)).fetchone()
            if not row:
                group = self.db.execute("SELECT group_id FROM items WHERE batch_id IS NULL AND body IS NOT NULL GROUP BY group_id HAVING count(*)>=? OR min(received_at)<=? ORDER BY min(received_at) LIMIT 1", (threshold, now - delay_ms)).fetchone()
                if not group:
                    return None
                batch_id = self._freeze(group[0])
                row = self.db.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
            batch = dict(row)
            batch["items"] = [dict(item) for item in self.db.execute("SELECT message_id,sender_id,received_at,body FROM items WHERE batch_id=? ORDER BY received_at,message_id", (batch["id"],))]
            return batch

    def begin_summary(self, batch_id: str, limit: int) -> bool:
        """Charge an LLM attempt durably before issuing it, including failed attempts."""
        day = time.strftime("%Y-%m-%d", time.gmtime())
        with self.db:
            row = self.db.execute("SELECT attempts FROM budget WHERE day=?", (day,)).fetchone()
            if row and row[0] >= limit:
                return False
            self.db.execute("INSERT INTO budget VALUES(?,1) ON CONFLICT(day) DO UPDATE SET attempts=attempts+1", (day,))
            self.db.execute("UPDATE batches SET attempted_at=? WHERE id=? AND state='pending'", (int(time.time() * 1000), batch_id))
        return True

    def save_summary(self, batch_id: str, summary: str):
        """Persist generated text or the fixed empty marker before any delivery or completion."""
        if not summary.strip() or len(summary.encode()) > 8192:
            raise ValueError("Summary is empty or exceeds 8192 UTF-8 bytes")
        with self.db:
            self.db.execute("UPDATE batches SET summary=? WHERE id=? AND state='pending'", (summary, batch_id))

    def delivered(self, batch_id: str):
        """Release plugin raw text only after the bridge committed the complete batch."""
        with self.db:
            self.db.execute("UPDATE batches SET state='delivered' WHERE id=?", (batch_id,))
            self.db.execute("UPDATE items SET body=NULL WHERE batch_id=?", (batch_id,))

    def finish_empty(self, batch_id: str):
        """Finish an empty summary locally; keep raw text until normal seven-day expiry."""
        with self.db:
            self.db.execute("UPDATE batches SET state='empty' WHERE id=? AND state='pending'", (batch_id,))

    def mark_sent(self, outbox_id: str):
        """Remember a successful QQ send before acknowledging it to the bridge."""
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO sent VALUES(?)", (outbox_id,))

    def was_sent(self, outbox_id: str) -> bool:
        """Return whether QQ delivery was already confirmed locally."""
        return self.db.execute("SELECT 1 FROM sent WHERE id=?", (outbox_id,)).fetchone() is not None

    def save_reply(self, request_id: str, payload: dict):
        """Queue a verified owner's private command for idempotent offline delivery."""
        with self.db:
            if self.db.execute("SELECT count(*) FROM replies").fetchone()[0] >= 1000:
                raise ValueError("Decision reply queue is full")
            self.db.execute("INSERT OR IGNORE INTO replies VALUES(?,?)", (request_id, json.dumps(payload, ensure_ascii=False)))

    def pending_replies(self) -> list[dict]:
        """Read a bounded reply batch; source metadata is never supplied by the model."""
        return [{"id": row[0], "payload": json.loads(row[1])} for row in self.db.execute("SELECT id,payload FROM replies ORDER BY rowid LIMIT 20")]

    def reply_delivered(self, request_id: str):
        """Remove a reply after a definitive bridge response."""
        with self.db:
            self.db.execute("DELETE FROM replies WHERE id=?", (request_id,))
