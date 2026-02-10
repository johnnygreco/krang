"""Integration tests for the krang MCP server tools."""

from __future__ import annotations

import pytest

import krang.server as server
from krang.models import NoteStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_store(store, monkeypatch):
    """Point the server module's store singleton at the test store."""

    async def _get_test_store():
        return store

    monkeypatch.setattr(server, "_get_store", _get_test_store)


# ---------------------------------------------------------------------------
# add_note
# ---------------------------------------------------------------------------


class TestAddNote:
    async def test_creates_note(self, store):
        result = await server.add_note("My Title", "My content")
        assert "Created note 'My Title'" in result
        assert "ID:" in result

    async def test_creates_note_with_tags_and_category(self, store):
        result = await server.add_note(
            "Tagged", "Content", tags=["a", "b"], category="cat1"
        )
        assert "Created note 'Tagged'" in result

    async def test_creates_note_with_metadata(self, store):
        result = await server.add_note(
            "Meta", "Content", metadata={"key": "value"}
        )
        assert "Created note 'Meta'" in result

    async def test_note_persists_in_store(self, store):
        await server.add_note("Persist", "Persisted content", tags=["t1"])
        notes = await store.list_all()
        assert len(notes) == 1
        assert notes[0].title == "Persist"
        assert notes[0].tags == ["t1"]


# ---------------------------------------------------------------------------
# search_notes
# ---------------------------------------------------------------------------


class TestSearchNotes:
    async def test_search_returns_results(self, populated_store):
        result = await server.search_notes("asyncio")
        assert "Found" in result
        assert "asyncio" in result.lower()
        assert "ID:" in result

    async def test_search_no_results(self, populated_store):
        result = await server.search_notes("zzzznonexistentzzzz")
        assert "No notes found matching" in result

    async def test_search_with_tag_filter(self, populated_store):
        result = await server.search_notes("python", tags=["python"])
        assert "Found" in result or "No notes" in result

    async def test_search_with_category_filter(self, populated_store):
        result = await server.search_notes("guide", category="engineering")
        assert isinstance(result, str)

    async def test_search_with_status_filter(self, populated_store):
        result = await server.search_notes("notes", status="active")
        assert isinstance(result, str)

    async def test_search_with_limit(self, populated_store):
        result = await server.search_notes("notes", limit=2)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# update_note
# ---------------------------------------------------------------------------


class TestUpdateNote:
    async def test_update_title(self, store):
        await server.add_note("Old Title", "Content")
        notes = await store.list_all()
        note_id = notes[0].note_id

        result = await server.update_note(note_id, title="New Title")
        assert f"Updated note '{note_id}'" in result

        updated = await store.get(note_id)
        assert updated.title == "New Title"

    async def test_update_content(self, store):
        await server.add_note("Title", "Old content")
        notes = await store.list_all()
        note_id = notes[0].note_id

        result = await server.update_note(note_id, content="New content")
        assert "Updated" in result

        updated = await store.get(note_id)
        assert updated.content == "New content"

    async def test_update_tags(self, store):
        await server.add_note("Title", "Content", tags=["old"])
        notes = await store.list_all()
        note_id = notes[0].note_id

        await server.update_note(note_id, tags=["new1", "new2"])
        updated = await store.get(note_id)
        assert updated.tags == ["new1", "new2"]

    async def test_update_status(self, store):
        await server.add_note("Title", "Content")
        notes = await store.list_all()
        note_id = notes[0].note_id

        await server.update_note(note_id, status="archived")
        updated = await store.get(note_id)
        assert updated.status == NoteStatus.ARCHIVED

    async def test_update_nonexistent_note(self, store):
        result = await server.update_note("nonexistent_id", title="New Title")
        assert "not found" in result


# ---------------------------------------------------------------------------
# delete_note
# ---------------------------------------------------------------------------


class TestDeleteNote:
    async def test_delete_existing_note(self, store):
        await server.add_note("Doomed", "Will be deleted")
        notes = await store.list_all()
        note_id = notes[0].note_id

        result = await server.delete_note(note_id)
        assert f"Deleted note '{note_id}'" in result

        assert await store.get(note_id) is None

    async def test_delete_nonexistent_note(self, store):
        result = await server.delete_note("nonexistent_id")
        assert "not found" in result


