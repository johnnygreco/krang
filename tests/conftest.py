"""Shared fixtures and factories for krang tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from krang.models import NoteCreate

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db_path(tmp_path: Path) -> Path:
    """Return a temporary SQLite database path (file doesn't exist yet)."""
    return tmp_path / "test_brain.db"


@pytest.fixture()
async def store(tmp_db_path: Path):
    """Yield an initialized SQLiteNoteStore backed by a temp database."""
    from krang.sqlite_store import SQLiteNoteStore

    s = SQLiteNoteStore(str(tmp_db_path))
    await s.initialize()
    yield s
    await s.close()


@pytest.fixture()
async def populated_store(store):
    """A store pre-loaded with a sample corpus of notes."""
    for note in SAMPLE_NOTES:
        await store.create(note)
    return store


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def make_note(**overrides) -> NoteCreate:
    """Build a NoteCreate with sensible defaults, overridden by kwargs."""
    defaults = {
        "title": "Test Note",
        "content": "This is test content for a krang note.",
        "tags": ["test"],
        "category": "general",
        "metadata": {},
    }
    defaults.update(overrides)
    return NoteCreate(**defaults)


# ---------------------------------------------------------------------------
# Sample corpus
# ---------------------------------------------------------------------------

SAMPLE_NOTES: list[NoteCreate] = [
    make_note(
        title="Python asyncio patterns",
        content="Event loops, coroutines, and tasks are the core asyncio primitives.",
        tags=["python", "async", "programming"],
        category="engineering",
    ),
    make_note(
        title="SQLite FTS5 guide",
        content="FTS5 is a full-text search extension for SQLite using BM25 ranking.",
        tags=["sqlite", "search", "database"],
        category="engineering",
    ),
    make_note(
        title="Weekly grocery list",
        content="Milk, eggs, bread, avocados, chicken, rice, and vegetables.",
        tags=["shopping", "food"],
        category="personal",
    ),
    make_note(
        title="MCP protocol overview",
        content=(
            "Model Context Protocol enables LLMs to interact"
            " with external tools and data sources."
        ),
        tags=["mcp", "ai", "protocol"],
        category="engineering",
    ),
    make_note(
        title="Meditation practice notes",
        content="Focus on breath for 10 minutes. Body scan technique helps with relaxation.",
        tags=["health", "mindfulness"],
        category="wellness",
    ),
    make_note(
        title="Project Krang architecture",
        content="Second brain MCP server with SQLite FTS5 backend. Pydantic models for contracts.",
        tags=["krang", "architecture", "mcp"],
        category="engineering",
    ),
    make_note(
        title="Book: Thinking Fast and Slow",
        content=(
            "System 1 is fast and intuitive. System 2 is slow"
            " and deliberate. Cognitive biases."
        ),
        tags=["books", "psychology", "reading"],
        category="learning",
    ),
    make_note(
        title="Docker compose tips",
        content=(
            "Use volumes for persistent data. Networks for"
            " service communication. Health checks."
        ),
        tags=["docker", "devops", "infrastructure"],
        category="engineering",
    ),
    make_note(
        title="Birthday gift ideas",
        content="Smart watch, cookbook, hiking gear, board game, concert tickets.",
        tags=["gifts", "personal"],
        category="personal",
    ),
    make_note(
        title="Pydantic v2 migration",
        content=(
            "model_validator replaces root_validator."
            " ConfigDict replaces class Config. Field changes."
        ),
        tags=["python", "pydantic", "migration"],
        category="engineering",
    ),
    make_note(
        title="Morning routine",
        content="Wake at 6am, meditate 10min, exercise 30min, cold shower, healthy breakfast.",
        tags=["health", "routine", "productivity"],
        category="wellness",
    ),
    make_note(
        title="REST API design principles",
        content=(
            "Use nouns for resources, HTTP verbs for actions."
            " Pagination, filtering, versioning."
        ),
        tags=["api", "rest", "design"],
        category="engineering",
    ),
    make_note(
        title="Investment portfolio review",
        content=(
            "60% index funds, 20% bonds, 10% international,"
            " 10% alternatives. Rebalance quarterly."
        ),
        tags=["finance", "investing"],
        category="finance",
    ),
    make_note(
        title="Garden planting schedule",
        content="Tomatoes in March, herbs in April, squash in May. Water daily in summer.",
        tags=["garden", "plants"],
        category="personal",
    ),
    make_note(
        title="Machine learning fundamentals",
        content=(
            "Supervised vs unsupervised learning."
            " Neural networks, gradient descent, backpropagation."
        ),
        tags=["ml", "ai", "programming"],
        category="learning",
    ),
]
