# FRIDAY — Development Progress

## Project Overview

**FRIDAY** — Personal AI Operating System.
Inspired by Tony Stark's JARVIS/FRIDAY. Not a chatbot. A co-founder, a 3am coding partner.

- **Repo**: `~/Desktop/JARVIS`
- **Model**: Qwen3-32B (cloud via Groq) + Qwen3.5-9B (local Ollama fallback)
- **Stack**: Python 3.12, uv, Groq API, Ollama, ChromaDB, SQLite, Tavily, Rich
- **Entry point**: `uv run friday` or `uv run python -m friday.cli`

---

## Phase 1 — Core System (COMPLETE)

**Target**: FRIDAY Core orchestrator + 10 agents + full tool library + CLI interface.

### Project Scaffolding
- [x] Initialized Python 3.12 project with `uv`
- [x] Installed all dependencies: `ollama`, `chromadb`, `httpx`, `rich`, `prompt-toolkit`, `python-dotenv`, `tavily-python`
- [x] Created module structure
- [x] CLI entry point registered in `pyproject.toml` (`friday = "friday.cli:run"`)

### Core Types (`friday/core/types.py`)
- [x] `ErrorCode` enum — NETWORK_ERROR, FILE_NOT_FOUND, PERMISSION_DENIED, PROCESS_TIMEOUT, COMMAND_FAILED, DATA_VALIDATION, PAYMENT_ERROR, WEBHOOK_ERROR, CONFIG_ERROR
- [x] `Severity` enum — LOW, MEDIUM, HIGH, CRITICAL
- [x] `ToolError` dataclass — structured error with code, message, severity, recoverable flag, retry_after
- [x] `ToolResult` dataclass — success/fail + data + error + metadata + timing
- [x] `AgentResponse` dataclass — agent_name, success, result, tools_called, duration_ms

### LLM Client (`friday/core/llm.py`)
- [x] Ollama wrapper with `chat()`, `extract_tool_calls()`, `extract_text()`
- [x] Handles Ollama SDK ChatResponse normalization (model_dump to dict)
- [x] Streaming support — `stream=True` returns chunk iterator
- [x] Native thinking control via Ollama's `think` parameter (not prompt tokens)

### Smart Thinking Control
- [x] Discovery: `/no_think` prompt tokens do NOT disable Qwen3.5 thinking — the model still generates 1000+ hidden tokens
- [x] Solution: Ollama's native `think=False` parameter disables the thinking pipeline at engine level
- [x] Results: "hey" went from **84s → 5s** (11 tokens vs 1123 tokens)
- [x] `_needs_thinking()` heuristic — only enables thinking for complex queries (explain, debug, implement)
- [x] All agent LLM calls use `think=False` (agents reason through tool use, not internal thinking)
- [x] Synthesis step always `think=False`

### Tool Library
- [x] **Web Tools** (`friday/tools/web_tools.py`)
  - `search_web()` — Tavily API with AI-generated answers + structured results
  - `fetch_page()` — httpx, strips HTML, truncates to 8K chars
  - `.env` auto-loaded via `friday.core.config` import (fixed TAVILY_API_KEY not loading bug)
- [x] **File Tools** (`friday/tools/file_tools.py`)
  - `read_file()` — with line range support (start_line/end_line)
  - `write_file()` — with append mode
  - `list_directory()` — depth control, pattern filter, hidden files, skip noise dirs
  - `search_files()` — by name, content, or both; extension filter
- [x] **Terminal Tools** (`friday/tools/terminal_tools.py`)
  - `run_command()` — shell execution with safety checks, cwd support, env vars
  - `run_background()` — long-running processes with auto-kill timer
  - `get_process()` — check status of background processes
  - `kill_process()` — graceful SIGTERM then SIGKILL
  - Blocks dangerous patterns: `rm -rf /`, `mkfs`, `dd`, `/dev/sd`
  - 30s default timeout, 10K char output limit
- [x] **Memory Tools** (`friday/tools/memory_tools.py`)
  - `store_memory()`, `search_memory()`, `get_recent_memories()`
  - Categories: project, decision, lesson, preference, person, general
  - Importance: 1 (trivial) to 10 (critical)
- [x] **Mac Control Tools** (`friday/tools/mac_tools.py`)
  - `run_applescript()` — execute AppleScript for Mac automation
  - `open_application()` — open apps with safe list (Cursor, Chrome, Finder, Slack, etc.)
  - `take_screenshot()` — full screen or region capture
  - `get_system_info()` — hostname, OS version, CPU, memory, disk, uptime
  - `set_volume()` — system volume 0-100
  - `toggle_dark_mode()` — switch macOS dark/light mode
- [x] **Browser Tools** (`friday/tools/browser_tools.py`)
  - `browser_navigate()` — go to URL, returns title + login detection
  - `browser_screenshot()` — capture page or element, saves to `~/Downloads/friday_screenshots/`
  - `browser_click()` — click elements with safety check for pay/delete/submit
  - `browser_fill()` — fill form fields
  - `browser_get_text()` — extract text content from page elements
  - `browser_wait_for_login()` — pause while Travis logs in manually, detects when login completes
  - `browser_close()` — close browser
  - **Default engine: Safari (Selenium)** — uses Travis's actual Safari with all existing cookies, sessions, saved passwords. No login walls. Modal, LinkedIn, Gmail — already logged in.
  - **Fallback: Playwright Chromium** — if Safari remote automation not enabled, falls back to Chromium with persistent profile at `~/.friday/browser_data/`
  - **Auto-detection** — `_detect_engine()` tries Safari first, caches result. Every tool function dispatches to the right engine.
  - **Login detection** — checks URL patterns and page content for login indicators, returns `login_required: true` flag
  - Safari setup (one time): Safari → Settings → Advanced → Show features for web developers, then Develop → Allow Remote Automation
- [x] **TV Tools** (`friday/tools/tv_tools.py`) — **18 tools, full WebOS command suite**
  - **Power**: `turn_on_tv()` (WakeOnLan), `turn_off_tv()` (WebOS SystemControl)
  - **Screen**: `tv_screen_off()` (audio keeps playing), `tv_screen_on()`
  - **Volume**: `tv_volume()` (exact 0-100, verified), `tv_volume_adjust()` (relative ±N, verified), `tv_mute()` (mute/unmute)
  - **Media**: `tv_play_pause()` — play, pause, stop, rewind, fast-forward
  - **Apps**: `tv_launch_app()` (verified — reads back current app), `tv_close_app()`, `tv_list_apps()`
  - **Sources**: `tv_list_sources()`, `tv_set_source()` (HDMI/antenna switching)
  - **Remote**: `tv_remote_button()` — 40+ buttons: nav, media, numbers (num_0-9), colours (red/green/yellow/blue), channel, special
  - **Text**: `tv_type_text()` — IME text input directly into search bars
  - **Notifications**: `tv_notify()` — send toast messages to TV screen
  - **Audio**: `tv_get_audio_output()`, `tv_set_audio_output()` — switch speakers/soundbar/ARC
  - **System**: `tv_system_info()` — software/hardware info
  - **Status**: `tv_status()` — power, volume, muted, current app
  - **Verification**: volume and app launch tools read back state to confirm commands took effect
  - **Safety**: `disconnect_input()` in try/except/finally blocks — physical remote always works after tool calls
  - Uses pywebostv for WebOS local API over WiFi (no cloud, no LG account)
  - Uses wakeonlan for WakeOnLan magic packets
  - One-time pairing CLI: `uv run python -m friday.tools.tv_tools`
  - Config: LG_TV_IP, LG_TV_MAC, LG_TV_CLIENT_KEY in `.env`
- [x] **X (Twitter) Tools** (`friday/tools/x_tools.py`)
  - `post_tweet()` — post tweets, replies, quote-tweets (280 char enforced)
  - `delete_tweet()` — delete own tweets
  - `get_my_mentions()` — get recent @mentions
  - `search_x()` — search recent tweets (7 days, costs credits, min 10 results)
  - `like_tweet()` — like a tweet
  - `retweet()` — retweet
  - `get_x_user()` — look up public X profiles (followers, bio, stats)
  - Uses tweepy with X API v2, pay-as-you-go credits
  - Supports both env var naming conventions (X_CONSUMER_KEY or X_API_KEY)
  - Auto-excludes retweets from search results
- [x] **Call History Tools** (`friday/tools/call_tools.py`)
  - `get_call_history()` — reads phone, FaceTime, and WhatsApp call logs
  - Native calls (Phone + FaceTime): `~/Library/Application Support/CallHistoryDB/CallHistory.storedata` — requires Full Disk Access
  - WhatsApp calls: `~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/CallHistory.sqlite` — always accessible
  - Filters: by type (phone/facetime/whatsapp), missed only
  - CoreData timestamp conversion (2001 epoch offset)
  - Voicemail not available on macOS (stays on iPhone/carrier)
  - Integrated into BriefingAgent for "catch me up" and "any missed calls"
- [x] **PDF Tools** (`friday/tools/pdf_tools.py`)
  - `pdf_read()` — extract text from PDFs with page range support, optional table extraction via pdfplumber
  - `pdf_metadata()` — title, author, page count, file size, encryption status
  - `pdf_merge()` — merge multiple PDFs into one
  - `pdf_split()` — split PDF into individual page files
  - `pdf_rotate()` — rotate pages by 90/180/270 degrees
  - `pdf_encrypt()` — password-protect a PDF
  - `pdf_decrypt()` — decrypt password-protected PDFs (with wrong password handling)
  - `pdf_watermark()` — overlay watermark PDF on every page
  - Uses pypdf for manipulation, pdfplumber for text/table extraction
  - Text output truncated at 15K chars for model compatibility
  - Dynamically loaded into SystemAgent when task mentions PDFs
- [x] **Monitor Tools** (`friday/tools/monitor_tools.py`)
  - `create_monitor()` — create persistent watcher (url/search/topic)
  - `list_monitors()` — list all active monitors
  - `pause_monitor()` — pause temporarily
  - `delete_monitor()` — delete permanently
  - `get_monitor_history()` — view change history
  - `force_check()` — immediate check
  - `run_monitor_check()` — core check logic (used by scheduler + force_check)
  - SHA-256 content hashing for change detection
  - Unified diff analysis with material change filtering
  - Keyword-based materiality: only alert if relevant keywords appear in diff
  - Importance routing: critical → interrupt, high → next interaction, normal → briefing queue
  - Auto-queues changes to briefing_queue table
- [x] **CV Tools** (`friday/tools/cv_tools.py`)
  - `get_cv()` — return full CV or specific section (experience, skills, etc.)
  - `tailor_cv()` — return CV + job context for agent-driven tailoring
  - `write_cover_letter()` — return CV + job context for cover letter generation
  - `generate_pdf()` — render CV or cover letter to A4 PDF via WeasyPrint + Jinja2
  - Structured CV data in `friday/data/cv.py` — single source of truth
  - Professional HTML templates for CV and cover letter PDFs
  - Output saved to `~/.friday/data/cv_output/`
- [x] **Briefing Tools** (`friday/tools/briefing_tools.py`)
  - `get_briefing_queue()` — get all undelivered items (morning/evening/quick)
  - `get_monitor_alerts()` — get undelivered monitor alerts by importance
  - `get_daily_digest()` — pull everything: alerts + queue + active monitors
  - `mark_briefing_delivered()` — mark items delivered so they don't repeat
- [x] **Email Tools** (`friday/tools/email_tools.py`)
  - `read_emails()` — filter by unread/today/urgent/custom query, priority sorting
  - `search_emails()` — Gmail search syntax (from:, subject:, has:attachment)
  - `read_email_thread()` — full conversation thread with bodies
  - `send_email()` — with `confirm=True` safety gate
  - `draft_email()` — creates Gmail draft for review
  - `send_draft()` — send an existing draft by ID, with `confirm=True` safety gate
  - `edit_draft()` — modify an existing draft (to, subject, body) without recreating
  - `label_email()` — add/remove labels (STARRED, IMPORTANT, TRASH, etc.)
  - Priority sender detection (Paystack/Stripe = critical, Railway/GitHub = high)
