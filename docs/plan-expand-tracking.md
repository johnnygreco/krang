# Plan: Expanding Kraang's Tracking Scope

## Current State

Kraang is an MCP server that tracks a single entity type: **Notes**. Each note has a title, content, tags, category, status, timestamps, and arbitrary key-value metadata. Notes are stored in a single SQLite database (`~/.kraang/brain.db`) with FTS5 full-text search. The system exposes 11 MCP tools, 3 prompts, and 1 resource template.

This plan proposes three new entity types — **Prompts**, **Plans**, and **Sessions** — plus supporting infrastructure to tie them together.

---

## 1. New Entity: Saved Prompts

### Problem

Users repeatedly compose similar instructions for agents. There is no way to save, recall, or template-ize a prompt for reuse. A user who frequently asks an agent to "review this PR for security issues with OWASP top-10 focus" should be able to store that once and recall it by keyword.

### Design

```
SavedPrompt
├── prompt_id: str              # Auto-generated 12-char hex
├── name: str                   # Short unique identifier (e.g., "security-review")
├── trigger: str                # Slash-command or keyword (e.g., "/sec-review")
├── template: str               # The prompt body, supports {{variable}} placeholders
├── description: str            # Human-readable explanation of what this prompt does
├── tags: list[str]             # For organization and search
├── category: str               # Grouping (e.g., "code-review", "writing", "ops")
├── variables: list[str]        # Declared template variables (extracted from template)
├── usage_count: int            # How many times this prompt has been invoked
├── last_used_at: datetime|None # Timestamp of last invocation
├── created_at: datetime
├── updated_at: datetime
└── metadata: dict[str, str]    # Arbitrary key-value pairs
```

### User Flow: How Prompts Get Added

