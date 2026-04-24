# Improvement Mode

Reference for FRIDAY's self-improvement capabilities: how she adapts at
runtime, captures user corrections, replays them into future prompts, and
loads contextual skill instructions.

## 1. What "Improvement Mode" Means

FRIDAY does **not** retrain or fine-tune her underlying model at runtime.
"Improvement mode" is runtime adaptation via two mechanisms:

1. **Memory injection** — corrections, preferences, and successful patterns
   are written to a persistent store and re-injected into the system prompt
   on future turns.
2. **Skill injection** — markdown instruction files (`SKILL.md`) are loaded
   into agent system prompts so behaviour can be tuned by editing a file
   rather than touching code.

The base model weights stay frozen. What changes is the **context** the
model sees on every turn.

A full conversation log is written to
`data/training/conversations.jsonl` for *eventual* fine-tuning, but that
corpus is not used as online-learning input today — see section 8.

## 2. Correction Capture

File: `/Users/travismoore/Desktop/JARVIS/friday/core/orchestrator.py`

After every turn the orchestrator calls `_auto_learn(user_input, response)`.
It scans the new user message for pushback signals and, if one fires,
stores a correction memory.

### Signals watched

```
"thats not what i", "not what i asked", "not what i meant",
"you didnt", "you didn't", "wrong", "that's wrong",
"dumb", "stupid", "slop", "generic", "useless",
"stop doing that", "don't do that", "i already told you",
"how many times", "you missed", "you forgot"
```

### The correction builder

```python
def _auto_learn(self, user_input: str, previous_response: str):
    low = user_input.strip().lower()
    is_correction = any(sig in low for sig in correction_signals)
    if not is_correction:
        return

    prev_friday = ""
    for msg in reversed(self.conversation[:-2]):
        if msg["role"] == "assistant":
            prev_friday = msg["content"][:200]
            break

    correction = (
        f"CORRECTION: When user said something similar to the previous "
        f"message, FRIDAY responded with: \"{prev_friday}...\" "
        f"User corrected: \"{user_input[:150]}\". "
        f"Learn: avoid this response pattern in future."
    )
    asyncio.ensure_future(self._store_correction(correction))
```

### The writer

```python
async def _store_correction(self, correction: str):
    from friday.tools.memory_tools import store_memory
    await store_memory(
        content=correction,
        category="correction",
        importance=8,
    )
```

The write is async so it never blocks the user-facing response. Importance
is hard-coded to 8 (high). Category is `correction`.

## 3. Correction Replay

File: `/Users/travismoore/Desktop/JARVIS/friday/memory/store.py`

On every turn the orchestrator builds its system prompt through
`_build_system_prompt(user_input)`, which calls
`self.memory.build_context(query=user_input)`.

Memories are stored in two backends:

- **SQLite** (`memories` table) — structured with `category`, `importance`,
  timestamps.
- **ChromaDB** — semantic vector index on the same content for similarity
  search.

`MemoryStore.search(query, n_results, category)` runs a cosine-similarity
query over ChromaDB. Relevant memories (including corrections) get
prepended to the system prompt under a `CONTEXT:` header before the user
turn is sent to the model.

Net effect: the next time a similar-looking user query arrives, the model
sees the stored correction as context and adjusts its response.

## 4. Skills System

File: `/Users/travismoore/Desktop/JARVIS/friday/skills/loader.py`

A skill is a folder containing a `SKILL.md` file with YAML frontmatter:

```yaml
---
name: skill-name
description: short description
agents: all            # or [research_agent, job_agent]
---
# Markdown body with instructions for the model
```

Discovery scans two directories:

1. `friday/skills/` — shipped with the repo
2. `~/.friday/skills/` — personal, gitignored, overrides repo skills of
   the same name

### Task-aware injection (current behaviour)

Previously every agent got every matching skill appended to its system
prompt — regardless of what the user actually asked. `job_agent` paid
~22 000 chars (~5 500 tokens) of skill text *per call* even for queries
where none of the skills applied. Worse, `research_agent` and
`deep_research_agent` built their prompts from scratch and **bypassed
the skills system entirely**.

