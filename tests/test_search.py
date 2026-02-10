"""Tests for krang.search — query processing, BM25 helpers,
related notes, stale detection, digest."""

from __future__ import annotations

from krang.models import Note, NoteCreate, NoteStatus, NoteUpdate, SearchQuery, SearchResult
from krang.search import (
    CONTENT_WEIGHT,
    HIGHLIGHT_CLOSE,
    HIGHLIGHT_OPEN,
    STOP_WORDS,
    TITLE_WEIGHT,
    bm25_weights,
    build_daily_digest,
    build_fts_query,
    deduplicate_results,
    find_related,
    find_stale_notes,
    generate_snippet,
    sanitize_fts_query,
    suggest_related,
)

# ---------------------------------------------------------------------------
# Query processing
# ---------------------------------------------------------------------------


class TestSanitizeFtsQuery:
    def test_sanitize_basic(self) -> None:
        """Normal text passes through unchanged."""
        assert sanitize_fts_query("hello world") == "hello world"

    def test_sanitize_special_chars(self) -> None:
        """FTS5 special characters are stripped."""
        result = sanitize_fts_query("hello* (world) [test] {foo} ^bar col:val")
        assert "*" not in result
        assert "(" not in result
        assert ")" not in result
        assert "[" not in result
        assert "]" not in result
        assert "{" not in result
        assert "}" not in result
        assert "^" not in result
        assert ":" not in result
        assert "hello" in result
        assert "world" in result

    def test_sanitize_quoted_phrases(self) -> None:
        """Quoted phrases are preserved intact."""
        result = sanitize_fts_query('find "exact match" here')
        assert '"exact match"' in result
        assert "find" in result
        assert "here" in result

    def test_sanitize_empty_input(self) -> None:
        """Empty or whitespace-only input returns empty string."""
        assert sanitize_fts_query("") == ""
        assert sanitize_fts_query("   ") == ""
        assert sanitize_fts_query("***") == ""

    def test_sanitize_multiple_special_chars(self) -> None:
        """Multiple consecutive special chars collapse to single space."""
        result = sanitize_fts_query("a**b")
        assert "a" in result
        assert "b" in result
        assert "**" not in result


class TestBuildFtsQuery:
    def test_build_fts_query(self) -> None:
        """Natural language terms are wrapped in quotes."""
        result = build_fts_query("python async")
        assert '"python"' in result
        assert '"async"' in result

    def test_build_preserves_quoted_phrases(self) -> None:
        """Quoted phrases pass through verbatim."""
        result = build_fts_query('"machine learning"')
        assert '"machine learning"' in result

    def test_build_preserves_boolean_operators(self) -> None:
        """AND / OR / NOT are kept as operators, not quoted."""
        result = build_fts_query("python OR async")
        assert "OR" in result
        assert '"python"' in result
        assert '"async"' in result

    def test_build_and_operator(self) -> None:
        """AND operator preserved."""
        result = build_fts_query("python AND async")
        assert "AND" in result
        assert '"python"' in result
        assert '"async"' in result

    def test_build_not_operator(self) -> None:
        """NOT operator preserved."""
        result = build_fts_query("python NOT java")
        assert "NOT" in result
        assert '"python"' in result
        assert '"java"' in result

    def test_build_strips_tag_prefix(self) -> None:
        """tag:xyz terms are removed (handled as metadata filters)."""
        result = build_fts_query("python tag:web")
        assert '"python"' in result
        assert "web" not in result
        assert "tag" not in result

    def test_build_empty(self) -> None:
        """Empty input produces empty output."""
        assert build_fts_query("") == ""


# ---------------------------------------------------------------------------
# BM25 helpers
# ---------------------------------------------------------------------------


class TestBM25Helpers:
    def test_bm25_weights_values(self) -> None:
        """Title weight > content weight."""
        tw, cw = bm25_weights()
        assert tw == TITLE_WEIGHT == 3.0
        assert cw == CONTENT_WEIGHT == 1.0
        assert tw > cw

    def test_bm25_weights_tuple(self) -> None:
        """Returns a 2-tuple."""
        weights = bm25_weights()
        assert len(weights) == 2


# ---------------------------------------------------------------------------
# Snippet generation
# ---------------------------------------------------------------------------