- [x] **Calendar Tools** (`friday/tools/calendar_tools.py`) — **native macOS Calendar via AppleScript**
  - `get_calendar()` — day/week view, supports today/tomorrow/next_event/ISO date
  - `create_event()` — with `confirm=True` safety gate, creates in macOS Calendar, syncs to iCloud
  - Reads from all synced calendars (iCloud, Google, Exchange, local)
  - Skips system calendars (Birthdays, Siri Suggestions, Scheduled Reminders, UK Holidays) for speed
  - Coding hours warning (10pm-4am)
  - Europe/London timezone
  - No API keys needed — works with native macOS Calendar.app
  - ~20s per query (AppleScript limitation)
- [x] **Google Auth** (`friday/tools/google_auth.py`)
  - Shared OAuth2 helper for Gmail + Calendar
  - Auto-detects Desktop vs Web app credentials
  - Token refresh handling
  - Credentials: `~/.friday/google_credentials.json`, token: `~/.friday/google_token.json`

### Background Scheduler (`friday/background/monitor_scheduler.py`)
- [x] APScheduler AsyncIOScheduler integration
- [x] Loads all active monitors from SQLite on startup
- [x] Schedules recurring checks: realtime (15min), hourly (60min), daily (1440min), weekly (10080min)
- [x] Auto-removes jobs when monitors are paused/deleted
- [x] Runtime monitor addition (new monitors start immediately)
- [x] Singleton pattern via `get_monitor_scheduler()`
- [x] Started in CLI on FRIDAY boot (non-blocking, graceful failure)

### Memory System (`friday/memory/store.py`)
- [x] Hybrid storage: ChromaDB (semantic search) + SQLite (structured queries)
- [x] SQLite schema: `memories`, `sessions`, `agent_calls`, `monitors`, `monitor_events`, `briefing_queue` tables
- [x] ChromaDB collection: `friday_memories` with cosine similarity
- [x] `build_context()` — constructs memory string for system prompt injection
- [x] `log_agent_call()` — debug logging for all agent dispatches
- [x] Singleton pattern via `get_memory_store()`

### Agents
- [x] **BaseAgent** (`friday/core/base_agent.py`)
  - ReAct loop: THOUGHT → ACTION → OBSERVATION → FINAL ANSWER
  - Max 10 iterations, auto-generates tool schemas
  - `on_tool_call` callback for CLI progress visibility
- [x] **CodeAgent** (`friday/agents/code_agent.py`)
  - Tools: file read/write, terminal, web search, memory
  - Prompt: match existing style, explicit errors, no hardcoded secrets, prefer async
- [x] **ResearchAgent** (`friday/agents/research_agent.py`)
  - Tools: web search, fetch page, memory store/search
  - Prompt: ALWAYS fetch pages (not just snippets), use known authoritative sources
  - Known source injection — auto-appends official URLs for topics like UK visas, Stripe, Supabase
  - Enforces English-only responses
- [x] **MemoryAgent** (`friday/agents/memory_agent.py`)
  - Tools: store/search/recall memory
  - Prompt: categorize by type, assign importance 1-10
- [x] **CommsAgent** (`friday/agents/comms_agent.py`)
  - Tools: 7 email (read, search, thread, send, draft, send_draft, edit_draft) + 2 calendar (get, create)
  - `max_iterations = 5` (comms tasks should finish in 1-3 loops, not 10)
  - Explicit tool-call mapping: "draft email" → must call `draft_email()`, "send it" → must call `send_email()` or `send_draft()`
  - Full draft lifecycle: create → edit → send, all via tools
  - Safety gates: `confirm=True` required for send_email, send_draft, and create_event
  - Priority sender flagging (Paystack, Stripe = critical; Railway, GitHub = high)
  - Coding hours warning (10pm-4am events flagged)
  - Anti-hallucination: "You know NOTHING — your first response MUST be a tool call"
- [x] **SystemAgent** (`friday/agents/system_agent.py`)
  - Core tools: run_command, run_background, open_application, take_screenshot, get_system_info, run_applescript, read_file, list_directory (8 tools)
  - Dynamic browser tool injection — adds Playwright tools + `browser_wait_for_login` when task mentions browser/navigate/webpage/linkedin
  - Dynamic PDF tool injection — adds 8 PDF tools (read, metadata, merge, split, rotate, encrypt, decrypt, watermark) when task mentions PDF
  - `max_iterations = 5`
  - **Login flow**: detects login pages → tells Travis to log in manually → waits → continues task
  - Routing patterns: open app, screenshot, dark mode, volume, system info, browse, process management
- [x] **HouseholdAgent** (`friday/agents/household_agent.py`)
  - Tools: 18 TV tools (full WebOS command suite)
  - `max_iterations = 8`
  - **Fast-path routing** — regex pattern matching bypasses LLM for simple commands (~200-600ms vs ~30s)
  - Fast-path covers: power on/off, volume set/adjust, mute/unmute, play/pause/stop/rewind/ff, screen off/on, channel up/down, close app, launch app, notify, status
  - Multi-step fast path: "turn on TV and put on Disney" → sequential with 6s boot delay
  - `_format_result()` — short FRIDAY-style responses for all 18 tools
  - LLM path only used for complex commands (e.g. "search for Black Widow on Disney+")
  - System prompt updated with full tool listing for LLM path
  - Routing: "tv", "turn on/off tv", "put on netflix", "volume up/down", "pause", "resume", "what's on tv", "screen off", "channel up", "close the app", "send notification"
- [x] **MonitorAgent** (`friday/agents/monitor_agent.py`)
  - Tools: 6 monitor tools (create, list, pause, delete, history, force_check)
  - `max_iterations = 5`
  - Creates persistent watchers for URLs, topics, web searches
  - Smart defaults: frequency based on topic type, keywords based on domain
  - Routing: "monitor X", "watch X", "track X", "show monitors", "check monitor"
- [x] **BriefingAgent** (`friday/agents/briefing_agent.py`)
  - Tools: 4 briefing tools + read_emails + get_calendar + get_call_history + search_x + get_my_mentions (9 tools)
  - `max_iterations = 10` (needs more turns for X searches)
  - Synthesises monitor alerts, emails, calendar, missed calls, X feed into tight briefings
  - Morning/evening/quick briefing formats
  - Call history integration — checks missed calls from phone, FaceTime, WhatsApp
  - **X monitoring integration** — every briefing pulls:
    - @samgeorgegh activity (Ghanaian MP)
    - Galamsey / illegal mining news
    - Viral travel posts (Africa focus)
    - Trending AI/tech posts (new releases, announcements)
    - @mentions (surfaced first, actionable)
  - Anti-hallucination: "You have ZERO knowledge — FIRST action MUST be tool calls"
  - Marks items as delivered after surfacing
  - Routing: "briefing", "catch me up", "what did I miss", "any updates", "any calls", "missed calls", "did anyone call"
- [x] **JobAgent** (`friday/agents/job_agent.py`)
  - Tools: 15 total — 4 CV tools + 2 web tools + 7 browser tools + 2 email tools
  - `max_iterations = 15` (multi-step applications need more iterations)
  - **Autonomous applications** — browses job sites, reads JDs, tailors CV, fills forms, screenshots before submit
  - CV tailoring — reorders/rephrases experience for specific JDs, never invents
  - Cover letter generation — confident tone, specific achievements, no corporate fluff
  - PDF generation via WeasyPrint + Jinja2 — dark sidebar A4 layout with lime accent
  - Email scanning — finds job openings in Gmail, extracts roles/links/deadlines
  - Multi-step form filling — navigates application pages, fills personal details
  - Login detection — pauses for manual login on protected job portals
  - Uses "Angelo Asante" (gov name) on all professional/job documents
  - Safety: always screenshots before submit, never submits without Travis confirming
  - Routing: "cv", "resume", "cover letter", "apply to/for", "job application", "tailor cv", "check emails for jobs", "go on X and apply"
- [x] **SocialAgent** (`friday/agents/social_agent.py`)
  - Tools: 7 X tools (post, delete, mentions, search, like, retweet, user lookup)
  - `max_iterations = 5`
  - Never posts without Travis confirming text first
  - Credit-aware: knows posting is cheap, searching costs credits
  - Routing: "tweet", "post on x/twitter", "mentions", "search twitter", "like tweet", "who is @user"

### Orchestrator (`friday/core/orchestrator.py`)
- [x] `FridayCore` — main brain, routes all tasks
- [x] Agent dispatch via Ollama tool calling (dispatch_agent tool)
- [x] Prompt forces immediate tool calls — no "I'm going to dispatch..." announcements
- [x] Conversation history (last 20 messages)
- [x] Memory context injection into system prompt
- [x] Conversation context injection into agent dispatch (last 3 exchanges for continuity)
- [x] Post-agent synthesis step (streamed, not blocking)
- [x] `needs_agent()` — regex classifier for chat vs task routing
- [x] Comms patterns: email, mail, inbox, calendar, schedule, meeting
- [x] System patterns: open app, screenshot, dark mode, volume, system info, browse, process management
- [x] 10 agents registered: code, research, memory, comms, system, household, monitor, briefing, job, social
- [x] Social routing patterns — X/Twitter queries always go to social_agent (checked BEFORE generic task patterns)
- [x] Vague query detection — "fix my bug" goes to chat (ask first), "fix the TypeError in main.py" dispatches
- [x] `process_and_stream()` — async generator with `on_status` callback for live progress
- [x] `stream()` — direct streaming for conversational responses

### Personality
- [x] Full Ghanaian expression dictionary (hawfar, oya, chale, e do, e no do, time no dey, etc.)
- [x] Travis-specific context (Ghanaian founder, Plymouth UK, Prempeh College, projects)
- [x] Hard rules: no bullet points for conversation, no corporate tone, no "Certainly!"
- [x] Energy matching: casual gets casual, urgent gets urgent
- [x] 2AM rule: less polish, more honest at late hours
- [x] Response length control: greetings = 1-2 lines, questions = 3-4 lines, tasks = as long as needed

### CLI (`friday/cli.py`)
- [x] Hacker-style green terminal aesthetic (ASCII art banner)
- [x] Status bar: ONLINE | model | memory status
- [x] Interactive prompt with history (prompt_toolkit)
- [x] Commands: `/quit`, `/clear`, `/memory`
- [x] **Streaming responses** — tokens appear as generated, not after full completion
- [x] **Live agent status** — shows what tools are running during dispatch:
  - `◈ routing...` → `◈ searching: "query"` → `◈ reading www.gov.uk` → `◈ synthesizing...`
- [x] Response timing display
- [x] Spinner animation while agents work

---

