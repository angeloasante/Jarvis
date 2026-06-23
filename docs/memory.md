# Memory

FRIDAY's memory system is the thing that makes FRIDAY *FRIDAY*. Without it,
she is a chatbot in a costume — a stateless LLM that forgets who you are the
moment the turn ends. With it, every conversation sits on top of a persistent
store of facts, decisions, preferences, corrections, and project context
that lives on your own disk and is never shipped to a third party unless a
tool explicitly chooses to include it in a prompt.

This document is the definitive reference for what that memory actually is,
where it lives, how it gets written, how it gets read back out, and how to
clear it when you want a fresh slate.

---

## 1. Overview

FRIDAY remembers four kinds of things:

1. **Seed facts** — the contents of `~/Friday/user.json` (name, bio, CV,
   project list, contact aliases). These are not "memories" in the
   vector-store sense; they are rendered into a `user_context_block()` and
   injected verbatim into every system prompt.
2. **Structured memories** — short atomic facts (decisions, preferences,
   people, corrections) stored in both SQLite *and* ChromaDB so they can be
   retrieved by semantic search or category filter.
3. **Operational state** — project sync cache, monitors, cron jobs, watch
   tasks, heartbeat state, agent dispatch logs. Pure SQLite, no embeddings.
4. **Conversation logs** — every user turn and every FRIDAY response is
   appended to a JSONL file for future fine-tuning datasets.

How this differs from ChatGPT's "memory":

| ChatGPT memory                                      | FRIDAY memory                                      |
| --------------------------------------------------- | -------------------------------------------------- |
| Stored on OpenAI's servers                          | Stored on your local disk only                     |
| Single opaque blob                                  | Structured: category, importance, tags, timestamps |
| Injected into every prompt regardless of relevance  | Only retrieved when query hints it should be       |
| No semantic search — it's all or nothing            | ChromaDB cosine search over every memory           |
| No conversation log for fine-tuning                 | Append-only JSONL traces every turn                |
| Cannot be wiped per-category or inspected directly  | SQLite you can `sqlite3` into at any time          |

The philosophy is that a personal assistant should know you deeply and
cheaply — deep because the CV, projects, and preferences are always in
context, and cheap because everything older than that is only pulled in
when it's relevant to the current query.

---

## 2. Storage backends

Two stores sit side-by-side, both under `data/memory/`:

```
data/
  memory/
    friday.db        # SQLite — structured rows, tables, indexes
    chroma/          # ChromaDB — HNSW vector index + metadata
  training/
    conversations.jsonl   # every user↔assistant turn
    react_traces.jsonl    # full tool-calling traces from BaseAgent
```

Paths are defined in [config.py](../friday/core/config.py):

```python
DATA_DIR = PROJECT_ROOT / "data"
MEMORY_DIR = DATA_DIR / "memory"
SQLITE_DB_PATH = MEMORY_DIR / "friday.db"
CHROMA_PERSIST_DIR = str(MEMORY_DIR / "chroma")
```

Both are initialised lazily by the `MemoryStore` singleton in
[store.py](../friday/memory/store.py) on first call to
`get_memory_store()`.

### 2.1 SQLite schema

Every table lives in one `.db` file. The schema is created idempotently
via `CREATE TABLE IF NOT EXISTS` on every process start:

```sql
-- The core memory table. Every store_memory() writes one row here
-- AND one vector in ChromaDB.
CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    tags TEXT DEFAULT '[]',          -- JSON array
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    importance INTEGER DEFAULT 5
);
CREATE INDEX idx_memories_category ON memories(category);

-- Tool-call audit log. Every agent dispatch writes one row.
CREATE TABLE agent_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    agent TEXT NOT NULL,
    tool TEXT,
    args TEXT,                       -- JSON
    result_summary TEXT,
    success INTEGER,
    duration_ms INTEGER,
    called_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_agent_calls_session ON agent_calls(session_id);

-- GitHub project cache, rebuilt by friday.background.github_sync.
CREATE TABLE projects (
    name TEXT PRIMARY KEY,
    description TEXT,
    url TEXT,
    language TEXT,
    all_languages TEXT DEFAULT '[]',
    topics TEXT DEFAULT '[]',
    private INTEGER DEFAULT 0,
    stars INTEGER DEFAULT 0,
    forks INTEGER DEFAULT 0,
    open_issues INTEGER DEFAULT 0,
    open_prs INTEGER DEFAULT 0,
    default_branch TEXT DEFAULT 'main',
    readme_summary TEXT,
    tech_stack TEXT,
    status TEXT DEFAULT 'active',
    synced_at TEXT,
    created_at TEXT,
    updated_at TEXT
);

-- Background monitors + their detected change events.
CREATE TABLE monitors (
    id TEXT PRIMARY KEY,
    topic TEXT, monitor_type TEXT, target TEXT,
    frequency TEXT, importance TEXT DEFAULT 'normal',
    keywords TEXT DEFAULT '[]',
    content_hash TEXT, last_content TEXT, last_checked TEXT,
    active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE monitor_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    monitor_id TEXT NOT NULL,
    change_summary TEXT, diff TEXT,
    is_material INTEGER DEFAULT 0,
    detected_at TEXT NOT NULL,
    delivered INTEGER DEFAULT 0
);

-- Queue of items waiting to be read out in the next briefing.
CREATE TABLE briefing_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    content TEXT NOT NULL,
    priority INTEGER DEFAULT 5,
    queued_at TEXT NOT NULL,
    delivered INTEGER DEFAULT 0
);

-- Scheduled tasks and polling watchers.
CREATE TABLE cron_jobs (
    id TEXT PRIMARY KEY, name TEXT NOT NULL,
    schedule TEXT NOT NULL, task TEXT NOT NULL,
    channel TEXT DEFAULT 'cli', enabled INTEGER DEFAULT 1,
    last_run TEXT, next_run TEXT, run_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE watch_tasks (
    id TEXT PRIMARY KEY, instruction TEXT NOT NULL,
    interval_seconds INTEGER NOT NULL DEFAULT 60,
    expires_at TEXT, last_check TEXT, last_state TEXT,
    active INTEGER DEFAULT 1, created_at TEXT NOT NULL
);

-- Misc session + heartbeat state.
CREATE TABLE sessions (id TEXT PRIMARY KEY, started_at TEXT, ended_at TEXT, summary TEXT);
CREATE TABLE heartbeat_state (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);
```

### 2.2 ChromaDB collection

ChromaDB holds one collection — `friday_memories` — using cosine
similarity over the default embedding model:

```python
self.chroma = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
self.collection = self.chroma.get_or_create_collection(
    name="friday_memories",
    metadata={"hnsw:space": "cosine"},
)
```

Every row in the `memories` SQLite table has a matching vector in ChromaDB
keyed by the same `id` (a UUID). The SQLite row is the source of truth for
structured fields (category, importance, tags, timestamps); the ChromaDB
vector is what answers "what do we know about X?".

---

## 3. The three memory tools

Three and only three tools are exposed to any agent. They all live in
[memory_tools.py](../friday/tools/memory_tools.py) and are thin wrappers
over `MemoryStore`:

### `store_memory(content, category="general", importance=5)`

```python
async def store_memory(content: str, category: str = "general",
                      importance: int = 5) -> ToolResult:
    store = get_memory_store()
    mem_id = store.store(content=content, category=category,
                         importance=importance)
    return ToolResult(success=True,
                      data=f"Memory stored: {mem_id}",
                      metadata={"id": mem_id})
```

- Writes one row to SQLite and one vector to ChromaDB, atomic per call.
- `category` is free-text but the prompt recommends: `project`, `decision`,
  `lesson`, `preference`, `person`, `general`, `correction`.
- `importance` is 1–10; not used for ranking today but stored for future
  weighting.
- Returns `ToolResult(success=True, data="Memory stored: <uuid>", metadata={"id": uuid})`.

### `search_memory(query, n_results=5)`

```python
async def search_memory(query: str, n_results: int = 5) -> ToolResult:
    store = get_memory_store()
    results = store.search(query=query, n_results=n_results)
    return ToolResult(success=True, data=results,
                      metadata={"count": len(results)})
```

- Semantic cosine search over the `friday_memories` collection.
- Returns a list of dicts: `{id, content, category, distance}`.
- Smaller distance = better match.
- `category` can be passed through to `store.search()` for hard filtering,
  though the tool wrapper currently exposes only `query` and `n_results`.

### `get_recent_memories(limit=10)`

```python
async def get_recent_memories(limit: int = 10) -> ToolResult:
    store = get_memory_store()
    results = store.get_recent(limit=limit)
    return ToolResult(success=True, data=results)
```

- Pulls the N most recent rows from the SQLite `memories` table,
  ordered by `updated_at DESC`.
