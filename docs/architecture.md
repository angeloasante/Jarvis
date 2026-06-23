# FRIDAY Architecture

A walkthrough of what actually happens between a user pressing enter and FRIDAY streaming a response back. This document traces the request through the 7-tier routing chain, the agent base class, the LLM provider layer, and the conversation state that holds it all together.

---

## 1. The Big Picture

FRIDAY is a **layered, latency-optimised agent orchestrator**. A single front door — `FridayCore._background_work()` in [orchestrator.py](../friday/core/orchestrator.py) — receives every user message and runs it through a cascade of matchers, each one **faster but narrower** than the next. The cheapest match wins. Only when regex, capability-scoped LLM classifiers, and direct tool dispatch all fail does the request reach a full ReAct agent, and only beyond that does it reach a multi-agent fanout or a free-form chat fallback. The whole system is designed around the observation that most user requests (greetings, TV control, "check my email", "set volume to 30") do not need a reasoning loop — they need a tool call. Everything else is built to gracefully degrade from "sub-second canned response" through "one tool + one format call" up to "multi-agent research document".

---

## 2. The 7-Tier Routing Chain

Tiers are evaluated in strict priority order inside [`_background_work()`](../friday/core/orchestrator.py) (see `orchestrator.py:244-475`). The first tier that handles the input returns — later tiers never run.

| # | Tier | LLM Calls | Latency | Decides by | File |
|---|------|-----------|---------|------------|------|
| 1 | fast_path (regex → tool) | 0 | <1s | Python regex | [fast_path.py](../friday/core/fast_path.py) |
| 2 | Greeting fast_chat / slim chat | 1 | 1-2s | Regex + task-signal check | [orchestrator.py](../friday/core/orchestrator.py) |
| 3 | Oneshot regex → tool → 1 LLM format | 1 | 2-4s | Python regex on verb+noun | [oneshot.py](../friday/core/oneshot.py) |
| 4 | Direct tool dispatch | 2 | 3-6s | 1 LLM picks tool from curated set | [tool_dispatch.py](../friday/core/tool_dispatch.py) |
| 5 | Router classify → agent (ReAct) | 3-6 | 5-30s | LLM classifier, regex fallback | [router.py](../friday/core/router.py) + [base_agent.py](../friday/core/base_agent.py) |
| 6 | Multi-agent fanout | 10+ | 2-3 min | Regex ("paper", "deep dive") | [deep_research_agent.py](../friday/agents/deep_research_agent.py) |
| 7 | LLM fallback chat / `dispatch_agent` | 1-4 | variable | Free-form SYSTEM_PROMPT + tool | [orchestrator.py](../friday/core/orchestrator.py) |

There is also an **override fast-path at priority 1.5** (`@agent` or "hand it off to X") and a **confirmation re-dispatch at 2.7** that routes bare "yes" / "do it" to the previously-used agent. These are not numbered tiers but live in the same cascade.

### Tier 1 — fast_path (zero LLM)

Pure Python: [`fast_path()`](../friday/core/fast_path.py) at `fast_path.py:29` lowercases the input, strips trailing vocatives ("bro", "fam", "mate"), and tests it against:

- A `_GREETINGS` table of `(pattern, canned_reply)` pairs (`fast_path.py:12-26`). Hits append to `conversation` and return immediately.
- `match_fast()` (`fast_path.py:57`) — direct tool calls for TV power/volume/app launch/mute/pause, screen casting (AirPlay), FaceTime starts, and Mac app launches from the `_safe_apps()` allowlist.

Zero LLM. Zero tokens. Sub-second. The compound pattern at `fast_path.py:66-80` even handles "turn on the TV and open Netflix" by awaiting the power-on, `asyncio.sleep(6)` for the TV to boot, then launching the app.

Decision to hand off: returns `None` if no regex fires. `_background_work()` moves to the next tier.

### Tier 2 — greeting fast_chat

Handled inline in [`_background_work()`](../friday/core/orchestrator.py) at `orchestrator.py:427-430` using [`is_likely_chat()`](../friday/core/router.py) from `router.py:565`, which returns `True` when no task-signal regex matches (no "search", "open", "email", "volume", "cv", etc.).

