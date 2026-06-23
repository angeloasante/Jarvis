# Project Structure

A map of the FRIDAY codebase for contributors. Shows where every important piece lives, what each module does, and where to put new code.

If you're new to the repo, start here and then jump into [core/orchestrator.py](../friday/core/orchestrator.py) — that's the entry point everything routes through.

---

## 1. Top-level tree

```
JARVIS/
├── friday/                  ← the Python package (pip-installable as friday-os)
│   ├── __init__.py
│   ├── cli.py               ← `friday` command entry point
│   ├── agents/              ← ReAct specialist agents
│   ├── background/          ← heartbeat, cron, monitors, GitHub sync
│   ├── core/                ← orchestrator, router, LLM client, base agent
│   ├── data/                ← shipped data (CV loader, Google OAuth client)
│   ├── memory/              ← ChromaDB + SQLite memory, conversation log
│   ├── skills/              ← SKILL.md instruction files for agents
│   ├── sms/                 ← Twilio webhook server
│   ├── tools/               ← every callable tool the agents can use
│   ├── vision/              ← MediaPipe gesture control
│   ├── voice/               ← STT, TTS, VAD, wake word, pipeline
│   └── whatsapp/            ← Baileys Node bridge for WhatsApp
├── Friday-mac/              ← SwiftUI menu-bar app (mentioned only)
├── Friday-glasses/          ← glasses prototype (Node + Blender)
├── docs/                    ← documentation (including this file)
├── tests/                   ← benchmark + integration tests
├── install.sh               ← one-shot installer script
├── pyproject.toml           ← package + build config
├── README.md                ← primary docs for end users
├── LICENSE                  ← Apache-2.0
└── NOTICE                   ← attribution notice
```

There is no `CHANGELOG.md` at the repo root yet — release notes live in GitHub Releases.

---

## 2. The `friday/` package

### `friday/cli.py`

Entry point for the `friday` command (wired via `pyproject.toml` `[project.scripts]`). Handles REPL, voice mode, and subcommands like `friday init`, `friday doctor`, `friday setup`.

File: [cli.py](../friday/cli.py)

---

### `friday/agents/` — ReAct specialists

Each agent is a `BaseAgent` subclass with a scoped set of tools and a system prompt. The orchestrator picks one agent per task.

| File | Purpose |
|---|---|
| [briefing_agent.py](../friday/agents/briefing_agent.py) | Synthesises monitor alerts, email, calendar into morning / quick briefings. |
| [code_agent.py](../friday/agents/code_agent.py) | Reads, writes, debugs, runs code. The hands of FRIDAY. |
| [comms_agent.py](../friday/agents/comms_agent.py) | Email, calendar, iMessage, FaceTime, WhatsApp, contacts. |
| [deep_research_agent.py](../friday/agents/deep_research_agent.py) | Multi-agent pipeline: planner → parallel executor → parallel writers → assembler. |
| [household_agent.py](../friday/agents/household_agent.py) | Smart home (LG TV via WebOS). Fast-path patterns skip the LLM. |
| [job_agent.py](../friday/agents/job_agent.py) | Autonomous job applications — find JD, tailor CV, fill form, submit. |
| [memory_agent.py](../friday/agents/memory_agent.py) | Stores / retrieves long-term memory with categories + importance. |
| [monitor_agent.py](../friday/agents/monitor_agent.py) | CRUD over persistent watchers on URLs, searches, topics. |
| [research_agent.py](../friday/agents/research_agent.py) | Fast 2-call research loop: pick tools + fetch, then answer. |
| [social_agent.py](../friday/agents/social_agent.py) | X (Twitter) — posts, searches, mentions, engagement. |
| [system_agent.py](../friday/agents/system_agent.py) | Mac control, browser automation, file ops, terminal. |

**Start here as a contributor:**
1. [core/base_agent.py](../friday/core/base_agent.py) — the ReAct loop all agents share.
2. [agents/research_agent.py](../friday/agents/research_agent.py) — simplest custom agent, good template.
3. [agents/system_agent.py](../friday/agents/system_agent.py) — shows how to conditionally load tool sets.

---

### `friday/background/` — long-running workers

