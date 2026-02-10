"""Kraang — a second brain for humans and their agents."""

from __future__ import annotations

try:
    from kraang._version import __version__
except ImportError:
    __version__ = "0.0.0"

from kraang.models import (
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
from kraang.store import NoteStore

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