## Bugs Found & Fixed

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| `'NoneType' object is not iterable` on first message | Ollama SDK returns `ChatResponse` objects, not dicts. `tool_calls` is `None`, not `[]` | `model_dump()` normalization + `or []` fallback |
| 84-121s response time for "hey" | Qwen3.5 generates massive hidden thinking tokens even with `/no_think` prompt token | Switched to Ollama's native `think=False` parameter (engine-level disable) |
| Chinese responses from research agent | Qwen3.5 defaults to Chinese for some synthesis tasks | Added "ALWAYS respond in English" to all agent and synthesis prompts |
| Tavily "TAVILY_API_KEY not set" | `.env` not loaded when `web_tools.py` reads `os.environ` | Import `friday.core.config` in web_tools to ensure `load_dotenv()` runs first |
| "im building you rn" dispatches to agent | Keyword "build" in substring match triggers false positive | Replaced with regex patterns matching task intent (verb + object structure) |
| "fix my bug" wastes 18s dispatching then asking | Vague requests with task verbs but no actionable context | Vague pattern filter — routes to chat for clarification instead |
| Research agent summarises from snippets only | System prompt didn't force page fetching | Added "ALWAYS fetch_page on top results, NEVER summarise from snippets alone" |
| Agent announces actions but doesn't do them | Orchestrator prompt too permissive — model talks about dispatching instead of calling the tool | Added "NEVER say 'I'm dispatching' — just call dispatch_agent" |
| "can you read my mail" not dispatching | Comms patterns didn't match "mail" variants | Added broader regex patterns for mail/email/inbox/calendar |
| Agent loses context between turns | Each dispatch starts fresh with no conversation history | Inject last 3 exchanges from `self.conversation` into agent context |
| Comms agent too slow (62-122s) | Multiple ReAct iterations when one tool call suffices | One-shot patterns in prompt + `max_iterations=5` + `include_body=True` by default |
| Comms agent hallucinating calendar events | Agent generates plausible data from personality context instead of calling tools | "You have ZERO knowledge" + "first response MUST be tool call" + compacted tool results |
| Calendar 400 Bad Request | `datetime.now()` + "Z" suffix mismatch — naive datetime with UTC marker | Timezone-aware datetimes with `ZoneInfo("Europe/London")` |
| Agent ignores tool results (says "nothing found" with 10 emails) | 14K chars of tool result data overwhelms 9B model | `_compact_data()` strips non-essential fields (thread IDs, labels, full bodies) |
| Comms agent fakes drafting/sending (no tool call) | 9B model generates plausible text instead of calling `draft_email`/`send_email` | Rewrote prompt with explicit tool-call mapping: "draft" → must call `draft_email()`, "send" → must call `send_email()` |
| "send draft ID: X" doesn't work | No `send_draft` tool existed; agent tried `send_email` with wrong params | Created `send_draft()` and `edit_draft()` tools using Gmail Drafts API |
| "send it" after discussing email doesn't route to comms | `needs_agent()` only matched "send an email" pattern, not follow-ups | Added follow-up patterns + `_recent_comms_context()` check for conversation-aware routing |
| Browser screenshots a login page and calls it done | No login detection — agent takes screenshot of whatever page loads | Added `_detect_login_page()` (URL + content checks) + `browser_wait_for_login()` tool |
| Browser sessions lost between runs | Fresh Playwright context each time — no cookies/sessions saved | Switched to Safari (Selenium) as default — uses Travis's actual Safari sessions. Playwright fallback with persistent profile at `~/.friday/browser_data/` |
| Screenshots saved to `/tmp/friday/` | Not user-accessible location | Changed to `~/Downloads/friday_screenshots/` for both mac and browser screenshots |
| No smart home control | No household agent or TV tools | Built HouseholdAgent + tv_tools.py with 6 WebOS/WOL tools for LG TV |
| Household agent "fakes" TV actions | LLM responds "Done!" without calling tools, or ignores tool failure results | Added verification (read-back) on volume/app launch; stronger prompt: "EVERY device action MUST be a tool call" |
| Household agent too slow (30-37s per command) | All commands go through LLM inference even for simple tasks | Fast-path regex matching bypasses LLM entirely — 200-600ms for simple commands |
| Multi-step "turn on tv and put on disney" only executes first step | Power-on pattern matched before multi-step; TV not booted for second command | Reordered patterns; added 6s boot delay between turn_on_tv and subsequent commands |
| `uv run friday` fails with "No such file or directory" | No `[build-system]` in pyproject.toml — uv skips entry point installation | Added `[build-system]` with setuptools backend |
| Physical TV remote stops working after tool calls | InputControl connect not followed by disconnect on errors | Added `disconnect_input()` in try/except/finally blocks for all InputControl tools |
| "search x for galamsey" goes to research_agent | Social patterns checked AFTER generic task patterns; LLM routing instruction too weak | Moved social_patterns before task_patterns in `needs_agent()`; added "ALWAYS use social_agent for X/Twitter, NEVER research_agent" to routing prompt |
| "who is @elonmusk" answered from chat (no dispatch) | LLM answered from knowledge; `@\w+` pattern existed but LLM overrode it | Strengthened social_patterns with explicit `who\s+is\s+@\w+` and more X trigger words |
| Briefing agent says "on it" instead of calling tools | 9B model generates acknowledgment text instead of tool calls | Added anti-hallucination: "You have ZERO knowledge — FIRST action MUST be tool calls" |
| Orchestrator outputs agent name as text instead of tool call | 9B model says "briefing_agent" as text, doesn't call dispatch_agent | Added "NEVER output just an agent name as text — CALL THE TOOL" + explicit "catch me up" → briefing_agent mapping |
| Calendar required Google API setup | google-api-python-client needed OAuth2 creds and API setup | Rewrote calendar_tools.py to use native macOS Calendar via AppleScript — no API keys needed |
| SQLite thread safety error in voice | `sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread` | Added `check_same_thread=False` to `sqlite3.connect()` in `store.py` |
| Voice no response (timeout) — agent path | `run_coroutine_threadsafe` on main event loop blocked when CLI prompt held the loop | Switched to `dispatch_background()` with own thread + event loop |
| Voice not streaming (no "instant feel") | Full response collected before speech — no sentence-by-sentence TTS | Rewrote pipeline with thread-safe queue; producer pushes chunks, voice thread speaks sentence-by-sentence |
| Text CLI 35-46s for "you good bruv?" | All queries went through LLM inference including simple greetings | Added `fast_path()` regex → canned responses, zero LLM calls (<1ms) |
| TV commands 35-44s through LLM | Household commands routed through agent dispatch (4 LLM calls) | Fast-path regex → direct tool call, no LLM (<0.5s) |
| "man, you good?" = 26.6s | `fast_path` pattern `^(you good...)` doesn't match when prefixed with "man," | Strip common prefixes (man, bro, bruv, fam, mate, etc.) before matching |
| Briefing takes 363s (12+ LLM calls) | ReAct loop calls tools one-by-one, each needing an LLM call | `direct_briefing()` — all tools in parallel via `asyncio.gather()`, 1 LLM synthesis |
| Agent tools run sequentially | `base_agent.py` loops through tool calls with `for tc in tool_calls` | Multiple tool calls now run in parallel via `asyncio.gather()` |
| "dispatching research_agent" but doesn't dispatch | `needs_agent()` missed patterns like "Ghana AI initiative" — fell through to `stream()` which has no dispatch tool | Removed `needs_agent()` gate; ALL queries go through `dispatch_background` where LLM always has DISPATCH_TOOL |
| 4 LLM calls per agent query (routing + agent×2 + synthesis) | Routing LLM decides which agent; synthesis LLM rewrites agent output — both redundant | `_match_agent()` regex skips routing; agent result used directly (skips synthesis). 4 → 2 LLM calls |
| Ollama XML 500 error crashes agent work | 9B model generates malformed XML in tool call response | `chat()` catches 500 errors, retries WITHOUT tools — model responds in plain text |
| Agent results dumped all at once (no streaming) | `dispatch_background` collected full result then sent `DONE:` | Synthesis streams via `CHUNK:` callbacks — tokens appear as generated |

---

## Performance Benchmarks (After Optimisations)

*All times measured after warm-up (model loaded in VRAM)*

| Query | Type | Time | Notes |
|-------|------|------|-------|
| "hey" | Chat (stream) | ~5-8s | `think=False`, ~11 tokens |
| "hawfar" | Chat (stream) | ~7-9s | Ghanaian slang, understood natively |
| "who are you" | Chat (stream) | ~10-13s | Longer response, still streaming |
| "charley im tired" | Chat (stream) | ~10-12s | Context-aware, personality match |
| Web research | Agent (dispatch) | ~50-150s | Depends on pages fetched + synthesis length |

| TV: volume/mute/pause | Household (fast-path) | ~165-340ms | No LLM — regex + direct tool call |
| TV: app launch (verified) | Household (fast-path) | ~2.5-6s | Includes verification read-back |
| TV: screen off/on, channel, notify | Household (fast-path) | ~217-330ms | New tools, all fast-path |
| TV: in-app search | Household (LLM) | ~30-90s | Multi-step: launch → navigate → type → select |

| X: user lookup | Social (dispatch) | ~8-15s | LLM routing + tweepy API call + synthesis |
| X: tweet search | Social (dispatch) | ~10-20s | LLM routing + X API search + synthesis |
| Briefing (with X) | Briefing (dispatch) | ~60-120s | 7+ tool calls: digest, emails, calendar, calls, 4x X search, mentions |

**First call** after cold start adds ~30-60s for ChromaDB init + model VRAM loading.

---

## Phase 3 — Performance & Background Agents (COMPLETE)

**Target**: Cut LLM calls in half, background agent execution, streaming everywhere.

### Direct Agent Dispatch (`_match_agent()`)
- [x] Regex pattern matching routes input directly to the correct agent — skips routing LLM call
- [x] Agent's own summary used directly — skips synthesis LLM call
- [x] Covers all 10 agents: comms, social, household, monitor, job, system, memory, research, code, briefing
- [x] LLM routing only used as fallback for ambiguous queries
- [x] Result: **4 LLM calls → 2 LLM calls** for most agent queries (~50% faster)

### Direct Briefing Dispatch (`_direct_briefing_streamed()`)
- [x] "catch me up" / "brief me" → all 8 briefing tools called in parallel via `asyncio.gather()`
- [x] Tools: digest, emails, calendar, calls, 4x X search, mentions — all at once
- [x] ONE LLM synthesis call (streamed token-by-token)
- [x] Result: **12+ LLM calls → 1 LLM call** (~360s → ~30-40s)

### Parallel Tool Execution (`base_agent.py`)
- [x] When LLM returns multiple tool calls in one response, they execute in parallel via `asyncio.gather()`
- [x] Single tool calls still run directly (no overhead)
- [x] Applies to all agents automatically

### Background Agent Execution (`dispatch_background()`)
- [x] Agent work runs in background thread with its own event loop
- [x] User keeps chatting while agents work (non-blocking)
- [x] Live status callbacks: `STATUS:`, `CHUNK:`, `ACK:`, `DONE:`, `ERROR:`
- [x] CLI shows live progress: `◈ comms working...` → `◈ checking emails` → streamed result
- [x] Voice pipeline uses same background dispatch for agent queries

### Streaming Everywhere
- [x] Agent synthesis streams token-by-token to CLI (same "instant feel" as direct chat)
- [x] Voice: synthesis chunks flow to sentence queue for TTS as they generate
- [x] Briefing synthesis streams while tools finish in parallel
- [x] CLI shows `FRIDAY (32s)` header on first chunk, then streams rest

### Fast Path Improvements
- [x] Greetings handle prefixes: "man, you good?", "bro hey", "fam, sup" — all instant
- [x] Common prefix stripping: man, bro, bruv, g, fam, mate, boss, chief, dawg, guy
- [x] Added: "how are you", "how you dey", "hello mate", "what's good"

### Ollama Error Recovery (`llm.py`)
- [x] Catches Ollama 500 errors (malformed XML from tool call attempts)
- [x] Retries without tools — model responds in plain text instead of crashing
- [x] Prevents "XML syntax error" crashes during agent work

### Routing Architecture Change
- [x] Removed `needs_agent()` gate from CLI — all non-fast-path queries go through `dispatch_background`
- [x] LLM always has `DISPATCH_TOOL` available — can dispatch agents for ANY query
- [x] Smart acknowledgment: only shows "On it" for agent work, not conversational responses
- [x] Removed `stream_response()` — unified path handles both chat and agent work

### Performance (After Phase 3)
| Query | Before | After | Improvement |
|-------|--------|-------|-------------|
| Greetings ("you good") | 5-8s (LLM) | <1ms (regex) | ~5000x |
| TV commands | <0.5s (fast path) | <0.5s (fast path) | Same |
| Email check | ~60s (4 LLM) | ~30s (2 LLM) | ~2x |
| Briefing ("catch me up") | ~360s (12+ LLM) | ~30-40s (1 LLM) | ~10x |
| Research query | ~150s (4 LLM) | ~100s (2 LLM) | ~1.5x |
| Conversational | ~20s (stream) | ~20s (background) | Same |

---

## Phase 3.5 — Direct Tool Dispatch & 7-Tier Routing (COMPLETE)

**Target**: Give the model direct tool access. Agents become fallback, not default. Cut single-tool queries from ~45s to ~25s.