Processes that run outside the request-response loop.

| File | Purpose |
|---|---|
| [cron_scheduler.py](../friday/background/cron_scheduler.py) | User-defined cron jobs; APScheduler runs them and fires through the orchestrator. |
| [github_sync.py](../friday/background/github_sync.py) | Pulls all GitHub repos into the projects DB every 6 hours. |
| [heartbeat.py](../friday/background/heartbeat.py) | Proactive awareness loop — static checks (email, monitors) + dynamic watch tasks. |
| [memory_processor.py](../friday/background/memory_processor.py) | Extracts structured memories from conversations in a background thread. |
| [monitor_scheduler.py](../friday/background/monitor_scheduler.py) | Runs all active monitors on their schedules, queues alerts for briefings. |

Heartbeat is the most important one to understand — it's where autonomy lives.

---

### `friday/core/` — the brain

The orchestrator, router, LLM client, prompts, and the ReAct base class. Everything else in `friday/` depends on this.

| File | Purpose |
|---|---|
| [base_agent.py](../friday/core/base_agent.py) | ReAct loop (THOUGHT → ACTION → OBSERVATION → ANSWER). All agents inherit this. |
| [briefing.py](../friday/core/briefing.py) | Parallel tool calls + 1 LLM synthesis (replaces old 12-call flow). |
| [config.py](../friday/core/config.py) | Model selection, paths, env loading. Single source of truth for settings. |
| [fast_path.py](../friday/core/fast_path.py) | Zero-LLM regex matches for greetings and trivial commands. |
| [llm.py](../friday/core/llm.py) | Wraps Ollama (local) and OpenAI-compatible APIs (cloud). |
| [onboarding.py](../friday/core/onboarding.py) | First-run wizard + `friday config` subcommands. |
| [oneshot.py](../friday/core/oneshot.py) | Regex → direct tool call → 1 LLM format. Skips ReAct for known shapes. |
| [oneshot_runner.py](../friday/core/oneshot_runner.py) | Streams pipeline to stdout as NDJSON for the Swift app. |
| [orchestrator.py](../friday/core/orchestrator.py) | **Top-level entry**. Routes tasks, never does them itself. |
| [prompts.py](../friday/core/prompts.py) | Personality + system prompt templates, rendered against `USER`. |
| [router.py](../friday/core/router.py) | Intent classification — LLM primary, regex fallback. |
| [setup_wizard.py](../friday/core/setup_wizard.py) | `friday doctor`, `friday setup <x>`, `friday test <x>`. |
| [tool_dispatch.py](../friday/core/tool_dispatch.py) | 2-call flow: 1 LLM picks tool, execute, 1 LLM formats. Priority 2.5. |
| [types.py](../friday/core/types.py) | `ToolResult`, `AgentResponse`, `ErrorCode`, `Severity` — shared types. |
| [user_config.py](../friday/core/user_config.py) | Loads `~/Friday/user.json` and exposes the `USER` singleton. |

**Start here as a contributor:**
1. [orchestrator.py](../friday/core/orchestrator.py) — understand the routing priorities.
2. [router.py](../friday/core/router.py) — how intent → agent is decided.
3. [base_agent.py](../friday/core/base_agent.py) — how a tool call actually runs.
4. [types.py](../friday/core/types.py) — every tool returns `ToolResult`, learn its shape.
5. [fast_path.py](../friday/core/fast_path.py) → [oneshot.py](../friday/core/oneshot.py) → [tool_dispatch.py](../friday/core/tool_dispatch.py) → agent dispatch — in that order, the four tiers of increasing LLM cost.

---

### `friday/data/` — shipped data

| File | Purpose |
|---|---|
| [cv.py](../friday/data/cv.py) | CV loader. Re-exports `CV` from `~/Friday/user.json` for back-compat. |
| `google_client.json` | Bundled OAuth client so users don't need their own GCP project. |

---

### `friday/memory/` — persistence

| File | Purpose |
|---|---|
| [conversation_log.py](../friday/memory/conversation_log.py) | Append-only JSONL log of every turn — used for fine-tuning datasets. |
| [store.py](../friday/memory/store.py) | ChromaDB (semantic) + SQLite (structured) memory backend. |