- No semantic scoring — just a time-ordered dump.

These three functions are the *only* mutation/read surface a model ever
sees. The underlying `MemoryStore` has many more methods (projects,
agent calls, monitors) but those are called from Python, never from an LLM.

---

## 4. Categories and importance

The `category` field is a soft convention, not an enum — SQLite will store
anything. The [memory_agent.py](../friday/agents/memory_agent.py) system
prompt defines the intended taxonomy:

```
Categories: project, decision, lesson, preference, person, general
Importance: 1 (trivial) to 10 (critical, never forget)
```

Categories that actually get used elsewhere in the code:

- **`preference`** / **`person`** / **`decision`** — surfaced into the
  system prompt by `build_context()` because these are the categories the
  orchestrator considers safe to inject without contaminating unrelated
  conversations.
- **`correction`** — written by `_auto_learn()` when the user pushes back
  on a response (importance hardcoded to 8).
- **`project`** / **`lesson`** / **`general`** — written by the memory
  agent but not auto-injected; they only surface via explicit
  `search_memory()` calls.

Importance is currently a passive metadata field. It is stored in both
SQLite (`memories.importance`) and ChromaDB metadata but is not factored
into ranking. The intent is that a future re-ranker could boost results
by `importance * (1 - distance)`.

---

## 5. How memory gets in

### 5.1 Explicit stores — user says "remember that X"

The user says something like `@memory remember that I prefer short
responses`. The router matches on the `@memory` prefix or the classifier
fires, and the turn is dispatched to `MemoryAgent` (see
[memory_agent.py](../friday/agents/memory_agent.py)).

`MemoryAgent` extends `BaseAgent`, loads `TOOL_SCHEMAS` from
`memory_tools.py`, and runs a normal ReAct loop. Its system prompt biases
it heavily towards picking `store_memory` with a sensible category and
importance. The result is one SQLite row + one ChromaDB vector.

### 5.2 Implicit stores — auto-learning from corrections

The orchestrator watches every turn for correction signals. See
[`_auto_learn()` in orchestrator.py](../friday/core/orchestrator.py):

```python
correction_signals = [
    "thats not what i", "that wasnt what i", "you didnt",
    "not what i asked", "not what i meant", "i said",
    "wrong", "dumb", "stupid", "slop", "ai slop",
    "generic", "useless", "not helpful",
    "stop doing that", "don't do that",
    "i already told you", "how many times",
]

is_correction = any(sig in low for sig in correction_signals)
if not is_correction:
    return
```

When a correction is detected the orchestrator grabs the previous FRIDAY
response from `self.conversation`, wraps it into a `CORRECTION: ...`
string, and fires `store_memory(..., category="correction", importance=8)`
on a background task. Next time the user asks something similar, the
memory agent (or any agent calling `search_memory`) can retrieve the
correction and steer around the failure pattern.

### 5.3 Seed facts — `user.json` and `user_context_block()`

Everything the user puts in `~/Friday/user.json` (name, bio, email, phone,
GitHub handle, CV with experience / projects / skills / education) is
flattened into a single string by `user_context_block()` in
[prompts.py](../friday/core/prompts.py):

```
ABOUT THE USER (from ~/Friday/user.json):
- Name: ...
- <bio line>
- Email: ...
- GitHub: github.com/...
- Title: ...
- Summary: ...
- Experience:
    • Role @ Company (period)
- Projects:
    • Name — summary
- Skills: category: a, b, c | category: d, e, f
- Education: School (qualification, period); ...
```

This block is then passed straight into `SYSTEM_PROMPT.format(...)` by
`_build_system_prompt()` in the orchestrator, so every single turn — no
matter which route — has the user's identity on tap. No retrieval step,
no LLM call, no latency.

### 5.4 Background processor — currently disabled

[memory_processor.py](../friday/background/memory_processor.py) defines a
singleton `MemoryProcessor` that was designed to watch every turn,
extract atomic facts via a small LLM call, and store them automatically.
The `.process()` method is deliberately a no-op today:

```python
def process(self, user_input: str, response: str, agent_name=None):
    """DISABLED: The LLM call competes for GPU with the main
    conversation, adding ~7s latency to the next user query."""
    return
```

The extraction prompt and worker thread are still wired up; re-enabling is
a one-line change if extraction is ever moved off the hot path.

---

## 6. How memory gets out

### 6.1 `build_context(query)` — system-prompt injection

On every turn, `_build_system_prompt()` calls
`self.memory.build_context(query=user_input)`:

```python
def build_context(self, query: str = "") -> str:
    sections = []
    USEFUL_CATEGORIES = ("preference", "person", "decision")
    recent = self.get_recent(5)
    useful = [m for m in recent if m.get("category") in USEFUL_CATEGORIES]
    if useful:
        sections.append("CONTEXT:")
        for m in useful:
            sections.append(f"- {m['content']}")
    return "\n".join(sections)
```

Deliberately conservative. It only injects `preference`, `person`, and
`decision` rows, and only the five most recent. The docstring explains
why:

> Only injects preferences and person/decision memories — NOT general
> facts from old conversations, which contaminate responses with stale
> info (e.g. Neuralink facts bleeding into Halo glasses questions).

General facts, corrections, and project notes are only retrieved when an
agent explicitly calls `search_memory` with a query that matches.

### 6.2 `get_project_context()` — top-N repo snapshot

Also on every turn, `_build_system_prompt()` calls
`self.memory.get_project_context()`:

```python
def get_project_context(self, limit: int = 10) -> str:
    projects = self.get_all_projects()[:limit]
    if not projects:
        return ""
    lines = ["TRAVIS'S PROJECTS (top repos):"]
    for p in projects:
        lang = p.get("language") or "?"
        desc = (p.get("description") or "")[:80]
        lines.append(f"- {p['name']} ({lang}): {desc}")
    return "\n".join(lines)
```

The `projects` table is populated by
[github_sync.py](../friday/background/github_sync.py), which pulls the
user's public repos on a schedule and upserts them via
`store.upsert_project()`. The system prompt therefore always knows what
repos exist without doing a GitHub round-trip per turn.

### 6.3 Agent-driven retrieval — `search_memory` in the ReAct loop

Any agent that loads `TOOL_SCHEMAS` from `memory_tools` gets the
`search_memory` tool. The [memory-first skill](../friday/skills/memory_first/SKILL.md)
instructs every agent to:

> Before searching the web or asking Travis for information, CHECK MEMORY.

The flow:

1. **Search memory** for anything related to the task.
2. If memory has what you need → use it, don't search the web.
3. If memory is incomplete → search web to fill gaps, then store.
4. If memory has nothing → search web, then store important findings.

This is how corrections, project-specific lessons, and older decisions
re-enter the conversation: the agent asks for them by topic.

---

## 7. Conversation log — the fine-tuning corpus

Everything that isn't in the memory store is in the conversation log. See
[conversation_log.py](../friday/memory/conversation_log.py).

Two files, both append-only JSONL, both under `data/training/`:

- **`conversations.jsonl`** — one entry per user↔FRIDAY turn, in OpenAI
  fine-tuning format:

  ```json
  {
    "timestamp": "...",
    "session_id": "...",
    "route": "fast_path | fast_chat | oneshot | direct_dispatch | agent",
    "duration_ms": 1234,
    "model": "...",
    "messages": [
      {"role": "user", "content": "..."},
      {"role": "assistant", "content": "..."}
    ],
    "agent": "code_agent",
    "tools_called": ["search_web", "fetch_page"],
    "tool_trace": [{"tool": "...", "args": {...}, "result": "...", "success": true, "ms": 123}]
  }
  ```

- **`react_traces.jsonl`** — the full multi-turn agent message chain
  (system → user → assistant+tool_calls → tool → ...) from `BaseAgent`.
  This is the richest training data: a complete record of how FRIDAY
  reasoned through a task with tools. Very long tool results are
  truncated to 2000 chars to keep the file a reasonable size.

`log_turn(...)` is called from `_log_and_append()` in the orchestrator
after every completed turn. No LLM call, no latency — just a file append.

---

## 8. Recent-agent tracking

Separate from "memory" but in the same SQLite file is the `agent_calls`
table. Every time an agent is dispatched — via direct dispatch, one-shot,
tool dispatch, or the synthesis path — the call is logged:

```python
self.memory.log_agent_call(
    session_id=self.session_id,
    agent=agent_name,
    tool="dispatch",
    args={"task": task},
    result_summary=result.result[:200],
    success=result.success,
    duration_ms=result.duration_ms or 0,
)
```

The router reads this back in `recent_agent_context()` in
[router.py](../friday/core/router.py):

```python
if memory:
    recent_calls = memory.get_recent_agent_calls(limit=1)
    if recent_calls:
        last_agent = recent_calls[0].get("agent")
```