When it triggers, [`_fast_chat()`](../friday/core/orchestrator.py) at `orchestrator.py:181` builds a message list with the **slim personality prompt** (`get_personality_slim()`, ~500 tokens instead of the full 2k+ system prompt), the last 10 conversation messages truncated to 400 chars each, and streams a `cloud_chat` response back with `max_tokens=300`. One LLM call, no tools, no routing.

### Tier 3 — Oneshot regex → tool → 1 LLM format

[`try_oneshot()`](../friday/core/oneshot.py) at `oneshot.py:17` handles **queries where the regex knows exactly which single tool to call but a canned response would sound wrong**. Examples: "check my email", "what's on my calendar", "search X for vision pro", "who is @elonmusk".

Flow:

1. Regex matches (e.g. `email_match` at `oneshot.py:92`)
2. Tool called directly (`read_emails(filter="unread", limit=10)`)
3. [`_oneshot_format()`](../friday/core/oneshot.py) at `oneshot.py:272` builds a 3-message prompt (slim personality + user input + tool results as a system message) and streams back one `cloud_chat` call with a `fmt_hint` like _"Summarize emails naturally. Group by priority."_
4. Writes to conversation, memory log, and training log.

Some branches skip even the format call — screenshots (`oneshot.py:151`), volume sets (`oneshot.py:204`), battery/system info (`oneshot.py:178`) use [`_oneshot_instant()`](../friday/core/oneshot.py) at `oneshot.py:249` which returns a canned string. Zero LLM for those.

The `_is_chained` flag at `oneshot.py:148` detects "and/then/also" and bails — chains need an agent.

### Tier 4 — Direct tool dispatch

[`try_direct_dispatch()`](../friday/core/tool_dispatch.py) at `tool_dispatch.py:158` sits between oneshot (regex-bound) and the agent ReAct loop (full tool set). It handles the long tail of single-tool queries that oneshot can't pattern-match.

Mechanism:

1. A **curated 40-tool registry** is lazy-built via `_build_tools()` at `tool_dispatch.py:108`. `TOOL_NAMES` at `tool_dispatch.py:75` lists every tool direct-dispatch is allowed to call (read/search emails, calendar, iMessage, WhatsApp, SMS, X search, web search, memory, cron, screen, casting, Mac control). Send-type tools like `send_email`/`post_tweet` are excluded — they need confirmation context.
2. Pre-filter bail-outs at `tool_dispatch.py:181-226`: too-short inputs, correction phrases, "save to desktop" patterns, URLs, file-creation verbs, chained "open X and Y" — these all return `False` to punt to the agent tier.
3. A **slim `DISPATCH_PROMPT`** (`tool_dispatch.py:19-41`) instructs the LLM to either call **exactly one tool**, or reply with the literal string `NEEDS_AGENT` (multi-step) or `NO_TOOL` (chat). It includes hard rules like "form filling → NEEDS_AGENT", "job applications → NEEDS_AGENT", "save-to-file → NEEDS_AGENT".
4. One `cloud_chat` call with the full `DIRECT_TOOL_SCHEMAS` list and the last 10 conversation messages for context.
5. If exactly one tool call comes back: execute it, then pass the result to [`_format_and_stream()`](../friday/core/tool_dispatch.py) at `tool_dispatch.py:314`, which runs a **second** `cloud_chat` with `get_format_prompt()` to turn the tool result into conversational prose.

Two LLM calls total, ~3-6s. Much faster than the agent ReAct loop's 3-4 calls + tool-schema prompt eval overhead.

### Tier 5 — Router classify → agent dispatch

When tiers 1-4 all pass, [`classify_intent()`](../friday/core/router.py) at `router.py:135` runs. It's an **LLM classifier** — `_CLASSIFY_PROMPT` (`router.py:21-132`) is a long, capability-aware prompt listing every agent's concrete abilities ("job_agent AUTONOMOUSLY APPLIES TO JOBS — can browse job sites, tailor CV, fill forms, submit"). The LLM returns **only the agent name** (e.g. `comms_agent`) or `CHAT`, with `max_tokens=20`.