Prompt creation is always **agent-mediated** — the user expresses intent in natural language, and the agent translates it into a `save_prompt` tool call. There is no raw command interception layer in kraang (MCP servers don't see user input directly; the agent does).

**Flow 1 — Explicit save request** (primary path):
```
User:  "Save this as a reusable prompt called sec-review:
        Review {{file_path}} for security issues with OWASP top-10 focus"

Agent: (recognizes save intent, calls save_prompt)
       save_prompt(
           name="sec-review",
           trigger="/sec-review",
           template="Review {{file_path}} for security issues with OWASP top-10 focus",
           description="OWASP-focused security review of a single file",
           tags=["security", "code-review"],
           category="code-review"
       )

Kraang: Creates the prompt, returns "Saved prompt 'sec-review' (ID: a1b2c3d4e5f6)"
```

**Flow 2 — Recall by trigger**:
```
User:  "/sec-review src/auth.py"

Agent: (recognizes trigger prefix, calls recall_prompt)
       recall_prompt(trigger="/sec-review", variables={"file_path": "src/auth.py"})

Kraang: Returns rendered template, increments usage_count, updates last_used_at
Agent: Uses the rendered prompt as its instructions
```

**Flow 3 — Recall by name or search** (when user doesn't remember the exact trigger):
```
User:  "Use that security review prompt on src/auth.py"

Agent: (searches for it)
       search_prompts(query="security review")

Kraang: Returns matching prompts with scores
Agent: Picks the best match, calls recall_prompt by name
```

**What kraang does NOT do**: Kraang never sees raw user input. It cannot intercept `/sec-review` before the agent. The agent must recognize the trigger pattern and translate it into a `recall_prompt` call. This is a deliberate design choice — kraang is a storage/retrieval layer, not an input processor.

### Trigger Rules and Determination

**Who picks the trigger?**

1. **User specifies**: "Save this as `/sec-review`" — the agent passes the trigger through directly.
2. **Auto-derived from name**: If no trigger is provided, kraang derives one from the `name` field by prepending `/`. So `name="sec-review"` automatically gets `trigger="/sec-review"`.
3. **No trigger**: A prompt can exist without a trigger (the field is nullable). It's still recallable by name or keyword search.

**Trigger format rules** (validated on save):

| Rule | Constraint |
|------|-----------|
| Prefix | Must start with `/` |
| Characters | Lowercase alphanumeric and hyphens only: `/[a-z0-9][a-z0-9-]*$/` |
| Length | 2-50 characters (excluding the `/` prefix) |
| Uniqueness | Must be unique across all saved prompts (enforced by DB `UNIQUE` constraint) |
| Reserved | Must not collide with reserved triggers (see below) |

**Auto-derivation logic** (in the store's create method):
```python
if trigger is None and name:
    candidate = f"/{name.lower().replace(' ', '-')}"
    if _is_valid_trigger(candidate):
        trigger = candidate
    # else: leave trigger as None, prompt is name/search-only
```

### Trigger Collision Handling

There are three collision domains to consider:

**1. Collisions between saved prompts** — Handled by the schema's `UNIQUE` constraint on `trigger`. If a user tries to save a prompt with `trigger="/sec-review"` and one already exists, `save_prompt` returns an error:

```
"Error: trigger '/sec-review' is already in use by prompt 'security-review'.
 Use a different trigger, or update the existing prompt."
```

**2. Collisions with kraang's own MCP tool names** — Not a real risk. MCP tools (`add_note`, `search_notes`, etc.) live in a different namespace from triggers. Tools are called programmatically by the agent; triggers are a user-facing convention the agent interprets. No overlap.

**3. Collisions with host application commands** — This is the real risk. If kraang is used inside Claude Code, commands like `/help`, `/clear`, `/compact`, `/review`, `/model`, etc. are intercepted by the host before the agent sees them. A saved prompt with trigger `/review` would be unreachable because Claude Code would consume the input first.

**Solution: Reserved trigger blocklist.** Kraang validates triggers against a blocklist of known host commands on save. The blocklist is stored as a constant and checked in `save_prompt`:

```python
RESERVED_TRIGGERS: frozenset[str] = frozenset({
    # Claude Code built-in commands
    "/help", "/clear", "/compact", "/review", "/init",
    "/config", "/cost", "/doctor", "/login", "/logout",
    "/status", "/memory", "/mcp", "/vim", "/model",
    "/permissions", "/terminal-setup", "/listen",
    "/commit", "/pr-comments", "/bug",
    # Generic safety reserves
    "/exit", "/quit", "/reset", "/undo", "/redo",
})
```

If a trigger matches a reserved name, `save_prompt` returns:

```
"Error: trigger '/review' is reserved (conflicts with a host application command).
 Choose a different trigger name."
```

**Recommendation**: The blocklist approach is simple and sufficient. A namespace prefix (e.g., `/k:sec-review`) was considered but rejected — it's ugly and hurts adoption. The blocklist is easy to maintain and covers the practical cases. If kraang is later used with a different host application, the blocklist can be made configurable via an environment variable (`KRAANG_RESERVED_TRIGGERS`).

### Template Variables

Templates use `{{variable}}` syntax. When a prompt is recalled, the caller can pass variable values:

```
Template: "Review {{file_path}} for {{checklist}} compliance"
Invocation: recall_prompt(trigger="/review", variables={"file_path": "src/auth.py", "checklist": "OWASP"})
Result: "Review src/auth.py for OWASP compliance"
```

Variables are auto-extracted from the template on save and stored in the `variables` field for discoverability (so agents can know what parameters a prompt expects).

### MCP Tools

| Tool | Description |
|------|-------------|
| `save_prompt` | Create or update a saved prompt with name, trigger, template, tags |
| `recall_prompt` | Retrieve a prompt by trigger or name, optionally filling template variables |
| `search_prompts` | Full-text search across saved prompts |
| `list_prompts` | Browse all saved prompts with optional category/tag filters |
| `delete_prompt` | Remove a saved prompt |
| `get_prompt_usage` | Show usage stats for a prompt (count, last used, etc.) |

### Database Schema

```sql
CREATE TABLE IF NOT EXISTS saved_prompts (
    prompt_id     TEXT PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    trigger       TEXT UNIQUE,             -- nullable; not all prompts need a trigger
    template      TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    category      TEXT NOT NULL DEFAULT '',
    variables_json TEXT NOT NULL DEFAULT '[]',
    usage_count   INTEGER NOT NULL DEFAULT 0,
    last_used_at  TEXT,                    -- nullable ISO 8601
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS prompt_tags (
    prompt_id TEXT NOT NULL REFERENCES saved_prompts(prompt_id) ON DELETE CASCADE,
    tag       TEXT NOT NULL,
    UNIQUE(prompt_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_prompt_tags_tag ON prompt_tags(tag);
CREATE INDEX IF NOT EXISTS idx_prompts_trigger ON saved_prompts(trigger);
CREATE INDEX IF NOT EXISTS idx_prompts_name ON saved_prompts(name);
CREATE INDEX IF NOT EXISTS idx_prompts_category ON saved_prompts(category);

CREATE VIRTUAL TABLE IF NOT EXISTS prompts_fts USING fts5(
    name, description, template,
    content=saved_prompts,
    content_rowid=rowid,
    tokenize='porter unicode61'
);
```

---

## 2. New Entity: Agent Plans

### Problem

When agents break a task into steps, that plan is ephemeral — it lives only in the conversation context and is lost when the session ends. Storing plans enables:

- Reviewing what an agent intended to do vs. what it actually did
- Resuming interrupted work across sessions
- Building a library of reusable plan templates for recurring tasks
- Auditing agent behavior over time

### Design

```
Plan
├── plan_id: str                # Auto-generated 12-char hex
├── title: str                  # Short description (e.g., "Add dark mode toggle")
├── description: str            # Longer context about the goal
├── status: PlanStatus          # draft | active | completed | abandoned
├── source_prompt_id: str|None  # FK to the saved_prompt that triggered this plan
├── session_id: str|None        # FK to the session where this plan was created
├── tags: list[str]
├── category: str
├── created_at: datetime
├── updated_at: datetime
├── completed_at: datetime|None
└── metadata: dict[str, str]

PlanStep
├── step_id: str                # Auto-generated 12-char hex
├── plan_id: str                # FK to parent plan
├── position: int               # Ordering (1-based)
├── title: str                  # Short step description
├── description: str            # Detailed instructions or notes
├── status: StepStatus          # pending | in_progress | completed | skipped | failed
├── result: str                 # What actually happened (filled on completion)
├── created_at: datetime
├── updated_at: datetime
└── metadata: dict[str, str]
```

### Plan Lifecycle

```
draft ──► active ──► completed
              │
              └────► abandoned
```

- **draft**: Plan is being composed, steps can be added/reordered.
- **active**: Work is underway. Steps move through `pending → in_progress → completed/skipped/failed`.
- **completed**: All steps are resolved (completed, skipped, or failed) and the plan is done.
- **abandoned**: Work was stopped before completion.

### MCP Tools

| Tool | Description |
|------|-------------|
| `create_plan` | Create a new plan with title, description, and optional initial steps |
| `get_plan` | Retrieve a plan with all its steps |
| `update_plan` | Update plan metadata (title, description, status, tags) |
| `add_plan_step` | Add a step to an existing plan |
| `update_plan_step` | Update a step's status, result, or description |
| `reorder_plan_steps` | Change step ordering within a plan |
| `list_plans` | Browse plans with status/category/tag filters |
| `search_plans` | Full-text search across plans and their steps |
| `complete_plan` | Mark a plan as completed (validates all steps are resolved) |
| `clone_plan` | Copy an existing plan as a template for a new task |
| `delete_plan` | Remove a plan and all its steps |

### Database Schema

```sql
CREATE TABLE IF NOT EXISTS plans (
    plan_id          TEXT PRIMARY KEY,
    title            TEXT NOT NULL,
    description      TEXT NOT NULL DEFAULT '',
    status           TEXT NOT NULL DEFAULT 'draft',  -- draft|active|completed|abandoned
    source_prompt_id TEXT REFERENCES saved_prompts(prompt_id) ON DELETE SET NULL,
    session_id       TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
    category         TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    completed_at     TEXT,
    metadata_json    TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS plan_steps (
    step_id       TEXT PRIMARY KEY,
    plan_id       TEXT NOT NULL REFERENCES plans(plan_id) ON DELETE CASCADE,
    position      INTEGER NOT NULL,
    title         TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending|in_progress|completed|skipped|failed
    result        TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS plan_tags (
    plan_id TEXT NOT NULL REFERENCES plans(plan_id) ON DELETE CASCADE,
    tag     TEXT NOT NULL,
    UNIQUE(plan_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_plan_tags_tag ON plan_tags(tag);
CREATE INDEX IF NOT EXISTS idx_plans_status ON plans(status);
CREATE INDEX IF NOT EXISTS idx_plans_category ON plans(category);
CREATE INDEX IF NOT EXISTS idx_plan_steps_plan ON plan_steps(plan_id, position);

CREATE VIRTUAL TABLE IF NOT EXISTS plans_fts USING fts5(
    title, description,
    content=plans,
    content_rowid=rowid,
    tokenize='porter unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS plan_steps_fts USING fts5(
    title, description, result,
    content=plan_steps,
    content_rowid=rowid,
    tokenize='porter unicode61'
);
```

---

## 3. New Entity: Sessions

### Problem

There is no record of *when* or *in what context* knowledge was created. A session log ties notes, prompts, and plans to the conversation that produced them, enabling temporal queries ("what did I work on last Tuesday?") and provenance tracking.

### Design

```
Session
├── session_id: str             # Auto-generated 12-char hex
├── title: str                  # Auto-generated or user-provided summary
├── started_at: datetime
├── ended_at: datetime|None
├── status: SessionStatus       # active | ended
├── tags: list[str]
└── metadata: dict[str, str]    # e.g., {"tool": "claude-code", "repo": "kraang"}

SessionEvent
├── event_id: str               # Auto-generated 12-char hex
├── session_id: str             # FK to parent session
├── event_type: EventType       # prompt_saved | plan_created | note_added | plan_completed | ...
├── entity_id: str              # ID of the related entity (note_id, plan_id, prompt_id)
├── entity_type: str            # "note" | "plan" | "prompt"
├── summary: str                # Human-readable description of what happened
├── created_at: datetime
└── metadata: dict[str, str]
```

### MCP Tools

| Tool | Description |
|------|-------------|
| `start_session` | Begin a new session (auto-starts if none active) |
| `end_session` | Close the current session |
| `get_session` | Retrieve a session with its event timeline |
| `list_sessions` | Browse past sessions |
| `search_sessions` | Search session events and summaries |

### Database Schema

```sql
CREATE TABLE IF NOT EXISTS sessions (
    session_id    TEXT PRIMARY KEY,
    title         TEXT NOT NULL DEFAULT '',
    started_at    TEXT NOT NULL,
    ended_at      TEXT,
    status        TEXT NOT NULL DEFAULT 'active',  -- active|ended
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS session_tags (
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    tag        TEXT NOT NULL,
    UNIQUE(session_id, tag)
);

CREATE TABLE IF NOT EXISTS session_events (
    event_id      TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    event_type    TEXT NOT NULL,
    entity_id     TEXT NOT NULL,
    entity_type   TEXT NOT NULL,
    summary       TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_session_events_session ON session_events(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_session_events_entity ON session_events(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
```

---

## 4. Single Database vs. Multiple Databases

### Recommendation: Single database, multiple tables

**Arguments for a single database:**

- **Referential integrity**: Plans can reference prompts and sessions via foreign keys. Cross-database foreign keys don't exist in SQLite.
- **Atomic transactions**: Creating a plan from a prompt within a session can be a single transaction. Multi-database transactions require manual coordination.
- **Simpler operations**: One backup, one WAL file, one connection pool, one migration path.
- **Cross-entity search**: "Find everything related to 'authentication'" can query notes, prompts, plans, and session events in a single pass.
- **SQLite scales fine**: SQLite handles millions of rows across dozens of tables without issue. The data volumes here (thousands of notes/prompts/plans) are trivially small.

**Arguments against multiple databases:**

- **Isolation**: If session event logs grow very large (millions of events), they could be separated to avoid bloating the main DB.
- **Different backup cadences**: You might want to back up notes daily but session logs weekly.
- **Security boundaries**: Prompts containing sensitive templates could live in a separate, encrypted DB.

**Verdict**: Start with a single database. The benefits of referential integrity and cross-entity queries are significant. If session events grow to the point of causing performance issues (unlikely for typical usage), the `NoteStore` protocol abstraction makes it straightforward to split out a `SessionStore` later. The code already uses a protocol-based design that supports exactly this kind of future split.

The one case where a second database might make sense from the start: if kraang is used by multiple agents concurrently and you want per-agent isolation. Even then, SQLite WAL mode handles concurrent reads well, and the write lock already serializes writes.

---

## 5. Cross-Entity Relationships

The new entities create a relationship graph:

```
Session ──has many──► SessionEvent
    │                      │
    │                      ├── references ──► Note
    │                      ├── references ──► Plan
    │                      └── references ──► SavedPrompt
    │
    └──────────────────► Plan
                           │
                           ├── triggered by ──► SavedPrompt
                           └── has many ──► PlanStep
```

### Cross-Entity MCP Tools

| Tool | Description |
|------|-------------|
| `get_session_timeline` | Get all notes, plans, and prompts created during a session |
| `get_prompt_plans` | List all plans that were created from a specific saved prompt |
| `search_all` | Unified search across notes, prompts, plans, and session events |

### Unified Search

A new `search_all` tool searches across all entity types and returns a unified result set:

```python
class UnifiedSearchResult(BaseModel):
    entity_type: str        # "note" | "prompt" | "plan" | "session"
    entity_id: str
    title: str
    snippet: str
    score: float
    created_at: datetime
```

This runs parallel FTS queries against `notes_fts`, `prompts_fts`, `plans_fts`, and `session_events`, merges by BM25 score, and returns a single ranked list.

---

## 6. Architecture Changes

### 6a. Models Layer (`models.py`)

Add new Pydantic models:

- `SavedPrompt`, `PromptCreate`, `PromptUpdate`
- `Plan`, `PlanCreate`, `PlanUpdate`, `PlanStep`, `StepCreate`, `StepUpdate`
- `Session`, `SessionCreate`, `SessionEvent`, `EventCreate`
- New enums: `PlanStatus`, `StepStatus`, `SessionStatus`, `EventType`
- `UnifiedSearchResult`, `UnifiedSearchResponse`

### 6b. Store Protocol (`store.py`)

Extend `NoteStore` or create additional protocols:

**Option A** (recommended): Extend the existing protocol into a broader `KraangStore` protocol that includes all CRUD and search methods for all entity types. This keeps the interface unified and avoids the caller needing to know about multiple store objects.

**Option B**: Create separate protocols (`PromptStore`, `PlanStore`, `SessionStore`) and compose them. Cleaner separation of concerns but more complex wiring.

Recommendation: **Option A** for now, with clear method-name prefixes (`prompt_create`, `plan_create`, `session_create`) to avoid confusion with the existing `create` (for notes).

### 6c. SQLite Store (`sqlite_store.py`)

- Add new tables to `_SCHEMA`
- Add FTS triggers for `saved_prompts`, `plans`, `plan_steps`
- Implement new CRUD methods for each entity type
- Implement cross-entity search in `search_all`
- Add schema migration logic (detect existing DB, add new tables if missing)

### 6d. Server (`server.py`)

- Register new MCP tools for prompts, plans, sessions
- Register new MCP prompts (e.g., `review_plans`, `prompt_library`)
- Register new MCP resources (e.g., `prompt://{prompt_id}`, `plan://{plan_id}`)

### 6e. Search (`search.py`)

- Add unified search function that queries multiple FTS tables
- Add prompt-specific query processing (handle trigger syntax)
- Add plan search with step content inclusion

---

## 7. Schema Migration Strategy

Since kraang uses `CREATE TABLE IF NOT EXISTS`, adding new tables to the existing `_SCHEMA` string is safe for fresh installs. For existing databases:

1. Add a `schema_version` table to track the current schema version.
2. On `initialize()`, check the version and run any needed migrations.
3. Migrations are idempotent SQL scripts (using `IF NOT EXISTS` everywhere).

```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL,
    applied_at TEXT NOT NULL
);
```

This is lightweight and avoids pulling in a migration framework like Alembic.

---

## 8. Implementation Order

### Phase 1: Saved Prompts
1. Add `SavedPrompt` models to `models.py`
2. Add `saved_prompts` and `prompt_tags` tables to schema
3. Implement prompt CRUD in `sqlite_store.py`
4. Add `save_prompt`, `recall_prompt`, `search_prompts`, `list_prompts`, `delete_prompt` tools to `server.py`
5. Add template variable extraction and rendering
6. Tests

### Phase 2: Agent Plans
1. Add `Plan`, `PlanStep` models to `models.py`
2. Add `plans`, `plan_steps`, `plan_tags` tables to schema
3. Implement plan CRUD (including step management) in `sqlite_store.py`
4. Add plan MCP tools to `server.py`
5. Add `clone_plan` for plan templates
6. Tests

### Phase 3: Sessions
1. Add `Session`, `SessionEvent` models to `models.py`
2. Add `sessions`, `session_tags`, `session_events` tables to schema
3. Implement session lifecycle in `sqlite_store.py`
4. Auto-record events when notes/prompts/plans are created (hook into existing create methods)
5. Add session MCP tools to `server.py`
6. Tests

### Phase 4: Cross-Entity Features
1. Implement `search_all` unified search
2. Add `get_session_timeline` and `get_prompt_plans` tools
3. Add schema migration system (`schema_version` table)
4. Add new MCP prompts and resources
5. Integration tests across entity types

---

## 9. Scope of New MCP Interface

After all phases, the MCP server would expose:

| Category | Count | Tools |
|----------|-------|-------|
| Notes (existing) | 11 | `add_note`, `search_notes`, `update_note`, `delete_note`, `get_note`, `list_tags`, `list_categories`, `list_notes`, `get_stale_items`, `daily_digest`, `suggest_related` |
| Prompts (new) | 6 | `save_prompt`, `recall_prompt`, `search_prompts`, `list_prompts`, `delete_prompt`, `get_prompt_usage` |
| Plans (new) | 11 | `create_plan`, `get_plan`, `update_plan`, `add_plan_step`, `update_plan_step`, `reorder_plan_steps`, `list_plans`, `search_plans`, `complete_plan`, `clone_plan`, `delete_plan` |
| Sessions (new) | 5 | `start_session`, `end_session`, `get_session`, `list_sessions`, `search_sessions` |
| Cross-entity (new) | 3 | `search_all`, `get_session_timeline`, `get_prompt_plans` |
| **Total** | **36** | |

New MCP Prompts: `review_plans` (review active plans), `prompt_library` (browse and suggest prompts)

New MCP Resources: `prompt://{prompt_id}`, `plan://{plan_id}`, `session://{session_id}`

---

## 10. Design Decisions (Resolved)

1. **Trigger collision handling**: Use a blocklist of reserved triggers validated on save, rejectable with a clear error message. The blocklist is configurable via `KRAANG_RESERVED_TRIGGERS` env var for non-Claude-Code hosts. Namespace prefixes (`/k:...`) were rejected for ergonomic reasons.

2. **Trigger determination**: User-specified first, auto-derived from `name` as fallback, nullable if neither works. Format: `/[a-z0-9][a-z0-9-]*`, 2-50 chars, must be unique.

3. **Prompt creation flow**: Always agent-mediated. The user expresses intent in natural language ("save this as a prompt"), the agent calls `save_prompt`. Kraang is a storage layer, not an input interceptor.

4. **Prompt recall flow**: The agent recognizes trigger patterns (e.g., user types `/sec-review`) and calls `recall_prompt`. Kraang increments `usage_count` and `last_used_at` on each recall.

---

## 11. Open Questions

1. **Prompt versioning**: Should updating a prompt's template create a new version or overwrite? Version history adds complexity but is valuable for frequently-edited prompts. A `prompt_versions` table could store previous template bodies. **Recommendation**: Defer. Start with overwrite semantics. Users who need version history can copy the old template into a note before updating. Add versioning in a future phase if usage patterns demand it.

2. **Plan-to-note linking**: Should completing a plan auto-generate a summary note? This would bridge the plan system back to the existing notes system, creating a permanent record. **Recommendation**: Yes, but make it opt-in. Add an `auto_summarize` flag on `complete_plan` (default `false`). When true, kraang creates a note with category `"plan-summary"` and a tag linking to the plan ID.

3. **Session auto-management**: Should sessions start/end automatically (e.g., start on first tool call, end after inactivity), or require explicit user control? **Recommendation**: Hybrid. Auto-start a session on the first tool call if none is active. Require explicit `end_session` to close. If a session is still active after 24 hours, auto-end it on the next tool call and start a fresh one. This gives ergonomic defaults without silent data loss.

4. **Event granularity**: Should session events record every tool call (high volume, good for auditing) or only entity lifecycle events like creation/completion (lower volume, sufficient for most use cases)? **Recommendation**: Entity lifecycle events only (create, update, delete, complete). This keeps the event table small and meaningful. A future "audit mode" could add tool-call-level logging behind a flag.

5. **Prompt sharing**: Should there be an import/export format for saved prompts (JSON, YAML) so users can share prompt libraries? **Recommendation**: Defer to Phase 5. When implemented, use JSON matching the `SavedPrompt` Pydantic model schema, with an `export_prompts` / `import_prompts` tool pair. This is a natural extension but not needed for the core system.

6. **Blocklist maintenance**: The reserved trigger blocklist will drift as host applications add new commands. **Recommendation**: Ship a sensible default, expose `KRAANG_RESERVED_TRIGGERS` as a comma-separated env var for overrides, and document the expectation that users update it if they hit collisions. Kraang could also expose a `list_reserved_triggers` tool so agents can help users avoid conflicts proactively.

7. **Template variable validation on recall**: What happens when a user recalls a prompt but doesn't provide all required variables? **Recommendation**: Return the template with unfilled `{{variable}}` placeholders intact and include a warning listing the missing variables. Don't error — the agent can still use a partially-filled template and fill the gaps from context. Add a `strict` parameter on `recall_prompt` (default `false`) that errors on missing variables for users who want enforcement.