This powers follow-up routing — if the user's previous turn was handled
by `comms_agent` and they now say "yes, send it", the router knows to
send the confirmation back to `comms_agent` rather than re-routing from
scratch.

---

## 9. Privacy

Everything described above lives on your disk and only your disk:

- `data/memory/friday.db` — a plain SQLite file you can open with any
  SQLite client.
- `data/memory/chroma/` — ChromaDB's on-disk persistence directory.
- `data/training/*.jsonl` — local JSONL.
- `~/Friday/user.json` — your identity file.

Memory content reaches an LLM only when code puts it there:

1. The seed `user_context_block()` and the first five recent
   `preference` / `person` / `decision` rows are inlined into every
   system prompt. The rest of memory is *not* sent until an agent calls
   `search_memory`.
2. When `search_memory` is called, the top-N documents that match the
   query are put in the tool result, which then lands in the next
   assistant turn of the ReAct loop. That is the only moment a raw
   memory leaves the local store.
3. Conversation logs (`conversations.jsonl` / `react_traces.jsonl`) are
   written only. Nothing ever reads them back into a prompt at runtime.

If you want to tighten file permissions on the memory directory:

```bash
chmod 700 ~/Desktop/JARVIS/data
chmod 600 ~/Desktop/JARVIS/data/memory/friday.db
chmod -R go-rwx ~/Desktop/JARVIS/data/memory/chroma
```

---

## 10. Inspecting and wiping memory

### Inside the CLI

- `/memory` — prints the 10 most recent memories with category prefixes.
- `/clear` — clears the in-process conversation buffer only (does not
  touch the stores).
- `/clearwatches` — marks every row in `watch_tasks` inactive.

### From the shell

```bash
# Open the SQLite DB directly.
sqlite3 data/memory/friday.db

# Eyeball every memory.
sqlite> SELECT category, importance, substr(content, 1, 80), updated_at
   ...> FROM memories ORDER BY updated_at DESC LIMIT 20;

# Count by category.
sqlite> SELECT category, COUNT(*) FROM memories GROUP BY category;

# See the last 20 agent dispatches.
sqlite> SELECT agent, tool, success, duration_ms, called_at
   ...> FROM agent_calls ORDER BY called_at DESC LIMIT 20;

# Nuke a single category (e.g. corrections you no longer want).
sqlite> DELETE FROM memories WHERE category = 'correction';
```

Note that deleting rows from SQLite does **not** remove the vectors from
ChromaDB. To keep the two stores in sync you need to also delete the
matching IDs from the `friday_memories` collection, or just wipe
everything and start fresh:

```bash
# Full reset — deletes every memory and every embedding.
rm -rf data/memory/friday.db data/memory/chroma

# Also wipe the fine-tuning corpus.
rm -rf data/training
```

On next start, `MemoryStore._init_sqlite()` will recreate the tables and
`_init_chroma()` will recreate the empty collection. The seed facts in
`user.json` remain untouched and repopulate the system prompt on the
first turn.

---

## File reference

- [friday/memory/store.py](../friday/memory/store.py) — `MemoryStore`,
  schemas, `build_context`, `get_project_context`.
- [friday/memory/conversation_log.py](../friday/memory/conversation_log.py)
  — `log_turn`, `log_react_trace`.
- [friday/memory/__init__.py](../friday/memory/__init__.py) — empty
  package marker.
- [friday/tools/memory_tools.py](../friday/tools/memory_tools.py) — the
  three LLM-callable tools and their JSON schemas.
- [friday/agents/memory_agent.py](../friday/agents/memory_agent.py) —
  the `@memory` specialist agent.
- [friday/core/orchestrator.py](../friday/core/orchestrator.py) —
  `_build_system_prompt`, `_auto_learn`, `_store_correction`,
  `_log_and_append`.
- [friday/core/prompts.py](../friday/core/prompts.py) —
  `user_context_block`, `SYSTEM_PROMPT` template.
- [friday/core/config.py](../friday/core/config.py) — `SQLITE_DB_PATH`,
  `CHROMA_PERSIST_DIR`, `DATA_DIR`.
- [friday/background/memory_processor.py](../friday/background/memory_processor.py)
  — disabled background extractor.
- [friday/background/github_sync.py](../friday/background/github_sync.py)
  — populates the `projects` table.
- [friday/skills/memory_first/SKILL.md](../friday/skills/memory_first/SKILL.md)
  — the memory-first skill enforced on every agent.
