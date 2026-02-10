"""MCP server for krang — exposes note tools and resources over stdio."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP

from krang.models import (
    NoteCreate,
    NoteStatus,
    NoteUpdate,
    SearchQuery,
)

logger = logging.getLogger("krang.server")
logging.basicConfig(stream=sys.stderr, level=logging.INFO)

mcp = FastMCP(
    "krang",
    instructions=(
        "A second brain for humans and their agents"
        " — knowledge management with full-text search"
    ),
)

# ---------------------------------------------------------------------------
# Store singleton — initialised lazily on first tool call
# ---------------------------------------------------------------------------

_store = None


async def _get_store():
    """Return the initialised NoteStore singleton."""
    global _store
    if _store is None:
        from krang.sqlite_store import SQLiteNoteStore

        db_path = os.environ.get("KRANG_DB_PATH", str(Path.home() / ".krang" / "brain.db"))
        db_path = str(Path(db_path).expanduser())
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        _store = SQLiteNoteStore(db_path)
        await _store.initialize()
    return _store


# TODO: Add graceful shutdown to close the store connection when the server
# exits.  FastMCP exposes a `lifespan` context-manager parameter but does not
# provide a simple `@mcp.on_shutdown` hook.  A lifespan-based approach would
# require restructuring the lazy singleton.  Revisit once FastMCP adds a
# first-class shutdown callback.


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def add_note(
    title: str,
    content: str,
    tags: list[str] | None = None,
    category: str = "",
    metadata: dict[str, str] | None = None,
) -> str:
    """Add a new note to the knowledge base.

    Args:
        title: Title of the note.
        content: Full text content of the note.
        tags: Optional list of tags for categorisation.
        category: Optional category label.
        metadata: Optional key-value metadata pairs.
    """
    try:
        tags = tags if tags is not None else []
        metadata = metadata if metadata is not None else {}
        store = await _get_store()
        note = await store.create(
            NoteCreate(
                title=title,
                content=content,
                tags=tags,
                category=category,
                metadata=metadata,
            )
        )
        return f"Created note '{note.title}' (ID: {note.note_id})"
    except Exception:
        logger.exception("add_note failed")
        return f"Error: could not create note '{title}'."


@mcp.tool()
async def search_notes(
    query: str,
    tags: list[str] | None = None,
    category: str = "",
    status: Literal["active", "archived", ""] = "",
    limit: int = 20,
) -> str:
    """Search notes by keyword, tags, category, or status.

    Args:
        query: Search query string (full-text search).
        tags: Filter results to notes that have ALL of these tags.
        category: Filter results to this category.
        status: Filter by note status ('active' or 'archived').
        limit: Maximum number of results to return (1-100, default 20).
    """
    try:
        tags = tags if tags is not None else []
        store = await _get_store()
        sq = SearchQuery(
            query=query,
            tags=tags,
            category=category if category else None,
            status=NoteStatus(status) if status else None,
            limit=limit,
        )
        response = await store.search(sq)

        if response.total == 0:
            return f"No notes found matching '{query}'."

        lines = [f"Found {response.total} results for '{query}':\n"]
        for i, result in enumerate(response.results, 1):
            note = result.note
            tag_str = ", ".join(note.tags) if note.tags else "none"
            snippet = result.snippet or note.content[:120]
            lines.append(f"{i}. {note.title} [ID: {note.note_id}] (score: {result.score:.2f})")
            lines.append(f"   {snippet}")
            lines.append(f"   Tags: {tag_str}\n")
        return "\n".join(lines)
    except Exception:
        logger.exception("search_notes failed")
        return f"Error: search for '{query}' failed."


@mcp.tool()
async def update_note(
    note_id: str,
    title: str | None = None,
    content: str | None = None,
    tags: list[str] | None = None,
    category: str | None = None,
    status: Literal["active", "archived"] | None = None,
) -> str:
    """Update an existing note. Only provided fields will be changed.

    Args:
        note_id: ID of the note to update.
        title: New title (optional).
        content: New content (optional).
        tags: New tag list, replaces existing tags (optional).
        category: New category (optional).
        status: New status — 'active' or 'archived' (optional).
    """
    try:
        store = await _get_store()
        update = NoteUpdate(
            title=title,
            content=content,
            tags=tags,
            category=category,
            status=NoteStatus(status) if status else None,
        )
        result = await store.update(note_id, update)
        if result is None:
            return f"Note '{note_id}' not found."
        return f"Updated note '{note_id}'."
    except Exception:
        logger.exception("update_note failed")
        return f"Error: could not update note '{note_id}'."


@mcp.tool()
async def delete_note(note_id: str) -> str:
    """Permanently delete a note from the knowledge base.

    Args:
        note_id: ID of the note to delete.
    """
    try:
        store = await _get_store()
        deleted = await store.delete(note_id)
        if not deleted:
            return f"Note '{note_id}' not found."
        return f"Deleted note '{note_id}'."
    except Exception:
        logger.exception("delete_note failed")
        return f"Error: could not delete note '{note_id}'."


@mcp.tool()
async def get_note(note_id: str) -> str:
    """Retrieve the full content of a note by its ID.

    Args:
        note_id: ID of the note to retrieve.
    """
    try:
        store = await _get_store()
        note = await store.get(note_id)
        if note is None:
            return f"Note '{note_id}' not found."

        tag_str = ", ".join(note.tags) if note.tags else "none"
        lines = [
            f"Title: {note.title}",
            f"ID: {note.note_id}",
            f"Status: {note.status.value}",
            f"Category: {note.category or 'none'}",
            f"Tags: {tag_str}",
            f"Created: {note.created_at.isoformat()}",
            f"Updated: {note.updated_at.isoformat()}",
        ]
        if note.metadata:
            meta_parts = [f"  {k}: {v}" for k, v in note.metadata.items()]
            lines.append("Metadata:")
            lines.extend(meta_parts)
        lines.append("---")
        lines.append(note.content)
        return "\n".join(lines)
    except Exception:
        logger.exception("get_note failed")
        return f"Error: could not retrieve note '{note_id}'."


@mcp.tool()
async def list_tags() -> str:
    """List all tags currently used across all notes."""
    try:
        store = await _get_store()
        tags = await store.list_tags()
        if not tags:
            return "No tags found."
        return f"Tags: {', '.join(tags)}"
    except Exception:
        logger.exception("list_tags failed")
        return "Error: could not list tags."


@mcp.tool()
async def list_categories() -> str:
    """List all categories currently used across all notes."""
    try:
        store = await _get_store()
        categories = await store.list_categories()
        if not categories:
            return "No categories found."
        return f"Categories: {', '.join(categories)}"
    except Exception:
        logger.exception("list_categories failed")
        return "Error: could not list categories."


@mcp.tool()
async def list_notes(
    status: Literal["active", "archived", ""] = "",
    limit: int = 20,
    offset: int = 0,
) -> str:
    """Browse notes in the knowledge base with optional status filter.

    Args:
        status: Filter by status ('active' or 'archived'). Empty for all.
        limit: Maximum number of notes to return (default 20).
        offset: Number of notes to skip for pagination (default 0).
    """
    try:
        store = await _get_store()
        s = NoteStatus(status) if status else None
        notes = await store.list_all(status=s, limit=limit, offset=offset)
        if not notes:
            return "No notes found."
        lines = [f"Showing {len(notes)} notes:\n"]
        for i, note in enumerate(notes, offset + 1):
            tag_str = ", ".join(note.tags) if note.tags else "none"
            lines.append(f"{i}. {note.title} [{note.status.value}]")
            lines.append(f"   ID: {note.note_id} | Tags: {tag_str}\n")
        return "\n".join(lines)
    except Exception:
        logger.exception("list_notes failed")
        return "Error: could not list notes."


@mcp.tool()
async def get_stale_items(days: int = 30) -> str:
    """Find notes that haven't been updated recently.

    Args:
        days: Number of days since last update to consider a note stale (default 30).
    """
    try:
        store = await _get_store()
        items = await store.get_stale(days)
        if not items:
            return f"No stale notes (all updated within the last {days} days)."
        lines = [f"{len(items)} stale notes (not updated in {days}+ days):\n"]
        for item in items:
            lines.append(f"- {item.note.title} ({item.days_since_update} days)")
        return "\n".join(lines)
    except Exception:
        logger.exception("get_stale_items failed")
        return "Error: could not retrieve stale items."


@mcp.tool()
async def daily_digest() -> str:
    """Get a summary of your knowledge base.

    Returns totals, recent activity, top categories/tags, and stale note count.
    """
    try:
        store = await _get_store()
        digest = await store.get_daily_digest()

        lines = ["Daily Digest\n"]
        lines.append(f"Total notes: {digest.total_notes}")
        lines.append(f"Recent activity: {len(digest.recent_notes)} notes")
        lines.append(f"Stale notes: {digest.stale_count}\n")

        if digest.category_distribution:
            sorted_cats = sorted(
                digest.category_distribution.items(), key=lambda x: x[1], reverse=True
            )
            cat_parts = [f"{cat} ({count})" for cat, count in sorted_cats[:5]]
            lines.append(f"Top categories: {', '.join(cat_parts)}")

        if digest.tag_distribution:
            sorted_tags = sorted(
                digest.tag_distribution.items(), key=lambda x: x[1], reverse=True
            )
            tag_parts = [f"{tag} ({count})" for tag, count in sorted_tags[:5]]
            lines.append(f"Top tags: {', '.join(tag_parts)}")

        return "\n".join(lines)
    except Exception:
        logger.exception("daily_digest failed")
        return "Error: could not generate daily digest."


@mcp.tool()
async def suggest_related(note_id: str, limit: int = 5) -> str:
    """Find notes that are related to the given note.

    Args:
        note_id: ID of the note to find related notes for.
        limit: Maximum number of related notes to return (default 5).
    """
    try:
        store = await _get_store()
        # First check the note exists
        note = await store.get(note_id)
        if note is None:
            return f"Note '{note_id}' not found."

        results = await store.get_related(note_id, limit)
        if not results:
            return f"No related notes found for '{note.title}'."

        lines = [f"Related to '{note.title}':\n"]
        for i, result in enumerate(results, 1):
            rid = result.note.note_id
            lines.append(f"{i}. {result.note.title} [ID: {rid}] (score: {result.score:.2f})")
        return "\n".join(lines)
    except Exception:
        logger.exception("suggest_related failed")
        return f"Error: could not find related notes for '{note_id}'."


# ---------------------------------------------------------------------------
# MCP Prompts
# ---------------------------------------------------------------------------


@mcp.prompt()
def review_stale(days: int = 30) -> str:
    """Review notes that haven't been updated recently and suggest actions."""
    return (
        f"Please use the get_stale_items tool with days={days} to find stale notes. "
        "For each stale note, suggest whether to update, archive, or delete it, "
        "and explain your reasoning."
    )


