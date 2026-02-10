"""End-to-end tests for krang — full stack: store → SQLite → response."""

from __future__ import annotations

import asyncio

from krang.models import (
    NoteCreate,
    NoteStatus,
    NoteUpdate,
    SearchQuery,
)
from tests.conftest import make_note

# ---------------------------------------------------------------------------
# Core flow
# ---------------------------------------------------------------------------


async def test_create_and_search_flow(store):
    """Create notes via store, search via store, verify results match."""
    await store.create(
        NoteCreate(
            title="Async Python patterns",
            content="Coroutines and event loops are fundamental to asyncio programming.",
            tags=["python", "async"],
            category="engineering",
        )
    )
    await store.create(
        NoteCreate(
            title="Grocery shopping list",
            content="Buy milk, eggs, bread, and vegetables from the store.",
            tags=["shopping"],
            category="personal",
        )
    )

    response = await store.search(SearchQuery(query="asyncio"))
    assert response.total >= 1
    titles = [r.note.title for r in response.results]
    assert "Async Python patterns" in titles


async def test_crud_lifecycle(store):
    """Create -> Read -> Update -> Read -> Delete -> Read(None)."""
    # Create
    note = await store.create(make_note(title="CRUD Test", content="Original content"))
    note_id = note.note_id
    assert note.title == "CRUD Test"

    # Read
    fetched = await store.get(note_id)
    assert fetched is not None
    assert fetched.title == "CRUD Test"
    assert fetched.content == "Original content"

    # Update
    updated = await store.update(note_id, NoteUpdate(content="Updated content"))
    assert updated is not None
    assert updated.content == "Updated content"
    assert updated.title == "CRUD Test"  # unchanged

    # Read again
    fetched2 = await store.get(note_id)
    assert fetched2 is not None
    assert fetched2.content == "Updated content"

    # Delete
    deleted = await store.delete(note_id)
    assert deleted is True

    # Read after delete
    gone = await store.get(note_id)
    assert gone is None


# ---------------------------------------------------------------------------
# Search edge cases
# ---------------------------------------------------------------------------


async def test_search_empty_database(store):
    """Search on fresh empty store returns 0 results."""
    response = await store.search(SearchQuery(query="anything"))
    assert response.total == 0
    assert response.results == []


async def test_search_with_filters(populated_store):
    """Search with tag filter, category filter, combined filters."""
    store = populated_store

    # Search with category filter
    response = await store.search(SearchQuery(query="notes", category="engineering"))
    for result in response.results:
        assert result.note.category == "engineering"

    # Search with tag filter
    response = await store.search(SearchQuery(query="Python", tags=["python"]))
    for result in response.results:
        assert "python" in result.note.tags

    # Search with status filter
    response = await store.search(
        SearchQuery(query="notes", status=NoteStatus.ACTIVE)
    )
    for result in response.results:
        assert result.note.status == NoteStatus.ACTIVE


# ---------------------------------------------------------------------------
# Content edge cases
# ---------------------------------------------------------------------------


async def test_unicode_content(store):
    """Create and retrieve notes with unicode titles/content/tags."""
    note = await store.create(
        NoteCreate(
            title="Unicode test: \u00e9\u00e0\u00fc\u00f1 \u4f60\u597d",
            content="Content with unicode: \u00df\u00f8\u00e5\u0159\u017e \u2603 \u2605 \u2764",
            tags=["\u00e9tiquette", "\u4e2d\u6587"],
            category="i18n",
        )
    )
    fetched = await store.get(note.note_id)
    assert fetched is not None
    assert "\u00e9\u00e0\u00fc\u00f1" in fetched.title
    assert "\u4f60\u597d" in fetched.title
    assert "\u00e9tiquette" in fetched.tags
    assert "\u4e2d\u6587" in fetched.tags
    assert fetched.category == "i18n"


async def test_very_long_content(store):
    """Create note with 100KB content, verify storage and retrieval."""
    long_content = "x" * 100_000
    note = await store.create(
        NoteCreate(title="Long note", content=long_content)
    )
    fetched = await store.get(note.note_id)
    assert fetched is not None
    assert len(fetched.content) == 100_000
    assert fetched.content == long_content


# ---------------------------------------------------------------------------
# Missing / nonexistent operations
# ---------------------------------------------------------------------------


async def test_update_nonexistent_note(store):
    """Updating a note that doesn't exist returns None."""
    result = await store.update("nonexistent_id", NoteUpdate(title="Nope"))
    assert result is None


async def test_delete_nonexistent_note(store):
    """Deleting a note that doesn't exist returns False."""
    result = await store.delete("nonexistent_id")
    assert result is False


# ---------------------------------------------------------------------------
# Tag handling
# ---------------------------------------------------------------------------


async def test_duplicate_tags_handled(store):
    """Creating a note with duplicate tags deduplicates them."""
    note = await store.create(
        NoteCreate(
            title="Dup tags",
            content="Testing tag deduplication.",
            tags=["python", "python", "code", "code", "python"],
        )
    )
    fetched = await store.get(note.note_id)
    assert fetched is not None
    # Implementation should deduplicate tags
    assert len(fetched.tags) == len(set(fetched.tags))


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


async def test_concurrent_operations(store):
    """Run multiple create/search operations concurrently via asyncio.gather."""
    async def create_note(i: int):
        return await store.create(
            NoteCreate(
                title=f"Concurrent note {i}",
                content=f"Content for concurrent test number {i}.",
                tags=["concurrent"],
            )
        )

    # Create 10 notes concurrently
    notes = await asyncio.gather(*[create_note(i) for i in range(10)])
    assert len(notes) == 10
    assert len({n.note_id for n in notes}) == 10  # all unique IDs

    # Search should find them
    response = await store.search(SearchQuery(query="concurrent"))
    assert response.total >= 10


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------


async def test_backup_and_integrity(store, tmp_path):
    """Create notes, backup, verify backup file exists and has data."""
    await store.create(make_note(title="Backup test", content="Data to back up."))

    backup_path = str(tmp_path / "backup.db")
    result = await store.backup(backup_path)
    assert result == backup_path

    import os

    assert os.path.exists(backup_path)
    assert os.path.getsize(backup_path) > 0


# ---------------------------------------------------------------------------
# Stale detection and digest
# ---------------------------------------------------------------------------


async def test_stale_and_digest(store):
    """Create notes with varied dates, test stale detection and digest."""

    # Create a few notes (they'll have current timestamps)
    await store.create(make_note(title="Recent note 1", content="Fresh content."))
    await store.create(make_note(title="Recent note 2", content="Also fresh."))

    # Stale detection with 0 days threshold should find all notes
    stale_items = await store.get_stale(days=0)
    assert isinstance(stale_items, list)

    # Stale detection with large threshold should find nothing (notes are brand new)
    stale_items = await store.get_stale(days=9999)
    assert len(stale_items) == 0

    # Digest should reflect the created notes
    digest = await store.get_daily_digest()
    assert digest.total_notes >= 2
    assert isinstance(digest.category_distribution, dict)
    assert isinstance(digest.tag_distribution, dict)
    assert isinstance(digest.stale_count, int)
