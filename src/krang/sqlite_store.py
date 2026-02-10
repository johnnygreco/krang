"""SQLite + FTS5 implementation of the NoteStore protocol."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

from krang.models import (
    DailyDigest,
    Note,
    NoteCreate,
    NoteStatus,
    NoteUpdate,
    SearchQuery,
    SearchResponse,
    SearchResult,
    StaleItem,
    _new_id,
    _utcnow,
)

# ---------------------------------------------------------------------------
# SQL constants
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    note_id     TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    content     TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS note_tags (
    note_id TEXT NOT NULL REFERENCES notes(note_id) ON DELETE CASCADE,
    tag     TEXT NOT NULL,
    UNIQUE(note_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_note_tags_tag ON note_tags(tag);
CREATE INDEX IF NOT EXISTS idx_notes_status ON notes(status);
CREATE INDEX IF NOT EXISTS idx_notes_updated ON notes(updated_at);
CREATE INDEX IF NOT EXISTS idx_notes_category ON notes(category);

CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    title, content, content=notes, content_rowid=rowid,
    tokenize='porter unicode61'
);

-- Triggers to keep FTS in sync.
CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts(rowid, title, content)
    VALUES (NEW.rowid, NEW.title, NEW.content);
END;

CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, title, content)
    VALUES ('delete', OLD.rowid, OLD.title, OLD.content);
END;

CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, title, content)
    VALUES ('delete', OLD.rowid, OLD.title, OLD.content);
    INSERT INTO notes_fts(rowid, title, content)
    VALUES (NEW.rowid, NEW.title, NEW.content);
END;
"""

# FTS5 special characters to strip from user queries.
_FTS5_SPECIAL = re.compile(r'[^\w\s"]+', re.UNICODE)


def _escape_fts(raw: str) -> str:
    """Turn a raw search string into safe FTS5 MATCH syntax.

    Individual words are wrapped in double quotes.  Existing quoted phrases
    are preserved.
    """
    if not raw or not raw.strip():
        return '""'

    # Pull out quoted phrases.
    phrases: list[str] = []

    def _stash(m: re.Match[str]) -> str:
        phrases.append(m.group(0))
        return f"\x00{len(phrases) - 1}\x00"

    text = re.sub(r'"[^"]*"', _stash, raw)
    text = _FTS5_SPECIAL.sub(" ", text)

    # Restore quoted phrases.
    for idx, phrase in enumerate(phrases):
        text = text.replace(f"\x00{idx}\x00", phrase)

    tokens = text.split()
    parts: list[str] = []
    for tok in tokens:
        if tok.startswith('"') and tok.endswith('"'):
            parts.append(tok)
        elif tok.upper() in ("AND", "OR", "NOT"):
            parts.append(tok.upper())
        else:
            parts.append(f'"{tok}"')

    return " ".join(parts) if parts else '""'


def _dt_to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _iso_to_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# SQLiteNoteStore
# ---------------------------------------------------------------------------