---

### `friday/skills/` — agent instructions

Markdown instruction files that tell agents *how* to think. Loaded at runtime by [skills/loader.py](../friday/skills/loader.py). Each skill is a folder containing a `SKILL.md` with YAML frontmatter (name, description, agents) and a markdown body.

Shipped skills:

```
adaptive_reasoning/   code_workflow/    humanize_text/
image_tools/          job_analysis/     marketing_strategy/
memory_first/         pdf_toolkit/      powerpoint/
proactive_execution/  self_improving/   web_research/
youtube_watcher/      browser_use/      frontend_design/
```

Two directories are scanned:
- `friday/skills/` — shipped with the repo (generic, visible here).
- `~/.friday/skills/` — user-specific, gitignored, takes precedence.

---

### `friday/sms/` — Twilio webhook

| File | Purpose |
|---|---|
| [server.py](../friday/sms/server.py) | Flask-style webhook receiving inbound SMS, piping through the orchestrator, replying via Twilio. |

Run with `python -m friday.sms.server`, expose via ngrok, point Twilio webhook at `/sms`.

---

### `friday/tools/` — the callable surface

Every tool agents can call. Each file exports a `TOOL_SCHEMAS` dict mapping tool name → JSON schema, plus the async implementations.

| File | Purpose |
|---|---|
| [briefing_tools.py](../friday/tools/briefing_tools.py) | Pulls monitor alerts, emails, calendar into daily digests. |
| [browser_tools.py](../friday/tools/browser_tools.py) | **v2** — persistent Chromium daemon with accessibility-tree refs. |
| [browser_tools_old.py](../friday/tools/browser_tools_old.py) | Legacy Safari + AppleScript browser control (kept as fallback). |
| [calendar_tools.py](../friday/tools/calendar_tools.py) | Read / create events via macOS Calendar AppleScript (iCloud, Google, Exchange). |
| [call_tools.py](../friday/tools/call_tools.py) | Phone / FaceTime / WhatsApp call history from local DBs. |
| [cron_tools.py](../friday/tools/cron_tools.py) | CRUD over user cron jobs; pairs with `background/cron_scheduler.py`. |
| [cv_tools.py](../friday/tools/cv_tools.py) | CV fetch, tailor, cover letter, PDF generation (WeasyPrint). |
| [email_tools.py](../friday/tools/email_tools.py) | Gmail read / send / draft / search / label. |
| [file_tools.py](../friday/tools/file_tools.py) | Read, write, list, search files — with line ranges and depth control. |
| [github_tools.py](../friday/tools/github_tools.py) | Repo info, commits, issues via the `gh` CLI (no Python deps). |
| [google_auth.py](../friday/tools/google_auth.py) | OAuth2 helper shared by Gmail + Calendar. |
| [imessage_tools.py](../friday/tools/imessage_tools.py) | Send / read iMessages, initiate FaceTime calls. |
| [mac_tools.py](../friday/tools/mac_tools.py) | AppleScript, app launcher, screenshots. |
| [memory_tools.py](../friday/tools/memory_tools.py) | Store / retrieve memory — thin wrapper over `memory/store.py`. |
| [monitor_tools.py](../friday/tools/monitor_tools.py) | Create and manage persistent URL / search / topic watchers. |
| [notify.py](../friday/tools/notify.py) | iMessage-to-self + Twilio SMS notifications. |
| [pdf_tools.py](../friday/tools/pdf_tools.py) | Read, merge, split, encrypt, watermark PDFs. |
| [screen_tools.py](../friday/tools/screen_tools.py) | Screenshot + macOS Vision OCR + Qwen2.5-VL screen understanding. |
| [screencast_tools.py](../friday/tools/screencast_tools.py) | AirPlay / Screen Mirroring via Control Center UI automation. |
| [sms_tools.py](../friday/tools/sms_tools.py) | Outbound SMS via Twilio (inbound lives in `sms/server.py`). |
| [terminal_tools.py](../friday/tools/terminal_tools.py) | Shell commands + background process management with safety checks. |
| [tv_tools.py](../friday/tools/tv_tools.py) | LG TV local WebOS + WakeOnLan (power, volume, apps, media). |
| [watch_tools.py](../friday/tools/watch_tools.py) | Create / list / cancel dynamic standing orders (heartbeat watches). |
| [web_tools.py](../friday/tools/web_tools.py) | Tavily search + httpx raw page fetching. |
| [whatsapp_tools.py](../friday/tools/whatsapp_tools.py) | Talks to the Baileys Node bridge on `localhost:3100`. |
| [x_tools.py](../friday/tools/x_tools.py) | X / Twitter posting, search, mentions via tweepy. |