**Thesis**: Most user requests need exactly 1 tool call. "Check my emails" → `read_emails()`. "Search X for AI" → `search_x()`. The full ReAct agent loop (3-4 LLM calls) is overkill. Give the model 9 curated tools, let it pick the right one in 1 LLM call, execute, format with 1 LLM call. **2 LLM calls instead of 3-4.**

### Direct Tool Dispatch (`friday/core/tool_dispatch.py`) — NEW FILE
- [x] Created `try_direct_dispatch()` — 1 LLM picks tool → execute → 1 LLM formats result
- [x] 9 curated tools covering ~85% of single-tool queries:
  - Communication: `read_emails`, `search_emails`, `draft_email`, `get_calendar`
  - Social: `search_x`, `get_my_mentions`
  - Information: `search_web`
  - Memory: `store_memory`, `search_memory`
- [x] Slim `DISPATCH_PROMPT` — just enough for tool selection, no personality bloat
- [x] `FORMAT_PROMPT` with FRIDAY personality for response formatting
- [x] Lazy tool registry via `_build_tools()` — loads schemas from existing TOOL_SCHEMAS
- [x] Chat pre-filter — skips dispatch for short queries without tool keywords (avoids wasting 10s+ on chat)
- [x] Instant confirm for `store_memory` — no format LLM call needed
- [x] `_format_and_stream()` — streams formatted response with `max_tokens=100`
- [x] Fallthrough: `NEEDS_AGENT` → agent dispatch, 2+ tool calls → agent, no tool → fast_chat
- [x] Tool data truncated to 1500 chars for fast prompt eval

### User Override (Priority 1.5) — `@agent` syntax
- [x] `@comms`, `@social`, `@research`, `@code`, `@system`, `@household`, `@monitor`, `@briefing`, `@job`, `@memory`
- [x] Also accepts `use comms`, `use research`, etc.
- [x] Bypasses all routing — goes straight to the specified agent
- [x] Extracts task from remainder of input (e.g. `@research quantum computing` → research_agent with task "quantum computing")

### Oneshot Tier (Priority 2) — regex + tool + 1 LLM format
- [x] Email oneshot — regex catches "check email", "any new emails", etc.
- [x] Calendar oneshot — regex catches "calendar", "schedule", "what's on"
- [x] Error fallbacks added — calendar/email failures return instant error instead of falling through to slow agent
- [x] Research removed from oneshot — user prefers explicit `@research` for research tasks
- [x] `_oneshot_format()` — `max_tokens=100`, tool data truncated to 1500 chars

### Fast Chat Tier (Priority 4)
- [x] Slim system prompt — personality only, no tool schemas
- [x] Conversation messages truncated to 200 chars each for speed
- [x] Handles all conversational queries (opinions, reactions, casual chat)
- [x] Target: 10-15s (1 LLM call with minimal context)

### Briefing Per-Task Timeouts
- [x] `asyncio.wait_for()` with per-task timeouts (15-30s) on all parallel briefing calls
- [x] Prevents one slow API (X/Twitter, DNS issues) from blocking entire briefing
- [x] Individual task failures logged, rest of briefing proceeds
- [x] Briefing synthesis `max_tokens=200`

### Dual-Model Configuration
- [x] `MODEL_NAME = "qwen3.5:9b"` — primary model for tool dispatch and formatting
- [x] `MODEL_NAME_FAST = "qwen3:4b"` — fast model for lightweight tasks
- [x] Both models kept warm in VRAM via `keep_alive: -1`

### 7-Tier Routing Priority (orchestrator.py)
```
Priority 1:   Fast Path          — regex → instant (0 LLM)              <1s
Priority 1.5: User Override      — @agent → direct agent dispatch        0s routing
Priority 2:   Oneshot            — regex → tool + 1 LLM format          10-15s
Priority 2.5: Direct Dispatch    — 1 LLM picks tool + 1 LLM format     20-25s
Priority 3:   Agent Dispatch     — regex → agent ReAct loop             45-90s
Priority 4:   Fast Chat          — 1 LLM slim prompt                    10-15s
Priority 5:   Full LLM Routing   — fat prompt + dispatch                60-90s
```

### Streaming UX Metrics (TTFT)
- [x] TTFT (time-to-first-token) identified as the real UX metric — responses stream, so first token matters more than total time
- [x] Median TTFT: 3.7s across all tiers
- [x] 69% of queries have TTFT < 6s (feels responsive)
- [x] Instant tier: 0.0-0.3s TTFT
- [x] Fast chat: 2.8-7.8s TTFT
- [x] Tool dispatch: varies by API latency

### Model Research
- [x] Researched Hugging Face + Ollama for alternatives to Qwen3.5:9B
- [x] **Qwen3.5:4B** — 97.5% tool calling accuracy (BFCL), beats models 5x its size
- [x] **xLAM-2-8b-fc-r** — #1 on Berkeley Function Calling Leaderboard
- [x] **Mistral Small** — "low latency function calling", 24B params
- [x] Ollama tool calling bottleneck identified: XML generation is ~25s on 9B regardless of tool count

### Stress Test Results (After Phase 3.5)

| Tier | Query | Time | TTFT |
|------|-------|------|------|
| ⚡ Instant | "take a screenshot" | 0.4s | 0.3s |
| ⚡ Instant | "open Safari" | 0.2s | 0.1s |
| ⚡ Instant | "volume 50" | 0.4s | 0.3s |
| ⚡ Instant | "whats my battery" | 0.2s | 0.1s |
| 🟢 Fast Chat | "what do you think about AI" | 10.4s | 2.8s |
| 🟢 Fast Chat | "im tired" | 14.7s | 7.7s |
| ⚡ Oneshot | "check my email" | 0.2s | 0.0s |
| 🟠 Oneshot | "check my calendar" | 31.4s | 24.7s |
| 🟡 Dispatch | "what is quantum computing" | 25.9s | 15.3s |
| 🟡 Dispatch | "who is jensen huang" | 26.9s | 21.2s |

**Overall: 52% fast (<15s), 32.2s average across 25 queries.**

---

## Architecture

```
User Input (CLI / Voice)
        │
        ▼
  ┌───────────┐
  │  FRIDAY   │  ← orchestrator, routes ALL tasks
  │   Core    │  ← memory context injected every call
  └─────┬─────┘
        │
  ┌─────┴─────────────────────────────────────────┐
  │              7-TIER ROUTING (fastest first)              │
  │                                                          │
  │  1.   Fast Path       — regex → direct tool (0 LLM)     │  <1s
  │       (greetings, TV, volume, screenshot, open app)      │
  │                                                          │
  │  1.5  User Override   — @agent → agent dispatch          │  0s routing
  │       (@comms, @research, @social, etc.)                 │
  │                                                          │
  │  2.   Oneshot         — regex → tool + 1 LLM format     │  10-15s
  │       (email check, calendar check)                      │
  │                                                          │
  │  2.5  Direct Dispatch — 1 LLM picks tool + 1 LLM format │  20-25s
  │       (9 curated tools: email, calendar, X, web, memory) │
  │                                                          │
  │  3.   Agent Dispatch  — regex → agent ReAct loop         │  45-90s
  │       (multi-step: draft+send, browse+fill, etc.)        │
  │                                                          │
  │  4.   Fast Chat       — 1 LLM slim prompt                │  10-15s
  │       (opinions, reactions, casual conversation)          │
  │                                                          │
  │  5.   Full LLM Route  — fat prompt + agent dispatch      │  60-90s
  │       (ambiguous queries, last resort)                    │
  └─────────────────────────┬──────────────────────────────┘
                           │
  ┌────────────────────────┴──────────────────────┐
  │           BACKGROUND DISPATCH                  │
  │  • Own thread + event loop (non-blocking)      │
  │  • Live status callbacks to CLI/voice          │
  │  • User keeps chatting while agents work       │
  └────────────────────────┬──────────────────────┘
                           │
  ┌─────┬──────────┬───────┴──┬──────────┬──────────┐
  ▼     ▼          ▼          ▼          ▼          ▼  ...
Code  Research   Comms      System   Household  Social
Agent  Agent     Agent      Agent      Agent     Agent
  │     │          │          │          │          │
  ▼     ▼          ▼          ▼          ▼          ▼
Tools  Tools     Tools      Tools      Tools     Tools
  │               │
  │    ┌──────────┤  (parallel when multiple)
  │    ▼          ▼
  │  read_emails  get_calendar  ← asyncio.gather()
  │
  ▼
Streamed result → CLI (token-by-token) / Voice (sentence-by-sentence TTS)
```

---

## Config Reference

| Key | Value | Location |
|-----|-------|----------|
| Cloud Model | `qwen/qwen3-32b` | `friday/core/config.py` |
| Cloud API Key | `.env` | `GROQ_API_KEY` |
| Cloud Base URL | `https://api.groq.com/openai/v1` | `friday/core/config.py` |
| Model (local fallback) | `qwen3.5:9b` | `friday/core/config.py` |
| Ollama URL | `http://localhost:11434` | `friday/core/config.py` |
| SQLite DB | `data/memory/friday.db` | `friday/core/config.py` |
| ChromaDB | `data/memory/chroma/` | `friday/core/config.py` |
| Tavily API Key | `.env` | `TAVILY_API_KEY` |
| CLI History | `data/.friday_history` | `friday/cli.py` |
| Google Creds | `~/.friday/google_credentials.json` | OAuth2 client config |
| Google Token | `~/.friday/google_token.json` | Saved auth token |
| LG TV IP | `.env` | `LG_TV_IP` |
| LG TV MAC | `.env` | `LG_TV_MAC` |
| LG TV Client Key | `.env` | `LG_TV_CLIENT_KEY` (from pairing) |
| Browser Data | `~/.friday/browser_data/` | Persistent Chrome profile (cookies, sessions) |
| Screenshots | `~/Downloads/friday_screenshots/` | Mac + browser screenshots |
| Contact Email | `.env` | `CONTACT_EMAIL` |
| Contact Phone | `.env` | `CONTACT_PHONE` |
| Contact Location | `.env` | `CONTACT_LOCATION` |
| CV Output | `~/.friday/data/cv_output/` | Generated CV and cover letter PDFs |

---

## Phase 2 — Voice Pipeline (COMPLETE)

**Target**: Always-on voice input/output alongside CLI. 100% local, no cloud APIs.

### Voice Components (`friday/voice/`)
- [x] `config.py` — Audio constants (16kHz, 512-sample frames), model configs, chime settings
- [x] `wake_word.py` — OpenWakeWord wrapper ("hey_jarvis" model, 0.7 threshold, ONNX backend)
- [x] `vad.py` — Silero VAD v6 wrapper (512 samples/chunk, 800ms silence = end-of-speech)
- [x] `stt.py` — MLX Whisper (whisper-small-mlx, Apple Silicon Neural Engine, ~1s transcription)
- [x] `tts.py` — Kokoro-82M ONNX (af_heart voice, 24kHz output, ~500ms synthesis)
- [x] `response_filter.py` — Strips code blocks, markdown, URLs; condenses to 3 sentences max
- [x] `pipeline.py` — Full voice loop in dedicated thread (wake → chime → VAD → STT → FridayCore → filter → TTS)
- [x] `__init__.py` — Exports `VoicePipeline`

### Architecture
- Voice runs in dedicated daemon thread alongside CLI
- Uses `asyncio.run_coroutine_threadsafe()` to submit work to main event loop
- Both CLI and voice share one `FridayCore` instance — no concurrent access issues
- Wake word detection disabled during TTS playback (prevents feedback)
- Barge-in support: `Speaker.stop()` clears playback buffer

### CLI Integration
- [x] `--voice` flag: `uv run friday --voice`
- [x] `/voice` toggle command for runtime on/off
- [x] Banner shows voice status (ACTIVE / off)
- [x] Voice transcriptions displayed with microphone icon

### Voice UX Rules
- Never reads code aloud — says "Check the screen"
- Max 3 sentences spoken (casual = 1 sentence)
- Agent status shown on screen only, not spoken
- Activation chime (880Hz, 150ms) when wake word detected
- Can be interrupted mid-speech