class SQLiteNoteStore:
    """Concrete NoteStore backed by SQLite + FTS5."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    # -- lifecycle -----------------------------------------------------------

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def __aenter__(self) -> SQLiteNoteStore:
        await self.initialize()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    @property
    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Store not initialised — call initialize() first")
        return self._db

    # -- helpers -------------------------------------------------------------

    async def _get_tags(self, note_id: str) -> list[str]:
        cur = await self._conn.execute(
            "SELECT tag FROM note_tags WHERE note_id = ? ORDER BY tag",
            (note_id,),
        )
        rows = await cur.fetchall()
        return [r["tag"] for r in rows]

    async def _set_tags(self, note_id: str, tags: list[str]) -> None:
        await self._conn.execute("DELETE FROM note_tags WHERE note_id = ?", (note_id,))
        seen: set[str] = set()
        for tag in tags:
            t = tag.strip()
            if t and t not in seen:
                seen.add(t)
                await self._conn.execute(
                    "INSERT INTO note_tags (note_id, tag) VALUES (?, ?)",
                    (note_id, t),
                )

    async def _row_to_note(self, row: aiosqlite.Row) -> Note:
        note_id = row["note_id"]
        tags = await self._get_tags(note_id)
        meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
        return Note(
            note_id=note_id,
            title=row["title"],
            content=row["content"],
            category=row["category"],
            status=NoteStatus(row["status"]),
            created_at=_iso_to_dt(row["created_at"]),
            updated_at=_iso_to_dt(row["updated_at"]),
            tags=tags,
            metadata=meta,
        )

    # -- CRUD ----------------------------------------------------------------

    async def create(self, note: NoteCreate) -> Note:
        note_id = _new_id()
        now = _utcnow()
        await self._conn.execute(
            """INSERT INTO notes (note_id, title, content, category, status,
                                  created_at, updated_at, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                note_id,
                note.title,
                note.content,
                note.category,
                NoteStatus.ACTIVE.value,
                _dt_to_iso(now),
                _dt_to_iso(now),
                json.dumps(note.metadata),
            ),
        )
        await self._set_tags(note_id, note.tags)
        await self._conn.commit()
        return (await self.get(note_id))  # type: ignore[return-value]

    async def get(self, note_id: str) -> Note | None:
        cur = await self._conn.execute(
            "SELECT * FROM notes WHERE note_id = ?", (note_id,)
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return await self._row_to_note(row)

    async def update(self, note_id: str, update: NoteUpdate) -> Note | None:
        existing = await self.get(note_id)
        if existing is None:
            return None

        sets: list[str] = []
        params: list[Any] = []

        if update.title is not None:
            sets.append("title = ?")
            params.append(update.title)
        if update.content is not None:
            sets.append("content = ?")
            params.append(update.content)
        if update.category is not None:
            sets.append("category = ?")
            params.append(update.category)
        if update.status is not None:
            sets.append("status = ?")
            params.append(update.status.value)
        if update.metadata is not None:
            sets.append("metadata_json = ?")
            params.append(json.dumps(update.metadata))

        now = _utcnow()
        sets.append("updated_at = ?")
        params.append(_dt_to_iso(now))
        params.append(note_id)

        if sets:
            sql = f"UPDATE notes SET {', '.join(sets)} WHERE note_id = ?"
            await self._conn.execute(sql, params)

        if update.tags is not None:
            await self._set_tags(note_id, update.tags)

        await self._conn.commit()
        return await self.get(note_id)

    async def delete(self, note_id: str) -> bool:
        cur = await self._conn.execute(
            "DELETE FROM notes WHERE note_id = ?", (note_id,)
        )
        await self._conn.execute(
            "DELETE FROM note_tags WHERE note_id = ?", (note_id,)
        )
        await self._conn.commit()
        return cur.rowcount > 0

    async def list_all(
        self,
        status: NoteStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Note]:
        if status is not None:
            cur = await self._conn.execute(
                "SELECT * FROM notes WHERE status = ? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (status.value, limit, offset),
            )
        else:
            cur = await self._conn.execute(
                "SELECT * FROM notes ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        rows = await cur.fetchall()
        return [await self._row_to_note(r) for r in rows]

    # -- search --------------------------------------------------------------

    async def search(self, query: SearchQuery) -> SearchResponse:
        fts_expr = _escape_fts(query.query)

        # Get matching rowids with BM25 scores from FTS.
        # bm25() weights: title (col 0) = 3.0, content (col 1) = 1.0
        base_sql = """
            SELECT notes.*, bm25(notes_fts, 3.0, 1.0) AS score,
                   snippet(notes_fts, 1, '<b>', '</b>', '...', 32) AS snip
            FROM notes_fts
            JOIN notes ON notes.rowid = notes_fts.rowid
            WHERE notes_fts MATCH ?
        """
        count_sql = """
            SELECT COUNT(*) AS cnt
            FROM notes_fts
            JOIN notes ON notes.rowid = notes_fts.rowid
            WHERE notes_fts MATCH ?
        """
        params: list[Any] = [fts_expr]
        count_params: list[Any] = [fts_expr]

        # Apply metadata filters.
        if query.tags:
            placeholders = ", ".join("?" for _ in query.tags)
            tag_clause = f"""
                AND notes.note_id IN (
                    SELECT note_id FROM note_tags WHERE tag IN ({placeholders})
                    GROUP BY note_id HAVING COUNT(DISTINCT tag) = ?
                )
            """
            base_sql += tag_clause
            count_sql += tag_clause
            params.extend(query.tags)
            params.append(len(query.tags))
            count_params.extend(query.tags)
            count_params.append(len(query.tags))

        if query.category:
            base_sql += " AND notes.category = ?"
            count_sql += " AND notes.category = ?"
            params.append(query.category)
            count_params.append(query.category)

        if query.status:
            base_sql += " AND notes.status = ?"
            count_sql += " AND notes.status = ?"
            params.append(query.status.value)
            count_params.append(query.status.value)

        if query.date_from:
            base_sql += " AND notes.updated_at >= ?"
            count_sql += " AND notes.updated_at >= ?"
            params.append(_dt_to_iso(query.date_from))
            count_params.append(_dt_to_iso(query.date_from))

        if query.date_to:
            base_sql += " AND notes.updated_at <= ?"
            count_sql += " AND notes.updated_at <= ?"
            params.append(_dt_to_iso(query.date_to))
            count_params.append(_dt_to_iso(query.date_to))

        base_sql += " ORDER BY score LIMIT ? OFFSET ?"
        params.extend([query.limit, query.offset])

        # Execute count query.
        cur_count = await self._conn.execute(count_sql, count_params)
        total_row = await cur_count.fetchone()
        total = total_row["cnt"] if total_row else 0

        # Execute results query.
        cur = await self._conn.execute(base_sql, params)
        rows = await cur.fetchall()

        results: list[SearchResult] = []
        for row in rows:
            note = await self._row_to_note(row)
            results.append(
                SearchResult(
                    note=note,
                    score=abs(row["score"]),  # bm25 returns negative values
                    snippet=row["snip"] or "",
                )
            )

        return SearchResponse(results=results, total=total, query=query.query)

    # -- taxonomy ------------------------------------------------------------

    async def list_tags(self) -> list[str]:
        cur = await self._conn.execute(
            "SELECT DISTINCT tag FROM note_tags ORDER BY tag"
        )
        rows = await cur.fetchall()
        return [r["tag"] for r in rows]

    async def list_categories(self) -> list[str]:
        cur = await self._conn.execute(
            "SELECT DISTINCT category FROM notes WHERE category != '' ORDER BY category"
        )
        rows = await cur.fetchall()
        return [r["category"] for r in rows]

    # -- intelligence --------------------------------------------------------

    async def get_stale(self, days: int = 30) -> list[StaleItem]:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=days)
        cur = await self._conn.execute(
            "SELECT * FROM notes WHERE status = ? AND updated_at < ? ORDER BY updated_at ASC",
            (NoteStatus.ACTIVE.value, _dt_to_iso(cutoff)),
        )
        rows = await cur.fetchall()
        items: list[StaleItem] = []
        for row in rows:
            note = await self._row_to_note(row)
            delta = now - note.updated_at
            items.append(StaleItem(note=note, days_since_update=delta.days))
        return items

    async def get_daily_digest(self) -> DailyDigest:
        from krang.search import build_daily_digest

        return await build_daily_digest(self)

    async def get_related(self, note_id: str, limit: int = 5) -> list[SearchResult]:
        note = await self.get(note_id)
        if note is None:
            return []
        from krang.search import find_related

        return await find_related(note, self, limit=limit)

    # -- maintenance ---------------------------------------------------------

    async def backup(self, path: str) -> str:
        await self._conn.execute("VACUUM INTO ?", (path,))
        return path
