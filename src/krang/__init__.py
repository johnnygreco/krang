"""Krang — a second brain for humans and their agents."""

from __future__ import annotations

__version__ = "0.1.0"

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
)
from krang.store import NoteStore

__all__ = [
    "DailyDigest",
    "Note",
    "NoteCreate",
    "NoteStatus",
    "NoteStore",
    "NoteUpdate",
    "SearchQuery",
    "SearchResponse",
    "SearchResult",
    "StaleItem",
]
