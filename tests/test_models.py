"""Unit tests for krang Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from krang.models import (
    Note,
    NoteCreate,
    NoteStatus,
    NoteUpdate,
    SearchQuery,
)

# ---------------------------------------------------------------------------
# NoteCreate
# ---------------------------------------------------------------------------


class TestNoteCreate:
    def test_valid(self):
        nc = NoteCreate(title="Hello", content="World", tags=["a"], category="cat")
        assert nc.title == "Hello"
        assert nc.content == "World"
        assert nc.tags == ["a"]
        assert nc.category == "cat"
        assert nc.metadata == {}

    def test_empty_title_rejected(self):
        with pytest.raises(ValidationError):
            NoteCreate(title="", content="body")

    def test_empty_content_rejected(self):
        with pytest.raises(ValidationError):
            NoteCreate(title="ok", content="")

    def test_title_max_length(self):
        with pytest.raises(ValidationError):
            NoteCreate(title="x" * 501, content="body")

    def test_defaults(self):
        nc = NoteCreate(title="T", content="C")
        assert nc.tags == []
        assert nc.category == ""
        assert nc.metadata == {}


# ---------------------------------------------------------------------------
# Note
# ---------------------------------------------------------------------------


class TestNote:
    def test_defaults(self):
        note = Note(title="T", content="C")
        assert note.status == NoteStatus.ACTIVE
        assert note.tags == []
        assert note.category == ""
        assert note.metadata == {}
        assert note.note_id  # auto-generated, non-empty
        assert note.created_at is not None
        assert note.updated_at is not None

    def test_id_auto_generated(self):
        n1 = Note(title="A", content="B")
        n2 = Note(title="A", content="B")
        assert n1.note_id != n2.note_id


# ---------------------------------------------------------------------------
# NoteUpdate
# ---------------------------------------------------------------------------


class TestNoteUpdate:
    def test_partial(self):
        update = NoteUpdate(title="New Title")
        assert update.title == "New Title"
        assert update.content is None
        assert update.tags is None
        assert update.category is None
        assert update.status is None
        assert update.metadata is None

    def test_all_none_by_default(self):
        update = NoteUpdate()
        assert update.title is None
        assert update.content is None

    def test_empty_title_rejected(self):
        with pytest.raises(ValidationError):
            NoteUpdate(title="")

    def test_status_field(self):
        update = NoteUpdate(status=NoteStatus.ARCHIVED)
        assert update.status == NoteStatus.ARCHIVED


# ---------------------------------------------------------------------------
# SearchQuery
# ---------------------------------------------------------------------------


class TestSearchQuery:
    def test_defaults(self):
        sq = SearchQuery(query="hello")
        assert sq.limit == 20
        assert sq.offset == 0
        assert sq.tags == []
        assert sq.category is None
        assert sq.status is None

    def test_limit_lower_bound(self):
        with pytest.raises(ValidationError):
            SearchQuery(query="test", limit=0)

    def test_limit_upper_bound(self):
        with pytest.raises(ValidationError):
            SearchQuery(query="test", limit=101)

    def test_limit_valid_boundaries(self):
        sq1 = SearchQuery(query="test", limit=1)
        assert sq1.limit == 1
        sq100 = SearchQuery(query="test", limit=100)
        assert sq100.limit == 100

    def test_offset_non_negative(self):
        with pytest.raises(ValidationError):
            SearchQuery(query="test", offset=-1)

    def test_empty_query_rejected(self):
        with pytest.raises(ValidationError):
            SearchQuery(query="")


# ---------------------------------------------------------------------------
# NoteStatus
# ---------------------------------------------------------------------------


class TestNoteStatus:
    def test_values(self):
        assert NoteStatus.ACTIVE == "active"
        assert NoteStatus.ARCHIVED == "archived"

    def test_string_enum(self):
        assert isinstance(NoteStatus.ACTIVE, str)
        assert NoteStatus.ACTIVE.value == "active"
        assert NoteStatus.ARCHIVED.value == "archived"
