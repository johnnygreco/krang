<table>
  <tr>
    <td><img src="assets/kraang.jpeg" alt="Kraang" width="350"></td>
    <td><h1>Kraang</h1><b>A second brain for you and your agents.</b></td>
  </tr>
</table>

Kraang is an MCP (Model Context Protocol) server that gives AI assistants persistent memory backed by SQLite with FTS5 full-text search. It stores, searches, and manages knowledge notes so your agent can recall what matters.

## Quick Start

Add to your MCP client configuration (e.g. Claude Code, Claude Desktop):

```json
{
  "mcpServers": {
    "kraang": {
      "command": "uvx",
      "args": ["kraang"],
      "env": { "KRAANG_DB_PATH": "~/.kraang/brain.db" }
    }
  }
}
```

Or install it explicitly:

```bash
uv pip install kraang
# or
pip install kraang
```

If `KRAANG_DB_PATH` is not set, it defaults to `~/.kraang/brain.db`.

## Tool Reference

| Tool | Description | Parameters |
|------|-------------|------------|
| `add_note` | Add a new note | `title`, `content`, `tags?`, `category?`, `metadata?` |
| `search_notes` | Full-text search with filters | `query`, `tags?`, `category?`, `status?`, `limit?` |
| `update_note` | Update an existing note | `note_id`, `title?`, `content?`, `tags?`, `category?`, `status?` |
| `delete_note` | Delete a note | `note_id` |
| `list_tags` | List all tags | *(none)* |
| `list_categories` | List all categories | *(none)* |
| `list_notes` | Browse/list notes | `status?`, `limit?`, `offset?` |
| `get_stale_items` | Find notes not updated recently | `days?` |
| `daily_digest` | Activity summary | *(none)* |
| `suggest_related` | Find related notes | `note_id`, `limit?` |

### Prompts

| Prompt | Description |
|--------|-------------|
| `review_stale` | Review stale notes and suggest actions (update/archive/delete) |
| `summarize_kb` | Get a high-level summary of the knowledge base |
| `find_gaps` | Identify underrepresented topics and organization improvements |

## Development

```bash
git clone https://github.com/johnnygreco/kraang.git && cd kraang
uv sync --extra dev
make test
make lint
```

Run the full check suite:

```bash
make coverage   # tests + coverage report
make format     # auto-format with ruff
```

## Architecture

Kraang uses a layered architecture:

1. **Models** (`models.py`) -- Pydantic schemas define the data contracts: `Note`, `NoteCreate`, `NoteUpdate`, `SearchQuery`, etc.
2. **Store Protocol** (`store.py`) -- An async `NoteStore` protocol that any storage backend must implement.
3. **SQLite Backend** (`sqlite_store.py`) -- The default implementation using SQLite with FTS5 for full-text search and BM25 ranking.
4. **MCP Server** (`server.py`) -- Exposes the store as MCP tools and resources over stdio, ready for any MCP-compatible client.

## License

Apache 2.0