@mcp.prompt()
def summarize_kb() -> str:
    """Summarize the current state of the knowledge base."""
    return (
        "Please use the daily_digest tool to get an overview of the knowledge base, "
        "then use search_notes with a broad query to understand the main topics. "
        "Provide a concise summary of: total notes, key topics and themes, "
        "category distribution, and any recommendations for organization."
    )


@mcp.prompt()
def find_gaps() -> str:
    """Identify gaps and underrepresented topics in the knowledge base."""
    return (
        "Please use the daily_digest tool, then list_tags and list_categories "
        "to understand the knowledge base structure. Identify: "
        "1) Categories with very few notes that might need expansion, "
        "2) Topics that seem related but aren't connected, "
        "3) Potential new categories or tags that could improve organization. "
        "Provide specific, actionable recommendations."
    )


# ---------------------------------------------------------------------------
# MCP Resources
# ---------------------------------------------------------------------------


@mcp.resource("note://{note_id}")
async def get_note_resource(note_id: str) -> str:
    """Retrieve the full content of a note by its ID."""
    try:
        store = await _get_store()
        note = await store.get(note_id)
        if note is None:
            return f"Note '{note_id}' not found."

        tag_str = ", ".join(note.tags) if note.tags else "none"
        meta_str = ""
        if note.metadata:
            meta_parts = [f"  {k}: {v}" for k, v in note.metadata.items()]
            meta_str = "\nMetadata:\n" + "\n".join(meta_parts)

        return (
            f"Title: {note.title}\n"
            f"ID: {note.note_id}\n"
            f"Status: {note.status.value}\n"
            f"Category: {note.category or 'none'}\n"
            f"Tags: {tag_str}\n"
            f"Created: {note.created_at.isoformat()}\n"
            f"Updated: {note.updated_at.isoformat()}\n"
            f"{meta_str}\n"
            f"---\n"
            f"{note.content}"
        )
    except Exception:
        logger.exception("get_note_resource failed")
        return f"Error: could not retrieve note '{note_id}'."


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the krang MCP server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