If classify fails (cloud offline, unexpected output), [`match_agent()`](../friday/core/router.py) at `router.py:181` runs the regex fallback — hundreds of patterns grouped by agent (comms, social, household, monitor, job, watch, cron, deep_research, screen, research, system, code, memory) with context-aware follow-up detection (`recent_agent_context()` at `router.py:494` looks at the last 6 messages and the memory's `get_recent_agent_calls`).

Once an agent is picked, [`FridayCore._dispatch()`](../friday/core/orchestrator.py) at `orchestrator.py:581` builds the agent's context (memory recall + last 6 conversation lines), registers a friendly-label `on_tool_call` callback (translates `search_web` → `"searching"`, `fetch_page` → `"reading example.com"`, etc. — see `orchestrator.py:592-689`), and calls `agent.run()`. That's the ReAct loop, covered in section 5.

### Tier 6 — Multi-agent fanout (deep_research_agent)

Triggered when regex hits "deep research", "write a paper", "comprehensive report", "detailed analysis", etc. (see `deep_research_patterns` at `router.py:389`). [`DeepResearchAgent`](../friday/agents/deep_research_agent.py) at `deep_research_agent.py:474` is the only agent that **doesn't** extend `BaseAgent`. Its flow (`deep_research_agent.py:477+`):

1. **Plan** — 1 LLM call to break the task into sections.
2. **Research** — parallel `search_web` + `fetch_page` calls per section (many tool calls, some in parallel).
3. **Write** — section-by-section drafting, each its own LLM call.
4. **Synthesis** — 1 LLM call to stitch.
5. **Save** — writes md/docx/pdf via file tools.

10+ LLM calls, 2-3 minutes, but produces a proper multi-section deliverable.

### Tier 7 — Fallback chat (`SYSTEM_PROMPT` + `dispatch_agent`)

If no earlier tier matched, `_background_work()` falls through to `orchestrator.py:432-474`. It builds the **full** system prompt (section 3), passes `DISPATCH_TOOL` (`prompts.py:341`) as an available function, and calls `cloud_chat`. The LLM either:

- Returns plain text → logged as `llm_fallback_chat`.
- Calls `dispatch_agent` (possibly multiple times) → results are gathered, then [`stream_synthesis()`](../friday/core/orchestrator.py) at `orchestrator.py:727` runs one final `cloud_chat` with a synthesis prompt (`_build_synthesis_messages` at `orchestrator.py:743`) to produce the user-facing answer.

This is the most expensive path — 4+ LLM calls — and is intentionally the last resort.

---

## 3. How the System Prompt Is Assembled

[`_build_system_prompt()`](../friday/core/orchestrator.py) at `orchestrator.py:161`:

```python
def _build_system_prompt(self, user_input: str) -> str:
    memory_context = self.memory.build_context(query=user_input)
    project_context = self.memory.get_project_context()
    current_time = datetime.now().strftime("%A %-I:%M%p")
    return SYSTEM_PROMPT.format(
        personality=get_personality(),
        user_context=user_context_block(),
        memory_context=memory_context,
        project_context=project_context,
        current_time=current_time,
    )
```

It composes five blocks into the `SYSTEM_PROMPT` template (`prompts.py:256`):

| Block | Source | Contents |
|-------|--------|----------|
| `personality` | `get_personality()` at `prompts.py:124` | Identity header + `_CORE_VOICE` voice rules + optional slang/tone from `~/.friday/user.json` |
| `user_context` | `user_context_block()` at `prompts.py:135` | Name, bio, email, GitHub, CV title/summary, top 5 experiences, top 6 projects, skills, education, contact aliases, briefing watchlist |
| `memory_context` | `memory.build_context(query=...)` | Semantic recall from the memory store, scoped to this query |
| `project_context` | `memory.get_project_context()` | What the user is currently working on |
| `current_time` | `datetime.now().strftime("%A %-I:%M%p")` | e.g. `"Sunday 4:37PM"` |

After that, the template hard-codes the agent roster and routing rules (`prompts.py:266-304`) — every agent's capability one-liner and routing hints.

`get_personality_slim()` at `prompts.py:224` is the compact variant used by tiers 2 and 3 — same structure, shorter voice block, no agent roster. Saves ~1500 tokens per turn.

---

## 4. `needs_thinking()` — Reasoning Token Control

[`needs_thinking()`](../friday/core/prompts.py) at `prompts.py:331` is a binary "should we enable reasoning mode" decision. The regex [`COMPLEX_SIGNALS`](../friday/core/prompts.py) at `prompts.py:325` matches:

```
explain | debug | why does | how does | implement | refactor |
architect | design | compare | analyze | write .{20,} | build |
create .{20,}
```

Only when one of those fires does `needs_thinking()` return `True`. Short queries, greetings, and simple tool asks all go through with `think=False` (Ollama) or the `/no_think` prefix (Qwen — injected in `llm.py:192-197`).

The counterpart regex [`SIMPLE_PATTERNS`](../friday/core/prompts.py) at `prompts.py:309` matches greetings, acknowledgements, yes/no, thanks — inputs that should never enable thinking.

Why it matters: Ollama's `think=False` parameter disables the reasoning pipeline at engine level. Measured impact (in `llm.py:39-41` comments): ~1-2s for a simple query with `think=False` vs ~90s with thinking enabled and 1123 tokens wasted on hidden thinking.

---

## 5. BaseAgent — The ReAct Loop

[`BaseAgent.run()`](../friday/core/base_agent.py) at `base_agent.py:100` is the single ReAct loop every agent inherits (except `deep_research_agent`, which is its own thing).

### Loop structure

```
for iteration in range(max_iterations):
    response = cloud_chat(messages, tools=offer_tools, model=self.model)
    tool_calls = extract_tool_calls(response)

    if not tool_calls:
        return AgentResponse(success=True, result=text, ...)

    # Append assistant message (with tool_calls) to history
    # Execute tools (single → direct; multiple → asyncio.gather in parallel)
    # Append tool-role messages with results to history

# Out of iterations → return success=False
```

Key details:

- `max_iterations` defaults to 10 (class attribute at `base_agent.py:73`). Agents override — `MemoryAgent` might be 3, `SystemAgent` higher.
- **Parallel tool execution** (`base_agent.py:241-252`): when the LLM returns multiple tool calls in one response, they run concurrently via `asyncio.gather`.
- **Tool-schema stripping** (`base_agent.py:159-161`): for single-tool agents (`max_iterations <= 2`), tools are dropped from the second iteration onward so the model generates prose instead of re-wasting prompt eval on schemas.
- **Result compaction** (`_compact_data()` at `base_agent.py:16`): large tool results (10 emails with full bodies) are trimmed — emails keep only `id/subject/from/date/snippet/unread/priority`, calendar events keep `title/start_time/end_time/location/video_link`, unknown shapes have string values truncated to 200 chars. Prevents smaller models from being overwhelmed.
- **Media path extraction** (`_extract_paths()` at `base_agent.py:127`): walks tool result data for `saved_path`/`path`/`file_path` keys ending in image/video/audio/pdf extensions, so the UI can render previews as ground truth (no regex on response text).
- **Skill injection** (`base_agent.py:109-114`): `build_skill_context(self.name)` loads markdown instruction docs from `friday/skills/` and appends them to the system prompt.
- **Error handling** (`execute_tool()` at `base_agent.py:85`): unknown tool names return a `ToolResult(success=False, data="Unknown tool: ...")`. Tool exceptions are caught and wrapped as `ToolResult(success=False, data=str(e))`. A max-iterations exit returns `AgentResponse(success=False, error="max_iterations_exceeded")`.
- **Trace logging** (`log_react_trace` calls at `base_agent.py:177` and `base_agent.py:282`): every ReAct run is persisted for fine-tuning.

### tool_call_id handling

OpenAI/Groq APIs require `tool_call_id` on tool-role messages. Local Ollama doesn't produce IDs, so `base_agent.py:196-200` generates synthetic `uuid4` IDs when missing.

---

## 6. Tool Schema Format

Every tool file under `friday/tools/` exports a `TOOL_SCHEMAS` dict. The shape, using `email_tools.py:475` as the reference example:

```python
TOOL_SCHEMAS = {
    "read_emails": {
        "fn": read_emails,                              # async callable
        "schema": {                                     # OpenAI-format function schema
            "type": "function",
            "function": {
                "name": "read_emails",
                "description": "Read emails from Gmail. ...",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filter": {"type": "string", "description": "..."},
                        "limit":  {"type": "integer", "description": "..."},
                        ...
                    },
                    "required": [],
                },
            },
        },
    },
    ...
}
```

The `fn + schema` pairing is the whole contract:

- `fn` is the async Python callable that executes when the LLM picks this tool. It receives keyword arguments exactly matching `schema.function.parameters.properties`.
- `schema` is handed verbatim to the LLM as an available function definition.

Agents register their tools by composing these dicts. [`BaseAgent._build_tool_definitions()`](../friday/core/base_agent.py) at `base_agent.py:79` walks `self.tools` and pulls `tool_info["schema"]` into `self.tool_definitions`. Direct-dispatch does the same in `_build_tools()` at `tool_dispatch.py:108`, merging 15+ tool modules and normalising each schema to the wrapped `{"type": "function", "function": {...}}` form (`tool_dispatch.py:147-152`).

All tools return a [`ToolResult`](../friday/core/types.py) with `success: bool`, `data: Any`, optional `error`. This consistent return shape lets the ReAct loop treat every tool identically when serializing results back to the LLM.

---

## 7. LLM Provider Abstraction

[`cloud_chat()`](../friday/core/llm.py) at `llm.py:127` is provider-agnostic. One function signature, many backends.

### Configuration

Three env-driven knobs in [`config.py`](../friday/core/config.py):

- `USE_CLOUD` — master switch.
- `CLOUD_API_KEY` — any OpenAI-compatible key.
- `CLOUD_BASE_URL` — Groq (`https://api.groq.com/openai/v1`), OpenRouter (`https://openrouter.ai/api/v1`), Together, Fireworks, Modal, Anthropic-via-proxy, OpenAI direct, or a local Ollama endpoint at `http://localhost:11434/v1`.
- `CLOUD_MODEL_NAME` — per-backend model string.

### How it stays provider-agnostic

1. **Client init** (`llm.py:81`): lazy-initialises a single `openai.OpenAI(base_url, api_key)` client. Every OpenAI-compatible provider speaks this dialect.
2. **Tool-schema wrapping** (`llm.py:175-182`): any tool passed in is normalised to `{"type": "function", "function": ...}` if it isn't already — handles both Ollama-style and OpenAI-style input.
3. **Message sanitisation** (`llm.py:149-167`): tool-calls whose arguments are dicts (normalised form) get re-serialised to JSON strings as the OpenAI API requires, with synthetic `id`/`type` fields if missing.
4. **Thinking suppression per model** (`llm.py:191-197`): Qwen 3 needs an explicit `/no_think` token prefix to suppress reasoning; Gemma 4 doesn't. Single switch.
5. **Response normalisation** (`_normalize_openai_response()` at `llm.py:90`): converts OpenAI's `ChatCompletion` object back to the dict shape Ollama's SDK returns (`{"message": {"role": ..., "content": ..., "tool_calls": [...]}}`). This means [`extract_text()`](../friday/core/llm.py) (`llm.py:236`) and [`extract_tool_calls()`](../friday/core/llm.py) (`llm.py:223`) work unchanged against either backend.
6. **Streaming normalisation** (`extract_stream_content()` at `llm.py:294`): extracts content from chunks whether they're Ollama `chunk.message.content`, Ollama dicts, or OpenAI `chunk.choices[0].delta.content`.
7. **Thinking filter** (`_ThinkingFilter` at `llm.py:242`, `_filtered_stream` at `llm.py:276`): stripping `<think>...</think>` blocks from streamed output is handled transparently — downstream code never sees them.
8. **Failure fallback** (`llm.py:213-218`): any cloud exception falls back to local Ollama via `chat()` (`llm.py:11`) with `think=False`. Same normalisation pipeline, same caller contract.

The `chat()` local-Ollama function at `llm.py:11` mirrors `cloud_chat`'s signature exactly and even retries without tools on an Ollama `500` (malformed tool XML) at `llm.py:57-61`.

---

## 8. Conversation State

Conversation lives on the `FridayCore` instance as `self.conversation: list[dict]` (declared at `orchestrator.py:75`). It's a plain list of `{"role": ..., "content": ...}` messages — the OpenAI/Ollama standard shape.

### Lifecycle

- **Appended** by every tier that produces a response. Tiers 1-3 append directly (see `fast_path.py:43-44`, `oneshot.py:259-260`, `oneshot.py:317-318`). Tiers 4-7 append via [`_log_and_append()`](../friday/core/orchestrator.py) at `orchestrator.py:82`, which also writes to the structured training log (`log_turn`) with `session_id`, route label, agent name, tools called, and `duration_ms`.
- **Read** with truncation. Each tier windows differently:
  - fast_chat: `self.conversation[-10:]`, each message truncated to 400 chars (`orchestrator.py:184-186`)
  - oneshot format: `self.conversation[-10:]`, 200 chars each (`oneshot.py:294-299`)
  - direct dispatch: `conversation[-10:]`, 300 chars each (`tool_dispatch.py:234`)
  - classify_intent: `conversation[-2:]`, 200 chars (`router.py:153`)
  - full process / fallback chat: `self.conversation[-20:]` (`orchestrator.py:484`, `535`)
  - agent context: `self.conversation[-6:]`, 300 chars (`orchestrator.py:694-702`)
- **Survives across turns** for the lifetime of the `FridayCore` instance. A new session starts a new `session_id` (`orchestrator.py:76`) but the in-memory list is per-process.
- **Persistence** is via the memory store (`get_memory_store()` at `orchestrator.py:74`) and `log_turn()` / `log_react_trace()` in [`conversation_log`](../friday/memory/conversation_log.py). The raw `self.conversation` list itself is not persisted across process restarts — it's the short-term working memory. Long-term recall comes from `memory.build_context(query=...)` which queries the store.

### Auto-learn hook

`_log_and_append()` also fires [`_auto_learn()`](../friday/core/orchestrator.py) at `orchestrator.py:105`. It scans the user's new input for correction signals ("wrong", "that's not what i", "you didn't", "i said"), and if detected, stores a structured correction memory via `store_memory` with `category="correction", importance=8` — so future agent runs can `search_memory` and avoid the same failure mode.

### Confirmation routing

`self._last_agent` (`orchestrator.py:80`) is set whenever a dispatch completes. Bare "yes" / "go ahead" / "do it" inputs at `orchestrator.py:371` re-dispatch to that agent instead of being misrouted to chat.

---

## 9. Request Flow Diagram

```
                                    user input
                                        │
                                        ▼
                          ┌──────────────────────────┐
                          │  _background_work()      │
                          │  (orchestrator.py:244)   │
                          └─────────────┬────────────┘
                                        │
         ┌──────────────────────────────┼───────────────────────────────┐
         │                              │                               │
         ▼                              ▼                               ▼
┌─────────────────┐      ┌─────────────────────────┐      ┌──────────────────────┐
│ Tier 1:         │      │ Priority 1 / 1.5 / 2.7  │      │ SMS-delivery strip   │
│ fast_path()     │      │  - briefing regex       │      │ (orchestrator:263)   │
│  regex → tool   │      │  - @agent override      │      └──────────────────────┘
│  (0 LLM)        │      │  - "yes" re-dispatch    │
└────────┬────────┘      └────────────┬────────────┘
         │ match                      │ match
         ▼                            ▼
    ┌─────────┐                  ┌──────────┐
    │ return  │                  │ dispatch │
    └─────────┘                  └──────────┘
         │ no match
         ▼
┌─────────────────┐
│ Tier 3:         │  regex → tool → _oneshot_format (1 LLM)
│ try_oneshot()   │────────── match ──────────▶ stream response, return
└────────┬────────┘
         │ no match
         ▼
┌─────────────────┐
│ Tier 4:         │  1 LLM picks tool → execute → 1 LLM formats
│ try_direct_     │────────── match ──────────▶ stream response, return
│ dispatch()      │
└────────┬────────┘
         │ NEEDS_AGENT / NO_TOOL / bail
         ▼
┌─────────────────┐
│ Tier 5:         │  classify_intent (LLM, ~1s) → agent_name
│ router +        │       or match_agent (regex fallback)
│ _dispatch()     │             │
└────────┬────────┘             ▼
         │          ┌─────────────────────────┐
         │          │ BaseAgent.run() ReAct   │
         │          │ loop: up to 10 cycles   │
         │          │ of cloud_chat(tools)    │
         │          │ → execute → append      │
         │          └────────────┬────────────┘
         │                       │
         │                       ▼
         │                  stream, return
         │ no match
         ▼
┌─────────────────┐
│ Tier 2:         │  slim personality + last 10 msgs (1 LLM)
│ is_likely_chat  │────── match ───▶ _fast_chat() streams, return
└────────┬────────┘
         │ no match
         ▼
┌─────────────────┐
│ Tier 7:         │  full SYSTEM_PROMPT + DISPATCH_TOOL
│ LLM fallback    │  ├─ plain text → return
│                 │  └─ tool_calls → _dispatch each → stream_synthesis
└─────────────────┘

Tier 6 (deep_research_agent) is reached via Tier 5 when classify_intent or
regex picks "deep_research_agent" — it runs its own 10+ LLM multi-step pipeline
outside the BaseAgent ReAct loop.
```

### End-to-end LLM-call budget

| Path | LLM Calls | Typical Latency |
|------|-----------|-----------------|
| Tier 1 (TV on, greeting) | 0 | <1s |
| Tier 3 instant (screenshot, volume) | 0 | <1s |
| Tier 3 formatted (email check, calendar) | 1 | 2-4s |
| Tier 2 (fast_chat) | 1 | 1-2s |
| Tier 4 (direct dispatch) | 2 | 3-6s |
| Tier 5 (simple agent, 1 tool) | 3 | 5-10s |
| Tier 5 (complex agent, 3-4 tools) | 5-6 | 15-30s |
| Tier 6 (deep research paper) | 10+ | 2-3 min |
| Tier 7 (multi-agent fallback + synthesis) | 4+ | 10-30s |

The cascade exists because hitting tier 1 for "turn on TV" is 90x faster than routing that same request through tier 7, and the user-facing difference between those two paths is the difference between "assistant" and "agent framework demo".

---

## File Map

- [orchestrator.py](../friday/core/orchestrator.py) — `FridayCore`, `_background_work`, `_dispatch`, `_build_system_prompt`, `_log_and_append`, `stream_synthesis`
- [fast_path.py](../friday/core/fast_path.py) — Tier 1 regex matcher
- [oneshot.py](../friday/core/oneshot.py) — Tier 3 regex + 1 LLM format
- [tool_dispatch.py](../friday/core/tool_dispatch.py) — Tier 4 direct dispatch, `TOOL_NAMES` registry
- [router.py](../friday/core/router.py) — `classify_intent` LLM classifier, `match_agent` regex fallback, `needs_agent`, `is_likely_chat`, `recent_agent_context`
- [prompts.py](../friday/core/prompts.py) — `SYSTEM_PROMPT`, `get_personality`, `get_personality_slim`, `user_context_block`, `needs_thinking`, `DISPATCH_TOOL`
- [llm.py](../friday/core/llm.py) — `chat` (local Ollama), `cloud_chat` (OpenAI-compatible), `extract_tool_calls`, `extract_text`, `extract_stream_content`, `_ThinkingFilter`
- [base_agent.py](../friday/core/base_agent.py) — `BaseAgent.run` ReAct loop, `execute_tool`, `_compact_data`, `_extract_paths`
- [deep_research_agent.py](../friday/agents/deep_research_agent.py) — Tier 6 multi-agent fanout (plan → parallel research → write → synthesise → save)
- [types.py](../friday/core/types.py) — `ToolResult`, `AgentResponse` dataclasses