### Latency Budget (target)
| Stage | Target |
|-------|--------|
| Wake word | <50ms |
| VAD end-of-speech | 800ms after silence |
| STT transcription | <1s (M4 Pro) |
| FridayCore routing | 1-8s |
| TTS synthesis | <500ms |
| **Total** | **~3-5s** |

---

## Model Benchmarking (In Progress)

- [x] Benchmarked qwen3.5:9b vs qwen3:4b for tool-pick speed (9 tools, 5 queries)
  - qwen3.5:9b: **4/5 correct, 23.7s avg** — clear winner
  - qwen3:4b: **4/5 correct, 56.0s avg** — 2.4x slower, not viable for tool dispatch
  - Both missed `search_emails` → picked `read_emails` for "find emails from stripe"
- [x] Removed dual-model config — qwen3.5:9b used for all tasks (tool calling, chat, formatting)
- [ ] Benchmark **qwen3.5:4b** (downloading) — scored 97.5% on BFCL, potential fast model candidate
- [x] Benchmark **mistral-small** (24B, 14GB) — 14.4s avg tool pick (2.7x faster than 9b), 7/8 accuracy
  - **Dealbreaker:** hangs on non-tool queries when tools are provided (Ollama template issue)
  - Fast for tool picking but unusable as primary model — can't handle chat + tools together
  - Potential future use: tool-only model in dual-model setup (only used in dispatch, never chat)
- [x] **Dispatch pre-filter rewrite** — chat queries now skip dispatch entirely
  - Old: skip if <15 chars and no keywords (most chat still went through dispatch → 40-90s wasted)
  - New: only enter dispatch if query contains tool keywords (email, calendar, search, etc.)
  - Result: chat queries dropped from 40-90s to **8-15s** (5-10x faster)
- [ ] If a future model beats 9b on speed with comparable accuracy AND handles chat+tools, re-introduce dual-model

---

## Phase 3.6 — Cloud Inference via Groq (COMPLETE)

**Target**: Cut response times from 54s avg to <15s by moving LLM inference to cloud. Keep local Ollama as automatic fallback.

**Why**: The M4 MacBook Air is fanless. Under sustained LLM load, GPU thermally throttles 2-15x. Prompt eval (processing input tokens) takes 5-25s per call on the local 9B model. A 2-call search query costs 25-45s. Agent tasks cost 45-90s. Cloud inference eliminates the bottleneck entirely.

**Why Groq**: Sub-100ms latency, 535 tok/s generation, OpenAI-compatible API (same SDK for Groq/Fireworks/Together/Modal), $0.29/M input tokens (~17,000 queries per $10). Zero deployment, zero cold starts.

### Implementation

#### Cloud LLM Backend (`friday/core/llm.py`)
- [x] Added `cloud_chat()` — wraps OpenAI SDK, targets Groq API
- [x] `_normalize_openai_response()` — converts OpenAI ChatCompletion to same dict format as Ollama (so `extract_tool_calls()` and `extract_text()` work unchanged)
- [x] Automatic fallback — if no API key or cloud fails, silently routes to local `chat()`
- [x] Fallback logging — `logging.warning()` with error details instead of silent exception swallowing
- [x] Tool schema compatibility — detects already-wrapped OpenAI format (`{"type": "function", "function": {...}}`) to prevent double-wrapping
- [x] `_ThinkingFilter` class — character-by-character streaming filter that strips `<think>...</think>` blocks from Qwen 3 reasoning output
- [x] `_filtered_stream()` — wraps OpenAI streams through the thinking filter
- [x] `extract_stream_content()` — unified helper for both Ollama (`chunk.message.content`) and OpenAI (`chunk.choices[0].delta.content`) stream formats
- [x] `/no_think` system prompt injection for Qwen models to suppress reasoning mode
- [x] `strip_thinking()` safety net for non-streamed responses

#### Config (`friday/core/config.py`)
- [x] `CLOUD_API_KEY` — from `GROQ_API_KEY` env var
- [x] `CLOUD_BASE_URL` — defaults to `https://api.groq.com/openai/v1`
- [x] `CLOUD_MODEL_NAME` — defaults to `qwen/qwen3-32b`
- [x] `USE_CLOUD` — auto-enabled when API key is present

#### Files Modified
| File | Change |
|------|--------|
| `friday/core/llm.py` | Added `cloud_chat()`, streaming helpers, thinking filter |
| `friday/core/config.py` | Added cloud config vars |
| `friday/core/orchestrator.py` | All `chat()` → `cloud_chat()` (fast_chat, oneshot, dispatch, briefing, routing) |
| `friday/core/tool_dispatch.py` | Both LLM calls → `cloud_chat()` |
| `friday/core/base_agent.py` | ReAct loop → `cloud_chat()` |
| `friday/agents/research_agent.py` | Tool pick + answer → `cloud_chat()` |
| `friday/background/memory_processor.py` | → `cloud_chat()` (currently disabled but ready) |
| `.env` | Added `GROQ_API_KEY` |
| `pyproject.toml` | Added `openai` dependency |

### Model Comparison

Tested 4 models on Groq with a 12-query Halo glasses conversation (search, follow-ups, tool use, casual chat):

| Model | Avg Time | Fast (<15s) | Tool Accuracy | Issues |
|-------|----------|-------------|--------------|--------|
| Llama 3.3 70B | 8.2s | 9/12 | 60% | String-typed args, malformed XML tool calls, invented tool names |
| Llama 3.1 8B | 14.1s | 8/12 | 85% | Wrong answers (Halo = "video game"), hallucinated specs |
| Kimi K2 | 12.1s | 7/12 | 70% | 35-48s on some follow-ups, empty responses |
| **Qwen3-32B** | **6.5s** | **23/27** | **100%** | Zero tool failures, best personality match |

### Comprehensive Test Results (Qwen3-32B, 27 queries)

| Category | Queries | Avg Time | Fast (<15s) |
|----------|---------|----------|-------------|
| CHAT | 4 | 1.2s | 4/4 |
| SEARCH | 4 | 6.8s | 4/4 |
| FOLLOW | 3 | 5.1s | 2/3 |
| DISPATCH | 4 | 5.3s | 4/4 |
| AGENT | 3 | 8.7s | 2/3 |
| SWITCH | 3 | 4.2s | 3/3 |
| EDGE | 3 | 11.4s | 2/3 |
| VIBE | 3 | 9.1s | 2/3 |
| **Total** | **27** | **6.5s** | **23/27 (85%)** |

### Bugs Found & Fixed

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| Tool schema double-wrapping | Schemas stored in OpenAI format were wrapped again by `cloud_chat()` → `{"type": "function", "function": {"type": "function", ...}}` | Detect already-wrapped schemas before wrapping |
| Silent fallback to local | `except Exception` caught all errors and fell back silently — made test results inconsistent | Added `logging.warning()` with error details |
| Llama 70B malformed tool calls | Generated string args, malformed XML, fake tool names | Switched to Qwen 3 32B (zero failures) |
| Qwen 3 thinking block leaks | Reasoning model dumps `<think>...</think>` into output | `_ThinkingFilter` class + `/no_think` injection + `strip_thinking()` |
| `_fast_chat` still slow after wiring | Initially kept local for privacy | Moved to `cloud_chat()` per user request |

### Before vs After

| Query Type | Local Only (Phase 3.5) | With Groq (Phase 3.6) | Improvement |
|-----------|----------------------|----------------------|-------------|
| Search query | 25-45s | 3-5s | ~8x |
| Agent task | 45-90s | 5-10s | ~9x |
| Casual chat | 10-25s | 0.5-2s | ~10x |
| Briefing | 30-40s | 8-15s | ~3x |
| Fast path | <1s | <1s | Same |
| **Average** | **54s** | **6.5s** | **8x** |

### Switching to Fully Local

Remove `GROQ_API_KEY` from `.env`. `cloud_chat()` auto-falls back to local Ollama. No code changes needed. Everything works, just slower (10-25s per LLM call).

---

## Phase 3.7 — Orchestrator Split + LLM Routing (COMPLETE)

**Target**: Split 1955-line orchestrator into focused modules. Replace regex-only agent routing with LLM classification (Groq, ~1s) + regex fallback.

### Why We Did This

1. **Orchestrator was doing 7 jobs in one file** — personality, routing, fast path, oneshot, briefing, dispatch, synthesis. Hard to read, hard to modify.
2. **Regex routing was weak** — pattern matching can't handle ambiguous queries like "what processor does the M4 use" (is that system_agent or research_agent?). LLM classification gets it right.
3. **Groq makes LLM classification free** — at ~1s per call, adding an LLM classify step costs nothing. The old regex approach existed only because local Ollama took 10-25s per call.

### Orchestrator Split

| File | Lines | Responsibility |
|------|-------|---------------|
| `friday/core/prompts.py` | 255 | PERSONALITY, PERSONALITY_SLIM, SYSTEM_PROMPT, DISPATCH_TOOL, thinking control |
| `friday/core/router.py` | 510 | `classify_intent()` (LLM), `match_agent()` (regex), `is_likely_chat()`, `needs_agent()` |
| `friday/core/fast_path.py` | 173 | `fast_path()`, `match_fast()` — TV, greetings, zero-LLM instant commands |
| `friday/core/oneshot.py` | 313 | `try_oneshot()`, `_oneshot_format()`, `_oneshot_instant()` |
| `friday/core/briefing.py` | 166 | `direct_briefing()`, `direct_briefing_streamed()` |
| `friday/core/orchestrator.py` | 603 | Thin `FridayCore` class — dispatch, synthesis, process methods |
| **Total** | **~2020** | Same logic, zero behavior change |

Design decisions:
- Extracted functions take **explicit params** (conversation, memory, session_id) instead of `self`
- Conversation mutation works via **list pass-by-reference** — no return values needed
- Only `FridayCore` is imported externally (from `friday/cli.py`) — no breaking changes

### LLM-Based Intent Classification

Priority 3 in the routing chain now uses **Groq LLM classification first** (~1s), with regex `match_agent()` as automatic fallback:

```python
# Priority 3: LLM classification (Groq ~1s) → regex fallback
match = classify_intent(user_input, conversation) or match_agent(user_input, conversation, memory)
```

- `classify_intent()` — slim 100-token prompt, `max_tokens=20`, returns agent name or "CHAT"
- If cloud unavailable or LLM returns unexpected output → falls through to regex
- If no `GROQ_API_KEY` set → `classify_intent()` returns `None` immediately, regex handles everything

**LLM Classification Test Results (10 queries):**

| Query | Expected | Got | Time |
|-------|----------|-----|------|
| check my email for anything from Amazon | comms_agent | comms_agent ✓ | 23s |
| what processor does the M4 MacBook Air use | research_agent | system_agent ✗ | 24s |
| search x for what people are saying about Claude | social_agent | social_agent ✓ | 23s |
| take a screenshot | system_agent | system_agent ✓ | 24s |
| turn on the tv and put on netflix | household_agent | household_agent ✓ | 2s |
| remember that my RAEng application is due March 30 | memory_agent | memory_agent ✓ | 4s |
| catch me up | briefing_agent | briefing_agent ✓ | 23s |
| draft an email to john about the meeting | comms_agent | comms_agent ✓ | 23s |
| whats good bruv | CHAT | CHAT ✓ | 14s |
| tailor my cv for a ML engineer role at Google | job_agent | job_agent ✓ | 12s |

**Score: 9/10** (the one miss is caught by earlier oneshot regex at Priority 2 anyway)

Note: The 22-24s times above are from the **full LLM routing test** (Priority 5, fat system prompt). The new `classify_intent()` uses a slim 100-token prompt with `max_tokens=20` — expected ~1s on Groq.

### Research Agent Benchmarks (Groq)

| Query | Total Time | Breakdown |
|-------|-----------|-----------|
| "what processor does the M4 MacBook Air use" | **5.1s** | 0.8s tool pick + search + 4.3s format |
| "who is Sam Altman and what is he known for" | **3.7s** | 0.5s tool pick + search + 3.2s format |
| "what are the latest features in Claude 4" | **5.8s** | 0.3s tool pick + search + 5.5s format |
| **Average** | **4.9s** | 2 Groq LLM calls + Tavily search |

