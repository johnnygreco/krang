"""Abstract NoteStore protocol — the contract that all storage backends implement."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

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


@runtime_checkable
class NoteStore(Protocol):
    """Async interface for note persistence and retrieval.

    Every method is async.  Implementations must support use as an async
    context manager (``async with store: ...``).
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create tables / run migrations if needed."""
        ...

    async def close(self) -> None:
        """Release resources (DB connections, file handles, etc.)."""
        ...

    async def __aenter__(self) -> NoteStore:
        """Enter async context manager (calls initialize)."""
        ...

    async def __aexit__(self, *exc: object) -> None:
        """Exit async context manager (calls close)."""
        ...

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create(self, note: NoteCreate) -> Note:
        """Persist a new note and return the full Note with generated fields."""
        ...

    async def get(self, note_id: str) -> Note | None:
        """Fetch a single note by ID, or None if not found."""
        ...

    async def update(self, note_id: str, update: NoteUpdate) -> Note | None:
        """Apply a partial update. Returns the updated Note, or None if not found."""
        ...

    async def delete(self, note_id: str) -> bool:
        """Hard-delete a note. Returns True if it existed, False otherwise."""
        ...

    async def list_all(
        self,
        status: NoteStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Note]:
        """List notes with optional status filter and pagination."""
        ...

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(self, query: SearchQuery) -> SearchResponse:
        """Full-text search with metadata filters and BM25 ranking."""
        ...

    # ------------------------------------------------------------------
    # Taxonomy
    # ------------------------------------------------------------------

    async def list_tags(self) -> list[str]:
        """Return all distinct tags across all notes, sorted alphabetically."""
        ...

    async def list_categories(self) -> list[str]:
        """Return all distinct categories, sorted alphabetically."""
        ...

    # ------------------------------------------------------------------
    # Intelligence / analytics
    # ------------------------------------------------------------------

    async def get_stale(self, days: int = 30) -> list[StaleItem]:
        """Find active notes not updated in the last *days* days."""
        ...

    async def get_daily_digest(self) -> DailyDigest:
        """Build an activity digest (last 24 h, distributions, staleness)."""
        ...

    async def get_related(self, note_id: str, limit: int = 5) -> list[SearchResult]:
        """Find notes semantically related to the given note."""
        ...

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    async def backup(self, path: str) -> str:
        """Create a backup of the database at *path*. Returns the backup path."""
        ...
