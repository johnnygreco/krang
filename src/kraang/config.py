"""Project configuration, DB path resolution, and title normalization."""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

# ---------------------------------------------------------------------------
# Title normalization
# ---------------------------------------------------------------------------

_WHITESPACE = re.compile(r"\s+")


def normalize_title(raw: str) -> str:
    """Normalize a title for deduplication and lookup.

    Applies: NFC unicode normalization -> collapse whitespace -> strip -> casefold.
    """
    text = unicodedata.normalize("NFC", raw)
    text = _WHITESPACE.sub(" ", text).strip()
    return text.casefold()


# ---------------------------------------------------------------------------
# Project root detection
# ---------------------------------------------------------------------------


def find_project_root(start: str | Path | None = None) -> Path:
    """Walk up from *start* (default: cwd) looking for a project root marker.

    Markers (in priority order): .git, pyproject.toml, package.json, Cargo.toml.
    Falls back to *start* itself if no marker is found.
    """
    p = Path(start) if start else Path.cwd()
    p = p.resolve()

    for directory in [p, *p.parents]:
        for marker in (".git", "pyproject.toml", "package.json", "Cargo.toml"):
            if (directory / marker).exists():
                return directory
    return p


# ---------------------------------------------------------------------------
# DB path resolution
# ---------------------------------------------------------------------------


def resolve_db_path(project_root: str | Path | None = None) -> Path:
    """Resolve the kraang database path.

    Priority:
    1. KRAANG_DB_PATH environment variable
    2. <project_root>/.kraang/kraang.db
    """
    env_path = os.environ.get("KRAANG_DB_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()

    root = Path(project_root) if project_root else find_project_root()
    return root / ".kraang" / "kraang.db"


# ---------------------------------------------------------------------------
# Claude Code session path encoding
# ---------------------------------------------------------------------------


def encode_project_path(project_path: str | Path) -> str:
    """Encode a project path the way Claude Code does for session directories.

    Replaces ``/`` with ``-``, e.g. ``/Users/foo/myproject`` -> ``-Users-foo-myproject``.
    """
    return str(project_path).replace("/", "-")


def get_sessions_dir(project_path: str | Path) -> Path:
    """Return the Claude Code sessions directory for the given project path."""
    encoded = encode_project_path(project_path)
    return Path.home() / ".claude" / "projects" / encoded