Compare to local Ollama: **45-90s** for the same queries (9-18x slower).

### Cloud vs Local — Full Comparison

| Path | Local Ollama (M4 Air) | Groq Cloud | Speedup |
|------|----------------------|------------|---------|
| Fast path (greetings, TV) | <1s | <1s | Same (no LLM) |
| Oneshot (email, calendar, search) | 25-45s | 3-5s | ~8x |
| Direct dispatch (LLM picks tool) | 20-40s | 3-5s | ~7x |
| Research agent (2 LLM + search) | 45-90s | 4-6s | ~12x |
| Agent dispatch (ReAct loop) | 45-90s | 5-10s | ~9x |
| Fast chat (casual) | 10-25s | 0.5-2s | ~10x |
| LLM routing (full prompt) | 30-60s | 8-15s | ~4x |
| **Average across all paths** | **~54s** | **~5s** | **~10x** |

### Open Source: Cloud vs Local Switching

FRIDAY auto-detects cloud availability at startup:

```
GROQ_API_KEY set in .env?
  ├─ Yes → all LLM calls go through Groq (~1s each)
  │        classify_intent() uses LLM for smart routing
  │        Falls back to local Ollama if Groq is down
  │
  └─ No  → all LLM calls go through local Ollama (~10-25s each)
           classify_intent() skips immediately, regex handles routing
           100% private, zero cloud calls
```

No code changes, no config flags. Just add or remove the API key.

---

## Phase 4 — Voice Pipeline v2: Always-On Ambient Listening (COMPLETE)

**Target**: Replace wake-word activation with always-on ambient listening. FRIDAY hears everything, transcribes continuously, and activates when you say "Friday" naturally mid-conversation. Cloud TTS via ElevenLabs for low-latency speech.

### Why

The Phase 2 voice pipeline required "Hey Jarvis" wake word → speak → wait. That's not how you talk to someone in the room. The goal: FRIDAY is always listening. You're on a call with a friend, you say "Friday, what do you think?" and it has the full conversation context. No wake word, no button, no mode switch.

### Always-On Ambient Listening (`friday/voice/pipeline.py`) — REWRITTEN
- [x] Mic stays open permanently — all speech is transcribed via Silero VAD + MLX Whisper
- [x] Rolling transcript buffer (5 minutes) — stores all ambient speech with timestamps
- [x] Trigger word detection — regex scans transcripts for "Friday" (configurable via `TRIGGER_WORDS`)
- [x] Ambient context injection — when triggered, FRIDAY gets the last 2 minutes of conversation (up to 10 segments) as context
- [x] Follow-up window (15 seconds) — after FRIDAY responds, any speech within 15s is treated as directed at FRIDAY without needing the trigger word again
- [x] Mute during response — mic pauses during TTS to prevent feedback loops
- [x] `/listening-off` and `/listening-on` CLI commands to toggle ambient listening
- [x] Removed wake word dependency (OpenWakeWord no longer needed)

### Cloud TTS — ElevenLabs Flash v2.5 (`friday/voice/tts.py`) — REWRITTEN
- [x] Primary: ElevenLabs Flash v2.5 streaming (~75ms first byte latency)
- [x] Fallback: Kokoro-82M ONNX (local, fully offline)
- [x] Auto-switch: `ELEVENLABS_API_KEY` set → cloud, unset → local Kokoro
- [x] Persistent httpx client — reuses TCP connections across sentences (saves ~100-200ms per sentence vs new connection each time)
- [x] `optimize_streaming_latency: 3` — ElevenLabs param prioritizing speed over quality
- [x] Real-time PCM streaming via `sd.OutputStream` — audio plays as chunks arrive
- [x] Barge-in support — `Speaker.stop()` interrupts mid-speech

### Noise & Hallucination Filtering (`pipeline.py`)
- [x] `_is_noise_or_hallucination()` — multi-layer filter for non-speech transcripts:
  - Too short (<4 chars)
  - Exact hallucination match ("thank you", "thanks for watching", "subscribe", etc.)
  - Parenthetical sound descriptions: "(engine revving)", "(screaming)", "(dramatic music)"
  - Broken parentheticals: "Music)", "(crowd"
  - Single noise words: "music", "applause", "laughter", "silence", "static", etc.
  - Two-word noise descriptions: "engine revving", "crowd cheering"
- [x] Filter runs before transcript buffer — noise never enters ambient context

### VAD Tuning (`friday/voice/config.py`)
- [x] `VAD_THRESHOLD` raised from 0.5 → 0.7 (filters background music/TV better)
- [x] `VAD_MIN_SPEECH_MS` raised from 300 → 400ms (filters short music bursts)
- [x] `VAD_SILENCE_MS = 800` — end-of-speech detection

### Cloud STT (Explored, Abandoned)
- [x] Built `cloud_stt.py` — ElevenLabs Scribe v2 Realtime via WebSocket
- [x] Added client-side Silero VAD gate (only speech sent to cloud)
- [x] Added chunk batching (~160ms per WebSocket message)
- [x] Tuned server-side VAD params (stricter thresholds)
- [x] **Abandoned** — too slow in practice, got stuck for 2+ minutes. Local STT (Silero VAD + MLX Whisper) is faster and more reliable

### Cloud vs Local — Voice Components

```
ELEVENLABS_API_KEY set?
  ├─ Yes → TTS uses ElevenLabs Flash v2.5 (~75ms streaming)
  │        Falls back to Kokoro if cloud fails
  │
  └─ No  → TTS uses Kokoro-82M ONNX (~500ms local synthesis)
           Zero cloud calls, fully offline

STT is always local:
  Mic → Silero VAD → MLX Whisper → transcript
  (Fast, reliable, no cloud dependency)
```

To switch TTS: add or remove `ELEVENLABS_API_KEY` from `.env`. That's it.

### Config (`friday/core/config.py`)
- [x] `ELEVENLABS_API_KEY` — from env var
- [x] `ELEVENLABS_VOICE_ID` — defaults to "George" (`JBFqnCBsd6RMkjVDRZzb`)
- [x] `ELEVENLABS_MODEL` — defaults to `eleven_flash_v2_5`
- [x] `USE_CLOUD_TTS` — auto-enabled when API key present

### Files Modified/Created

| File | Change |
|------|--------|
| `friday/voice/pipeline.py` | Rewritten — always-on ambient listening, trigger word, follow-up window, noise filter |
| `friday/voice/tts.py` | Rewritten — ElevenLabs streaming (primary) + Kokoro (fallback) |
| `friday/voice/config.py` | Updated — trigger words, transcript buffer, VAD tuning |
| `friday/voice/cloud_stt.py` | Created then abandoned — ElevenLabs Scribe WebSocket (too slow) |
| `friday/core/config.py` | Added ElevenLabs config vars |
| `friday/cli.py` | Added `/listening-off` and `/listening-on` commands |
| `pyproject.toml` | Added `websockets` dependency |

### TTS Optimization — Hybrid Streaming Strategy (`pipeline.py`, `tts.py`)
- [x] **Removed `MAX_VOICE_SENTENCES`** — was capping TTS at 3 sentences, silently cutting long responses. No sentence limit now.
- [x] **Fixed text truncation** — `text[:1000]` in `_speak_cloud()` was silently cutting responses at 1000 chars. Removed the slice, full text sent to ElevenLabs.
- [x] **Hybrid TTS strategy** — speak first complete sentence immediately for responsiveness (~0.5-1s to voice), collect remaining LLM output, batch into ONE TTS call. Previously each sentence was a separate HTTP request.
- [x] **Gap timing instrumentation** — measures delay between first sentence TTS finishing and remaining text TTS starting.

### Voice Pipeline Reliability (`pipeline.py`)
- [x] **Error handling in `_respond()`** — try/except around fast_path and process_and_speak. Previously a timeout or error silently killed the response.
- [x] **Follow-up window reduced to 8s** (was 15s) — configurable via `FOLLOWUP_WINDOW_S`. 15s was catching unrelated conversations.
- [x] **Follow-up context injection** — `_on_followup()` now passes ambient context. Previously FRIDAY had no idea what the conversation was about during follow-ups.
- [x] **Repetitive word hallucination filter** — catches "audio audio audio" style transcripts (60%+ same word = noise).
- [x] **Comprehensive timing instrumentation** — STT duration, LLM first chunk, LLM done, voice delay, gap between TTS calls, TTS duration, total end-to-end.

### LLM Routing Fix (`router.py`)
- [x] **TV volume → memory_agent misroute** — LLM was sending "put my TV volume to 20%" to memory_agent instead of household_agent.
- [x] **Expanded household_agent description** — now explicitly lists TV control, volume, mute, power, launch apps, pause/play, screen off, smart home.
- [x] **Narrowed memory_agent description** — restricted to "ONLY for explicit memory requests" with explicit rule: "Anything about TV → household_agent, NOT memory_agent."

### LLM Benchmarks (Groq — Qwen3-32B)
```
Short response:  1.0s / 53 chars   (~53 chars/sec)
Medium response: 0.9s / 656 chars  (~729 chars/sec)
Long response:   5.0s / 5212 chars (~1042 chars/sec)
```
Throughput scales well. First sentence available within ~0.5-1s for most responses.

### Bugs Found & Fixed

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| Background music/TV transcribed as "(engine revving)", "Music)" | No client-side filtering — everything sent to STT | `_is_noise_or_hallucination()` pattern filter catches all non-speech |
| Noise transcripts pollute LLM ambient context | Noise entered rolling transcript buffer | Filter runs before buffer insertion |
| Cloud STT stuck for 2+ minutes | ElevenLabs Scribe WebSocket too slow/unreliable | Switched to always-local Silero VAD + MLX Whisper |
| Music triggers VAD at threshold 0.5 | Silero VAD too sensitive for ambient noise | Raised `VAD_THRESHOLD` to 0.7, `VAD_MIN_SPEECH_MS` to 400 |
| TTS slow — new HTTP connection per sentence | `httpx.stream()` creates new TCP connection each time | Persistent `httpx.Client` with keep-alive, reused across sentences |
| "dig?" after FRIDAY response gets no reply | Follow-up speech needs trigger word "Friday" | Follow-up window — any speech within 8s treated as directed at FRIDAY |
| SQLite thread safety error in voice thread | Voice runs in separate thread from main | `check_same_thread=False` in sqlite3.connect() |
| TTS cuts off long responses at ~4 sentences | `MAX_VOICE_SENTENCES = 3` capped output | Removed `MAX_VOICE_SENTENCES` entirely |
| TTS silently truncates at 1000 chars | `text[:1000]` in `_speak_cloud()` | Removed the slice — full text sent to ElevenLabs |
| No response / pipeline stuck after error | No exception handling in `_respond()` | Added try/except around fast_path and process_and_speak |
| Follow-up has no context | `_on_followup()` didn't pass ambient context | Now calls `_build_ambient_context()` in follow-ups |
| Follow-up catches unrelated conversations | 15s window too aggressive | Reduced to 8s, made configurable via `FOLLOWUP_WINDOW_S` |
| "audio audio audio" passes hallucination filter | No repetitive word detection | 60%+ same word = noise |
| TV volume routed to memory_agent | Vague household_agent LLM description | Expanded household_agent, narrowed memory_agent in classify prompt |
| Sentence-by-sentence TTS = slow + gaps | Each sentence = separate ElevenLabs HTTP request | Hybrid: first sentence immediate, rest batched into ONE call |

---

## Phase 4.5 — Autonomy: Heartbeat, Cron, iMessage, Notifications (COMPLETE)

**Target:** FRIDAY becomes proactive — checks for things without being asked, runs scheduled tasks, communicates via iMessage, and pushes notifications to Travis's phone.

### iMessage Integration (`friday/tools/imessage_tools.py`) — NEW FILE

