"""Session indexing engine — parses Claude Code JSONL files into the sessions table."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from kraang.config import encode_project_path, find_project_root
from kraang.models import Session, TranscriptTurn, utcnow
from kraang.store import SQLiteStore

logger = logging.getLogger("kraang.indexer")

# Patterns to skip in user messages (noise)
_NOISE_PATTERNS = re.compile(
    r"<system-reminder>|<local-command-|<task-notification>|<command-name>|<user-prompt-submit-hook>"
)

# Types to skip entirely
_SKIP_TYPES = frozenset({"file-history-snapshot", "progress", "queue-operation"})

# Tool names that edit files
_FILE_EDIT_TOOLS = frozenset({"Edit", "Write", "NotebookEdit"})


# ---------------------------------------------------------------------------
# JSONL Parsing
# ---------------------------------------------------------------------------


def _extract_text_from_content(content: str | list[dict]) -> str:
    """Extract plain text from a message content field."""
    if isinstance(content, str):
        return content
    texts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            texts.append(block.get("text", ""))
    return "\n".join(texts)


def _is_noise_message(text: str) -> bool:
    """Check if a user message is noise (system commands, tags, etc.)."""
    return bool(_NOISE_PATTERNS.search(text))


def _is_tool_result(content: str | list[dict]) -> bool:
    """Check if content is a tool result."""
    if isinstance(content, list):
        return any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
    return False


def _extract_tool_calls(content: str | list[dict]) -> tuple[list[str], list[str]]:
    """Extract tool names and edited file paths from assistant content.

    Returns (tool_names, file_paths).
    """
    tool_names: list[str] = []
    file_paths: list[str] = []

    if not isinstance(content, list):
        return tool_names, file_paths

    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "tool_use":
            continue

        name = block.get("name", "")
        if name:
            tool_names.append(name)

        inp = block.get("input", {})
        if not isinstance(inp, dict):
            continue

        # Extract file paths from common tool inputs
        if name in _FILE_EDIT_TOOLS:
            fp = inp.get("file_path") or inp.get("notebook_path", "")
            if fp:
                file_paths.append(fp)
        elif name == "Read":
            pass  # Don't count reads as edits
        elif name == "Bash":
            pass  # Commands, not file edits

    return tool_names, file_paths


def parse_jsonl(jsonl_path: Path, project_path: str = "") -> Session | None:
    """Parse a Claude Code JSONL session file into a Session object.

    Returns None if the file is empty or unparseable.
    """
    if not jsonl_path.exists():
        return None

    stat = jsonl_path.stat()
    if stat.st_size == 0:
        return None

    session_id = jsonl_path.stem
    slug = ""
    git_branch = ""
    model = ""
    cwd = project_path

    timestamps: list[datetime] = []
    user_texts: list[str] = []
    assistant_texts: list[str] = []
    all_tool_names: list[str] = []
    all_file_paths: list[str] = []
    user_turn_count = 0
    assistant_turn_count = 0
    summary = ""

    with open(jsonl_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type", "")

            # Skip noise types
            if entry_type in _SKIP_TYPES:
                continue

            # Extract metadata from entries
            if not slug and entry.get("slug"):
                slug = entry["slug"]
            if not git_branch and entry.get("gitBranch"):
                git_branch = entry["gitBranch"]
            if not cwd and entry.get("cwd"):
                cwd = entry["cwd"]

            # Parse timestamp
            ts_str = entry.get("timestamp", "")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    timestamps.append(ts)
                except (ValueError, TypeError):
                    pass

            message = entry.get("message", {})
            if not isinstance(message, dict):
                continue

            role = message.get("role", "")
            content = message.get("content", "")

            if entry_type == "user" and role == "user":
                # Skip tool results
                if _is_tool_result(content):
                    continue

                text = _extract_text_from_content(content)
                if not text or _is_noise_message(text):
                    continue

                # Skip meta messages
                if entry.get("isMeta"):
                    continue

                user_texts.append(text)
                user_turn_count += 1

                # First real user message becomes the summary
                if not summary:
                    summary = text[:500]

            elif entry_type == "assistant" and role == "assistant":
                # Extract text (skip thinking blocks)
                text = _extract_text_from_content(content)
                if text:
                    assistant_texts.append(text)
                    assistant_turn_count += 1

                # Extract tool calls
                tools, files = _extract_tool_calls(content)
                all_tool_names.extend(tools)
                all_file_paths.extend(files)

                # Try to get model from assistant entry
                if not model and entry.get("model"):
                    model = entry["model"]

    # If no meaningful content, skip
    if not user_texts and not assistant_texts:
        return None

    # Compute timestamps
    if timestamps:
        started_at = min(timestamps)
        ended_at = max(timestamps)
        duration_s = int((ended_at - started_at).total_seconds())
    else:
        now = utcnow()
        started_at = now
        ended_at = now
        duration_s = 0

    # Deduplicate tools and files
    unique_tools = list(dict.fromkeys(all_tool_names))
    unique_files = list(dict.fromkeys(all_file_paths))

    return Session(
        session_id=session_id,
        slug=slug,
        project_path=cwd or project_path,
        git_branch=git_branch,
        model=model,
        started_at=started_at,
        ended_at=ended_at,
        duration_s=duration_s,
        user_turn_count=user_turn_count,
        assistant_turn_count=assistant_turn_count,
        summary=summary,
        user_text="\n".join(user_texts),
        assistant_text="\n".join(assistant_texts),
        tools_used=unique_tools,
        files_edited=unique_files,
        source_mtime=stat.st_mtime,
        source_size=stat.st_size,
        indexed_at=utcnow(),
    )


def _parse_subagent_text(subagent_path: Path) -> tuple[str, str]:
    """Extract user and assistant text from a subagent JSONL file.

    Returns (user_text, assistant_text).
    """
    user_texts: list[str] = []
    assistant_texts: list[str] = []

    if not subagent_path.exists():
        return "", ""

    with open(subagent_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type", "")
            if entry_type in _SKIP_TYPES:
                continue

            message = entry.get("message", {})
            if not isinstance(message, dict):
                continue

            role = message.get("role", "")
            content = message.get("content", "")

            if role == "user" and not _is_tool_result(content):
                text = _extract_text_from_content(content)
                if text and not _is_noise_message(text) and not entry.get("isMeta"):
                    user_texts.append(text)
            elif role == "assistant":
                text = _extract_text_from_content(content)
                if text:
                    assistant_texts.append(text)

    return "\n".join(user_texts), "\n".join(assistant_texts)


# ---------------------------------------------------------------------------
# Transcript reading (for read_session tool)
# ---------------------------------------------------------------------------


def read_transcript(jsonl_path: Path) -> list[TranscriptTurn]:
    """Read a JSONL file and produce a clean conversation transcript."""
    if not jsonl_path.exists():
        return []

    turns: list[TranscriptTurn] = []

    with open(jsonl_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type", "")
            if entry_type in _SKIP_TYPES:
                continue

            message = entry.get("message", {})
            if not isinstance(message, dict):
                continue

            role = message.get("role", "")
            content = message.get("content", "")
            timestamp = entry.get("timestamp", "")

            if entry_type == "user" and role == "user":
                if _is_tool_result(content):
                    continue
                text = _extract_text_from_content(content)
                if not text or _is_noise_message(text) or entry.get("isMeta"):
                    continue

                turns.append(
                    TranscriptTurn(
                        role="User",
                        timestamp=timestamp,
                        text=text,
                    )
                )

            elif entry_type == "assistant" and role == "assistant":
                text = _extract_text_from_content(content)
                tools, _ = _extract_tool_calls(content)

                # Format tool calls as bullet points
                tool_summaries: list[str] = []
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            name = block.get("name", "")
                            inp = block.get("input", {})
                            if isinstance(inp, dict):
                                summary = _summarize_tool_call(name, inp)
                                tool_summaries.append(summary)

                if text or tool_summaries:
                    turns.append(
                        TranscriptTurn(
                            role="Agent",
                            timestamp=timestamp,
                            text=text,
                            tool_calls=tool_summaries,
                        )
                    )

    return turns


def _summarize_tool_call(name: str, inp: dict[str, object]) -> str:
    """Create a one-line summary of a tool call."""
    if name == "Read":
        return f"Read {inp.get('file_path', '?')}"
    elif name == "Write":
        return f"Write {inp.get('file_path', '?')}"
    elif name == "Edit":
        return f"Edit {inp.get('file_path', '?')}"
    elif name == "Glob":
        return f"Glob {inp.get('pattern', '?')}"
    elif name == "Grep":
        return f"Grep {inp.get('pattern', '?')}"
    elif name == "Bash":
        cmd = str(inp.get("command", "?"))
        if len(cmd) > 80:
            cmd = cmd[:77] + "..."
        return f"Bash: {cmd}"
    elif name == "Task":
        return f"Task: {inp.get('description', '?')}"
    elif name == "NotebookEdit":
        return f"NotebookEdit {inp.get('notebook_path', '?')}"
    else:
        return f"{name}()"


# ---------------------------------------------------------------------------
# Index orchestration
# ---------------------------------------------------------------------------


def find_session_files(project_path: str | Path | None = None) -> list[Path]:
    """Find all JSONL session files for the given project."""
    root = Path(project_path) if project_path else find_project_root()
    root = root.resolve()
    encoded = encode_project_path(str(root))
    sessions_dir = Path.home() / ".claude" / "projects" / encoded

    if not sessions_dir.exists():
        return []

    return sorted(sessions_dir.glob("*.jsonl"))


async def index_sessions(
    store: SQLiteStore,
    project_path: str | Path | None = None,
    single_file: Path | None = None,
) -> int:
    """Index session files into the store. Returns number of sessions indexed.

    If single_file is provided, only that file is indexed.
    Otherwise, all session files for the project are scanned incrementally.
    """
    root = Path(project_path) if project_path else find_project_root()
    root = root.resolve()

    files = [single_file] if single_file else find_session_files(root)

    indexed = 0
    for jsonl_path in files:
        session_id = jsonl_path.stem
        stat = jsonl_path.stat()

        # Check if reindexing is needed
        if not await store.needs_reindex(session_id, stat.st_mtime, stat.st_size):
            continue

        session = parse_jsonl(jsonl_path, project_path=str(root))
        if session is None:
            continue

        # Check for subagent files
        session_dir = jsonl_path.parent / session_id
        subagents_dir = session_dir / "subagents"
        if subagents_dir.exists():
            for subagent_file in subagents_dir.glob("agent-*.jsonl"):
                sub_user, sub_assistant = _parse_subagent_text(subagent_file)
                if sub_user:
                    session.user_text += "\n" + sub_user
                if sub_assistant:
                    session.assistant_text += "\n" + sub_assistant

        await store.upsert_session(session)
        indexed += 1
        logger.debug("Indexed session %s (%s)", session_id[:8], session.slug or "no slug")

    return indexed
