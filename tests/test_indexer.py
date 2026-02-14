"""Tests for kraang.indexer — JSONL parsing, session extraction, transcript reading."""

from __future__ import annotations

from kraang.indexer import parse_jsonl, read_transcript

# ---------------------------------------------------------------------------
# parse_jsonl
# ---------------------------------------------------------------------------


class TestParseJsonl:
    def test_parse_sample_session(self, sample_jsonl_file):
        session = parse_jsonl(sample_jsonl_file, project_path="/test/project")
        assert session is not None
        assert session.session_id == "test-session-001"
        assert session.git_branch == "main"
        assert session.project_path == "/test/project"

    def test_extracts_slug(self, sample_jsonl_file):
        session = parse_jsonl(sample_jsonl_file)
        assert session is not None
        assert session.slug == "test-gathering-dove"

    def test_extracts_user_text(self, sample_jsonl_file):
        session = parse_jsonl(sample_jsonl_file)
        assert session is not None
        assert "FTS5 search" in session.user_text
        assert "fixed it" in session.user_text

    def test_extracts_assistant_text(self, sample_jsonl_file):
        session = parse_jsonl(sample_jsonl_file)
        assert session is not None
        assert "FTS5 configuration" in session.assistant_text
        assert "porter stemming" in session.assistant_text

    def test_summary_is_first_user_message(self, sample_jsonl_file):
        session = parse_jsonl(sample_jsonl_file)
        assert session is not None
        assert session.summary.startswith("How do I configure FTS5")

    def test_extracts_tool_names(self, sample_jsonl_file):
        session = parse_jsonl(sample_jsonl_file)
        assert session is not None
        assert "Read" in session.tools_used

    def test_turn_counts(self, sample_jsonl_file):
        session = parse_jsonl(sample_jsonl_file)
        assert session is not None
        assert session.user_turn_count == 2  # 2 real user messages
        assert session.assistant_turn_count == 2  # 2 assistant messages with text

    def test_duration_calculated(self, sample_jsonl_file):
        session = parse_jsonl(sample_jsonl_file)
        assert session is not None
        assert session.duration_s > 0  # 3 minutes

    def test_source_metadata(self, sample_jsonl_file):
        session = parse_jsonl(sample_jsonl_file)
        assert session is not None
        assert session.source_mtime > 0
        assert session.source_size > 0

    def test_filters_noise(self, sample_jsonl_with_noise):
        session = parse_jsonl(sample_jsonl_with_noise)
        assert session is not None
        # Should only capture the real user question, not noise
        assert "actual user question" in session.user_text
        assert "local-command" not in session.user_text
        assert "system-reminder" not in session.user_text

    def test_nonexistent_file(self, tmp_path):
        result = parse_jsonl(tmp_path / "nonexistent.jsonl")
        assert result is None

    def test_empty_file(self, tmp_path):
        empty_file = tmp_path / "empty.jsonl"
        empty_file.write_text("")
        result = parse_jsonl(empty_file)
        assert result is None

    def test_skips_tool_results(self, sample_jsonl_file):
        session = parse_jsonl(sample_jsonl_file)
        assert session is not None
        # tool_result content should not be in user_text
        assert "file content here" not in session.user_text


# ---------------------------------------------------------------------------
# read_transcript
# ---------------------------------------------------------------------------


class TestReadTranscript:
    def test_basic_transcript(self, sample_jsonl_file):
        turns = read_transcript(sample_jsonl_file)
        assert len(turns) > 0

    def test_user_turns(self, sample_jsonl_file):
        turns = read_transcript(sample_jsonl_file)
        user_turns = [t for t in turns if t.role == "User"]
        assert len(user_turns) >= 2

    def test_agent_turns(self, sample_jsonl_file):
        turns = read_transcript(sample_jsonl_file)
        agent_turns = [t for t in turns if t.role == "Agent"]
        assert len(agent_turns) >= 1

    def test_tool_calls_summarized(self, sample_jsonl_file):
        turns = read_transcript(sample_jsonl_file)
        agent_turns = [t for t in turns if t.role == "Agent"]
        # First agent turn should have a Read tool call
        tool_turn = next((t for t in agent_turns if t.tool_calls), None)
        assert tool_turn is not None
        assert any("Read" in tc for tc in tool_turn.tool_calls)

    def test_filters_noise(self, sample_jsonl_with_noise):
        turns = read_transcript(sample_jsonl_with_noise)
        user_turns = [t for t in turns if t.role == "User"]
        assert len(user_turns) == 1
        assert "actual user question" in user_turns[0].text

    def test_nonexistent_file(self, tmp_path):
        turns = read_transcript(tmp_path / "nonexistent.jsonl")
        assert turns == []

    def test_timestamps_preserved(self, sample_jsonl_file):
        turns = read_transcript(sample_jsonl_file)
        for turn in turns:
            assert turn.timestamp  # All turns should have timestamps
