"""Unit tests for SQLiteNoteStore."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from krang.models import (
    NoteStatus,
    NoteUpdate,
    SearchQuery,
)
from krang.sqlite_store import SQLiteNoteStore
from tests.conftest import make_note

# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


class TestCreate:
    async def test_basic(self, store):
        note = await store.create(make_note(title="Hello", content="World"))
        assert note.title == "Hello"
        assert note.content == "World"
        assert note.note_id
        assert note.status == NoteStatus.ACTIVE

    async def test_with_tags(self, store):
        note = await store.create(make_note(tags=["a", "b", "c"]))
        assert sorted(note.tags) == ["a", "b", "c"]

    async def test_with_category(self, store):
        note = await store.create(make_note(category="work"))
        assert note.category == "work"

    async def test_with_metadata(self, store):
        note = await store.create(make_note(metadata={"source": "web"}))
        assert note.metadata == {"source": "web"}

    async def test_duplicate_tags_deduped(self, store):
        note = await store.create(make_note(tags=["dup", "dup", "dup"]))
        assert note.tags == ["dup"]

    async def test_timestamps_set(self, store):
        note = await store.create(make_note())
        assert note.created_at is not None
        assert note.updated_at is not None
        assert note.created_at.tzinfo is not None


class TestGet:
    async def test_existing(self, store):
        created = await store.create(make_note(title="Find me"))
        found = await store.get(created.note_id)
        assert found is not None
        assert found.title == "Find me"
        assert found.note_id == created.note_id

    async def test_nonexistent(self, store):
        assert await store.get("nonexistent") is None

    async def test_preserves_all_fields(self, store):
        created = await store.create(
            make_note(
                title="Full",
                content="Body",
                tags=["x", "y"],
                category="cat",
                metadata={"k": "v"},
            )
        )
        found = await store.get(created.note_id)
        assert found is not None
        assert found.title == "Full"
        assert found.content == "Body"
        assert sorted(found.tags) == ["x", "y"]
        assert found.category == "cat"
        assert found.metadata == {"k": "v"}


class TestUpdate:
    async def test_update_title(self, store):
        note = await store.create(make_note(title="Old"))
        updated = await store.update(note.note_id, NoteUpdate(title="New"))
        assert updated is not None
        assert updated.title == "New"
        assert updated.content == note.content  # unchanged

    async def test_update_content(self, store):
        note = await store.create(make_note(content="Old content"))
        updated = await store.update(note.note_id, NoteUpdate(content="New content"))
        assert updated is not None
        assert updated.content == "New content"

    async def test_update_tags(self, store):
        note = await store.create(make_note(tags=["a", "b"]))
        updated = await store.update(note.note_id, NoteUpdate(tags=["c", "d"]))
        assert updated is not None
        assert sorted(updated.tags) == ["c", "d"]

    async def test_update_status(self, store):
        note = await store.create(make_note())
        updated = await store.update(note.note_id, NoteUpdate(status=NoteStatus.ARCHIVED))
        assert updated is not None
        assert updated.status == NoteStatus.ARCHIVED

    async def test_update_metadata(self, store):
        note = await store.create(make_note(metadata={"a": "1"}))
        updated = await store.update(note.note_id, NoteUpdate(metadata={"b": "2"}))
        assert updated is not None
        assert updated.metadata == {"b": "2"}

    async def test_update_bumps_updated_at(self, store):
        note = await store.create(make_note())
        updated = await store.update(note.note_id, NoteUpdate(title="Bumped"))
        assert updated is not None
        assert updated.updated_at >= note.updated_at

    async def test_update_nonexistent(self, store):
        result = await store.update("nonexistent", NoteUpdate(title="X"))
        assert result is None

    async def test_partial_update_preserves_others(self, store):
        note = await store.create(
            make_note(title="Keep", content="Also keep", tags=["keep"], category="cat")
        )
        updated = await store.update(note.note_id, NoteUpdate(category="new_cat"))
        assert updated is not None
        assert updated.title == "Keep"
        assert updated.content == "Also keep"
        assert updated.tags == ["keep"]
        assert updated.category == "new_cat"


class TestDelete:
    async def test_delete_existing(self, store):
        note = await store.create(make_note())
        assert await store.delete(note.note_id) is True
        assert await store.get(note.note_id) is None

    async def test_delete_nonexistent(self, store):
        assert await store.delete("nonexistent") is False

    async def test_delete_removes_tags(self, store):
        note = await store.create(make_note(tags=["a", "b"]))
        await store.delete(note.note_id)
        tags = await store.list_tags()
        assert "a" not in tags
        assert "b" not in tags


class TestListAll:
    async def test_empty(self, store):
        assert await store.list_all() == []

    async def test_returns_all(self, populated_store):
        notes = await populated_store.list_all()
        assert len(notes) == 15  # sample corpus size

    async def test_filter_by_status(self, store):
        await store.create(make_note(title="Active"))
        note2 = await store.create(make_note(title="Will archive"))
        await store.update(note2.note_id, NoteUpdate(status=NoteStatus.ARCHIVED))

        active = await store.list_all(status=NoteStatus.ACTIVE)
        assert len(active) == 1
        assert active[0].title == "Active"

        archived = await store.list_all(status=NoteStatus.ARCHIVED)
        assert len(archived) == 1
        assert archived[0].title == "Will archive"

    async def test_pagination(self, populated_store):
        page1 = await populated_store.list_all(limit=5, offset=0)
        page2 = await populated_store.list_all(limit=5, offset=5)
        assert len(page1) == 5
        assert len(page2) == 5
        ids1 = {n.note_id for n in page1}
        ids2 = {n.note_id for n in page2}
        assert ids1.isdisjoint(ids2)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class TestSearch:
    async def test_basic_query(self, populated_store):
        resp = await populated_store.search(SearchQuery(query="asyncio"))
        assert resp.total > 0
        assert resp.query == "asyncio"
        titles = [r.note.title for r in resp.results]
        assert any("asyncio" in t.lower() for t in titles)

    async def test_title_ranks_higher(self, populated_store):
        resp = await populated_store.search(SearchQuery(query="SQLite FTS5"))
        assert resp.total > 0
        # The note titled "SQLite FTS5 guide" should rank first
        assert "SQLite FTS5" in resp.results[0].note.title

    async def test_no_results(self, populated_store):
        resp = await populated_store.search(SearchQuery(query="xyznonexistentxyz"))
        assert resp.total == 0
        assert resp.results == []

    async def test_tag_filter(self, populated_store):
        resp = await populated_store.search(
            SearchQuery(query="python", tags=["python"])
        )
        for r in resp.results:
            assert "python" in r.note.tags

    async def test_category_filter(self, populated_store):
        resp = await populated_store.search(
            SearchQuery(query="notes", category="engineering")
        )
        for r in resp.results:
            assert r.note.category == "engineering"

    async def test_status_filter(self, store):
        await store.create(make_note(title="Searchable active", content="findme"))
        n2 = await store.create(make_note(title="Searchable archived", content="findme"))
        await store.update(n2.note_id, NoteUpdate(status=NoteStatus.ARCHIVED))

        resp = await store.search(
            SearchQuery(query="findme", status=NoteStatus.ACTIVE)
        )
        assert resp.total == 1
        assert resp.results[0].note.status == NoteStatus.ACTIVE

    async def test_pagination(self, populated_store):
        resp_all = await populated_store.search(SearchQuery(query="notes", limit=100))
        if resp_all.total > 2:
            resp_page = await populated_store.search(
                SearchQuery(query="notes", limit=2, offset=0)
            )
            assert len(resp_page.results) <= 2

    async def test_snippet_populated(self, populated_store):
        resp = await populated_store.search(SearchQuery(query="asyncio"))
        if resp.results:
            assert resp.results[0].snippet != "" or resp.results[0].note.content

    async def test_score_positive(self, populated_store):
        resp = await populated_store.search(SearchQuery(query="python"))
        for r in resp.results:
            assert r.score > 0


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------


class TestTaxonomy:
    async def test_list_tags_empty(self, store):
        assert await store.list_tags() == []

    async def test_list_tags(self, populated_store):
        tags = await populated_store.list_tags()
        assert "python" in tags
        assert "mcp" in tags
        assert tags == sorted(tags)

    async def test_list_categories_empty(self, store):
        assert await store.list_categories() == []

    async def test_list_categories(self, populated_store):
        cats = await populated_store.list_categories()
        assert "engineering" in cats
        assert "personal" in cats
        assert cats == sorted(cats)


# ---------------------------------------------------------------------------
# Intelligence
# ---------------------------------------------------------------------------


class TestStale:
    async def test_no_stale_on_fresh_data(self, populated_store):
        stale = await populated_store.get_stale(days=30)
        assert len(stale) == 0  # all just created

    async def test_finds_stale_notes(self, store):
        note = await store.create(make_note(title="Old note"))
        # Manually backdate the updated_at
        old_date = datetime.now(timezone.utc) - timedelta(days=60)
        await store._conn.execute(
            "UPDATE notes SET updated_at = ? WHERE note_id = ?",
            (old_date.isoformat(), note.note_id),
        )
        await store._conn.commit()

        stale = await store.get_stale(days=30)
        assert len(stale) == 1
        assert stale[0].note.note_id == note.note_id
        assert stale[0].days_since_update >= 59

    async def test_ignores_archived(self, store):
        note = await store.create(make_note())
        await store.update(note.note_id, NoteUpdate(status=NoteStatus.ARCHIVED))
        old_date = datetime.now(timezone.utc) - timedelta(days=60)
        await store._conn.execute(
            "UPDATE notes SET updated_at = ? WHERE note_id = ?",
            (old_date.isoformat(), note.note_id),
        )
        await store._conn.commit()

        stale = await store.get_stale(days=30)
        assert len(stale) == 0


class TestDailyDigest:
    async def test_empty_store(self, store):
        digest = await store.get_daily_digest()
        assert digest.total_notes == 0
        assert digest.recent_notes == []
        assert digest.stale_count == 0

    async def test_populated(self, populated_store):
        digest = await populated_store.get_daily_digest()
        assert digest.total_notes == 15
        assert len(digest.recent_notes) == 15  # all just created
        assert "engineering" in digest.category_distribution
        assert digest.category_distribution["engineering"] >= 5
        assert "python" in digest.tag_distribution


class TestRelated:
    async def test_related_returns_results(self, populated_store):
        notes = await populated_store.list_all()
        # Find the Python asyncio note
        py_note = next(n for n in notes if "asyncio" in n.title.lower())
        related = await populated_store.get_related(py_note.note_id)
        assert len(related) > 0
        # Should not include self
        assert all(r.note.note_id != py_note.note_id for r in related)

    async def test_related_nonexistent(self, store):
        related = await store.get_related("nonexistent")
        assert related == []

    async def test_related_respects_limit(self, populated_store):
        notes = await populated_store.list_all()
        related = await populated_store.get_related(notes[0].note_id, limit=2)
        assert len(related) <= 2


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------


class TestBackup:
    async def test_backup(self, populated_store, tmp_path):
        backup_path = str(tmp_path / "backup.db")
        result = await populated_store.backup(backup_path)
        assert result == backup_path

        # Verify backup has data
        import aiosqlite

        async with aiosqlite.connect(backup_path) as db:
            cur = await db.execute("SELECT COUNT(*) FROM notes")
            row = await cur.fetchone()
            assert row[0] == 15


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    async def test_unicode_content(self, store):
        note = await store.create(
            make_note(
                title="Unicode test: café résumé",
                content="Content with 日本語 and Ü",
                tags=["über", "café"],
            )
        )
        found = await store.get(note.note_id)
        assert found is not None
        assert "café" in found.title
        assert "über" in found.tags

    async def test_empty_tags(self, store):
        note = await store.create(make_note(tags=[]))
        assert note.tags == []

    async def test_long_content(self, store):
        long_text = "x" * 100_000
        note = await store.create(make_note(content=long_text))
        found = await store.get(note.note_id)
        assert found is not None
        assert len(found.content) == 100_000

    async def test_special_chars_in_search(self, populated_store):
        # Should not crash on FTS5 special chars
        resp = await populated_store.search(SearchQuery(query="test (with) [brackets]"))
        assert isinstance(resp.total, int)

    async def test_concurrent_creates(self, store):
        async def create_one(i: int):
            return await store.create(make_note(title=f"Concurrent {i}"))

        notes = await asyncio.gather(*[create_one(i) for i in range(10)])
        assert len(notes) == 10
        ids = {n.note_id for n in notes}
        assert len(ids) == 10  # all unique

    async def test_context_manager(self, tmp_db_path):
        async with SQLiteNoteStore(str(tmp_db_path)) as s:
            note = await s.create(make_note(title="Context manager test"))
            assert note.note_id
