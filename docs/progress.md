# FRIDAY — Development Progress

## Project Overview

**FRIDAY** — Personal AI Operating System.
Inspired by Tony Stark's JARVIS/FRIDAY. Not a chatbot. A co-founder, a 3am coding partner.

- **Repo**: `~/Desktop/JARVIS`
- **Model**: Qwen3.5-9B (local via Ollama)
- **Stack**: Python 3.12, uv, Ollama, ChromaDB, SQLite, Tavily, Rich
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
  - `browser_navigate()` — go to URL, returns title + status code + login detection
  - `browser_screenshot()` — capture page or element, saves to `~/Downloads/friday_screenshots/`
  - `browser_click()` — click elements with safety check for pay/delete/submit
  - `browser_fill()` — fill form fields
  - `browser_get_text()` — extract text content from page elements
  - `browser_wait_for_login()` — pause while Travis logs in manually, detects when login completes
  - `browser_close()` — close browser, sessions are saved
  - **Persistent browser profile** — uses real Chrome (`channel="chrome"`), cookies/sessions saved in `~/.friday/browser_data/`
  - **Login detection** — checks URL patterns and page content for login indicators, returns `login_required: true` flag
  - Log in once, sessions persist across FRIDAY restarts
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
| Browser sessions lost between runs | Fresh Playwright context each time — no cookies/sessions saved | Persistent browser profile at `~/.friday/browser_data/` with `channel="chrome"` |
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
| Model (primary) | `qwen3.5:9b` | `friday/core/config.py` |
| Model (fast) | `qwen3:4b` | `friday/core/config.py` |
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

*Last updated: 2026-03-24*