The new path in `base_agent.py` runs a two-stage task-aware selector on
the user's task before building the system prompt:

```python
from friday.skills.selector import build_skill_context_for_task
skill_context = build_skill_context_for_task(self.name, task)
full_system = self.system_prompt
if skill_context:
    full_system += f"\n\n# SKILLS (follow these instructions)\n\n{skill_context}"
```

`research_agent.py` and `deep_research_agent.py` now do the same at their
custom run()/planner prompt assembly, so those paths are no longer
skill-blind.

**Stage 1 — embedding shortlist (`friday/skills/embedder.py`)**

Embeds every skill's `description` field with local Ollama
`nomic-embed-text`. Caches vectors in `~/.friday/skill_embeddings.json`
keyed by a hash of the description — rebuild is automatic when a
description changes. Cosine-similarity ranks all agent-matching skills
and returns the top 5 above `similarity >= 0.3`.

If the embed model isn't pulled (`ollama pull nomic-embed-text`), stage 1
is skipped cleanly — the selector forwards every agent-matching skill to
stage 2 instead.

**Stage 2 — LLM precision pick (`friday/skills/selector.py`)**

Sends the shortlist plus the task to `cloud_chat` with:

```
System: You are a skill router. Given a user's task and a list of
        candidate skills (each with a one-line description), return the
        names of the skills actually useful for THIS task.
        Return ONLY JSON: {"skills": ["name1", "name2"]}. Choose at most 3.
```

JSON back, at most 3 skill names. Those bodies are concatenated under
`## Skill: <name>` headers and injected.

**Shortcuts & fallbacks** (all safe):

- **Trivial tasks** (`hi`, `ok`, `thanks`, under 4 chars) → return `[]`,
  zero skills injected, zero extra LLM calls.
- **Single candidate** after stage 1 → skip the LLM picker.
- **No cloud configured** → return the full shortlist (old behaviour).
- **LLM picker errors / JSON parse fails** → return the full shortlist.

**Observability**

Every selection logs at INFO:

```
friday.skills.selector INFO: skill-select agent=research_agent
  picked=['youtube-watcher', 'web-research', 'memory-first']
  (from 9 candidates)
```

That line is the answer to "did FRIDAY actually use a skill here?". `grep
'skill-select' ~/Library/Logs/friday.log` shows every pick across the
session.

### Shipped skills

| Skill | One-liner |
|-------|-----------|
| `adaptive_reasoning` | Assess task complexity before responding; match effort to complexity. |
| `browser_use` | Advanced browser automation patterns; connect to Chrome, handle SPAs, manage sessions. |
| `code_workflow` | Structured coding workflow — plan, test, verify before delivering. |
| `frontend_design` | Build beautiful modern UIs at startup quality bar. |
| `humanize_text` | Make AI-generated text sound human and natural. |
| `image_tools` | Create, resize, compress, convert, and optimise images. |
| `job_analysis` | Analyse job postings, assess fit, compare to projects, score. |
| `marketing_strategy` | Product marketing, GTM, positioning, launch planning. |
| `memory_first` | Always check memory before searching the web. |
| `pdf_toolkit` | Create, extract, merge, split, manipulate PDFs. |
| `powerpoint` | Create and edit PowerPoint/PPTX presentations. |
| `proactive_execution` | Never ask "should I proceed?"; just do the work. |
| `self_improving` | Learn from corrections, preferences, and patterns via `store_memory`. |
| `web_research` | Research URLs and topics properly — fetch, summarise, opine. |
| `youtube_watcher` | Fetch and summarise YouTube video transcripts. |

### Cache and reload

`discover()` caches the result in module-level `_skills`. Call
`reload()` after editing a skill at runtime.

### Autonomous skill creation

File: `/Users/travismoore/Desktop/JARVIS/friday/skills/creator.py`

