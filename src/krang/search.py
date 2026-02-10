"""Search and intelligence functions for krang.

Pure logic that works against the NoteStore protocol — no direct DB access.
Provides query preprocessing, BM25 helpers, related-note discovery, stale
detection, and daily digest generation.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from krang.store import NoteStore

from krang.models import (
    DailyDigest,
    Note,
    NoteStatus,
    SearchQuery,
    SearchResult,
    StaleItem,
)

# ---------------------------------------------------------------------------
# Stop words
# ---------------------------------------------------------------------------

STOP_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "shall",
        "of",
        "in",
        "to",
        "for",
        "with",
        "on",
        "at",
        "by",
        "from",
        "about",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "out",
        "off",
        "over",
        "under",
        "again",
        "further",
        "then",
        "once",
        "and",
        "but",
        "or",
        "nor",
        "not",
        "so",
        "yet",
        "both",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "only",
        "own",
        "same",
        "than",
        "too",
        "very",
        "just",
        "because",
        "as",
        "until",
        "while",
        "if",
        "that",
        "this",
        "it",
        "its",
        "he",
        "she",
        "they",
        "them",
        "we",
        "you",
        "i",
        "me",
        "my",
        "his",
        "her",
        "our",
        "your",
        "their",
        "what",
        "which",
        "who",
        "whom",
        "how",
        "when",
        "where",
        "why",
        "all",
        "any",
        "also",
        "here",
        "there",
    }
)

# FTS5 special characters that need to be stripped from bare terms.
_FTS5_SPECIAL = re.compile(r"[\^\*\(\)\{\}\[\]:]")

# Match a quoted phrase (double quotes).
_QUOTED_PHRASE = re.compile(r'"[^"]*"')

# Recognised boolean operators that FTS5 understands natively.
_BOOLEAN_OPS = {"AND", "OR", "NOT"}

# ---------------------------------------------------------------------------
# Column weights for BM25 ranking
# ---------------------------------------------------------------------------

# FTS5 bm25() returns negative scores (more negative = more relevant).
# Weights are passed as arguments: bm25(fts_table, w0, w1, w2, ...)
# where w_i is the weight for the i-th column in the FTS table.
# Convention: title=col0, content=col1.
TITLE_WEIGHT = 3.0
CONTENT_WEIGHT = 1.0

# Highlight markers for snippet generation.
HIGHLIGHT_OPEN = ">>>"
HIGHLIGHT_CLOSE = "<<<"


# ---------------------------------------------------------------------------
# Query processing
# ---------------------------------------------------------------------------


def sanitize_fts_query(raw: str) -> str:
    """Escape special FTS5 characters and prepare *raw* for a MATCH clause.

    - Strips FTS5 special chars from bare terms
    - Preserves quoted phrases intact
    - Returns ``""`` when the input is all whitespace / punctuation
    """
    if not raw or not raw.strip():
        return ""

    # Pull out quoted phrases first, replacing with placeholders.
    phrases: list[str] = []

    def _stash(m: re.Match[str]) -> str:
        phrases.append(m.group(0))
        return f"\x00{len(phrases) - 1}\x00"

    text = _QUOTED_PHRASE.sub(_stash, raw)

    # Strip FTS5 special chars from the remaining bare text.
    text = _FTS5_SPECIAL.sub(" ", text)

    # Restore quoted phrases.
    for idx, phrase in enumerate(phrases):
        text = text.replace(f"\x00{idx}\x00", phrase)

    # Collapse whitespace.
    result = " ".join(text.split())
    return result


def build_fts_query(raw: str) -> str:
    """Convert a natural-language query string to FTS5 query syntax.

    * Individual bare words are wrapped in double quotes.
    * Quoted phrases are preserved verbatim.
    * ``AND`` / ``OR`` / ``NOT`` operators are kept as-is.
    * ``tag:xyz`` prefixes are stripped (handled as metadata filters).
    * Returns ``""`` if nothing useful remains.
    """
    # Strip tag:xyz prefixes before sanitization (colon is a special char).
    stripped = re.sub(r"\btag:\S+", "", raw, flags=re.IGNORECASE)

    sanitized = sanitize_fts_query(stripped)
    if not sanitized:
        return ""

    # Tokenise: pull out quoted phrases and individual words.
    tokens: list[tuple[str, int, str]] = []

    # Extract quoted phrases first.
    for match in _QUOTED_PHRASE.finditer(sanitized):
        tokens.append(("phrase", match.start(), match.group(0)))

    # Extract bare words (everything outside quotes).
    no_quotes = _QUOTED_PHRASE.sub(lambda m: " " * len(m.group(0)), sanitized)
    for match in re.finditer(r"\S+", no_quotes):
        word = match.group(0)
        tokens.append(("word", match.start(), word))

    # Sort by original position to preserve order.
    tokens.sort(key=lambda t: t[1])

    parts: list[str] = []
    for kind, _pos, value in tokens:
        if kind == "phrase" or value in _BOOLEAN_OPS:
            parts.append(value)
        else:
            parts.append(f'"{value}"')

    result = " ".join(parts)
    return result


# ---------------------------------------------------------------------------
# BM25 helpers (used by sqlite_store to build SQL)
# ---------------------------------------------------------------------------


def bm25_weights() -> tuple[float, float]:
    """Return ``(title_weight, content_weight)`` for FTS5 bm25().

    The SQLite store should use these in its ``bm25(fts_table, ?, ?)`` call
    so that title matches are ranked 3x and content 1x.
    """
    return (TITLE_WEIGHT, CONTENT_WEIGHT)


def generate_snippet(
    content: str,
    query_terms: list[str],
    max_length: int = 200,
) -> str:
    """Generate a text snippet with highlight markers around matched terms.

    Returns a substring of *content* centred on the first match, with
    ``>>>term<<<`` markers around each matched term.  Falls back to the
    first *max_length* characters if no terms match.
    """
    if not content or not query_terms:
        return content[:max_length] if content else ""

    lower_content = content.lower()
    clean_terms = [t.strip('"').lower() for t in query_terms if t.strip('"')]

    # Find the position of the first matching term.
    first_pos = len(content)
    for term in clean_terms:
        pos = lower_content.find(term)
        if pos != -1 and pos < first_pos:
            first_pos = pos

    if first_pos == len(content):
        # No match found — return start of content.
        return content[:max_length]

    # Centre the window around the first match.
    half = max_length // 2
    start = max(0, first_pos - half)
    end = min(len(content), start + max_length)
    if end == len(content):
        start = max(0, end - max_length)

    window = content[start:end]

    # Insert highlight markers.
    for term in clean_terms:
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        window = pattern.sub(
            lambda m: f"{HIGHLIGHT_OPEN}{m.group(0)}{HIGHLIGHT_CLOSE}",
            window,
        )

    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(content) else ""
    return f"{prefix}{window}{suffix}"


def deduplicate_results(results: list[SearchResult]) -> list[SearchResult]:
    """Remove duplicate notes from search results, keeping the highest-scoring entry."""
    seen: dict[str, SearchResult] = {}
    for r in results:
        nid = r.note.note_id
        if nid not in seen or r.score > seen[nid].score:
            seen[nid] = r
    # Preserve the original ranking order (by score descending).
    deduped = sorted(seen.values(), key=lambda r: r.score, reverse=True)
    return deduped


# ---------------------------------------------------------------------------
# Related notes
# ---------------------------------------------------------------------------


async def find_related(
    note: Note, store: NoteStore, limit: int = 5
) -> list[SearchResult]:
    """Find notes related to *note* by title keywords and tags."""
    # Extract key terms from title.
    title_words = [
        w.lower()
        for w in re.findall(r"[A-Za-z0-9]+", note.title)
        if w.lower() not in STOP_WORDS and len(w) > 1
    ]

    # Add tags as search terms.
    all_terms = list(dict.fromkeys(title_words + [t.lower() for t in note.tags]))

    if not all_terms:
        return []

    # OR-join for broader recall.
    fts_query = " OR ".join(f'"{t}"' for t in all_terms)

    query = SearchQuery(query=fts_query, limit=limit + 1)  # +1 to account for self
    response = await store.search(query)

    results = [r for r in response.results if r.note.note_id != note.note_id]
    return results[:limit]


async def suggest_related(
    note_id: str, store: NoteStore, limit: int = 5
) -> list[SearchResult]:
    """Find notes related to the note identified by *note_id*.

    Convenience wrapper that fetches the note first, then delegates to
    :func:`find_related`.  Returns an empty list if the note is not found.
    """
    note = await store.get(note_id)
    if note is None:
        return []
    return await find_related(note, store, limit=limit)


# ---------------------------------------------------------------------------
# Stale detection
# ---------------------------------------------------------------------------


async def find_stale_notes(store: NoteStore, days: int = 30) -> list[StaleItem]:
    """Return active notes not updated in the last *days* days, most stale first.

    Reference implementation that works with any NoteStore backend.
    SQLiteNoteStore uses an optimised SQL query instead.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    all_active = await store.list_all(status=NoteStatus.ACTIVE)

    stale: list[StaleItem] = []
    for n in all_active:
        updated = n.updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        if updated < cutoff:
            delta = now - updated
            stale.append(StaleItem(note=n, days_since_update=delta.days))

    stale.sort(key=lambda s: s.days_since_update, reverse=True)
    return stale


# ---------------------------------------------------------------------------
# Daily digest
# ---------------------------------------------------------------------------


async def build_daily_digest(store: NoteStore) -> DailyDigest:
    """Build an activity summary over all notes in the store.

    Reference implementation that works with any NoteStore backend.
    SQLiteNoteStore uses optimised SQL queries instead.
    """
    all_notes = await store.list_all()

    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(hours=24)

    recent: list[Note] = []
    category_counts: Counter[str] = Counter()
    tag_counts: Counter[str] = Counter()

    for n in all_notes:
        # Recent: created or updated in last 24 hours.
        updated = n.updated_at
        created = n.created_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)

        if updated >= yesterday or created >= yesterday:
            recent.append(n)

        # Distributions.
        if n.category:
            category_counts[n.category] += 1
        for tag in n.tags:
            tag_counts[tag] += 1

    # Top 20 tags.
    top_tags = dict(tag_counts.most_common(20))

    # Stale count: active notes not updated in 30 days.
    stale_items = await find_stale_notes(store, days=30)

    return DailyDigest(
        total_notes=len(all_notes),
        recent_notes=recent,
        category_distribution=dict(category_counts),
        tag_distribution=top_tags,
        stale_count=len(stale_items),
    )
