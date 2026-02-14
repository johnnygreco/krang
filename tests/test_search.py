"""Tests for kraang.search — query processing."""

from __future__ import annotations

from kraang.search import (
    build_fts_query,
    sanitize_fts_query,
)

# ---------------------------------------------------------------------------
# Query processing
# ---------------------------------------------------------------------------


class TestSanitizeFtsQuery:
    def test_basic(self):
        assert sanitize_fts_query("hello world") == "hello world"

    def test_special_chars(self):
        result = sanitize_fts_query("hello* (world) [test] {foo} ^bar col:val")
        assert "*" not in result
        assert "(" not in result
        assert ")" not in result
        assert "hello" in result
        assert "world" in result

    def test_quoted_phrases(self):
        result = sanitize_fts_query('find "exact match" here')
        assert '"exact match"' in result
        assert "find" in result

    def test_empty_input(self):
        assert sanitize_fts_query("") == ""
        assert sanitize_fts_query("   ") == ""
        assert sanitize_fts_query("***") == ""

    def test_unbalanced_quotes(self):
        result = sanitize_fts_query('foo "bar')
        assert '"' not in result

    def test_even_quotes_preserved(self):
        result = sanitize_fts_query('"foo" "bar"')
        assert '"foo"' in result
        assert '"bar"' in result


class TestBuildFtsQuery:
    def test_basic(self):
        result = build_fts_query("python async")
        assert '"python"' in result
        assert '"async"' in result

    def test_preserves_quoted_phrases(self):
        result = build_fts_query('"machine learning"')
        assert '"machine learning"' in result

    def test_preserves_boolean_operators(self):
        result = build_fts_query("python OR async")
        assert "OR" in result
        assert '"python"' in result

    def test_and_operator(self):
        result = build_fts_query("python AND async")
        assert "AND" in result

    def test_not_operator(self):
        result = build_fts_query("python NOT java")
        assert "NOT" in result

    def test_strips_tag_prefix(self):
        result = build_fts_query("python tag:web")
        assert '"python"' in result
        assert "web" not in result

    def test_unbalanced_quotes_safe(self):
        result = build_fts_query('foo "bar')
        assert result != ""

    def test_empty(self):
        assert build_fts_query("") == ""