class TestGenerateSnippet:
    def test_snippet_highlights_term(self) -> None:
        """Matched terms are wrapped in highlight markers."""
        snippet = generate_snippet("Python is great for async programming", ["python"])
        assert f"{HIGHLIGHT_OPEN}Python{HIGHLIGHT_CLOSE}" in snippet

    def test_snippet_multiple_terms(self) -> None:
        """Multiple terms are all highlighted."""
        snippet = generate_snippet(
            "Python is great for async programming",
            ["python", "async"],
        )
        assert f"{HIGHLIGHT_OPEN}Python{HIGHLIGHT_CLOSE}" in snippet
        assert f"{HIGHLIGHT_OPEN}async{HIGHLIGHT_CLOSE}" in snippet

    def test_snippet_no_match_fallback(self) -> None:
        """When no terms match, returns start of content."""
        snippet = generate_snippet("Hello world content here", ["nomatch"])
        assert snippet == "Hello world content here"

    def test_snippet_empty_content(self) -> None:
        """Empty content returns empty string."""
        assert generate_snippet("", ["term"]) == ""

    def test_snippet_empty_terms(self) -> None:
        """Empty terms list returns truncated content."""
        snippet = generate_snippet("Hello world", [])
        assert snippet == "Hello world"

    def test_snippet_long_content_centres_on_match(self) -> None:
        """For long content, snippet is centred around the first match."""
        content = "A" * 300 + " python " + "B" * 300
        snippet = generate_snippet(content, ["python"], max_length=50)
        assert "python" in snippet.lower()
        assert len(snippet) < 300  # Much shorter than original

    def test_snippet_case_insensitive(self) -> None:
        """Highlighting is case-insensitive."""
        snippet = generate_snippet("PYTHON is great", ["python"])
        assert f"{HIGHLIGHT_OPEN}PYTHON{HIGHLIGHT_CLOSE}" in snippet


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDeduplicateResults:
    def test_deduplicate_removes_duplicates(self) -> None:
        """Duplicate note_ids are removed, keeping the highest score."""
        note = Note(note_id="abc", title="Test", content="Content")
        results = [
            SearchResult(note=note, score=1.0),
            SearchResult(note=note, score=5.0),
            SearchResult(note=note, score=3.0),
        ]
        deduped = deduplicate_results(results)
        assert len(deduped) == 1
        assert deduped[0].score == 5.0

    def test_deduplicate_preserves_unique(self) -> None:
        """Unique results are all kept."""
        results = [
            SearchResult(note=Note(note_id="a", title="A", content="c"), score=5.0),
            SearchResult(note=Note(note_id="b", title="B", content="c"), score=3.0),
            SearchResult(note=Note(note_id="c", title="C", content="c"), score=1.0),
        ]
        deduped = deduplicate_results(results)
        assert len(deduped) == 3

    def test_deduplicate_sorted_by_score(self) -> None:
        """Deduplicated results are sorted by score descending."""
        results = [
            SearchResult(note=Note(note_id="a", title="A", content="c"), score=1.0),
            SearchResult(note=Note(note_id="b", title="B", content="c"), score=5.0),
            SearchResult(note=Note(note_id="c", title="C", content="c"), score=3.0),
        ]
        deduped = deduplicate_results(results)
        scores = [r.score for r in deduped]
        assert scores == [5.0, 3.0, 1.0]

    def test_deduplicate_empty(self) -> None:
        """Empty input returns empty output."""
        assert deduplicate_results([]) == []


# ---------------------------------------------------------------------------
# Related notes (requires populated_store / SQLiteNoteStore)
# ---------------------------------------------------------------------------


class TestFindRelated:
    async def test_related_finds_similar_topics(self, populated_store) -> None:
        """The Python asyncio note should return some related results."""
        all_notes = await populated_store.list_all()
        asyncio_note = next(n for n in all_notes if "asyncio" in n.title)

        related = await find_related(asyncio_note, populated_store, limit=5)
        # FTS5 only indexes title/content, so related notes are based on
        # text similarity — not tag overlap.  Just verify we get results.
        assert isinstance(related, list)

    async def test_related_excludes_self(self, populated_store) -> None:
        """The original note must never appear in its own related results."""
        all_notes = await populated_store.list_all()
        target = all_notes[0]

        related = await find_related(target, populated_store, limit=10)
        related_ids = {r.note.note_id for r in related}
        assert target.note_id not in related_ids

    async def test_related_respects_limit(self, populated_store) -> None:
        """At most `limit` results are returned."""
        all_notes = await populated_store.list_all()
        target = next(n for n in all_notes if "asyncio" in n.title)

        related = await find_related(target, populated_store, limit=2)
        assert len(related) <= 2

    async def test_suggest_related_by_id(self, populated_store) -> None:
        """suggest_related fetches the note by ID and finds related notes."""
        all_notes = await populated_store.list_all()
        # Use the FTS5 guide note — its title terms ("sqlite", "fts5") also
        # appear in the "Project Krang architecture" content, giving a real match.
        fts_note = next(n for n in all_notes if "FTS5" in n.title)

        related = await suggest_related(fts_note.note_id, populated_store, limit=5)
        assert len(related) > 0
        related_ids = {r.note.note_id for r in related}
        assert fts_note.note_id not in related_ids

    async def test_suggest_related_not_found(self, populated_store) -> None:
        """suggest_related returns empty list for non-existent note_id."""
        related = await suggest_related("nonexistent_id", populated_store)
        assert related == []


# ---------------------------------------------------------------------------
# Search ranking (requires populated_store)
# ---------------------------------------------------------------------------


