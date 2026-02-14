"""Integration tests for the kraang MCP server tools."""

from __future__ import annotations

import pytest

import kraang.server as server

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
# remember
# ---------------------------------------------------------------------------


class TestRemember:
    async def test_creates_note(self, store):
        result = await server.remember("My Title", "My content")
        assert 'Created "My Title"' in result

    async def test_updates_existing(self, store):
        await server.remember("Title", "v1")
        result = await server.remember("Title", "v2")
        assert 'Updated "Title"' in result

    async def test_with_tags_and_category(self, store):
        result = await server.remember("Tagged", "Content", tags=["a", "b"], category="cat1")
        assert 'Created "Tagged"' in result
        assert "a | b" in result

    async def test_note_persists(self, store):
        await server.remember("Persist", "Persisted content", tags=["t1"])
        notes = await store.list_notes()
        assert len(notes) == 1
        assert notes[0].title == "Persist"

    async def test_error_handling(self, store, monkeypatch):
        async def _broken(*a, **kw):
            raise RuntimeError("db error")

        monkeypatch.setattr(store, "upsert_note", _broken)
        result = await server.remember("Title", "Content")
        assert "Error:" in result


class TestRememberValidation:
    async def test_empty_title(self, store):
        result = await server.remember("", "content")
        assert "Error:" in result
        assert "title" in result.lower()

    async def test_whitespace_title(self, store):
        result = await server.remember("   ", "content")
        assert "Error:" in result
        assert "title" in result.lower()

    async def test_empty_content(self, store):
        result = await server.remember("Title", "")
        assert "Error:" in result
        assert "content" in result.lower()

    async def test_whitespace_content(self, store):
        result = await server.remember("Title", "   ")
        assert "Error:" in result
        assert "content" in result.lower()


# ---------------------------------------------------------------------------
# recall
# ---------------------------------------------------------------------------


class TestRecall:
    async def test_returns_results(self, populated_store):
        result = await server.recall("asyncio")
        assert "Results for" in result
        assert "asyncio" in result.lower()

    async def test_no_results(self, populated_store):
        result = await server.recall("zzzznonexistentzzzz")
        assert "No results found" in result

    async def test_scope_notes(self, populated_store):
        result = await server.recall("python", scope="notes")
        assert "Results for" in result or "No results" in result

    async def test_scope_sessions(self, populated_store):
        result = await server.recall("python", scope="sessions")
        # No sessions indexed in test, so should be empty
        assert "No results" in result or "Results for" in result

    async def test_error_handling(self, store, monkeypatch):
        async def _broken(*a, **kw):
            raise RuntimeError("db error")

        monkeypatch.setattr(store, "search_notes", _broken)
        result = await server.recall("query")
        assert "Error:" in result


# ---------------------------------------------------------------------------
# forget
# ---------------------------------------------------------------------------


class TestForget:
    async def test_forget_note(self, store):
        await server.remember("Forgettable", "Content")
        result = await server.forget("Forgettable")
        assert 'Forgot "Forgettable"' in result
        assert "0.0" in result

    async def test_forget_partial(self, store):
        await server.remember("Partial", "Content")
        result = await server.forget("Partial", relevance=0.3)
        assert "0.3" in result

    async def test_forget_not_found(self, store):
        result = await server.forget("nonexistent")
        assert "not found" in result

    async def test_remember_restores(self, store):
        await server.remember("Restore me", "v1")
        await server.forget("Restore me")

        # Note is hidden
        notes = await store.list_notes()
        assert len(notes) == 0

        # remember restores it
        await server.remember("Restore me", "v2")
        notes = await store.list_notes()
        assert len(notes) == 1
        assert notes[0].relevance == 1.0

    async def test_forget_out_of_range(self, store):
        await server.remember("Range test", "Content")
        result = await server.forget("Range test", relevance=5.0)
        assert "between 0.0 and 1.0" in result

    async def test_error_handling(self, store, monkeypatch):
        async def _broken(*a, **kw):
            raise RuntimeError("db error")

        monkeypatch.setattr(store, "set_relevance", _broken)
        result = await server.forget("title")
        assert "Error:" in result


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


class TestStatus:
    async def test_empty_store(self, store):
        result = await server.status()
        assert "Kraang Status" in result
        assert "Notes:" in result

    async def test_populated(self, populated_store):
        result = await server.status()
        assert "Kraang Status" in result
        assert "Categories" in result
        assert "Tags" in result

    async def test_error_handling(self, store, monkeypatch):
        async def _broken(*a, **kw):
            raise RuntimeError("db error")

        monkeypatch.setattr(store, "count_notes", _broken)
        result = await server.status()
        assert "Error:" in result


# ---------------------------------------------------------------------------
# read_session
# ---------------------------------------------------------------------------


class TestReadSession:
    async def test_not_found(self, store):
        result = await server.read_session("nonexistent-session-id")
        assert "not found" in result.lower()

    async def test_missing_transcript_file(self, store):
        """Session exists in DB but JSONL file is missing."""
        from kraang.models import Session, utcnow

        session = Session(
            session_id="test-read-session-123",
            slug="test-slug",
            project_path="/nonexistent/project/path",
            git_branch="main",
            model="claude-opus-4-6",
            started_at=utcnow(),
            ended_at=utcnow(),
            duration_s=60,
            user_turn_count=2,
            assistant_turn_count=2,
            summary="Test session",
            user_text="user text",
            assistant_text="assistant text",
            tools_used=["Read"],
            files_edited=[],
            source_mtime=123.0,
            source_size=456,
        )
        await store.upsert_session(session)

        result = await server.read_session("test-read-session-123")
        assert "not found" in result.lower()