**Start here as a contributor:**
1. [file_tools.py](../friday/tools/file_tools.py) — simplest, no external service. Good template for a new tool.
2. [web_tools.py](../friday/tools/web_tools.py) — shows how to handle an external API + env var keys.
3. [email_tools.py](../friday/tools/email_tools.py) — shows the full OAuth + async pattern.

---

### `friday/vision/` — gesture control

MediaPipe hand tracking. Two-hand combos, pinch drag, all local on CPU.

| File | Purpose |
|---|---|
| [__init__.py](../friday/vision/__init__.py) | Suppresses MediaPipe / TFLite noise before any import. |
| [gesture_commands.py](../friday/vision/gesture_commands.py) | Loads gesture-to-command mapping from `.env`, hot-reloadable. |
| [gesture_daemon.py](../friday/vision/gesture_daemon.py) | Standalone daemon spawned by the Mac app on `/gestures-on`. |
| [gesture_engine.py](../friday/vision/gesture_engine.py) | MediaPipe GestureRecognizer + custom pinch detection (~30fps on M-series). |
| [gesture_listener.py](../friday/vision/gesture_listener.py) | Daemon thread + asyncio bridge, same shape as the voice pipeline. |

---

### `friday/voice/` — speech pipeline

Always-on ambient listening. Auto-switches between cloud and local depending on whether `ELEVENLABS_API_KEY` is set.

| File | Purpose |
|---|---|
| [cloud_stt.py](../friday/voice/cloud_stt.py) | ElevenLabs Scribe v2 Realtime via WebSocket (~150ms). |
| [config.py](../friday/voice/config.py) | Audio + VAD + voice constants (16kHz, 512-sample frames). |
| [pipeline.py](../friday/voice/pipeline.py) | Always-on ambient listener; wake-word in rolling transcript buffer. |
| [response_filter.py](../friday/voice/response_filter.py) | Strips code / markdown / URLs before TTS. |
| [stt.py](../friday/voice/stt.py) | MLX Whisper wrapper (Apple Silicon local STT). |
| [tts.py](../friday/voice/tts.py) | ElevenLabs Flash v2.5 streaming primary, Kokoro ONNX fallback. |
| [vad.py](../friday/voice/vad.py) | Silero VAD wrapper. |
| [wake_word.py](../friday/voice/wake_word.py) | OpenWakeWord wrapper (currently optional — pipeline uses transcript matching). |

---

### `friday/whatsapp/` — Baileys bridge

A small Node.js HTTP server (`server.js` + `package.json`) that runs WhatsApp Web multi-device auth and exposes send / read over `localhost:3100`. Auto-started the first time a WhatsApp tool is called from [whatsapp_tools.py](../friday/tools/whatsapp_tools.py).

---

## 3. Peer top-level directories

### `Friday-mac/`

SwiftUI menu-bar app. Spawns the Python orchestrator as a subprocess and reads NDJSON events over stdout (see [core/oneshot_runner.py](../friday/core/oneshot_runner.py)). Full Xcode project under `Friday-mac/Friday/`.

### `Friday-glasses/`

Early-stage glasses prototype — Node server (`server.js`), a Discord puller, Blender reference assets. Not yet wired to the main package.

### `docs/`

End-user + contributor documentation.