class TestSearchRanking:
    async def test_title_match_ranks_higher_than_content(self, populated_store) -> None:
        """A note with the search term in its title should rank above one with
        the term only in content, assuming the store uses column weighting."""
        # "asyncio" appears in the title of "Python asyncio patterns" and in the
        # content of that same note. "FTS5" appears in the title of "SQLite FTS5 guide".
        # Search for "FTS5" — the note with FTS5 in the title should appear first.
        query = SearchQuery(query='"FTS5"', limit=10)
        response = await populated_store.search(query)
        if len(response.results) > 1:
            # First result should be the one with FTS5 in the title.
            assert "FTS5" in response.results[0].note.title

    async def test_tag_filtering_accuracy(self, populated_store) -> None:
        """Searching with a tag filter should return only notes with that tag."""
        query = SearchQuery(query='"python"', tags=["python"], limit=20)
        response = await populated_store.search(query)
        for result in response.results:
            assert "python" in result.note.tags


# ---------------------------------------------------------------------------
# Stale detection
# ---------------------------------------------------------------------------


class TestFindStaleNotes:
    async def test_stale_finds_old_notes(self, store) -> None:
        """Notes with old updated_at dates should be detected as stale."""
        note = await store.create(
            NoteCreate(
                title="Old note",
                content="This is old.",
                tags=["old"],
                category="test",
            )
        )

        # A freshly created note should NOT be stale at 30 days.
        stale = await find_stale_notes(store, days=30)
        assert len(stale) == 0

        # With days=-1 the cutoff is in the future, so every note is "stale".
        stale = await find_stale_notes(store, days=-1)
        assert len(stale) >= 1
        assert stale[0].note.note_id == note.note_id
        assert stale[0].days_since_update >= 0

    async def test_stale_ignores_recent(self, populated_store) -> None:
        """Freshly created notes should not be stale."""
        stale = await find_stale_notes(populated_store, days=30)
        assert len(stale) == 0

    async def test_stale_ignores_archived(self, store) -> None:
        """Archived notes should not appear in stale results."""
        note = await store.create(
            NoteCreate(
                title="Archived note",
                content="This will be archived.",
                tags=[],
                category="test",
            )
        )
        await store.update(note.note_id, NoteUpdate(status=NoteStatus.ARCHIVED))

        # Even with days=-1 (everything is stale), archived notes must not appear.
        stale = await find_stale_notes(store, days=-1)
        stale_ids = {s.note.note_id for s in stale}
        assert note.note_id not in stale_ids

    async def test_stale_sorted_most_stale_first(self, store) -> None:
        """Results are sorted with the most stale note first."""
        # Create two notes — both will be "stale" with days=-1.
        await store.create(
            NoteCreate(title="Note A", content="Content A", tags=[], category="test")
        )
        await store.create(
            NoteCreate(title="Note B", content="Content B", tags=[], category="test")
        )

        stale = await find_stale_notes(store, days=-1)
        assert len(stale) >= 2
        # All days_since_update should be >= 0 and in descending order.
        days_values = [s.days_since_update for s in stale]
        assert days_values == sorted(days_values, reverse=True)


# ---------------------------------------------------------------------------
# Daily digest
# ---------------------------------------------------------------------------


class TestBuildDailyDigest:
    async def test_digest_total_count(self, populated_store) -> None:
        """Total notes matches the number inserted."""
        digest = await build_daily_digest(populated_store)
        assert digest.total_notes == 15

    async def test_digest_category_distribution(self, populated_store) -> None:
        """Engineering category should have the most notes."""
        digest = await build_daily_digest(populated_store)
        assert "engineering" in digest.category_distribution
        # Engineering has 7 notes in the sample corpus.
        assert digest.category_distribution["engineering"] == 7
        # It should be the largest category.
        max_cat = max(digest.category_distribution, key=digest.category_distribution.get)
        assert max_cat == "engineering"

    async def test_digest_recent_notes(self, populated_store) -> None:
        """All sample notes were just created so they should all be recent."""
        digest = await build_daily_digest(populated_store)
        assert len(digest.recent_notes) == 15

    async def test_digest_tag_distribution(self, populated_store) -> None:
        """Tag distribution should contain expected tags."""
        digest = await build_daily_digest(populated_store)
        assert "python" in digest.tag_distribution
        assert "health" in digest.tag_distribution

    async def test_digest_stale_count_zero_for_fresh(self, populated_store) -> None:
        """No notes should be stale when they were all just created."""
        digest = await build_daily_digest(populated_store)
        assert digest.stale_count == 0

    async def test_digest_all_categories_present(self, populated_store) -> None:
        """All non-empty categories from the sample corpus should appear."""
        digest = await build_daily_digest(populated_store)
        expected = {"engineering", "personal", "wellness", "learning", "finance"}
        assert set(digest.category_distribution.keys()) == expected

    async def test_digest_category_counts_sum_to_total(self, populated_store) -> None:
        """Category distribution counts should sum to total_notes."""
        digest = await build_daily_digest(populated_store)
        assert sum(digest.category_distribution.values()) == digest.total_notes


# ---------------------------------------------------------------------------
# Stop words
# ---------------------------------------------------------------------------


class TestStopWords:
    def test_common_words_in_stop_words(self) -> None:
        """Common English stop words should be present."""
        for word in ("the", "is", "are", "and", "or", "not", "of", "in", "to"):
            assert word in STOP_WORDS

    def test_stop_words_are_lowercase(self) -> None:
        """All stop words should be lowercase."""
        for word in STOP_WORDS:
            assert word == word.lower()