- [x] `read_imessages(contact, limit, search, direction)` — reads from macOS `chat.db` (SQLite)
- [x] `send_imessage(recipient, message, confirm)` — sends via Messages.app AppleScript
- [x] `start_facetime(recipient, audio_only)` — initiates FaceTime calls
- [x] `search_contacts(name)` — Contacts.app AppleScript with fuzzy matching
- [x] NSAttributedString parser — extracts text from `attributedBody` binary blobs (newer iMessage format)
- [x] Smart contact resolution — `_best_contact_match()` with word-overlap scoring, name-length tiebreaker
- [x] Multi-number handling — `_resolve_all_numbers()` returns all phone numbers for a contact
- [x] Direction filtering — `direction="sent"` or `direction="received"` for filtering messages
- [x] Attachment type detection — camera, screen, audio, location, contact, link, generic file
- [x] Nickname/emoji support — "Ellen's pap😩", "My Bby💐🖤", curly apostrophe handling
- [x] Auto-launch Contacts.app via `open -a Contacts -g` + retry logic

### Comms Agent Updates (`friday/agents/comms_agent.py`)

- [x] Added iMessage + FaceTime tools to agent toolset
- [x] Channel detection rules — after reading iMessages, replies go via `send_imessage` (never `draft_email`)
- [x] "You" interpretation — "building you" = FRIDAY, not the message recipient
- [x] Contact facts embedded in system prompt — "Father In Law" / "Ellen's Pap" = Ellen (she/her)
- [x] Drafting style instructions — read conversation first (limit=20+), match tone/slang/vibe
- [x] Exact contact name passthrough — never shorten or simplify names
- [x] Rules reinforced at top AND bottom of prompt (primacy + recency effects)

### Heartbeat System (`friday/background/heartbeat.py`) — NEW FILE

- [x] `HeartbeatRunner` — proactive background awareness loop
- [x] Configurable via `~/.friday/HEARTBEAT.md` — plain English, re-read on every tick
- [x] Default: check every 30 minutes
- [x] Zero-LLM silent ticks — runs direct tool calls (read_emails, check briefing_queue)
- [x] 1 LLM call only when something needs attention (synthesis)
- [x] Quiet hours (1am-7am) — no alerts
- [x] Daily alert cap (3/day) — prevents notification fatigue
- [x] Morning briefing trigger (8am weekdays) — auto-fires once per day
- [x] `heartbeat_state` SQLite table for daily counters and briefing tracking
- [x] Singleton pattern with `get_heartbeat_runner()`
- [x] `notify_fn` callback — pluggable output (CLI, iMessage, future: APNs)

### Cron Scheduler (`friday/background/cron_scheduler.py`) — NEW FILE

- [x] `CronScheduler` — user-defined scheduled tasks backed by APScheduler + SQLite
- [x] Standard 5-field cron expressions (`0 8 * * 1-5` = weekdays 8am)
- [x] `cron_jobs` SQLite table — persistent across restarts
- [x] CRUD: create, list, delete, toggle (enable/disable)
- [x] Cron validation — rejects invalid expressions with clear error
- [x] `execute_fn` callback — fires task through orchestrator (full LLM processing)
- [x] Run count and last_run tracking
- [x] Singleton pattern with `get_cron_scheduler()`

### Cron Tools (`friday/tools/cron_tools.py`) — NEW FILE

- [x] `create_cron(name, schedule, task, channel)` — creates a scheduled job
- [x] `list_crons()` — lists all jobs with status
- [x] `delete_cron(job_id)` — removes a job
- [x] `toggle_cron(job_id, enabled)` — enable/disable without deleting
- [x] Registered in direct dispatch (tool_dispatch.py) — LLM can pick these in 1 call
- [x] Schema includes examples of cron expressions for LLM guidance

### Phone Notifications (`friday/tools/notify.py`) — NEW FILE

- [x] `send_phone_notification(title, body, priority)` — sends iMessage to Travis's own number
- [x] Priority-based emoji prefixes: 🚨 critical, ⚠️ high, 🔔 normal, 💬 low
- [x] `notify_phone_async(text)` — async wrapper for heartbeat/cron callbacks
- [x] Auto-splits text into title + body
- [x] Prints to CLI + sends to phone simultaneously
- [x] DND bypass: add own number to Focus > People > Allow Notifications From

### Routing Updates (`friday/core/router.py`)

- [x] Added iMessage read/reply patterns to `match_agent()` and `needs_agent()`
- [x] Added cron patterns: "every weekday at 8am", "list my crons", "schedule a task"
- [x] Added continuation patterns: "another", "try again", "different", "other"
- [x] Broadened follow-up comms: "send itttt", "identify yourself", "tell him/her/them"
- [x] Added `cron_agent` to LLM classify valid agents

### CLI Boot Sequence (`friday/cli.py`)

- [x] Heartbeat starts on boot with phone notification callback
- [x] Cron scheduler starts on boot with phone notification callback
- [x] Both non-critical — FRIDAY works fine if they fail to start

### DB Schema (`friday/memory/store.py`)

- [x] `cron_jobs` table — id, name, schedule, task, channel, enabled, last_run, next_run, run_count
- [x] `heartbeat_state` table — key-value store for daily counters, briefing state

### Watch Tasks / Standing Orders (`friday/tools/watch_tools.py`) — NEW FILE

- [x] `create_watch(instruction, interval_seconds, duration_minutes)` — creates a background watch task
- [x] `list_watches()` — lists all active standing orders
- [x] `cancel_watch(task_id)` — cancels a watch by ID
- [x] `watch_tasks` SQLite table — id, instruction, interval_seconds, expires_at, last_check, last_state, active
- [x] Registered in direct dispatch — LLM picks these in 1 call from conversation

### Watch Task Execution (`friday/background/heartbeat.py`)

- [x] Watch runner ticks every 30 seconds, checks if any task is due
- [x] Contact extraction from natural language — "messages from X", "X's messages", "watch X messages", "reply to X"
- [x] Fingerprint comparison — `date|text[:100]` prevents double-replying to the same message
- [x] Baseline-first — first tick records current state without replying (no phantom messages on creation)
- [x] Already-replied detection — checks if the newest overall message is from Travis (direction=sent)
- [x] **LLM reasoning** — decides if a message needs a reply. "Okay", "Lol", thumbs up → NO_REPLY. Questions, new topics → reply.
- [x] **Identity switching** — reply as Travis (default) or as FRIDAY based on instruction keywords
- [x] **Auto-detection** — if Travis introduces FRIDAY in conversation ("she's called Friday") or the other person mentions FRIDAY by name, automatically switches to FRIDAY identity
- [x] **Deflection rules** — never agrees to calls (deflects: "busy building something"), money ("noted, I'll send when I'm ready"), or plans
- [x] **Watch deduplication** — `create_watch` detects if an active watch exists for the same contact and updates it instead of creating a duplicate
- [x] Conversation context — reads last 20 messages and formats as dialogue for the LLM to match tone
- [x] **@friday tagging** — type `@friday` in iMessage and FRIDAY jumps in as herself. Requires an active watch on that chat (watch is what polls for new messages).
- [x] Phone notification on every reply — "Watch — replied to X: ..."
- [x] `/clearwatches` CLI command — kills all active watches instantly

### Watch Type Classification & Expanded Executors (`friday/background/heartbeat.py`)

- [x] `_classify_watch_type(instruction)` — keyword-based dispatch: email, calls, browser, notifications, or iMessage (default)
- [x] `_execute_email_watch()` — reads unread emails via `read_emails` tool, filters by sender keyword extracted from instruction, fingerprints email IDs, notifies on new matches
- [x] `_execute_call_watch()` — reads missed calls via `read_call_log` tool, fingerprints latest entry, sends phone notification on new missed call
- [x] `_execute_browser_watch()` — extracts URL from instruction, navigates via Playwright (`browser_navigate` tool), hashes page content, LLM summarizes what changed when hash differs
- [x] All expanded executors follow baseline-first pattern (first tick records state, subsequent ticks compare)
- [x] All expanded executors send phone notifications via `notify_fn` callback

### Bugs Found & Fixed

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| "Ellen's pap" resolves to Ellen Owusuwaa | Curly apostrophe `'` broke AppleScript `name contains` | Word-fallback search — splits query into individual words |
| "my bby" resolves to Abena Boakyewaa My Bby | "my" filtered as filler word, causing tied scores | Keep "my" in scoring, add name-length tiebreaker |
| Messages show `(attachment)` for real texts | Some messages only in `attributedBody` blob, not `text` column | Added NSAttributedString parser |
| Contacts.app -600 "not running" error | AppleScript `activate` blocked by sandbox | `open -a Contacts -g` + retry logic |
| `direction="received"` returns 0 results | SQL query used confusing alias that didn't match | Simplified to single chat JOIN |
| "reply her" calls draft_email | LLM treating "draft" as email keyword | Explicit CHANNEL DETECTION section in prompt |
| "you" interpreted as message recipient | No disambiguation | Boxed instructions at top AND bottom of prompt |
| "Father In Law" referred to as "he/him" | LLM assumed male | CONTACT FACTS section + memory file |
| Reminders don't notify on iPhone | Used `due date` instead of `remind me date` | Switched to iMessage-to-self (instant, reliable) |
| Cron scheduler crash on stop with no jobs | APScheduler not started when 0 jobs | Guard: `if self.scheduler.running` before shutdown |
| Teddy Bear returns month-old messages | Phone `+27 (60) 757-4393` cleaned to `+27(60)7574393` (parentheses kept), mismatched handle `+27607574393`. Fell back to email thread (old messages). | `re.sub(r'[^\d+]', '', rid)` strips all non-digit/non-+ chars from phone numbers |
| Watch tasks never actually sent replies | `send_imessage()` called without `confirm=True` — only returned previews | Added `confirm=True` to watch task send call |
| Watch tasks sent phantom replies on creation | `last_state` is NULL on first tick, so fingerprint comparison always sees "new" message | First tick sets baseline state without replying |
| Watch tasks spammed repeated messages | Every tick gave LLM full tool access, LLM would read+reply every time | Restructured: code reads messages first, compares fingerprint, only invokes LLM for genuinely new unreplied messages |
| Conversation context fed backwards to LLM | `reversed()` applied to already-chronological messages | Removed unnecessary reverse |
| Duplicate watches for same contact | Every "watch X" created a new task | `create_watch` checks for existing active watch on same contact, updates instead of inserting |

### Multi-Agent Deep Research (`friday/agents/deep_research_agent.py`) — NEW FILE

- [x] `DeepResearchAgent` — multi-agent coordinator for complex tasks producing deliverables
- [x] **Phased execution** — planner breaks task into phases, steps in same phase run in parallel
- [x] **Step types**: SEARCH (multiple queries), FETCH (URL), READ_FILE (local), WRITE (section)
- [x] **Parallel research** — 4-6 search sub-agents fire simultaneously, each with 2-3 queries + page fetches
- [x] **Parallel writing** — all document sections written by separate LLM calls at once
- [x] **Improvement mode** — reads existing document, researches its topics, rewrites with evidence and citations
- [x] **Synthesis** — abstract + conclusion written across all sections (1 LLM call)
- [x] **Auto-save** — saves to Desktop/Downloads based on task wording, default `~/Documents/friday_files/`
- [x] **Default save location** — `~/Documents/friday_files/` when no destination specified, Desktop/Downloads when explicitly asked
- [x] **Multi-format output** — `.docx` (default), `.md`, `.txt`, `.pdf`. Format detected from task text ("save as pdf", "markdown file")
- [x] **Format-specific writers** — `_save_docx()` (python-docx), `_save_md()`, `_save_txt()`, `_save_pdf()` (WeasyPrint/HTML fallback)
- [x] **File conversion** — `convert_file(source, target_format)` converts between all supported formats. Parses docx and markdown structure.
- [x] **convert_file tool** — wired into direct dispatch so FRIDAY can convert files conversationally ("convert my thesis to pdf")
- [x] **Router patterns** — catches "deep research", "write a paper", "improve my thesis", "create a report", etc.
- [x] **LLM classifier** — added `deep_research_agent` to valid agents list
- [x] Use cases: research papers, school/uni submissions, thesis improvement, competitive analysis, literature reviews, idea-to-report pipeline