# ---------------------------------------------------------------------------
# list_tags
# ---------------------------------------------------------------------------


class TestListTags:
    async def test_list_tags_empty(self, store):
        result = await server.list_tags()
        assert "No tags found" in result

    async def test_list_tags_populated(self, populated_store):
        result = await server.list_tags()
        assert "Tags:" in result
        assert "python" in result


# ---------------------------------------------------------------------------
# list_categories
# ---------------------------------------------------------------------------


class TestListCategories:
    async def test_list_categories_empty(self, store):
        result = await server.list_categories()
        assert "No categories found" in result

    async def test_list_categories_populated(self, populated_store):
        result = await server.list_categories()
        assert "Categories:" in result
        assert "engineering" in result


# ---------------------------------------------------------------------------
# list_notes
# ---------------------------------------------------------------------------


class TestListNotes:
    async def test_list_notes_empty(self, store):
        result = await server.list_notes()
        assert "No notes found" in result

    async def test_list_notes_populated(self, populated_store):
        result = await server.list_notes()
        assert "Showing" in result
        assert "notes" in result

    async def test_list_notes_with_status_filter(self, populated_store):
        result = await server.list_notes(status="active")
        assert "Showing" in result


# ---------------------------------------------------------------------------
# get_stale_items
# ---------------------------------------------------------------------------


class TestGetStaleItems:
    async def test_no_stale_items(self, store):
        await server.add_note("Fresh", "Just created")
        result = await server.get_stale_items(days=30)
        assert "No stale notes" in result or "0 stale" in result

    async def test_stale_items_with_zero_days(self, populated_store):
        # With days=0, all notes should be stale
        result = await server.get_stale_items(days=0)
        assert "stale notes" in result.lower()


# ---------------------------------------------------------------------------
# daily_digest
# ---------------------------------------------------------------------------


class TestDailyDigest:
    async def test_digest_empty(self, store):
        result = await server.daily_digest()
        assert "Daily Digest" in result
        assert "Total notes: 0" in result

    async def test_digest_populated(self, populated_store):
        result = await server.daily_digest()
        assert "Daily Digest" in result
        assert "Total notes:" in result
        assert "Top categories:" in result
        assert "Top tags:" in result


# ---------------------------------------------------------------------------
# suggest_related
# ---------------------------------------------------------------------------


class TestSuggestRelated:
    async def test_related_nonexistent_note(self, store):
        result = await server.suggest_related("nonexistent_id")
        assert "not found" in result

    async def test_related_returns_results(self, populated_store):
        notes = await populated_store.list_all()
        note_id = notes[0].note_id
        result = await server.suggest_related(note_id)
        # Should either return related notes or say none found
        assert "Related to" in result or "No related notes" in result

    async def test_related_with_custom_limit(self, populated_store):
        notes = await populated_store.list_all()
        note_id = notes[0].note_id
        result = await server.suggest_related(note_id, limit=2)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# get_note_resource
# ---------------------------------------------------------------------------


class TestGetNoteResource:
    async def test_resource_existing_note(self, store):
        await server.add_note("Resource Test", "Resource content", tags=["t1"], category="cat")
        notes = await store.list_all()
        note_id = notes[0].note_id

        result = await server.get_note_resource(note_id)
        assert "Title: Resource Test" in result
        assert "Resource content" in result
        assert "Tags: t1" in result
        assert "Category: cat" in result
        assert "Status: active" in result
        assert f"ID: {note_id}" in result

    async def test_resource_nonexistent_note(self, store):
        result = await server.get_note_resource("nonexistent_id")
        assert "not found" in result

    async def test_resource_with_metadata(self, store):
        await server.add_note("Meta Note", "Content", metadata={"source": "web"})
        notes = await store.list_all()
        note_id = notes[0].note_id

        result = await server.get_note_resource(note_id)
        assert "Metadata:" in result
        assert "source: web" in result

    async def test_resource_returns_error_on_store_failure(self, store, monkeypatch):
        async def _broken_get(note_id):
            raise RuntimeError("db exploded")

        monkeypatch.setattr(store, "get", _broken_get)
        result = await server.get_note_resource("some-id")
        assert "Error:" in result
        assert "could not retrieve note" in result