After a successful agent task that uses **5+ tools**, FRIDAY silently
drafts a reusable `SKILL.md` from the trace and drops it in
`~/.friday/skills/auto_<slug>/`. This is modelled on the Hermes Agent
pattern and means the skill library grows to fit your actual workflows
without you having to write markdown.

**Trigger conditions** (all must hold):

1. `tools_called >= 5`
2. `success == True`
3. Task text is not trivial (greeting, ack, single word)
4. No existing skill's description has cosine similarity `>= 0.85` to
   the new one — the embedder (`nomic-embed-text`) handles dedup

**Hook points** — three agent paths fire the creator:

- `BaseAgent.run()` — covers every agent that inherits the standard ReAct loop.
- `ResearchAgent.run()` — its two-call optimised path has its own return.
- `DeepResearchAgent.run()` — its multi-section workflow returns separately.

All three call `schedule()` which runs the drafter in a background task,
never blocking the user-visible reply.

**Draft prompt**

The LLM is shown the task, the ordered list of tools used, compact args,
and the final response. It's asked to produce a generalised SKILL.md
(YAML frontmatter + markdown body) that captures the *pattern*, not the
one-off details. Personal names, URLs, IDs are stripped by instruction.

**Safety**

- File is written only if frontmatter has `name`, `description`, and
  non-empty `agents` fields.
- `name` is slugged to kebab-case.
- Directory name is namespaced `auto_<name>` so user-authored skills in
  `~/.friday/skills/` are never overwritten.
- Every decision (created / skipped_duplicate / validation_failed) is
  logged to `~/.friday/skills/auto_creation_log.jsonl` for audit.

**Pruning**

Autogenerated skills go under `~/.friday/skills/auto_*`. To prune, just
`rm -rf` the directory — the skill cache reloads on next agent call.

## 5. The `self_improving` Skill

File: `/Users/travismoore/Desktop/JARVIS/friday/skills/self_improving/SKILL.md`

Applies to **all** agents. It teaches three things:

- **When to learn.** Corrections get importance 8; preferences get 7;
  successful patterns get 6. The skill lists explicit trigger phrases so
  the model recognises each category.
- **When not to learn.** One-time instructions ("just this once"),
  hypotheticals, silence, and casual chat are excluded.
- **The pre-task check.** Before executing, the agent should
  `search_memory` for corrections, preferences, and patterns relevant to
  the incoming task.

The skill documents the feedback loop:

```
Task → search memory → execute with context
     → corrected? store what went wrong
     → praised?   store what went right
     → next time, same task done better
```

Note: the skill tells agents to *proactively* call `store_memory`, while
`_auto_learn` in the orchestrator provides a *fallback* that captures
corrections even if the agent forgets.

## 6. The `adaptive_reasoning` Skill

File: `/Users/travismoore/Desktop/JARVIS/friday/skills/adaptive_reasoning/SKILL.md`

Tells agents to score task complexity 0–10 before responding, with
positive signals (multi-step logic, ambiguity, multiple tools, math,
novelty, high stakes) and negative signals (routine, single answer,
simple lookup).

Response strategy is banded by score:

| Score | Response |
|-------|----------|
| 0–2 | Fast, one sentence, no filler. |
| 3–5 | Standard — brief explanation plus action. |
| 6–7 | Thorough — think through steps, explain reasoning. |
| 8–10 | Deep — full analysis, alternatives, structured output. |

Purpose: stop the model over-reasoning trivial commands ("mute the tv")
while still giving depth for genuinely complex asks.

## 7. The `proactive_execution` Skill

File: `/Users/travismoore/Desktop/JARVIS/friday/skills/proactive_execution/SKILL.md`

Single rule: never ask "should I proceed?" When given a task, execute it
to completion. Exceptions are irreversible actions (sending email,
applying to jobs, spending money), genuinely personal choices, or an
explicit "check with me first" from the user.

Also instructs chaining: fetch → analyse → summarise without stopping.

## 8. Runtime Adaptation vs Fine-Tuning