| File | What |
|---|---|
| [app-spec.md](./app-spec.md) | Mac app spec. |
| [friday-glasses-integration.md](./friday-glasses-integration.md) | Glasses integration plan. |
| [gesture-control.md](./gesture-control.md) | Gesture mappings + MediaPipe notes. |
| [mac-app.md](./mac-app.md) | Mac app build + run. |
| [ollama-setup.md](./ollama-setup.md) | Local inference setup. |
| [progress.md](./progress.md) | Running dev log. |
| [project-structure.md](./project-structure.md) | This file. |
| [sms-setup.md](./sms-setup.md) | Twilio webhook setup. |
| [user-config.md](./user-config.md) | Schema for `~/Friday/user.json`. |
| [user.example.json](./user.example.json) | Example user config to copy. |
| [whatsapp-setup.md](./whatsapp-setup.md) | Baileys bridge setup + pairing. |

### `tests/`

Benchmarks — provider speed, tool accuracy, streaming latency, full-architecture comparisons. Not unit tests in the traditional sense; they run against live models.

| File | What |
|---|---|
| `test_3way_fair.py` | Parallel 3-provider benchmark with 20s timeouts. |
| `test_full_benchmark.py` | Gemma 4 31B vs Qwen3-32B across all three LLM paths. |
| `test_gemma_vs_qwen.py` | Head-to-head tool-calling accuracy + speed. |
| `test_production_benchmark.py` | Real prompts, all 32 tools, 3 providers. |
| `test_streaming_and_vision.py` | Streaming TTFT + vision + audio. |
| `test_top3_providers.py` | End-to-end pipeline on top 3 OpenRouter providers. |

### Installer and manifests

- `install.sh` — one-shot installer. Checks deps, installs the package, wires the CLI, runs `friday init`.
- `pyproject.toml` — see below.
- `README.md` — primary end-user docs.
- `LICENSE` — Apache-2.0.
- `NOTICE` — attribution.

---

## 4. Runtime layout (where things live on disk)

FRIDAY splits state into a **visible** config and a **hidden** runtime directory.

### `~/Friday/` (visible, in Finder)

| Path | What |
|---|---|
| `~/Friday/user.json` | Single source of truth for identity, tone, slang, contacts, CV, briefing watchlist. Chmod 600. Loaded by [core/user_config.py](../friday/core/user_config.py). |
| `~/Friday/README.md` | Auto-written explainer so the user knows what the folder is. |

### `~/.friday/` (hidden runtime)

| Path | What |
|---|---|
| `~/.friday/.env` | Per-user secrets (API keys). Loaded ahead of repo `.env`. |
| `~/.friday/google_token.json` | Gmail + Calendar OAuth tokens. |
| `~/.friday/google_credentials.json` | Optional BYO OAuth client (bundled one is used by default). |
| `~/.friday/friday.db` | SQLite — crons, monitors, projects, structured memory. |
| `~/.friday/browser_data/` | Persistent Chromium profile for [browser_tools.py](../friday/tools/browser_tools.py) v2. |
| `~/.friday/whatsapp/` | Baileys auth state for the WhatsApp bridge. |
| `~/.friday/models/` | Downloaded local models (Whisper, Kokoro, OpenWakeWord). |
| `~/.friday/skills/` | User-added skills; override shipped ones with the same name. |

Additional runtime-ish paths:
- `data/training/conversations.jsonl` — append-only log written by [memory/conversation_log.py](../friday/memory/conversation_log.py) for fine-tuning datasets.
- ChromaDB collections live under `~/.friday/` (managed by [memory/store.py](../friday/memory/store.py)).

---

## 5. Build and packaging

FRIDAY ships as `friday-os` on PyPI. Everything is declarative in [pyproject.toml](../pyproject.toml):

```toml
[project]
name = "friday-os"
version = "0.4.0"
requires-python = ">=3.12"

[project.scripts]
friday = "friday.cli:run"

[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["friday*"]
exclude = ["tests*", "docs*"]

[tool.setuptools.package-data]
"friday" = ["skills/**/*", "data/**/*.json"]
```

Key points:
- **Entry point** — `friday = "friday.cli:run"` exposes the `friday` command after `pip install`.
- **Packages** — anything under `friday/` is included; `tests/` and `docs/` are not.
- **Package data** — shipped skills (every `SKILL.md` under `friday/skills/`) and bundled JSON under `friday/data/` (the Google OAuth client) are included in the wheel so first run works with zero external setup.
- **Dependencies** — pinned minimums in `[project] dependencies`. See the file for the full list (ChromaDB, Ollama, Playwright, MLX Whisper, Kokoro, MediaPipe, Twilio, tweepy, WeasyPrint, etc.).

