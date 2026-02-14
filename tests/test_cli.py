"""Tests for kraang.cli — CLI commands via typer CliRunner."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from kraang.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# kraang init
# ---------------------------------------------------------------------------


class TestInit:
    def test_creates_kraang_dir(self, tmp_path):
        result = runner.invoke(app, ["init", str(tmp_path)])
        assert result.exit_code == 0
        assert (tmp_path / ".kraang").is_dir()
        assert (tmp_path / ".kraang" / "kraang.db").exists()

    def test_creates_mcp_json(self, tmp_path):
        runner.invoke(app, ["init", str(tmp_path)])
        mcp_json = tmp_path / ".mcp.json"
        assert mcp_json.exists()
        config = json.loads(mcp_json.read_text())
        assert "kraang" in config["mcpServers"]

    def test_creates_hook(self, tmp_path):
        runner.invoke(app, ["init", str(tmp_path)])
        settings = tmp_path / ".claude" / "settings.json"
        assert settings.exists()
        config = json.loads(settings.read_text())
        assert "SessionEnd" in config["hooks"]

    def test_updates_gitignore(self, tmp_path):
        # Create existing gitignore
        (tmp_path / ".gitignore").write_text("*.pyc\n")
        runner.invoke(app, ["init", str(tmp_path)])
        content = (tmp_path / ".gitignore").read_text()
        assert ".kraang/" in content
        assert "*.pyc" in content

    def test_idempotent(self, tmp_path):
        runner.invoke(app, ["init", str(tmp_path)])
        result = runner.invoke(app, ["init", str(tmp_path)])
        assert result.exit_code == 0

    def test_merges_existing_mcp_json(self, tmp_path):
        existing = {"mcpServers": {"other": {"command": "other"}}}
        (tmp_path / ".mcp.json").write_text(json.dumps(existing))
        runner.invoke(app, ["init", str(tmp_path)])
        config = json.loads((tmp_path / ".mcp.json").read_text())
        assert "other" in config["mcpServers"]
        assert "kraang" in config["mcpServers"]

    def test_merges_existing_session_end_hooks(self, tmp_path):
        """Existing SessionEnd with other hooks; kraang hook gets appended."""
        other_hook = {
            "hooks": {
                "SessionEnd": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "echo done",
                                "timeout": 30,
                            }
                        ]
                    }
                ]
            }
        }
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text(json.dumps(other_hook))

        runner.invoke(app, ["init", str(tmp_path)])

        config = json.loads((claude_dir / "settings.json").read_text())
        entries = config["hooks"]["SessionEnd"]
        assert len(entries) == 2
        # Original hook preserved
        assert entries[0]["hooks"][0]["command"] == "echo done"
        # Kraang hook appended
        commands = [h["command"] for entry in entries for h in entry["hooks"]]
        assert "uvx kraang index --from-hook" in commands

    def test_init_hook_idempotent(self, tmp_path):
        """Running init twice doesn't duplicate the kraang hook."""
        runner.invoke(app, ["init", str(tmp_path)])
        runner.invoke(app, ["init", str(tmp_path)])

        settings = tmp_path / ".claude" / "settings.json"
        config = json.loads(settings.read_text())
        entries = config["hooks"]["SessionEnd"]
        kraang_commands = [
            h["command"]
            for entry in entries
            for h in entry.get("hooks", [])
            if h.get("command") == "uvx kraang index --from-hook"
        ]
        assert len(kraang_commands) == 1

    def test_backup_corrupt_mcp_json(self, tmp_path):
        """Corrupt .mcp.json is backed up before being overwritten."""
        mcp_path = tmp_path / ".mcp.json"
        mcp_path.write_text("{invalid json!!")

        result = runner.invoke(app, ["init", str(tmp_path)])
        assert result.exit_code == 0

        # New valid config was written
        config = json.loads(mcp_path.read_text())
        assert "kraang" in config["mcpServers"]

        # Backup file exists with original corrupt content
        backups = list(tmp_path.glob(".mcp.json.*.bak"))
        assert len(backups) == 1
        assert backups[0].read_text() == "{invalid json!!"

    def test_backup_corrupt_settings_json(self, tmp_path):
        """Corrupt settings.json is backed up before being overwritten."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings_path = claude_dir / "settings.json"
        settings_path.write_text("not valid json {{{")

        result = runner.invoke(app, ["init", str(tmp_path)])
        assert result.exit_code == 0

        # New valid config was written
        config = json.loads(settings_path.read_text())
        assert "SessionEnd" in config["hooks"]

        # Backup file exists with original corrupt content
        backups = list(claude_dir.glob("settings.json.*.bak"))
        assert len(backups) == 1
        assert backups[0].read_text() == "not valid json {{{"


# ---------------------------------------------------------------------------
# kraang notes
# ---------------------------------------------------------------------------


class TestNotes:
    def test_empty_db(self, tmp_path):
        runner.invoke(app, ["init", str(tmp_path)])
        db = str(tmp_path / ".kraang" / "kraang.db")
        result = runner.invoke(app, ["notes"], env={"KRAANG_DB_PATH": db})
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# kraang status
# ---------------------------------------------------------------------------


class TestStatusCmd:
    def test_status(self, tmp_path):
        runner.invoke(app, ["init", str(tmp_path)])
        db = str(tmp_path / ".kraang" / "kraang.db")
        result = runner.invoke(app, ["status"], env={"KRAANG_DB_PATH": db})
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# kraang sessions
# ---------------------------------------------------------------------------


class TestSessionsCmd:
    def test_sessions_empty_db(self, tmp_path):
        runner.invoke(app, ["init", str(tmp_path)])
        db = str(tmp_path / ".kraang" / "kraang.db")
        result = runner.invoke(app, ["sessions"], env={"KRAANG_DB_PATH": db})
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# kraang search
# ---------------------------------------------------------------------------


class TestSearchCmd:
    def test_search_basic(self, tmp_path):
        runner.invoke(app, ["init", str(tmp_path)])
        db = str(tmp_path / ".kraang" / "kraang.db")
        result = runner.invoke(app, ["search", "test"], env={"KRAANG_DB_PATH": db})
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# kraang index
# ---------------------------------------------------------------------------


class TestIndexCmd:
    def test_index_basic(self, tmp_path):
        runner.invoke(app, ["init", str(tmp_path)])
        db = str(tmp_path / ".kraang" / "kraang.db")
        result = runner.invoke(app, ["index", str(tmp_path)], env={"KRAANG_DB_PATH": db})
        assert result.exit_code == 0
