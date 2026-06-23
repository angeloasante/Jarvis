# Changelog

All notable changes to FRIDAY. Newest at top. Loosely follows [Keep a Changelog](https://keepachangelog.com), adapted for FRIDAY's phase-based history.

> The `## [Unreleased]` section is regenerated from git commit messages by
> `scripts/changelog.py` (auto-run via the post-commit hook — install with
> `bash scripts/install-hooks.sh`). Cut a release with
> `python scripts/changelog.py --release "Phase N — Title"`.

<!-- changelog-marker: c9b7567 -->

---

## [Unreleased]

### Added
- **Multi-agent orchestration** — one prompt can fan out to several agents. Independent tasks run in parallel (`asyncio.gather`, capped at 4 concurrent); dependent tasks run as a chain with each agent's output threaded into the next. The router declares the shape via a new `depends_on` field on `dispatch_agent`; a heuristic infers a chain when the prompt sequences ("...then...then...") but the router forgot to mark it.
- **`~/Friday/SOUL.md`** — a user-owned, plain-text identity layer (à la Hermes' SOUL.md). Read fresh into every personality prompt, above the built-in voice rules.
- **Action-claim "lie guard"** — when a response claims action ("I'll fetch X", "running in the background", "Message sent via Telegram") but zero agents actually ran this turn, FRIDAY detects the lie via a per-turn ground-truth counter and escalates to actually do the work.
- **Multi-task routing gate** — prompts that clearly contain more than one task skip the single-task fast paths and go straight to the multi-agent router.
- **Dynamic dispatch enum** — the router's agent list is built from the live registry, so optional agents (e.g. the gitignored investigation_agent) become dispatchable only when present.
- **Browser-extension bridge** — Chrome extension + Python WebSocket bridge so agents act in the user's real, logged-in Chrome (anti-bot pages, logged-in sessions). Coexists with the Playwright path. Docs: `docs/browser-extension.md`.
- **Investigation / OSINT agent** (private, gitignored) — Companies House, Police, GOV.UK, Gazette, insolvency register, WHOIS, Wayback, HIBP, TinEye reverse-image, online-presence + Ghana-press search, report compiler. Docs: `docs/investigation.md` (incl. SpiderFoot + Holehe/Sherlock/Maigret hybrid roadmap).
- **`/logs` REPL command** — logs now go to an in-memory ring buffer + rotating file at `~/Friday/logs/friday.log`; `/logs [n]` shows the last n lines. Terminal stays clean.
- **`scripts/changelog.py` + post-commit hook** — CHANGELOG auto-generated from commit messages.

### Changed
- **Job agent** — wired in GitHub tools + a mandatory "FIT ASSESSMENT" workflow; CV tailoring rebuilt around small structured deltas (summary + reorder + bullet additions) instead of the model emitting a full CV dict; experience entries now each render as their own block; official name **Angelo Asante** used on all CVs.
- **Routing** — fit-questions, OSINT, and "send via Telegram" now route deterministically (job_agent / investigation_agent / comms_agent) instead of misrouting to research or system_agent; URL-bearing prompts never fall to chat.
- **Telegram** — `send_telegram_document` fuzzy-matches a hallucinated filename to the real artifact on disk.
- **Web search** — Tavily → Firecrawl → DuckDuckGo cascade.

### Fixed
- Telegram/SMS bridges, voice barge-in false-triggers from TV/ambient, DOM extraction returning empty body on some sites, conversation-context truncation losing prior-turn job descriptions.

---

## Phase 6 — Open Source Prep & Distribution  *(2026-04-21 → 2026-04-22)*

### Added
- **Per-user config** at `~/Friday/user.json` — single source of truth for identity, bio, tone, slang, contact aliases, CV, briefing watchlist. Injected into every system prompt.
- **CLI admin surface** — `friday onboard` (QuickStart/Advanced guided flow), `friday init` (profile wizard), `friday doctor` (audit), `friday update` (install-method-aware upgrade), `friday config` (show/edit/path/open), `friday heartbeat`.
- **`friday setup <component>`** — openrouter (with live model picker), groq, tavily, elevenlabs, x, twilio, gmail, voice, gestures, deps (brew-install auto-fixer).
- **`friday test <component>`** — llm, gmail, twilio, tv connectivity checks.
- **Bundled Google OAuth client** at `friday/data/google_client.json` — Gmail setup becomes "click sign in" instead of a GCP walkthrough.
- **`install.sh`** — curl one-liner bootstraps `uv` + installs `friday-os` from git or PyPI.
- **pip/PyPI-ready package** — renamed to `friday-os`, v0.4.0, Apache 2.0, package-data includes skills + data JSON.
- **18 new docs** under `docs/` — architecture, agents, install, cli-commands, memory, watch-tasks, cron, notifications, deep-research, improvement-mode, screen-vision, tech-stack, llm-providers, project-structure, setup-google, setup-voice, setup-openrouter-groq, setup-tavily.
- **`CHANGELOG.md`** (this file) — extracted from README.

### Changed
- De-personalised every agent and tool prompt — personal context flows from `user.json` at runtime; codebase is open-source ready.
- README slimmed from 1,618 lines by extracting sections to `docs/*.md` + `CHANGELOG.md`.
- Mac app `SettingsView.swift` reads/writes the same `user.json` the CLI uses.
- `fast_path` handles "open `<app>`" with zero LLM calls.

### Fixed
- Missing `screencast_tools`, `oneshot_runner`, `data/__init__.py`, `gesture_daemon` in wheel (commit `324e8de`).
- Gesture camera permission on macOS — `OPENCV_AVFOUNDATION_SKIP_AUTH=1` + clearer error text (commit `25266b0`).

---

## Phase 7 — SMS & Remote Access *(Complete)*

### Added
- **Twilio SMS integration** — text FRIDAY from any phone, full pipeline processing, TwiML replies.
- SMS webhook server on port 3200 — receives inbound, processes through FridayCore, replies.
- SMS tools — `send_sms`, `read_sms` integrated into CommsAgent.
- **Tailscale Funnel** — permanent public HTTPS URL, no ngrok, no dynamic DNS, free.
- Auto-start — SMS server + Tailscale Funnel boot with `uv run friday`, die with Ctrl+C.
- Security — allowed-numbers gate, response truncation, processing timeout.
- Dual Twilio numbers supported — UK (+447367000489) for local, US (+17405588099) for international.

---

## Phase 5 — Skills & Intelligence *(In Progress)*

### Added
- **Skill system** — markdown `SKILL.md` files (same format as OpenClaw/ClawHub) that agents load before executing.
- Skill loader discovers skills from `friday/skills/` (repo) + `~/.friday/skills/` (personal).
- YAML frontmatter: name, description, agents (which agents load it).
- `agents: all` = every agent; `agents: [job_agent, research_agent]` = specific.
- **14 skills shipped**: `proactive-execution`, `adaptive-reasoning`, `memory-first`, `self-improving`, `web-research`, `job-analysis`, `youtube-watcher`, `humanize-text`, `browser-use`, `pdf-toolkit`, `image-tools`, `powerpoint`, `code-workflow`, `marketing-strategy`.
- **Proactive execution** — never ask "should I proceed?", chain steps automatically.
- **Adaptive reasoning** — score task complexity 0-10, match effort to difficulty.
- **Memory first** — check memory before searching web, never say "I don't have info" without searching.
- **Self-improving** — learn from corrections, store preferences, record successful patterns.
- **Web research** — fetch URL flow with JS fallback, search-before-answering pattern.
- **Job analysis** — fetch posting → check memory for projects → score fit → rank projects → give verdict.
- **YouTube watcher** — fetch video transcripts via `yt-dlp`, summarize, answer questions about videos.
- **Humanize text** — strip AI patterns (delve, tapestry, "I'd be happy to"), match natural writing style.
- **Browser use** — snapshot→act→verify pattern, form filling best practices, session persistence.
- **PDF toolkit** — extract text/tables, create, merge, split, rotate PDFs (`pypdf`, `pdfplumber`, `WeasyPrint`).
- **Image tools** — resize, compress, convert, crop images, social-media size presets (`Pillow`, `ffmpeg`).
- **PowerPoint** — create/edit PPTX presentations, pitch deck templates (`python-pptx`).
- **Code workflow** — structured plan→execute→verify→deliver, anti-patterns, git conventions.
- **Marketing strategy** — April Dunford positioning, ICP, competitive battlecards, launch tiers, pricing.
- `fetch_page` auto-fallback — detects JS-only pages, renders with browser automatically.
- `youtube_transcript` tool — yt-dlp transcript extraction + metadata.
- Memory seeded with corrections, patterns, and preferences from real usage.
- Fine-tuning data collection from sessions (JSONL conversation logs).

### Pending
- [ ] QLoRA fine-tune on smaller model (personality + routing baked into weights).
- [ ] Additional agents (Git, Deploy, Database).
- [ ] Self-hosted inference on Modal/RunPod (for privacy or custom fine-tuned models).

---

## Phase 4.7 — Gesture Control *(Complete)*

### Added
- MediaPipe `GestureRecognizer` — 7 built-in gestures per hand, two-hand detection.
- **29 total gestures**: 8 right, 8 left, 7 both hands, 2 mixed combos, 4 pinch drag.
- Custom pinch detection — thumb + index tip distance from landmarks.
- **Pinch drag** — continuous control (volume slider in mid-air, Iron Man style).
- **100% `.env` configured** — every gesture, timing, and threshold customizable without touching code.
- **Wrist-based handedness** — uses wrist x-position instead of MediaPipe's unreliable classifier for left/right.
- **Two-hand frame buffer** — 0.4s buffer merges hands from consecutive frames for reliable combos.
- `/gestures-on`, `/gestures-off`, `/gestures` toggle + `/help` command listing all controls.
- Daemon thread architecture — same pattern as voice pipeline, runs alongside voice simultaneously.
- Hold threshold (0.4s) + cooldown (1.5s) + grace window (0.3s) for flicker tolerance.
- Commands routed through `fast_path` (sub-second TV control) or agent dispatch (briefings).
- C++ log suppression (MediaPipe/TFLite noise silenced at fd level).
- `/gestures` CLI toggle + `FRIDAY_GESTURES=true` env flag.
- Zero GPU — runs on CPU at 30fps via TFLite XNNPACK.

---

## Phase 4.5 — Autonomy: Heartbeat, Cron, Watch Tasks, iMessage, Notifications *(Complete)*

### Added
- **iMessage integration** — read conversations from `chat.db`, send via AppleScript, `NSAttributedString` parsing.
- **FaceTime integration** — initiate video/audio calls, multi-number contact handling.
- **Contact resolution** — fuzzy matching with word-overlap scoring, nickname/emoji support.
- **Heartbeat system** — proactive background loop (30min default), zero-LLM silent ticks, 1 LLM synthesis only when urgent.
- Configurable via `HEARTBEAT.md` — plain English, editable at runtime.
- Quiet hours (1am-7am), daily alert cap (3/day), morning briefing trigger.
- **Cron scheduler** — user-defined scheduled tasks, standard 5-field cron expressions.
- Cron tools — `create_cron`, `list_crons`, `delete_cron`, `toggle_cron` (conversational creation).
- **Standing orders (watch tasks)** — "watch X's messages for the next hour, reply like me".
- Watch-task reasoning — LLM decides if a message needs a reply (skips "okay", "lol", thumbs up).
- **Watch identity switching** — reply as the user or as FRIDAY based on instruction + conversation context.
- Auto-detection — if user introduces FRIDAY or the other person mentions her, she switches to herself.
- **`@friday` tagging** — type `@friday` in iMessage mid-conversation and she jumps in (requires active watch).
- **Deflection rules** — never agrees to calls, money, or plans. Deflects casually.
- Watch deduplication — updating a watch for the same contact modifies the existing one, no duplicates.
- Baseline-first — first tick records state, only replies on genuinely new messages after watch creation.
- **Universal watch system** — keyword dispatch to iMessage, WhatsApp, email, calls, URL, search, topic, or browser executors.
- **Email watch** — reads unread emails, filters by sender keyword, notifies on new matches.
- **Call-log watch** — reads missed calls, fingerprints latest, notifies on new missed calls.
- **Browser watch** — opens URL via Playwright, hashes page content, LLM summarizes changes.
- **URL/search/topic watch** — web-page diffing, recurring web searches, topic monitoring with materiality detection.
- **WhatsApp watch** — monitors WhatsApp messages, auto-replies with same standing-order system as iMessage.
- Phone notifications — iMessage to self, instant delivery, works with DND bypass.
- `/clearwatches` CLI command — kill all active watches instantly.
- All background systems boot automatically on CLI startup.
- **Screen vision** — "can you see what I'm doing", OCR + vision model, privacy-gated, 48h auto-delete.
- **Full-page question solver** — "solve the questions on Safari", scrolls entire page, OCRs + deduplicates, solves all questions, saves formatted `.docx` with app targeting and viewport-only mode.
- **Multi-agent deep research** — parallel sub-agents (search + fetch + read + write), phased execution, produces real documents saved to disk.

---

## Phase 4 — Voice Pipeline v2: Always-On Ambient Listening *(Complete)*

### Added
- Always-on ambient listening — mic stays open, all speech transcribed continuously.
- Trigger-word activation — say "Friday" naturally mid-conversation, no wake-word model needed.
- Rolling transcript buffer — 5 minutes of ambient context, injected when triggered.
- Follow-up window — 15 seconds after response, any speech treated as directed at FRIDAY.
- Cloud TTS — ElevenLabs Flash v2.5 streaming (~75ms), Kokoro local fallback.
- Noise/hallucination filtering — parenthetical descriptions, music, TV all filtered out.
- VAD tuning — threshold 0.7 filters background music, 400ms min speech.
- `/listening-off` and `/listening-on` CLI commands.
- Cloud vs local TTS — set/remove `ELEVENLABS_API_KEY` in `.env` to switch.

---

## Phase 3.7 — Orchestrator Split + LLM Routing *(Complete)*

### Added
- LLM-based intent classification via Groq (~1s) with regex fallback for offline use.
- Clean cloud/local auto-switch: no API key = fully local, with key = cloud.

### Changed
- Split 1,955-line orchestrator into 6 focused modules (`prompts`, `router`, `fast_path`, `oneshot`, `briefing`, `orchestrator`).

### Performance
- Research agent: **45–90s → 4–6s** (12× improvement).

---

## Phase 3.6 — Cloud Inference *(Complete)*

### Added
- Cloud LLM via Groq API (Qwen3-32B, sub-100ms latency, 535 tok/s).
- All LLM paths routed through `cloud_chat()` — tool dispatch, agents, formatting, chat.
- Automatic fallback to local Ollama when cloud unavailable or API key unset.
- Thinking block filtering (`<think>...</think>`) for Qwen reasoning models.
- Stream format bridging — Ollama and OpenAI chunk formats unified via `extract_stream_content()`.

### Performance
- Average response time: **54s → 6.5s** (8× improvement).

---

## Phase 3.5 — Direct Tool Dispatch & 7-Tier Routing *(Complete)*

### Added
- Direct tool dispatch — LLM picks from 9 curated tools in 1 call (agents become fallback).
- **7-tier routing**: fast path → user override → oneshot → direct dispatch → agent → fast chat → full LLM.
- User override — `@comms`, `@research`, `@social` etc. bypasses routing entirely.
- Dual-model architecture — Qwen3.5:9B (primary) + Qwen3:4B (fast).
- Briefing per-task timeouts — prevents one slow API from blocking everything.
- Oneshot error fallbacks — instant error responses instead of falling through to slow agents.
- Fast chat tier — slim prompt, truncated context, 10–15s conversational responses.
- TTFT as primary UX metric — median 3.7s, 69% responsive (<6s).

---

## Phase 3 — Performance & Background Agents *(Complete)*

### Added
- Direct agent dispatch — regex skips routing LLM (4 → 2 LLM calls per query).
- Direct briefing — parallel tools + 1 LLM synthesis (12+ → 1 LLM call).
- Parallel tool execution — `asyncio.gather()` when multiple tools in one response.
- Background agent execution — user keeps chatting while agents work.
- Live status updates — `◈ checking emails...` → `◈ synthesizing...`.
- Streaming synthesis — agent results stream token-by-token to CLI and voice.
- Expanded fast path — greeting prefixes, Ollama error recovery.
- Unified routing — all queries go through dispatch, LLM always has `DISPATCH_TOOL`.

---

## Phase 2 — Voice Pipeline *(Complete)*

### Added
- Voice pipeline — Silero VAD + MLX Whisper + Kokoro TTS.
- `--voice` flag and `/voice` runtime toggle.
- Response filter (strips code/markdown for speech, condenses to 3 sentences).
- Activation chime, barge-in support, feedback prevention.
- Both CLI and voice work simultaneously (shared `FridayCore` instance).

---

## Phase 1 — Core System *(Complete)*

### Added
- Multi-agent orchestrator with smart routing.
- **11 specialist agents** (Code, Research, Deep Research, Memory, Comms, System, Household, Monitor, Briefing, Job, Social).
- Tool library (web, file, terminal, memory, email, calendar, mac, browser).
- **Gmail integration** — read, search, send, draft, edit draft, send draft, label, thread.
- **macOS/iCloud Calendar integration** — day/week view, create events (no API keys needed).
- **Mac control** — AppleScript, app launcher, screenshots, volume, dark mode.
- **Screen vision** — OCR (Apple Vision, offline) + image understanding (Qwen2.5-VL), auto-cleanup after 48h.
- **Full-page question solver** — scroll + OCR entire pages, solve all questions, save formatted `.docx`, app targeting, viewport-only mode.
- **Browser automation** — Safari (Selenium, real sessions) + Playwright fallback, login detection.
- **LG TV control** — WebOS local API + WakeOnLan (no cloud).
- **Persistent monitoring** — URL/topic/search watchers with material-change detection.
- **Briefing system** — morning/evening/quick briefings from monitor alerts + email + calendar.
- **Job agent** — CV tailoring, cover letters, PDF generation (`WeasyPrint` + `Jinja2`).
- **Background scheduler** — APScheduler runs monitor checks on configurable intervals.
- **Background process management** — start, monitor, kill.
- **Hybrid memory** (ChromaDB + SQLite).
- **Streaming CLI** with hacker aesthetic.
- **Smart thinking control** (84s → 5s for simple queries).
- **Personality + Ghanaian expression understanding** (later made user-configurable in Phase 6).
- **Known-source injection** for research.
- **Vague-query detection** (ask before wasting time).
- **Conversation context injection** (agents remember recent turns).
- **Live tool-call status** during agent work.
- **Compacted tool results** for 9B-model compatibility.

---

## Phase 8 — Ecosystem *(Roadmap / not started)*

### Planned
- **Telegram bot integration** — another remote access channel.
- FRIDAY iOS app — native push notifications via APNs, full assistant UI.
- Mac Mini server — FRIDAY runs 24/7 on dedicated hardware.
- Redis async messaging between agents.
- MCP server integration.
- Screenpipe integration (screen-context awareness).
- Self-improving loop (auto fine-tune from corrections).
- Multi-user support.
- Plugin/extension system.
