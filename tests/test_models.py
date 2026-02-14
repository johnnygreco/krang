"""Unit tests for kraang Pydantic models."""

from __future__ import annotations

from kraang.models import (
    Note,
    NoteSearchResult,
    SearchScope,
    Session,
    SessionSearchResult,
    TranscriptTurn,
    utcnow,
)

# ---------------------------------------------------------------------------
# Note
# ---------------------------------------------------------------------------


class TestNote:
    def test_defaults(self):
        note = Note(title="T", content="C")
        assert note.relevance == 1.0
        assert note.tags == []
        assert note.category == ""
        assert note.note_id  # auto-generated
        assert note.created_at is not None

    def test_id_auto_generated(self):
        n1 = Note(title="A", content="B")
        n2 = Note(title="A", content="B")
        assert n1.note_id != n2.note_id

    def test_relevance_bounds(self):
        note = Note(title="T", content="C", relevance=0.5)
        assert note.relevance == 0.5


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


class TestSession:
    def test_basic(self):
        now = utcnow()
        session = Session(
            session_id="abc",
            project_path="/test",
            started_at=now,
            ended_at=now,
            source_mtime=123.0,
            source_size=456,
        )
        assert session.session_id == "abc"
        assert session.slug == ""
        assert session.duration_s == 0


# ---------------------------------------------------------------------------
# Search results
# ---------------------------------------------------------------------------


class TestSearchResults:
    def test_note_search_result(self):
        note = Note(title="T", content="C")
        result = NoteSearchResult(note=note, score=5.0, snippet="test...")
        assert result.score == 5.0

    def test_session_search_result(self):
        now = utcnow()
        session = Session(
            session_id="abc",
            project_path="/test",
            started_at=now,
            ended_at=now,
            source_mtime=0.0,
            source_size=0,
        )
        result = SessionSearchResult(session=session, score=3.0)
        assert result.score == 3.0


# ---------------------------------------------------------------------------
# SearchScope
# ---------------------------------------------------------------------------


class TestSearchScope:
    def test_values(self):
        assert SearchScope.ALL == "all"
        assert SearchScope.NOTES == "notes"
        assert SearchScope.SESSIONS == "sessions"


# ---------------------------------------------------------------------------
# TranscriptTurn
# ---------------------------------------------------------------------------


class TestTranscriptTurn:
    def test_basic(self):
        turn = TranscriptTurn(role="User", text="Hello")
        assert turn.role == "User"
        assert turn.tool_calls == []
