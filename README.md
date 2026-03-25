# FRIDAY

**Personal AI Operating System** — inspired by Tony Stark's JARVIS/FRIDAY.

Not a chatbot. Not an assistant. A co-founder. A 3am coding partner who remembers you, understands your slang, and gets things done.

```
  ███████╗██████╗ ██╗██████╗  █████╗ ██╗   ██╗
  ██╔════╝██╔══██╗██║██╔══██╗██╔══██╗╚██╗ ██╔╝
  █████╗  ██████╔╝██║██║  ██║███████║ ╚████╔╝
  ██╔══╝  ██╔══██╗██║██║  ██║██╔══██║  ╚██╔╝
  ██║     ██║  ██║██║██████╔╝██║  ██║   ██║
  ╚═╝     ╚═╝  ╚═╝╚═╝╚═════╝ ╚═╝  ╚═╝   ╚═╝
```

---

## What Is FRIDAY?

FRIDAY is a multi-agent AI system that routes your requests to specialist agents — code, research, memory, comms, system, household, monitor, briefing, job — and synthesises their work into a single coherent response. Runs hybrid: cloud inference via Groq for speed (6.5s avg), with automatic fallback to fully local Ollama when offline or if you prefer privacy.

**Core idea:** You talk to FRIDAY. FRIDAY figures out what needs to happen, dispatches the right agent, and delivers the result. You never interact with agents directly.

```
You: "man, you good?"
FRIDAY: Always. What's the play?                    ← <1ms, zero LLM

You: "check my emails"
FRIDAY: Say less. Working on it in the background.  ← instant ack
  ◈ checking emails                                 ← live status
FRIDAY (12s) You've got 4 unread. One from Stripe   ← direct dispatch (2 LLM)
  (critical) — payment webhook failing on prod...

You: "catch me up"
FRIDAY: On it. Keep chatting, I'll holler when done.
  ◈ checking emails...                              ← all 8 tools
  ◈ checking calendar...                              in parallel
  ◈ checking x_ai...
  ◈ ✓ emails done
  ◈ ✓ calendar done
  ◈ synthesizing briefing...
FRIDAY (32s) Three things. Global Talent page        ← 1 LLM call (was 12+)
  updated. Sam George tweeted about digital
  infrastructure. Calendar's empty...
```

---

## Quick Start

### Prerequisites