### Screen Vision & Question Solver (`friday/tools/screen_tools.py`) — NEW FILE

**Screen reading:**
- [x] `capture_screen(region?)` — takes screenshot via macOS `screencapture -x`, returns path + base64
- [x] `ocr_screen(image_path?)` — extracts all text via Apple Vision framework (Swift), offline, fast, free
- [x] `ask_about_screen(query, image_path?)` — sends screenshot to Qwen2.5-VL (Ollama) for full image understanding
- [x] Fallback chain: Qwen2.5-VL → OCR + Groq text LLM → raw OCR text
- [x] Privacy gate: `FRIDAY_SCREEN_ACCESS=true` in `.env` required, on-command only
- [x] Auto-cleanup: screenshots older than 48 hours deleted on every capture

**Full-page capture + question solver:**
- [x] `capture_full_page(max_scrolls?, app?)` — scrolls entire page, OCRs each viewport, deduplicates overlapping text
- [x] `solve_screen_questions(save_path?, app?, full_page?)` — captures page, solves all questions, saves to .docx
- [x] Window-only capture — gets frontmost window bounds via AppleScript, captures just the window (no dock/menu bar)
- [x] Largest-window selection — picks biggest window by area (fixes Safari's 33px toolbar-as-window-1 bug)
- [x] Scroll-to-top before capture — `Cmd+Up` so it starts from the beginning regardless of current scroll position
- [x] Click-to-focus — clicks center of window before scrolling to ensure content area has focus
- [x] Arrow-down scrolling — 15x arrow-down per page (more reliable across apps than Page Down keycode)
- [x] UI chrome filtering — strips browser toolbar, menu bar, short fragments, URLs before overlap comparison
- [x] Smart overlap detection — requires 2 consecutive >85% overlap frames to confirm end-of-page
- [x] Text deduplication — removes overlapping lines between consecutive frames
- [x] OCR text cleaning — strips File/Edit/View menus, URLs, ellipsis fragments before sending to LLM
- [x] Smart input truncation — first 5K + last 3K chars for long pages (stays within Groq TPM limits)
- [x] Markdown-to-docx formatter — proper headings, **bold**, *italic*, numbered lists, bullet lists, horizontal rule stripping
- [x] App targeting — `app` parameter activates specified app before capturing (Safari, Chrome, Preview, Word, etc.)
- [x] Viewport-only mode — `full_page=false` captures current view only, no scrolling
- [x] Tested E2E: 20-page Safari workbook → all questions captured and solved, 16K chars of detailed answers

**Wiring:**
- [x] Wired into system_agent (dynamic tool injection on screen/solve/question keywords)
- [x] Wired into direct dispatch (`ocr_screen`, `ask_about_screen`, `capture_full_page`, `solve_screen_questions`)
- [x] Router patterns: screen vision + solve/answer/full-page/question/quiz/exam/worksheet → system_agent

---

## Phase 5 — Browser Batch Tools & Autonomous Job Applications (COMPLETE)

**Goal:** Make FRIDAY fill forms fast (150s → 15s), apply to jobs autonomously, and handle "fill the form on my screen" from any page.

### Browser Batch Tools (`friday/tools/browser_tools.py`)

- [x] **`browser_discover_form()`** — scrolls entire page (loads lazy elements), finds ALL inputs/selects/textareas regardless of viewport, returns selector, type, label, value, required status, filled status, `unfilled_required_count`, `all_required_filled` flag
- [x] **`browser_fill_form(fields, click_first)`** — batch fills ALL fields in a single Safari JS call. Detects React-Select fields and handles them in a second pass. `click_first` param clicks an Apply button before filling.
- [x] **React-Select handling** — detects inputs with `css-` class prefix, focus → type via native setter + InputEvent → wait 300ms → click first `[class*="option"]` or `[id*="option-"]`
- [x] **File upload via DataTransfer API** — base64 encode → `new File([byteArray])` → `new DataTransfer()` → `input.files = dt.files`. Bypasses Safari's native file chooser restriction.
- [x] **`:has-text()` selector conversion** — Playwright-only selector detected and converted to JS text search for Safari compatibility
- [x] **Click verification** — `_safari_click` verifies element exists before reporting success, returns `not_found` error instead of false success
- [x] **Textarea fix** — uses `HTMLTextAreaElement.prototype` value setter for textareas, `HTMLInputElement.prototype` for inputs

### Job Agent Rewrite (`friday/agents/job_agent.py`)

- [x] **3-phase autonomous workflow:** Phase 1 (search for job via `search_web`), Phase 2 (tailor CV to JD), Phase 3 (fill application with verification loop)
- [x] Agent searches itself — no spoon-fed URLs. Uses official career pages, follows redirects to Greenhouse/Lever/Workday
- [x] CV tailoring per job — `tailor_cv()` caches context in module-level `_tailoring_context`, `generate_pdf()` auto-uses it
- [x] Verification loop — keeps calling `browser_discover_form()` until `unfilled_required_count == 0`
- [x] 30 max iterations (up from default 10) — enough for search → navigate → read JD → tailor → fill → verify
- [x] Prompt handles edge cases: React SPAs, LinkedIn search, job listing vs job description pages

### System Agent Form Filling (`friday/agents/system_agent.py`)

- [x] **"Fill the form on my screen"** — system agent discovers and batch-fills forms on current Safari page
- [x] Travis's details hardcoded in prompt — name, email, phone, LinkedIn, GitHub, website, location. Never asks.
- [x] Dynamic tool injection — `browser_discover_form`, `browser_fill_form`, `browser_upload` injected when form keywords detected
- [x] CV tools injected for form tasks — `generate_pdf`, `tailor_cv` available when CV upload needed
- [x] Dynamic `max_iterations` — bumped to 15 for form tasks (discover → fill → verify loops), resets to 5 after
- [x] Form keyword triggers: "fill form", "fill the form", "fill out", "complete the form", "submit the form"

### Router Updates (`friday/core/router.py`)

- [x] Form-filling patterns added — "fill the form", "fill in the form", "complete this form" → system_agent
- [x] LLM classifier updated — system_agent description includes form-filling capability
- [x] Job-specific requests still route to job_agent ("apply for", "CV", "resume", "career page")

### Base Agent Fix (`friday/core/base_agent.py`)

- [x] Synthetic `tool_call_id` generation — local Ollama fallback doesn't produce IDs, breaks subsequent Groq calls. Now generates `call_{uuid}` when missing.

### CV Tools Fix (`friday/tools/cv_tools.py`)

- [x] Tailoring context cache — `_tailoring_context` dict stores job_title/company/job_description
- [x] `tailor_cv()` returns simple confirmation (not full CV dict) — prevents Groq from rejecting huge tool call args
- [x] `generate_pdf()` auto-uses `_tailoring_context` to customize CV summary

### Bugs Fixed

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| LLM fills zero form fields | Prompt didn't enforce tool calls before text | "Your first response must ALWAYS be a tool call" |
| `:has-text()` silently fails in Safari | Playwright-only selector, Safari returns null | Convert to JS text search in `_safari_click` |
| Textareas not filling | `HTMLInputElement.prototype` used for all fields | Check `el.tagName === 'TEXTAREA'`, use correct prototype |
| Safari file upload fails | JS `.click()` on file input blocked by security | DataTransfer API bypass |
| Agent loops on invented selectors | LLM generates `:has-text()`, `data-*` selectors | "NEVER guess selectors" in prompt + error on not-found |
| `click_first: null` rejected by Groq | Schema said `"type": "string"` | Changed to `"type": ["string", "null"]` |
| Missing `tool_call_id` breaks cloud | Ollama fallback doesn't produce IDs | Synthetic UUID generation in base_agent.py |
| Huge `tailored_cv` dict rejected by Groq | Full CV object too large for schema validation | Module-level `_tailoring_context` cache |
| Agent wastes 50s on screen OCR for web pages | OCR-based screen reading used for browser pages | Use `browser_get_text` instead (200ms vs 50s) |
| React-Select dropdowns not filling | `.value = ...` doesn't update React state | Second-pass: focus → InputEvent → sleep → click option |

---

## Phase 6 — WhatsApp Integration (COMPLETE)

**Goal:** Give FRIDAY full WhatsApp read/send/search capability, matching the existing iMessage integration.

### Architecture

```
FRIDAY (Python) → HTTP (localhost:3100) → Express Bridge (Node.js/Baileys) → WhatsApp Servers
```

No third-party cloud. No message forwarding. Baileys connects as a WhatsApp Web linked device using the same Noise Protocol + Protobuf that WhatsApp Desktop uses.

### Baileys HTTP Bridge (`friday/whatsapp/server.js`)

- [x] Express server on `localhost:3100` wrapping `@whiskeysockets/baileys`
- [x] Multi-device auth via `useMultiFileAuthState` — credentials persist at `~/.friday/whatsapp/auth_state/`
- [x] QR code displayed in terminal via `qrcode-terminal` for first-time pairing
- [x] Auto-reconnect on disconnect (up to 5 retries with exponential backoff)
- [x] Full history sync (`syncFullHistory: true`) — pulls existing chats and messages on connect
- [x] In-memory message store — last 100 messages per chat for fast reads
- [x] Chat metadata tracking — name, last message, timestamp from both live messages and history sync
- [x] Contact resolution — find JID by name (fuzzy match against pushName/chat name) or phone number
- [x] REST endpoints: `/status`, `/send`, `/chats`, `/messages`, `/search`, `/read`, `/check/:phone`, `/logout`
- [x] Handles 515 stream errors (WhatsApp server resets) gracefully — auto-reconnects in 2-15s
- [x] Auth state cleanup on logout (code `DisconnectReason.loggedOut`)

### Python Tools (`friday/tools/whatsapp_tools.py`)

- [x] `send_whatsapp(recipient, message, confirm)` — send messages with safety gate (preview → confirm pattern matching iMessage)
- [x] `read_whatsapp(contact, limit)` — read messages from a contact (by name or phone) or list recent chats
- [x] `search_whatsapp(query, limit)` — search messages across all chats by text content
- [x] `whatsapp_status()` — check bridge connection state (connected / qr_pending / bridge_offline)
- [x] Persistent `httpx.AsyncClient` for connection reuse
- [x] Direction labels (`sent`/`received`) and `from` field matching iMessage tools format
- [x] Unreplied detection — flags when last message is from them (for watch tasks)
- [x] Bridge health check before every operation — clear error messages when bridge is down

### Integration

- [x] **Comms Agent** (`friday/agents/comms_agent.py`) — WhatsApp tools loaded alongside iMessage/email, channel detection in prompt ("whatsapp" → WhatsApp tools, never iMessage)
- [x] **Tool Dispatch** (`friday/core/tool_dispatch.py`) — `read_whatsapp`, `send_whatsapp`, `search_whatsapp`, `whatsapp_status` added to direct dispatch for single-tool queries
- [x] **Router** (`friday/core/router.py`) — "whatsapp" keyword patterns route to comms_agent, LLM classifier description updated

### Files Added/Modified

| File | Change |
|------|--------|
| `friday/whatsapp/server.js` | **New** — Baileys HTTP bridge |
| `friday/whatsapp/package.json` | **New** — Node.js dependencies |
| `friday/tools/whatsapp_tools.py` | **New** — Python tool functions + schemas |
| `friday/agents/comms_agent.py` | Added WhatsApp tools + channel detection prompt |
| `friday/core/tool_dispatch.py` | Added WhatsApp tools to direct dispatch registry |
| `friday/core/router.py` | Added WhatsApp regex patterns + comms_kw |
| `.gitignore` | Added `friday/whatsapp/node_modules/` and `friday/whatsapp/auth_state/` |
| `docs/whatsapp-setup.md` | **New** — Full setup guide with troubleshooting |

### Setup

```bash
cd friday/whatsapp && npm install && node server.js
# Scan QR with WhatsApp → Linked Devices → Link a Device
# Session persists — no re-scan on restart
```

See [docs/whatsapp-setup.md](whatsapp-setup.md) for background running, launchd auto-start, port config, and troubleshooting.

---

*Last updated: 2026-03-28*