To build locally:

```bash
uv pip install -e .        # editable dev install
uv build                   # produce sdist + wheel in dist/
```

The Mac app at `Friday-mac/` bundles its own Python runtime — see `Friday-mac/build_bundle.sh`.

---

## 6. Contributing conventions

### Adding a new tool

1. Create `friday/tools/my_tool.py`.
2. Define async functions that return `ToolResult` (from [core/types.py](../friday/core/types.py)). Never raise — wrap in `ToolResult(ok=False, error=ToolError(...))`.
3. Export a `TOOL_SCHEMAS` dict at module level:
   ```python
   TOOL_SCHEMAS = {
       "my_function": {
           "type": "function",
           "function": {
               "name": "my_function",
               "description": "...",
               "parameters": { ... json schema ... },
           },
       },
   }
   ```
4. Import the schemas into the agent(s) that should expose it — e.g. in [agents/system_agent.py](../friday/agents/system_agent.py):
   ```python
   from friday.tools.my_tool import TOOL_SCHEMAS as MY_TOOLS
   ```
5. Register the callable in [core/tool_dispatch.py](../friday/core/tool_dispatch.py) if it should be reachable from the fast 2-call path.
6. If it uses secrets, document the env var in `docs/` and add a `friday setup` clause in [core/setup_wizard.py](../friday/core/setup_wizard.py).

Pattern templates: [file_tools.py](../friday/tools/file_tools.py) (pure stdlib), [web_tools.py](../friday/tools/web_tools.py) (API + env keys), [email_tools.py](../friday/tools/email_tools.py) (OAuth + async).

### Adding a new agent

1. Create `friday/agents/my_agent.py` subclassing `BaseAgent` from [core/base_agent.py](../friday/core/base_agent.py).
2. Write a tight system prompt — keep it under ~500 tokens so small models (9B) can still follow it. Look at [agents/social_agent.py](../friday/agents/social_agent.py) for a minimal example.
3. Import only the `TOOL_SCHEMAS` you actually need; small tool sets → better tool selection.
4. Register the agent in [core/orchestrator.py](../friday/core/orchestrator.py)'s dispatch table and add a routing rule in [core/router.py](../friday/core/router.py) (both LLM classification prompt and regex fallback).
5. Add routing fixtures to [tests/test_production_benchmark.py](../tests/test_production_benchmark.py) so regressions get caught.

### Adding a new skill

1. Create `friday/skills/my_skill/SKILL.md`.
2. Start with YAML frontmatter, then markdown instructions:
   ```markdown
   ---
   name: my-skill
   description: One line describing when to use this skill.
   agents: [research_agent, code_agent]
   ---
   # Instructions
   ...
   ```
3. Skills are auto-discovered by [skills/loader.py](../friday/skills/loader.py) — no registration needed.
4. For user-specific skills, drop them in `~/.friday/skills/` instead — they override shipped skills with the same name and stay out of git.
5. Make sure the skill folder is picked up by the wheel — it already is via the `"friday" = ["skills/**/*", ...]` glob in `pyproject.toml`.

### Style

- Async everywhere tools touch I/O (`httpx`, `aiofiles`, subprocess wrappers).
- Every tool returns `ToolResult`, never raises past its own boundary.
- Match the style of the file you're editing — no reformatting drive-bys.
- No silent failures. Errors go into `ToolResult.error` with the right `ErrorCode` from [core/types.py](../friday/core/types.py).
- No hardcoded secrets; read from env via [core/config.py](../friday/core/config.py).
- Comments for the *why*, not the *what*.

### Commits and PRs

- Conventional messages (`feat:`, `fix:`, `docs:`, `refactor:`). Look at `git log` for the house style.
- Keep diffs focused — one concern per PR.
- Run the relevant benchmarks in `tests/` when you change routing, prompts, or tool-calling logic.