| Dimension | Memory + Skills (today) | Fine-Tuning (future) |
|-----------|-------------------------|----------------------|
| Scope | Runtime prompt mutation | Model weight update |
| Speed | Takes effect next turn | Hours to days offline |
| Storage | SQLite + ChromaDB | JSONL training corpus |
| Reversibility | Edit/delete a row | Retrain from checkpoint |
| Trigger | `_auto_learn`, `store_memory` | Manual dataset curation |

File: `/Users/travismoore/Desktop/JARVIS/friday/memory/conversation_log.py`

`log_turn(...)` appends every user/response pair to
`data/training/conversations.jsonl` in OpenAI fine-tuning format. Full
ReAct traces are written to `data/training/react_traces.jsonl`.

This corpus is **not** consumed as online learning. It exists so that
later, once there is enough signal, it can be used for a real fine-tune.
Today's adaptation is 100% prompt-side.

## 9. Debugging

### Inspect stored corrections

```bash
sqlite3 ~/.friday/data/friday.db \
  "SELECT id, importance, created_at, content
   FROM memories WHERE category='correction'
   ORDER BY created_at DESC LIMIT 20;"
```

### Inspect all memory categories

```bash
sqlite3 ~/.friday/data/friday.db \
  "SELECT category, COUNT(*) FROM memories GROUP BY category;"
```

### Clear all corrections

```bash
sqlite3 ~/.friday/data/friday.db \
  "DELETE FROM memories WHERE category='correction';"
```

ChromaDB holds a parallel vector copy — wipe the persist dir to fully
reset semantic search:

```bash
rm -rf ~/.friday/data/chroma
```

### Confirm which skills loaded for an agent

```python
from friday.skills.loader import get_skills_for_agent
for s in get_skills_for_agent("research_agent"):
    print(s["name"], "-", s["description"])
```

### Force-reload skills after editing

```python
from friday.skills.loader import reload
reload()
```

### Watch the fine-tune corpus grow

```bash
wc -l data/training/conversations.jsonl
tail -n 1 data/training/conversations.jsonl | jq .
```

### Watch which skills the selector picks

```bash
tail -f ~/Library/Logs/friday.log | grep skill-select
# or in the CLI:
#   friday.skills.selector INFO: skill-select agent=... picked=[...] (from N candidates)
```

### Pre-pull the embedder for stage-1 shortlisting

```bash
ollama pull nomic-embed-text   # 137 MB, one-off
```

Without it, every skill-selection round-trips through `cloud_chat` instead
of taking a <10 ms local path. Nothing breaks — it's just slower and
consumes a free-tier LLM request per agent call.

## Related Files

- `/Users/travismoore/Desktop/JARVIS/friday/core/orchestrator.py`
- `/Users/travismoore/Desktop/JARVIS/friday/core/base_agent.py`
- `/Users/travismoore/Desktop/JARVIS/friday/memory/store.py`
- `/Users/travismoore/Desktop/JARVIS/friday/memory/conversation_log.py`
- `/Users/travismoore/Desktop/JARVIS/friday/skills/loader.py`
- `/Users/travismoore/Desktop/JARVIS/friday/skills/selector.py`
- `/Users/travismoore/Desktop/JARVIS/friday/skills/embedder.py`
- `/Users/travismoore/Desktop/JARVIS/friday/skills/creator.py` (autonomous SKILL.md creation)
- `/Users/travismoore/Desktop/JARVIS/friday/agents/research_agent.py` (task-aware skill injection + autoskill hook)
- `/Users/travismoore/Desktop/JARVIS/friday/agents/deep_research_agent.py` (task-aware skill injection + autoskill hook)
- `~/.friday/skills/auto_*/SKILL.md` (autogenerated skills)
- `~/.friday/skills/auto_creation_log.jsonl` (audit log of every creation decision)
- `/Users/travismoore/Desktop/JARVIS/friday/skills/self_improving/SKILL.md`
- `/Users/travismoore/Desktop/JARVIS/friday/skills/adaptive_reasoning/SKILL.md`
- `/Users/travismoore/Desktop/JARVIS/friday/skills/proactive_execution/SKILL.md`
