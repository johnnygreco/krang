"""Pydantic models for kraang — the shared data contracts."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class NoteStatus(str, Enum):
    """Lifecycle status of a note."""

    ACTIVE = "active"
    ARCHIVED = "archived"


# ---------------------------------------------------------------------------
# Core note models
# ---------------------------------------------------------------------------


class Note(BaseModel):
    """A single knowledge note stored in the brain."""

    note_id: str = Field(default_factory=new_id)
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)
    category: str = ""
    status: NoteStatus = NoteStatus.ACTIVE
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, str] = Field(default_factory=dict)


class NoteCreate(BaseModel):
    """Input schema for creating a new note."""

    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=1, max_length=200_000)
    tags: list[str] = Field(default_factory=list)
    category: str = ""
    metadata: dict[str, str] = Field(default_factory=dict)


class NoteUpdate(BaseModel):
    """Input schema for partially updating a note. Only provided fields are changed."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    content: str | None = Field(default=None, min_length=1, max_length=200_000)
    tags: list[str] | None = None
    category: str | None = None
    status: NoteStatus | None = None
    metadata: dict[str, str] | None = None


# ---------------------------------------------------------------------------
# Search models
# ---------------------------------------------------------------------------


class SearchQuery(BaseModel):
    """Parameters for a full-text + metadata search."""

    query: str = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)
    category: str | None = None
    status: NoteStatus | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class SearchResult(BaseModel):
    """A single search hit with relevance score."""

    note: Note
    score: float
    snippet: str = ""


class SearchResponse(BaseModel):
    """Paginated search results."""

    results: list[SearchResult]
    total: int
    query: str


# ---------------------------------------------------------------------------
# Analytics / intelligence models
# ---------------------------------------------------------------------------


class StaleItem(BaseModel):
    """A note that hasn't been updated in a while."""

    note: Note
    days_since_update: int


class DailyDigest(BaseModel):
    """Aggregated activity summary."""

    total_notes: int
    recent_notes: list[Note]
    category_distribution: dict[str, int]
    tag_distribution: dict[str, int]
    stale_count: int