- **macOS** (tested on Apple Silicon)
- **Python 3.12+**
- **Ollama** — [install here](https://ollama.com)
- **uv** — Python package manager ([install](https://docs.astral.sh/uv/getting-started/installation/))

### Setup

```bash
# 1. Clone the repo
git clone <repo-url> && cd JARVIS

# 2. Pull the models
ollama pull qwen3.5:9b
ollama pull qwen3:4b

# 3. Create your .env file
echo 'TAVILY_API_KEY=your-key-here' > .env

# 4. Install dependencies
uv sync

# 5. Run FRIDAY
uv run friday

# 6. Run with voice (optional)
uv run friday --voice
```

That's it. No Docker. No config files to edit. Cloud inference is optional — see [Cloud Inference](#cloud-inference) below.

### Voice Mode

FRIDAY has an always-on ambient voice pipeline. The mic stays open — FRIDAY hears and transcribes everything. Say **"Friday"** naturally at any point (even mid-conversation with someone else) and FRIDAY activates with full context of what was just said.

```bash
# Start with voice enabled
uv run friday --voice

# Or toggle at runtime
/voice

# Pause/resume ambient listening
/listening-off
/listening-on
```

After FRIDAY responds, you have a **15-second follow-up window** — just keep talking without saying "Friday" again. CLI and voice work simultaneously — type or talk, your choice.

**STT (always local):** Silero VAD + MLX Whisper. Fast, reliable, no cloud dependency.

**TTS (cloud or local — your choice):**
```bash
# Cloud TTS (ElevenLabs Flash v2.5, ~75ms latency) — add to .env:
ELEVENLABS_API_KEY=your-key-here
ELEVENLABS_VOICE_ID=JBFqnCBsd6RMkjVDRZzb   # Optional — defaults to "George"

# Local TTS (Kokoro-82M ONNX, ~500ms) — just don't set the key above.
# Remove ELEVENLABS_API_KEY from .env and FRIDAY uses Kokoro automatically.
```

To switch between cloud and local TTS: add or remove `ELEVENLABS_API_KEY` from `.env`. That's it.

### Getting a Tavily API Key

FRIDAY uses [Tavily](https://tavily.com) for web search. Sign up at [app.tavily.com](https://app.tavily.com) — the free tier gives you 1,000 searches/month.

### Google API Setup

For email and calendar access (optional — FRIDAY works without it, just no comms agent):

```bash
# 1. Go to https://console.cloud.google.com
# 2. Create a project → Enable Gmail API + Calendar API
# 3. Create OAuth2 credentials (Desktop app is simplest)
# 4. Download the JSON → save as:
cp ~/Downloads/client_secret_*.json ~/.friday/google_credentials.json

# 5. Authenticate (opens browser for consent):
uv run python -m friday.tools.google_auth
```

**Note:** If your app is in "Testing" mode in Google Cloud Console, add your email as a test user under OAuth consent screen → Test users.

---

## Architecture

```
User Input (CLI / Voice)
      │
      ▼
┌───────────┐
│  FRIDAY   │  Orchestrator — routes tasks, never does the work itself
│   Core    │  Memory + conversation context injected every call
└─────┬─────┘
      │
      ├─ 1.   Fast Path       → regex → instant            (0 LLM, <1s)
      ├─ 1.5  User Override   → @agent → agent dispatch    (0s routing)
      ├─ 2.   Oneshot         → regex → tool + 1 LLM      (1 LLM, ~2s)
      ├─ 2.5  Direct Dispatch → LLM picks tool + format    (2 LLM, ~3-5s)
      ├─ 3.   Agent Dispatch  → regex → ReAct loop         (2-4 LLM, ~5-10s)
      ├─ 4.   Fast Chat       → 1 LLM slim prompt          (1 LLM, ~1s)
      └─ 5.   Full LLM Route  → fat prompt + dispatch      (4 LLM, ~8-15s)
      │
      ▼  (background thread — user keeps chatting)
      │
      ├────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┐
      ▼        ▼        ▼        ▼        ▼        ▼        ▼        ▼        ▼        ▼
┌────────┐┌────────┐┌────────┐┌────────┐┌────────┐┌────────┐┌────────┐┌────────┐┌────────┐┌────────┐
│  Code  ││Research││ Memory ││ Comms  ││ System ││  Home  ││Monitor ││Briefing││  Job   ││ Social │
│  Agent ││ Agent  ││ Agent  ││ Agent  ││ Agent  ││ Agent  ││ Agent  ││ Agent  ││ Agent  ││ Agent  │
└───┬────┘└───┬────┘└───┬────┘└───┬────┘└───┬────┘└───┬────┘└───┬────┘└───┬────┘└───┬────┘└───┬────┘
    │         │         │         │         │         │         │         │         │         │
    ▼         ▼         ▼         ▼         ▼         ▼         ▼         ▼         ▼         ▼
 File I/O  Tavily    ChromaDB  Gmail API AppleScript LG WebOS  Web fetch Monitors  CV Data   X API
 Terminal  httpx     SQLite    Calendar  Playwright  WakeOnLan Scheduler Emails    WeasyPrint tweepy
 Git       Known src Semantic  Drafts    Chrome,PDF  Smart Home Diffing  Calendar  Jinja2    Mentions
                                  │                                        │
                                  └── asyncio.gather() ────────────────────┘
                                      (parallel tool execution)
```

### How Routing Works (7-tier, fastest first)

| Priority | Path | How | Speed |
|----------|------|-----|-------|
| 1 | **Fast Path** | Regex → instant canned response or tool call | <1s, 0 LLM |
| 1.5 | **User Override** | `@agent` or `use agent` → direct dispatch | 0s routing |
| 2 | **Oneshot** | Regex → tool + 1 LLM format | ~3-5s |
| 2.5 | **Direct Dispatch** | LLM picks tool + 1 LLM format | ~3-5s |
| 3 | **Agent Dispatch** | LLM classify (~1s) → agent ReAct loop, regex fallback | ~5-10s |
| 4 | **Fast Chat** | 1 LLM with slim prompt | ~1s |
| 5 | **Full LLM Route** | Fat prompt + dispatch (ambiguous only) | ~8-15s |

**Priority 3 uses Groq LLM classification** (~1s) to pick the right agent, with regex as automatic fallback when offline. This replaced the old regex-only routing which couldn't handle ambiguous queries.

**All agent work runs in background** — user keeps chatting. Live status updates stream to CLI/voice. Parallel tool execution via `asyncio.gather()`.

### Smart Thinking Control

Qwen3.5 has a built-in reasoning mode that generates internal chain-of-thought. This is powerful for complex tasks but wastes time on simple ones.

FRIDAY uses Ollama's native `think` parameter:
- `think=False` for conversation and tool calls (~1-2s per LLM call)
- `think=True` for deep reasoning tasks like "explain how async/await works" (~30-60s but higher quality)

This alone took response times from **84-121s down to 5-12s** for conversational messages.

---

## Project Structure

```
JARVIS/
├── friday/
│   ├── cli.py                 # Terminal interface (hacker green aesthetic)
│   ├── core/
│   │   ├── config.py          # Model, paths, settings (single source of truth)
│   │   ├── types.py           # ToolResult, AgentResponse, ErrorCode, Severity
│   │   ├── llm.py             # LLM abstraction (cloud via Groq + local Ollama fallback)
│   │   ├── base_agent.py      # ReAct loop base class for all agents
│   │   ├── tool_dispatch.py   # Direct tool dispatch — 1 LLM picks tool, 1 LLM formats
│   │   ├── prompts.py         # Personality, system prompt, dispatch tool schema
│   │   ├── router.py          # Intent classification (LLM + regex), agent matching
│   │   ├── fast_path.py       # Zero-LLM instant commands (TV, greetings)
│   │   ├── oneshot.py         # Regex → tool → 1 LLM format
│   │   ├── briefing.py        # Parallel tool calls → 1 LLM synthesis
│   │   └── orchestrator.py    # FRIDAY Core — thin dispatcher, imports from above
│   ├── agents/
│   │   ├── code_agent.py      # File ops, terminal, git, debugging
│   │   ├── research_agent.py  # Web search, page fetching, known sources
│   │   ├── memory_agent.py    # Store/recall decisions, lessons, context
│   │   ├── comms_agent.py     # Email (Gmail) + Calendar (macOS/iCloud)
│   │   ├── system_agent.py    # Mac control, browser, terminal, file ops
│   │   ├── household_agent.py # Smart home control (LG TV, future: all appliances)
│   │   ├── monitor_agent.py   # Persistent watchers for URLs, topics, searches
│   │   ├── briefing_agent.py  # Daily briefings from monitor alerts + email + calendar
│   │   ├── job_agent.py       # CV tailoring, cover letters, PDF generation
│   │   └── social_agent.py    # X (Twitter) management
│   ├── data/
│   │   └── cv.py              # Structured CV data (single source of truth)
│   ├── tools/
│   │   ├── web_tools.py       # Tavily search + httpx page fetch
│   │   ├── file_tools.py      # Read, write, list, search (with line ranges, content search)
│   │   ├── terminal_tools.py  # Shell execution, background processes, process management
│   │   ├── mac_tools.py       # AppleScript, app launcher, screenshots, system info
│   │   ├── browser_tools.py   # Playwright browser automation (navigate, click, fill, screenshot)
│   │   ├── memory_tools.py    # ChromaDB + SQLite memory operations
│   │   ├── email_tools.py     # Gmail read, search, send, draft, label
│   │   ├── calendar_tools.py  # macOS/iCloud Calendar read + create events
│   │   ├── tv_tools.py        # LG TV WebOS control + WakeOnLan (18 tools)
│   │   ├── pdf_tools.py       # PDF read, merge, split, rotate, encrypt, watermark
│   │   ├── call_tools.py      # Phone, FaceTime, WhatsApp call history
│   │   ├── x_tools.py         # X (Twitter) API — post, search, mentions
│   │   ├── monitor_tools.py   # Persistent monitor CRUD + change detection
│   │   ├── briefing_tools.py  # Briefing queue, digest, alert delivery
│   │   ├── cv_tools.py        # CV get/tailor, cover letters, PDF generation
│   │   └── google_auth.py     # Shared OAuth2 for Gmail + Calendar
│   ├── voice/
│   │   ├── config.py          # Audio constants, VAD thresholds, trigger words, TTS config
│   │   ├── pipeline.py        # Always-on ambient listener + trigger word + follow-up window
│   │   ├── vad.py             # Silero VAD v6 wrapper (speech detection)
│   │   ├── stt.py             # MLX Whisper local transcription
│   │   └── tts.py             # ElevenLabs streaming (cloud) + Kokoro ONNX (local fallback)
│   ├── memory/
│   │   └── store.py           # Hybrid memory (semantic + structured)
│   └── skills/                # (Phase 5 — knowledge docs for agents)
├── Idea/                      # Design docs, system maps, tool specs
├── docs/
│   └── progress.md            # Development log
│   └── background/
│       └── monitor_scheduler.py # APScheduler background monitor jobs
├── data/                      # Runtime data (gitignored)
│   └── memory/
│       ├── friday.db          # SQLite (conversations, agent calls)
│       └── chroma/            # ChromaDB (semantic memory vectors)
├── .env                       # API keys (gitignored)
├── pyproject.toml             # Project config + dependencies
└── uv.lock                    # Dependency lock file
```

---

## Agents

### Code Agent

The hands. Reads, writes, debugs, and runs code.

**Tools:** `read_file`, `write_file`, `list_directory`, `search_files`, `run_command`, `search_web`, `search_memory`

**Capabilities:**
- Read and modify files with style-matching
- Run terminal commands (git, npm, python, system)
- Search the web for documentation
- Safety checks block dangerous commands (`rm -rf /`, `mkfs`, etc.)

### Research Agent

The eyes. Searches the web, reads full pages, synthesises findings.

**Tools:** `search_web`, `fetch_page`, `store_memory`, `search_memory`

**Capabilities:**
- Tavily-powered web search with AI-generated answers
- Full page fetching and HTML stripping (not just snippets)
- Known source injection — for topics like UK visas, it fetches gov.uk directly
- Cross-referencing and date-awareness for time-sensitive topics

**Known Sources:**
| Topic | Authoritative URL |
|-------|-------------------|
| UK Global Talent Visa | gov.uk/global-talent |
| Stripe | stripe.com/docs |
| Paystack | paystack.com/docs |
| Supabase | supabase.com/docs |
| Modal | modal.com/docs |
| Railway | docs.railway.com |
| Vercel | vercel.com/docs |
| Ollama | github.com/ollama/ollama |

### Memory Agent

The brain's filing system. Stores decisions, lessons, and context for future recall.

**Tools:** `store_memory`, `search_memory`, `get_recent_memories`

**Categories:** `project`, `decision`, `lesson`, `preference`, `person`, `general`

**Importance scale:** 1 (trivial) → 10 (critical, never forget)

### Comms Agent

The mouth and schedule. Handles all email and calendar operations.

**Tools:** `read_emails`, `search_emails`, `read_email_thread`, `send_email`, `draft_email`, `send_draft`, `edit_draft`, `get_calendar`, `create_event`

**Capabilities:**
- Read, search, and triage Gmail (priority-sorted: critical → high → normal)
- Draft and send emails with Travis's tone (never sends without explicit confirmation)
- Full draft lifecycle — create, edit, and send Gmail drafts by ID
- Read macOS/iCloud Calendar (day/week view, next event) — no API keys needed
- Create calendar events via AppleScript — syncs to iCloud automatically
- Priority sender flagging — Paystack/Stripe = critical, Railway/GitHub = high
- Coding hours warning — flags events during 10pm-4am
- Follow-up awareness — "send it" after discussing a draft routes back to comms agent
- One-shot patterns — most requests complete in a single tool call

**Safety gates:** `send_email`, `send_draft`, and `create_event` all require `confirm=True`. FRIDAY always previews before acting.

**Setup:** Email requires Google OAuth2 — see [Google API Setup](#google-api-setup) below. Calendar works out of the box (reads native macOS Calendar via AppleScript).

### System Agent

The body. Controls the Mac itself — apps, browser, terminal, files.

**Core Tools (always loaded):** `run_command`, `run_background`, `open_application`, `take_screenshot`, `get_system_info`, `run_applescript`, `read_file`, `list_directory`

**Browser Tools (loaded on demand):** `browser_navigate`, `browser_screenshot`, `browser_click`, `browser_get_text`, `browser_wait_for_login`

**PDF Tools (loaded on demand):** `pdf_read`, `pdf_metadata`, `pdf_merge`, `pdf_split`, `pdf_rotate`, `pdf_encrypt`, `pdf_decrypt`, `pdf_watermark`

**Capabilities:**
- Open any app from the safe list (Cursor, Chrome, Slack, Finder, etc.)
- Run terminal commands with safety checks + background processes
- Take screenshots (saved to `~/Downloads/friday_screenshots/`)
- Run AppleScript for Mac automation (dark mode, volume, UI control)
- Automated browsing with **persistent sessions** — uses real Chrome, logins saved permanently
- **Login detection** — detects login pages, pauses for manual login, then continues
- Navigate, click, fill forms, read page content
- System info — CPU, memory, disk, uptime
- **PDF operations** — read/extract text+tables, merge, split, rotate, encrypt/decrypt, watermark, metadata

**Persistent browser:** Uses your installed Google Chrome with a FRIDAY-specific profile (`~/.friday/browser_data/`). Log in once and sessions are saved — no re-authentication needed.

**Dynamic tool loading:** Browser and PDF tools are only injected when the task mentions them. Base tool count stays at 8 (comfortable for 9B models), scales to 13 (browser) or 16 (PDF) when needed.

**Safety:** Dangerous buttons (pay, delete, submit) require explicit confirmation. Dangerous terminal commands are blocked.

### Household Agent

The home brain. Controls smart devices in Travis's home over local network — no cloud, no accounts.

**Tools:** 18 TV tools — `turn_on_tv`, `turn_off_tv`, `tv_screen_off`, `tv_screen_on`, `tv_volume`, `tv_volume_adjust`, `tv_mute`, `tv_play_pause`, `tv_launch_app`, `tv_close_app`, `tv_list_apps`, `tv_list_sources`, `tv_set_source`, `tv_remote_button`, `tv_type_text`, `tv_notify`, `tv_get_audio_output`, `tv_set_audio_output`, `tv_system_info`, `tv_status`

**Capabilities:**
- LG TV control via WebOS local API (WiFi, no LG account needed)
- WakeOnLan to power on the TV from off state
- **Fast-path routing** — simple commands (volume, mute, launch app, power) bypass the LLM entirely via regex pattern matching. ~200-600ms instead of ~30s
- Volume control — exact level ("volume to 20") or relative adjust ("turn it up" → +5), with read-back verification
- Mute/unmute
- Media playback — pause, resume, stop, rewind, fast-forward
- App launching — Netflix, YouTube, Spotify, Prime, Disney+, Apple TV, HDMI inputs, with launch verification
- Screen off/on — audio keeps playing with screen off (Spotify mode)
- Close apps, list installed apps
- Input source switching — list and switch HDMI/antenna sources
- Full remote control — 40+ buttons: navigation, media, numbers (0-9), colours (red/green/yellow/blue), channel up/down, special keys
- IME text input — type directly into search bars without navigating virtual keyboard
- Toast notifications — send messages to the TV screen
- Audio output switching — TV speakers, soundbar, ARC, optical
- In-app search — LLM handles complex multi-step commands like "search for Black Widow on Disney+"
- Multi-step commands — "turn on TV and put on Netflix" handled sequentially with boot delay
- TV status — power state, current volume, active app (friendly names)

**Supported Apps:**
| Command | App |
|---------|-----|
| `netflix` | Netflix |
| `youtube` | YouTube |
| `spotify` | Spotify |
| `prime` / `amazon` | Prime Video |
| `disney` / `disney+` | Disney+ |
| `apple tv` | Apple TV |
| `hdmi1`-`hdmi4` | HDMI inputs |
| `live tv` | Live TV |
| `browser` | Web Browser |
| `settings` | TV Settings |

**Remote Buttons:**
| Category | Buttons |
|----------|---------|
| Navigation | `up`, `down`, `left`, `right`, `ok`, `back`, `home`, `menu`, `exit`, `dash`, `info` |
| Media | `play`, `pause`, `stop`, `rewind`, `fastforward`, `volume_up`, `volume_down`, `mute`, `channel_up`, `channel_down` |
| Numbers | `num_0` through `num_9` |
| Colours | `red`, `green`, `yellow`, `blue` |
| Special | `asterisk`, `cc` |

**Performance (fast-path):**
| Command | Time |
|---------|------|
| Volume/mute/pause | 165-340ms |
| Screen off/on | 217-305ms |
| Status check | 310ms |
| Volume set (verified) | 517-567ms |
| App launch (verified) | 2.5-6s |
| Complex search (LLM) | 30-90s |

**Setup:**
```bash
# 1. Add to .env:
LG_TV_IP=192.168.1.xx       # TV's local IP (check router admin)
LG_TV_MAC=AA:BB:CC:DD:EE:FF # TV's MAC address (for WakeOnLan)

# 2. Pair with TV (one-time, TV must be on):
uv run python -m friday.tools.tv_tools
# Accept the prompt on your TV → save the client key to .env:
LG_TV_CLIENT_KEY=<key-from-pairing>
```

**Future:** LG ThinQ API for all LG appliances, smart lights, thermostats.

**How fast-path works:** FRIDAY uses regex pattern matching to detect simple TV commands ("volume to 20", "mute", "put on Netflix") and executes them directly — no LLM inference needed. Only complex commands like "search for Black Widow on Disney+" fall through to the LLM for multi-step reasoning.

### Monitor Agent

The eyes that never sleep. Creates persistent watchers that track URLs, topics, and web searches for material changes.

**Tools:** `create_monitor`, `list_monitors`, `pause_monitor`, `delete_monitor`, `get_monitor_history`, `force_check`

**Capabilities:**
- Watch specific URLs for content changes (e.g. gov.uk visa pages)
- Recurring web searches for topic awareness (e.g. "YC W27 deadline")
- Broad topic monitoring (e.g. "AI visa policy UK")
- Material change detection — keyword filtering so only relevant changes trigger alerts
- SHA-256 content hashing with unified diff analysis
- Importance-based routing: critical = interrupt, high = next interaction, normal = briefing
- APScheduler background jobs: realtime (15min), hourly, daily, weekly

**Monitor types:**
| Type | Use case | Example |
|------|----------|---------|
| `url` | Watch a specific page | gov.uk/global-talent |
| `search` | Recurring web search | "YC W27 applications" |
| `topic` | Broad awareness | "AI immigration policy UK" |

**Smart diffing:** Not everything that changes matters. Nav menu updates, date stamps, minor wording — ignored. New eligibility criteria, deadline changes, policy updates — flagged immediately.

### Briefing Agent

The morning voice. Synthesises monitor alerts, emails, and calendar into tight, actionable briefings.

**Tools:** `get_briefing_queue`, `get_monitor_alerts`, `get_daily_digest`, `mark_briefing_delivered` + `read_emails`, `get_calendar`, `get_call_history` + `search_x`, `get_my_mentions`

**Briefing types:**
- **Morning briefing** — comprehensive: critical alerts, today's calendar, unread emails, missed calls, X feed highlights, monitor changes
- **Evening briefing** — what shipped, what's blocked, tomorrow's first event
- **Quick briefing** — one thing, two sentences, the most important item
- **"Catch me up"** — checks everything: emails, calls, calendar, monitors, X feed

**X (Twitter) monitoring** — every briefing pulls:
- **@samgeorgegh** — Ghanaian MP, policy/tech/Ghana news
- **Galamsey / illegal mining** — breaking news, government action, viral posts
- **Travel** — viral travel posts, especially Africa-related
- **AI / Tech** — new AI releases, major announcements, trending posts
- **@mentions** — anyone who mentioned Travis (surfaced first, actionable)

**Call history:** Reads phone/FaceTime calls (requires Full Disk Access) and WhatsApp calls (always accessible). Surfaces missed calls in briefings.

**Delivery:** Briefing items are marked as delivered after being surfaced, so they never repeat.

**Example:**
```
"Oya. Three things.
 Global Talent Visa page updated — new guidance dropped.
 Sam George tweeted about digital infrastructure funding.
 Galamsey trending — government announced new drone surveillance.
 Calendar's empty. What are we building?"
```

### Job Agent

The career arm. Doesn't just generate CVs — actually applies to jobs autonomously.

**Tools:** `get_cv`, `tailor_cv`, `write_cover_letter`, `generate_pdf` + `search_web`, `fetch_page` + `browser_navigate`, `browser_screenshot`, `browser_click`, `browser_fill`, `browser_get_text`, `browser_wait_for_login`, `browser_close` + `read_emails`, `search_emails` (15 tools)

**Capabilities:**
- Structured CV data as single source of truth (`friday/data/cv.py`) — dark sidebar design
- CV tailoring — reorders and rephrases experience for specific job descriptions
- Cover letter generation — confident, specific, no corporate fluff
- PDF generation via WeasyPrint + Jinja2 — dark sidebar A4 layout with lime accent
- **Autonomous job applications** — browses job sites, reads JDs, tailors CV, fills forms
- **Email scanning** — finds job openings in Gmail, extracts roles/links/deadlines
- **Multi-step form filling** — navigates application pages, fills personal details, uploads CV
- Company/role research via web tools before applying
- Login detection — pauses for manual login on protected job portals
- Never invents experience — only reframes existing data

**Safety:** Always screenshots before submit, never clicks submit without Travis confirming.

**Name handling:** Uses "Angelo Asante" (gov name) on all professional documents. "Travis Moore" is casual/preferred only.

**Example commands:**
```
"apply for this role: [URL]"
"check my emails for job openings"
"go on LinkedIn and apply for AI engineer roles"
"tailor my CV for [role] at [company]"
"generate my CV as PDF"
```

**PDF output:** Saved to `~/.friday/data/cv_output/`

### Social Agent

The voice on X. Posts tweets, checks mentions, searches, engages — all through the X API.

**Tools:** `post_tweet`, `delete_tweet`, `get_my_mentions`, `search_x`, `like_tweet`, `retweet`, `get_x_user`

**Capabilities:**
- Post tweets (280 char limit enforced), reply, quote-tweet
- Check @mentions
- Search recent tweets (last 7 days) — costs credits, used sparingly
- Like and retweet
- Look up any public X profile (followers, bio, tweet count)
- Never posts without Travis confirming the text first

**Credit awareness:** Posting/liking/retweeting is cheap. Searching/lookups cost credits. FRIDAY knows the difference.

**Setup:**
```bash
# Add to .env (from X Developer Portal):
X_CONSUMER_KEY=your_consumer_key
X_CONSUMER_SECRET=your_consumer_secret
X_BEARER_TOKEN=your_bearer_token
X_ACCESS_TOKEN=your_access_token
X_ACCESS_TOKEN_SECRET=your_access_token_secret
```

**Example commands:**
```
"tweet this: just shipped v0.2"
"check my mentions"
"search twitter for AI startups UK"
"who is @elonmusk"
"like that tweet"
```

---

## Memory System

FRIDAY uses a hybrid memory architecture:

| Layer | Tech | Purpose |
|-------|------|---------|
| **Semantic** | ChromaDB | "Find memories similar to X" — cosine similarity search |
| **Structured** | SQLite | Categories, importance scores, timestamps, agent call logs |

Memory is injected into every system prompt so FRIDAY has context about you, your projects, and past decisions. The more you use FRIDAY, the better it knows you.

---

## CLI Commands

| Command | Description |
|---------|-------------|
| `/quit` | Exit FRIDAY |
| `/clear` | Reset conversation history |
| `/memory` | Show recent stored memories |
| `/voice` | Toggle voice pipeline on/off |
| `/listening-off` | Pause ambient listening |
| `/listening-on` | Resume ambient listening |

---

## Personality

FRIDAY isn't generic. It's built for Travis — a Ghanaian founder based in Plymouth, UK who builds at 2-4am. It understands:

- **Ghanaian expressions** — "hawfar", "oya", "chale", "e no do", "time no dey", "sharp sharp"
- **Energy matching** — casual gets casual, urgent gets urgent
- **No corporate tone** — no "Certainly!", no bullet-point self-descriptions, no fluff
- **2am rule** — late night = less polish, more honest

```
▶ hawfar
  FRIDAY  E dey. You good? What are we doing.

▶ chale this thing no dey work
  FRIDAY  What broke. Show me.

▶ time no dey
  FRIDAY  Sharp sharp. What's the priority.
```

---

## Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| **LLM (cloud)** | Qwen3-32B via Groq | 32B params, sub-100ms latency, 535 tok/s, OpenAI-compatible API |
| **LLM (local)** | Qwen3.5-9B via Ollama | 9B params, fully offline fallback, thinking toggle, Apache 2.0 |
| **Package Manager** | uv | 10-100x faster than pip |
| **Web Search** | Tavily | Built for AI agents, returns structured data, AI answers |
| **Vector DB** | ChromaDB | Lightweight, embedded, cosine similarity |
| **Structured DB** | SQLite | Zero-config, built into Python |
| **CLI Framework** | Rich + prompt_toolkit | Beautiful output, history, auto-suggest |
| **HTTP** | httpx | Async, modern, follow redirects |
| **Google APIs** | google-api-python-client + google-auth-oauthlib | Gmail OAuth2 |
| **Calendar** | AppleScript + macOS Calendar.app | Native iCloud/local calendar, no API keys |
| **Browser Automation** | Playwright + Chrome (persistent sessions) | Navigate, click, fill, screenshot, login detection |
| **TV Control** | pywebostv + wakeonlan | LG TV local API over WiFi, no cloud dependency |
| **Background Jobs** | APScheduler | Persistent monitor scheduling, async event loop integration |
| **PDF Generation** | WeasyPrint + Jinja2 | CV and cover letter PDF rendering, clean A4 layout |
| **PDF Processing** | pypdf + pdfplumber | Read, merge, split, rotate, encrypt, extract text/tables |
| **Social Media** | tweepy (X API v2) | Post, search, mentions, engage — pay-as-you-go credits |
| **Voice Activity** | Silero VAD v6 | <1ms/chunk, enterprise-grade end-of-speech detection |
| **Speech-to-Text** | MLX Whisper (whisper-small) | 10x faster than whisper.cpp on Apple Silicon, always local |
| **Text-to-Speech (cloud)** | ElevenLabs Flash v2.5 | ~75ms streaming latency, PCM 24kHz, persistent connections |
| **Text-to-Speech (local)** | Kokoro-82M (ONNX) | 82M params, natural voice, Apache 2.0, ~500ms synthesis |
| **Audio I/O** | python-sounddevice | Callback-based, clean macOS support |

---

## Development Roadmap

### Phase 1 — Core System (Complete)
- [x] Multi-agent orchestrator with smart routing
- [x] 10 specialist agents (Code, Research, Memory, Comms, System, Household, Monitor, Briefing, Job, Social)
- [x] Tool library (web, file, terminal, memory, email, calendar, mac, browser)
- [x] Gmail integration — read, search, send, draft, edit draft, send draft, label, thread
- [x] macOS/iCloud Calendar integration — day/week view, create events (no API keys needed)
- [x] Mac control — AppleScript, app launcher, screenshots, volume, dark mode
- [x] Browser automation — Playwright + Chrome with persistent sessions and login detection
- [x] LG TV control — WebOS local API + WakeOnLan (no cloud)
- [x] Persistent monitoring — URL/topic/search watchers with material change detection
- [x] Briefing system — morning/evening/quick briefings from monitor alerts + email + calendar
- [x] Job agent — CV tailoring, cover letters, PDF generation (WeasyPrint + Jinja2)
- [x] Background scheduler — APScheduler runs monitor checks on configurable intervals
- [x] Background process management — start, monitor, kill
- [x] Hybrid memory (ChromaDB + SQLite)
- [x] Streaming CLI with hacker aesthetic
- [x] Smart thinking control (84s → 5s for simple queries)
- [x] Personality + Ghanaian expression understanding
- [x] Known source injection for research
- [x] Vague query detection (ask before wasting time)
- [x] Conversation context injection (agents remember recent turns)
- [x] Live tool call status during agent work
- [x] Compacted tool results for 9B model compatibility

### Phase 2 — Voice Pipeline (Complete)
- [x] Voice pipeline — Silero VAD + MLX Whisper + Kokoro TTS
- [x] `--voice` flag and `/voice` runtime toggle
- [x] Response filter (strips code/markdown for speech, condenses to 3 sentences)
- [x] Activation chime, barge-in support, feedback prevention
- [x] Both CLI and voice work simultaneously (shared FridayCore instance)

### Phase 3 — Performance & Background Agents (Complete)
- [x] Direct agent dispatch — regex skips routing LLM (4 → 2 LLM calls per query)
- [x] Direct briefing — parallel tools + 1 LLM synthesis (12+ → 1 LLM call)
- [x] Parallel tool execution — `asyncio.gather()` when multiple tools in one response
- [x] Background agent execution — user keeps chatting while agents work
- [x] Live status updates — `◈ checking emails...` → `◈ synthesizing...`
- [x] Streaming synthesis — agent results stream token-by-token to CLI and voice
- [x] Expanded fast path — greeting prefixes, Ollama error recovery
- [x] Unified routing — all queries go through dispatch, LLM always has DISPATCH_TOOL

### Phase 3.5 — Direct Tool Dispatch & 7-Tier Routing (Complete)
- [x] Direct tool dispatch — LLM picks from 9 curated tools in 1 call (agents become fallback)
- [x] 7-tier routing: fast path → user override → oneshot → direct dispatch → agent → fast chat → full LLM
- [x] User override — `@comms`, `@research`, `@social` etc. bypasses routing entirely
- [x] Dual-model architecture — Qwen3.5:9B (primary) + Qwen3:4B (fast)
- [x] Briefing per-task timeouts — prevents one slow API from blocking everything
- [x] Oneshot error fallbacks — instant error responses instead of falling through to slow agents
- [x] Fast chat tier — slim prompt, truncated context, 10-15s conversational responses
- [x] TTFT as primary UX metric — median 3.7s, 69% responsive (<6s)

### Phase 3.6 — Cloud Inference (Complete)
- [x] Cloud LLM via Groq API (Qwen3-32B, sub-100ms latency, 535 tok/s)
- [x] All LLM paths routed through `cloud_chat()` — tool dispatch, agents, formatting, chat
- [x] Automatic fallback to local Ollama when cloud unavailable or API key unset
- [x] Thinking block filtering (`<think>...</think>`) for Qwen reasoning models
- [x] Stream format bridging — Ollama and OpenAI chunk formats unified via `extract_stream_content()`
- [x] Average response time: **54s → 6.5s** (8x improvement)

### Phase 3.7 — Orchestrator Split + LLM Routing (Complete)
- [x] Split 1955-line orchestrator into 6 focused modules (prompts, router, fast_path, oneshot, briefing, orchestrator)
- [x] LLM-based intent classification via Groq (~1s) with regex fallback for offline use
- [x] Research agent benchmarks: **45-90s → 4-6s** (12x improvement)
- [x] Clean cloud/local auto-switch: no API key = fully local, with key = cloud

### Phase 4 — Voice Pipeline v2: Always-On Ambient Listening (Complete)
- [x] Always-on ambient listening — mic stays open, all speech transcribed continuously
- [x] Trigger word activation — say "Friday" naturally mid-conversation, no wake word needed
- [x] Rolling transcript buffer — 5 minutes of ambient context, injected when triggered
- [x] Follow-up window — 15 seconds after response, any speech treated as directed at FRIDAY
- [x] Cloud TTS — ElevenLabs Flash v2.5 streaming (~75ms), Kokoro local fallback
- [x] Noise/hallucination filtering — parenthetical descriptions, music, TV all filtered out
- [x] VAD tuning — threshold 0.7 filters background music, 400ms min speech
- [x] `/listening-off` and `/listening-on` CLI commands
- [x] Cloud vs local TTS — set/remove `ELEVENLABS_API_KEY` in `.env` to switch

### Phase 5 — Intelligence
- [ ] Skill system (knowledge docs agents read before executing)
- [ ] Fine-tuning data collection from sessions
- [ ] QLoRA fine-tune on smaller model (personality + routing baked into weights)
- [ ] Additional agents (Git, Deploy, Database)
- [ ] Self-hosted inference on Modal/RunPod (for privacy or custom fine-tuned models)

### Phase 6 — Ecosystem
- [ ] Redis async messaging between agents
- [ ] MCP server integration
- [ ] Screenpipe integration (screen context awareness)
- [ ] Self-improving loop (auto fine-tune from corrections)
- [ ] Multi-user support
- [ ] Plugin/extension system

---

## Cloud Inference

FRIDAY uses **Groq** for cloud inference — an OpenAI-compatible API running Qwen3-32B at 535 tokens/second with sub-100ms latency. This is what makes FRIDAY feel instant.

### Why Cloud?

Running Qwen3.5-9B locally on an M4 MacBook Air gave us 54s average response time. The M4 Air is fanless — under sustained LLM load, the GPU thermally throttles 2-15x. A 2-call search query took 25-45s. Agent tasks took 45-90s. Cloud inference brought the average down to **6.5s** — an 8x improvement.

### Why Groq?

We tested 4 models across 3 providers:

| Model | Avg Time | Tool Accuracy | Issues |
|-------|----------|--------------|--------|
| Llama 3.3 70B (Groq) | 8.2s | 60% | Malformed tool calls, string-typed args, fake tool names |
| Llama 3.1 8B (Groq) | 4.8s | 85% | Fast but wrong answers, hallucinated specs |
| Kimi K2 (Groq) | 12.1s | 70% | Slow on follow-ups, 35-48s for some queries |
| **Qwen3-32B (Groq)** | **6.5s** | **100%** | Zero tool call failures, best personality match |

Qwen3-32B won on every metric: zero tool failures, accurate search results, proper Ghanaian personality, and fast enough to feel responsive.

### How It Works

All LLM calls go through `cloud_chat()` in `friday/core/llm.py`. If Groq is available, it uses the cloud. If not, it silently falls back to local Ollama. No code changes needed to switch.

```
cloud_chat()
  ├─ Groq API available? → use cloud (sub-second per call)
  └─ No API key or network down? → fall back to local Ollama (10-25s per call)
```

### Before vs After

| Query Type | Local Ollama (M4 Air) | With Groq | Speedup |
|-----------|----------------------|-----------|---------|
| Greetings, TV commands | <1s | <1s | Same (no LLM) |
| Search query (oneshot) | 25-45s | 3-5s | ~8x |
| Research agent (2 LLM + Tavily) | 45-90s | **4-6s** | ~12x |
| Agent task (ReAct loop) | 45-90s | 5-10s | ~9x |
| Intent classification | 10-25s (regex only) | **~1s** (LLM) | ~15x |
| Casual chat | 10-25s | 0.5-2s | ~10x |
| **Average** | **~54s** | **~5s** | **~10x** |

## Cloud vs Local — Your Choice

FRIDAY auto-detects what's available. No config flags, no code changes — just environment variables.

### Option A: Cloud (Groq) — Fast, recommended

```bash
# Add your free Groq API key to .env
echo 'GROQ_API_KEY=gsk_your_key_here' >> .env

# Get a key at https://console.groq.com (free tier available)
```

All LLM calls go through Groq (~1s each). LLM-based intent classification is enabled. If Groq goes down mid-session, FRIDAY silently falls back to local Ollama.

### Option B: Fully Local — Private, no cloud

```bash
# Just don't set GROQ_API_KEY (or remove it from .env)
# Make sure Ollama is running:
ollama pull qwen3.5:9b
ollama serve

# Run FRIDAY as normal
uv run friday
```

All LLM calls go through local Ollama (~10-25s each on M4 Air). Intent classification uses regex instead of LLM. 100% private, zero data leaves your machine.

### How it works under the hood

```
GROQ_API_KEY set?
  ├─ Yes → cloud_chat() uses Groq API (~1s per call)
  │        classify_intent() uses LLM for smart agent routing
  │        Auto-fallback to Ollama if Groq is unreachable
  │
  └─ No  → cloud_chat() routes to local Ollama (~10-25s per call)
           classify_intent() skips, regex handles all routing
           Zero cloud calls, fully offline capable
```

To switch between modes: add or remove `GROQ_API_KEY` from `.env` and restart FRIDAY. That's it.

---

## Configuration

All config lives in `friday/core/config.py`:

```python
# Cloud LLM (Groq — default, fastest)
CLOUD_API_KEY = os.getenv("GROQ_API_KEY", "")
CLOUD_BASE_URL = os.getenv("CLOUD_BASE_URL", "https://api.groq.com/openai/v1")
CLOUD_MODEL_NAME = os.getenv("CLOUD_MODEL", "qwen/qwen3-32b")
USE_CLOUD = bool(CLOUD_API_KEY)       # Auto-enable if key present

# Local Ollama (fallback)
MODEL_NAME = "qwen3.5:9b"            # Local model (used when cloud unavailable)
OLLAMA_BASE_URL = "http://localhost:11434"
```

Environment variables (`.env`):
```
TAVILY_API_KEY=your-key-here
GROQ_API_KEY=gsk_...                 # Optional — enables cloud LLM inference
ELEVENLABS_API_KEY=...               # Optional — enables cloud TTS (local Kokoro fallback)
ELEVENLABS_VOICE_ID=JBFqnCBsd6RMkjVDRZzb  # Optional — defaults to "George"
```

Google credentials (managed by `google_auth.py`):
```
~/.friday/google_credentials.json   # OAuth2 client config (from Google Cloud Console)
~/.friday/google_token.json          # Auto-saved after first auth
```

---

## Design Philosophy

1. **Speed first, local always available** — cloud inference via Groq for sub-second LLM calls. Automatic fallback to local Ollama when offline. Remove the API key and everything runs on your machine.
2. **Agents are specialists** — each agent gets focused context and tools. No god-agent.
3. **Memory is identity** — FRIDAY remembers you. That's what makes it personal.
4. **Speed over perfection** — streaming, think control, fast routing. Latency kills the vibe.
5. **Personality is not optional** — a tool without personality is just a tool.

---

## Setting Up Ollama (Local LLM)

Ollama runs LLMs locally on your Mac. FRIDAY uses it as the local inference backend (and as fallback when cloud is unavailable).

### Install Ollama

```bash
# Download from https://ollama.com or use Homebrew:
brew install ollama
```

This installs the `ollama` CLI and the Ollama app. On first launch, it sets up the local server at `http://localhost:11434`.

### Pull the Model

```bash
# Pull the model FRIDAY uses (Qwen 3.5 9B, ~6GB download)
ollama pull qwen3.5:9b
```

This downloads the quantized model to `~/.ollama/models/`. It only downloads once — subsequent runs use the cached model.

### Start the Server

```bash
# Option 1: Launch the Ollama app (from Applications or Spotlight)
# The app runs the server in the background with a menu bar icon.

# Option 2: Start from terminal
ollama serve
```

The server must be running for FRIDAY to use local inference. If you're using cloud (Groq), the server is only needed as a fallback.

### Verify It Works

```bash
# Quick test — should respond in a few seconds
ollama run qwen3.5:9b "hello"

# Check the server is running
curl http://localhost:11434/api/tags
```

### Hardware Requirements

| Mac | RAM | Performance |
|-----|-----|------------|
| M1/M2/M3/M4 (any) | 16GB+ | Works well, 10-25s per call |
| M1/M2/M3/M4 Pro/Max | 32GB+ | Faster, can run larger models |
| Intel Mac | 16GB+ | Works but slower (CPU only) |

The model uses ~6GB of RAM. Ollama keeps it loaded in memory (`keep_alive: -1`) so subsequent calls are faster — no reload time.

### Troubleshooting

- **"connection refused"** — Ollama server isn't running. Launch the app or run `ollama serve`.
- **"model not found"** — Run `ollama pull qwen3.5:9b` to download it.
- **Slow responses** — Normal on fanless Macs (M4 Air). GPU throttles under sustained load. Use cloud (Groq) for speed.
- **Out of memory** — Close other heavy apps. The 9B model needs ~6GB free RAM.

---

## Groq Pricing

FRIDAY uses Groq's cloud API for fast inference. Current pricing for the model we use:

| | Qwen3-32B on Groq |
|---|---|
| **Input** | $0.29 / million tokens |
| **Output** | $0.59 / million tokens |
| **Speed** | 662 tokens/sec |
| **Free tier** | Yes — free credits on signup |

**What does this cost in practice?** A typical FRIDAY query uses ~500 input tokens and ~200 output tokens. That's ~$0.0003 per query. **$1 covers ~3,000 queries.** The free tier is more than enough for personal use.

Sign up at [console.groq.com](https://console.groq.com) — no credit card required for the free tier.

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) for full text.

**Attribution:** If you use FRIDAY in your project, product, or research, please credit the original author:

> Built on FRIDAY by Travis Moore (Angelo Asante)

See [NOTICE](NOTICE) for full attribution requirements.

---

*Built at 2am in Plymouth, UK. By Travis Moore.*
