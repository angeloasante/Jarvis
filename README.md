# FRIDAY

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Built by](https://img.shields.io/badge/Built%20by-Travis%20Moore-green.svg)](https://github.com/angeloasante)

> **Copyright Travis Moore (Angelo Asante)**
> Licensed under the Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE) for details.

**Personal AI Operating System**

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

Tony Stark had JARVIS. This is FRIDAY.

Not a demo. Not a wrapper around ChatGPT. A personal AI OS built from scratch — local inference, persistent memory, smart home control, gesture control via your camera, browser automation, email, calendar, iMessage, WhatsApp, X, job applications, a hologram display if you're into that.

You talk to it in whatever way you talk. It gets things done without you having to explain yourself twice.

Built by one person in Plymouth, UK, at 3am, between night shifts. Apache 2.0. Use it. Build on it. Just don't pretend you made it.

Runs hybrid: cloud inference via Groq for speed (6.5s avg), with automatic fallback to fully local Ollama when offline or if you prefer privacy.

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

You: "watch father in law's messages for the next hour, reply as friday"
FRIDAY: Got it. Watching every 60 seconds.           ← standing order created
  💛 FRIDAY Watch — replied to Father In Law:        ← background, autonomous
  "FRIDAY: He's building me right now, I'll
  let him know you texted."

You (in iMessage to father in law): "I'm innocent 😂 @friday defend me here wai"
  💛 FRIDAY Watch — replied to Father In Law:        ← tagged mid-conversation
  "FRIDAY: 😂😂😂 As told by Travis, who's busy
   not telling me to chill. (I'm just the AI,
   don't shoot the messenger)"
```

That last one actually happened. 2:50am. Father-in-law sent a LeBron reaction image. FRIDAY held down the conversation while Travis was building her. iMessage became a command interface — type `@friday` mid-chat, FRIDAY picks it up, acts on it, replies. The other person just thinks you're having a laugh.

---

## Quick Start

### Prerequisites

- **macOS** (tested on Apple Silicon)
- **Python 3.12+**
- **uv** — Python package manager ([install](https://docs.astral.sh/uv/getting-started/installation/))

### Install

**Option 1 · one-liner (recommended)**

```bash
curl -fsSL https://raw.githubusercontent.com/angeloasante/Jarvis/main/install.sh | sh
```

Installs `uv` if you don't have it, installs FRIDAY into an isolated tool environment, and kicks off `friday onboard`. No system Python needed — uv brings its own. Read the script first (it's short): [install.sh](install.sh).

**Option 2 · uv (already have it)**

```bash
uv tool install friday-os      # from PyPI (once released)
# or, today, before the PyPI release:
uv tool install "friday-os @ git+https://github.com/angeloasante/Jarvis"
friday onboard
friday
```

**Option 3 · pipx**

```bash
pipx install friday-os         # or: pipx install git+https://github.com/angeloasante/Jarvis
friday onboard
friday
```

**Option 4 · plain pip**

```bash
pip install --user friday-os   # leaks into your user Python — fine but less isolated
friday onboard
friday
```

Any of these put the `friday` command on your PATH.

**Updating later** — once FRIDAY is installed, just run **`friday update`** to pull the latest code. It detects which installer you used (pip, pipx, uv tool, source, or the Mac app) and runs the right upgrade command under the hood. You can also re-run the curl one-liner; it's idempotent.

`friday onboard` is the one-stop wizard — it asks **QuickStart vs Advanced** up front, then walks through:

1. **Profile** — name, bio, tone → `~/Friday/user.json`
2. **System deps** — detects Python/`uv`/`ollama`/`node`/`ngrok`/`brew`, offers to brew-install anything missing
3. **LLM provider** — pick OpenRouter (with a live model picker from `openrouter.ai/api/v1/models`), Groq, or skip for local Ollama
4. *(Advanced only)* Gmail + Calendar, Twilio SMS, Voice, Hand gestures
5. **Health check** — runs `friday doctor` to confirm everything

Re-running is safe: existing config is preserved unless you explicitly overwrite it.

**Option 5 · from source (for contributors)**

```bash
git clone https://github.com/angeloasante/Jarvis.git && cd JARVIS
uv sync
uv run friday onboard
uv run friday
```

Either way, your whole setup — identity, tone, slang, contact aliases, CV, briefing watchlist — lives in **`~/Friday/user.json`**. One file, visible in Finder, chmod 600. FRIDAY injects it into the model's context on every turn, so the assistant always knows who you are, what you're building, and how you want to be talked to.

- Edit it any time: `friday config edit`
- See it in Finder: `friday config open`
- Mac app equivalent: **Settings → Profile**

On first run, if the file doesn't exist, FRIDAY runs the wizard before starting.

Now pick how you want FRIDAY to think:

### Option A: Cloud via OpenRouter (Recommended)

Gemma 4 31B — 97% tool calling accuracy on FRIDAY's own benchmarks. Cheaper than Groq (~$3.43/month). Free tier available.

```bash
# Add your OpenRouter key — get one free at https://openrouter.ai/settings/keys
echo 'OPENROUTER_API_KEY=sk-or-v1-your_key_here' >> .env

# Run FRIDAY
uv run friday
```

That's it. No models to download, no GPU needed. FRIDAY auto-detects the provider from your API key.

### Option A2: Cloud via Groq (Fastest)

Qwen3-32B at 535 tok/s, sub-100ms latency. Faster than OpenRouter but lower tool accuracy. Good if speed matters more than correctness.

```bash
echo 'GROQ_API_KEY=gsk_your_key_here' >> .env
uv run friday
```

### Any OpenAI-Compatible Provider

FRIDAY works with any provider that speaks the OpenAI API — Together AI, Fireworks, RunPod, your own vLLM deployment. Set these in `.env`:

```bash
CLOUD_API_KEY=your_key
CLOUD_BASE_URL=https://api.together.xyz/v1
CLOUD_MODEL=google/gemma-4-31B-it
```

If multiple keys are set, priority is: `CLOUD_API_KEY` (manual) > `OPENROUTER_API_KEY` > `GROQ_API_KEY` > local Ollama fallback.

### Option B: Fully Local via Ollama

Private. Zero cloud calls. Everything runs on your machine. Slower (~10-25s per call on M4 Air) but no API keys, no data leaves your device.

```bash
# Install Ollama and pull the model
brew install ollama
ollama pull qwen3.5:9b
ollama serve

# Run FRIDAY (no GROQ_API_KEY in .env = fully local)
uv run friday
```

For detailed Ollama setup, troubleshooting, and hardware requirements — see [docs/ollama-setup.md](docs/ollama-setup.md).

### Option C: Both (Hybrid)

Set `GROQ_API_KEY` **and** have Ollama running. FRIDAY uses Groq for speed, falls back to Ollama automatically if cloud is unreachable. Best of both worlds.

### Switching Between Modes

Add or remove the API key from `.env` and restart FRIDAY. That's it. No code changes, no config flags. FRIDAY auto-detects which provider is available.

### Voice Mode

FRIDAY supports ambient voice — say **"Friday"** naturally at any point. Works well in quiet environments and moderate background noise. Loud music or overlapping conversations will reduce accuracy — even Siri and Alexa struggle here. A denoiser pre-processing step (coming soon) improves this significantly. Voice is **off by default** and only runs when you explicitly enable it.

**Privacy model:**
- **Nothing leaves your machine by default.** Speech recognition (Silero VAD + MLX Whisper) runs entirely on-device. No audio is sent anywhere.
- Audio is processed in real-time and immediately discarded — FRIDAY keeps a rolling text transcript (last 5 minutes), never raw audio.
- If you enable cloud TTS (ElevenLabs), only FRIDAY's **response text** is sent to generate speech — your voice and ambient audio still never leave your device.
- `/listening-off` pauses the mic entirely. `/voice` disables the whole pipeline. You're always in control.

```bash
# Start with voice enabled (off by default)
uv run friday --voice

# Or toggle at runtime
/voice

# Pause/resume ambient listening
/listening-off
/listening-on
```

After FRIDAY responds, you have an **8-second follow-up window** — just keep talking without saying "Friday" again. CLI and voice work simultaneously — type or talk, your choice.

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

### WhatsApp Setup

FRIDAY can read and send WhatsApp messages through a local Node.js bridge. No third-party servers — runs entirely on your machine.

```bash
# 1. Install bridge dependencies
cd friday/whatsapp && npm install

# 2. Start the bridge (first time — shows QR code)
node server.js

# 3. Scan the QR code with WhatsApp → Linked Devices → Link a Device
# 4. Once connected, FRIDAY can use WhatsApp
```

After pairing, the session persists — restart the bridge anytime without re-scanning. For background running, auto-start on login, and troubleshooting — see [docs/whatsapp-setup.md](docs/whatsapp-setup.md).

### SMS Setup (Text FRIDAY From Anywhere)

FRIDAY has a Twilio phone number. Text it from any phone on any network — no app, no WhatsApp, no iMessage required.

```bash
# 1. Add Twilio credentials to .env
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_PHONE_NUMBER=+447367000489   # Your Twilio number

# 2. Install Tailscale (stable public URL, free)
brew install --cask tailscale
tailscale login
tailscale funnel 3200   # First time: approve Funnel in browser

# 3. Set webhook in Twilio Console:
#    Phone Numbers → your number → Messaging → Webhook:
#    https://your-machine.tailnet.ts.net/sms  (HTTP POST)

# 4. Start FRIDAY — SMS server + Funnel start automatically
uv run friday
```

Text your Twilio number and FRIDAY replies. It processes through the full pipeline — same routing, same agents, same personality as CLI and voice.

For detailed architecture, troubleshooting, and cost breakdown — see [docs/sms-setup.md](docs/sms-setup.md).

### macOS App

There's a native SwiftUI app wrapping all of this — menu bar bolt, full-window chat with sidebar and streaming token-by-token responses, an onboarding flow that handles Google sign-in and LLM key entry, and a bundled Python 3.12 runtime so end users don't need `uv` or the repo at all. Shared keys (Tavily) ship with the app; per-user keys (OpenRouter, Twilio, X) get entered once in the GUI and persist in Keychain.

```bash
# Dev: run against the repo
open Friday-mac/Friday/Friday.xcodeproj    # ⌘R in Xcode

# Release: produce a self-contained .app
cd Friday-mac && ./build_bundle.sh release
```

Architecture, menu bar integration, NDJSON streaming protocol, onboarding flow, reset procedure, and build pipeline — see [docs/mac-app.md](docs/mac-app.md). Product spec (wow moments, feature roadmap, iOS app) — see [docs/app-spec.md](docs/app-spec.md).

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
 Git       Known src Semantic  iMessage  Chrome,PDF  Smart Home Diffing  Calendar  Jinja2    Mentions
                               WhatsApp                                            Twilio SMS
                               Twilio SMS
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
│   │   ├── imessage_tools.py  # iMessage read/send + FaceTime + Contacts
│   │   ├── whatsapp_tools.py  # WhatsApp read/send/search via Baileys bridge
│   │   ├── sms_tools.py       # Twilio SMS send/read (text FRIDAY from anywhere)
│   │   ├── cron_tools.py      # Scheduled task CRUD (create, list, delete, toggle)
│   │   ├── watch_tools.py     # Standing orders — create, list, cancel watch tasks
│   │   ├── notify.py          # Phone notifications via iMessage to self
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
│   ├── background/
│   │   ├── monitor_scheduler.py # APScheduler background monitor jobs
│   │   ├── heartbeat.py       # Proactive awareness loop (30min ticks, zero-LLM silent checks)
│   │   ├── cron_scheduler.py  # User-defined scheduled tasks (APScheduler + SQLite)
│   │   ├── github_sync.py     # Background GitHub project sync
│   │   └── memory_processor.py # Background memory processing
│   ├── memory/
│   │   └── store.py           # Hybrid memory (semantic + structured)
│   ├── whatsapp/
│   │   ├── server.js          # Baileys HTTP bridge (Express + WhatsApp Web)
│   │   └── package.json       # Node.js dependencies
│   ├── sms/
│   │   ├── __init__.py        # Package init
│   │   └── server.py          # Twilio SMS webhook server (port 3200)
│   └── skills/                # (Phase 5 — knowledge docs for agents)
├── Idea/                      # Design docs, system maps, tool specs
├── Friday-mac/                 # Native SwiftUI macOS app (menu bar + chat window)
│   ├── Friday/Friday/          # Swift sources (app, chat, onboarding, services)
│   ├── build_bundle.sh         # Bundles Python 3.12 + FridayCore into Friday.app
│   └── README.md               # Xcode setup + build instructions
├── docs/
│   ├── progress.md            # Development log
│   ├── mac-app.md             # macOS app + menu bar architecture
│   ├── app-spec.md            # Product spec for Mac + iOS apps
│   ├── ollama-setup.md        # Local LLM setup guide (Ollama)
│   ├── whatsapp-setup.md      # WhatsApp integration setup (Baileys bridge)
│   ├── sms-setup.md           # SMS integration setup (Twilio + Tailscale)
│   ├── gesture-control.md     # MediaPipe gesture control
│   ├── friday-glasses-integration.md  # Halo glasses integration spec
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

The mouth and schedule. Handles email, calendar, iMessage, FaceTime, and contacts.

**Tools:** `read_emails`, `search_emails`, `read_email_thread`, `send_email`, `draft_email`, `send_draft`, `edit_draft`, `get_calendar`, `create_event`, `read_imessages`, `send_imessage`, `start_facetime`, `search_contacts`, `send_whatsapp`, `read_whatsapp`, `search_whatsapp`, `whatsapp_status`, `send_sms`, `read_sms`

**Capabilities:**
- Read, search, and triage Gmail (priority-sorted: critical → high → normal)
- Draft and send emails with Travis's tone (never sends without explicit confirmation)
- Full draft lifecycle — create, edit, and send Gmail drafts by ID
- Read macOS/iCloud Calendar (day/week view, next event) — no API keys needed
- Create calendar events via AppleScript — syncs to iCloud automatically
- **iMessage** — read conversations from `chat.db`, send texts via Messages.app AppleScript
- **FaceTime** — initiate video/audio calls, multi-number contact handling
- **Contacts** — search Contacts.app with fuzzy matching, nickname resolution, emoji support
- **WhatsApp** — read chats, send messages, search across conversations via local Baileys bridge (Node.js)
- **SMS** — send/receive texts via Twilio from any phone. Inbound SMS processed through full FRIDAY pipeline via webhook server + Tailscale Funnel
- **Smart contact resolution** — "Ellen's pap", "my bby", "father in law" all resolve correctly via word-overlap scoring
- **NSAttributedString parsing** — extracts text from newer iMessage binary format (`attributedBody`)
- **Channel-aware** — after reading iMessages, replies go via `send_imessage` (never `draft_email`)
- **Tone matching** — reads recent messages to match the conversation's vibe when drafting
- Priority sender flagging — Paystack/Stripe = critical, Railway/GitHub = high
- Coding hours warning — flags events during 10pm-4am

**Safety gates:** `send_email`, `send_draft`, `send_imessage`, `send_whatsapp`, and `create_event` all require `confirm=True`. FRIDAY always previews before acting.

**Setup:** Email requires Google OAuth2 — see [Google API Setup](#google-api-setup) below. Calendar, iMessage, FaceTime, and Contacts work out of the box (native macOS APIs, no API keys needed). iMessage reading requires Full Disk Access for `chat.db`. WhatsApp requires the Baileys bridge — see [docs/whatsapp-setup.md](docs/whatsapp-setup.md). SMS requires Twilio + Tailscale — see [docs/sms-setup.md](docs/sms-setup.md).

### System Agent

The body. Controls the Mac itself — apps, browser, terminal, files.

**Core Tools (always loaded):** `run_command`, `run_background`, `open_application`, `take_screenshot`, `get_system_info`, `run_applescript`, `read_file`, `list_directory`

**Browser Tools (loaded on demand):** `browser_navigate`, `browser_screenshot`, `browser_click`, `browser_get_text`, `browser_wait_for_login`, `browser_discover_form`, `browser_fill_form`, `browser_upload`

**PDF Tools (loaded on demand):** `pdf_read`, `pdf_metadata`, `pdf_merge`, `pdf_split`, `pdf_rotate`, `pdf_encrypt`, `pdf_decrypt`, `pdf_watermark`

**Capabilities:**
- Open any app from the safe list (Cursor, Chrome, Slack, Finder, etc.)
- Run terminal commands with safety checks + background processes
- Take screenshots (saved to `~/Downloads/friday_screenshots/`)
- Run AppleScript for Mac automation (dark mode, volume, UI control)
- Automated browsing with **persistent sessions** — uses Safari with your existing sessions/cookies
- **Login detection** — detects login pages, pauses for manual login, then continues
- Navigate, click, fill forms, read page content
- **"Fill the form on my screen"** — discovers all fields on the current Safari page, batch-fills with Travis's details (name, email, phone, LinkedIn, GitHub, website, location), uploads CV if needed, verifies all required fields are filled
- System info — CPU, memory, disk, uptime
- **PDF operations** — read/extract text+tables, merge, split, rotate, encrypt/decrypt, watermark, metadata

**Browser engine:** Safari via AppleScript + JavaScript injection — uses your actual Safari with all existing cookies, sessions, saved passwords. No login walls. No Selenium, no Playwright. One JS call fills entire forms.

**Dynamic tool loading:** Browser, PDF, screen, and form tools are only injected when the task mentions them. Base tool count stays at 8 (comfortable for 9B models), scales to 18+ (browser + forms) or 16 (PDF) when needed. Form tasks also get CV tools and higher iteration limits (15 vs default 5).

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

**Tools:** `tailor_cv`, `generate_pdf` + `search_web` + `browser_navigate`, `browser_discover_form`, `browser_fill_form`, `browser_screenshot`, `browser_click`, `browser_type`, `browser_scroll`, `browser_upload`, `browser_get_text`, `browser_execute_js`, `browser_elements`, `browser_wait_for_login` (15 tools, 30 max iterations)

**Capabilities:**
- **3-phase autonomous workflow:** search for the job → tailor CV to the JD → fill the application form
- Searches company career pages itself — uses official sites, follows redirects to Greenhouse/Lever/Workday
- CV tailoring — rewrites summary and reorders experience for specific job descriptions (not generic)
- PDF generation via WeasyPrint + Jinja2 — dark sidebar A4 layout with lime accent
- **Batch form filling** — `browser_discover_form` scrolls the entire page and finds ALL fields, `browser_fill_form` fills everything in a single JS call (150s → 15s)
- **React-Select dropdown support** — detects React-Select inputs, types to search, clicks option
- **File upload via DataTransfer API** — bypasses Safari's file chooser restriction, injects file directly
- **Verification loop** — keeps calling `browser_discover_form` until `all_required_filled` is true
- Login detection — pauses for manual login on protected job portals
- Never invents experience — only reframes existing data

**Safety:** Always asks Travis before final submit. Never clicks submit without confirmation.

**Name handling:** Uses "Angelo Asante" (gov name) on all professional documents. "Travis Moore" is casual/preferred only.

**Example commands:**
```
"apply for software engineer at Anthropic"
"go on LinkedIn and apply for AI engineer roles"
"tailor my CV for [role] at [company]"
"generate my CV as PDF"
"fill the form on my screen"
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

## Standing Orders (Watch Tasks)

This is the real autonomy. You tell FRIDAY to watch someone's messages and handle them while you're busy. It runs in the background, checks every 60 seconds, and only acts when something new comes in.

```
"watch Teddy Bear's messages for the next hour, reply like me"
"check father in law's messages every 60 seconds, reply as friday"
"do the same for My Bby"
"watch my emails for anything from Stripe, notify me"
"check for missed calls every 2 minutes, ping me if anything comes in"
"open LinkedIn and check for new notifications every 5 minutes"
```

Real example from a live session:

```
You: "watch father in law's messages, reply as friday"
FRIDAY: Got it. Watching every 60 seconds.

  💛 FRIDAY Watch — replied to Ellen's Pap:
  "FRIDAY: Hi, I'm FRIDAY — Travis's AI assistant.
   He's been busy building me. I read your chat
   and noticed you mentioned your eyes — how are
   they feeling?"
```

### How It Works

FRIDAY classifies each watch by keywords and dispatches to the right executor:

| Watch Type | Keywords | What It Does |
|------------|----------|--------------|
| **iMessage** | (default) | Reads messages, reasons about replies, sends as you or FRIDAY |
| **Email** | "email", "inbox", "gmail" | Reads unread emails, filters by sender keyword, notifies on new matches |
| **Missed Calls** | "missed call", "call log" | Reads call history, fingerprints latest, notifies on new missed calls |
| **Browser** | "linkedin", "website", "notifications" | Opens URL via Playwright, hashes page content, LLM summarizes changes |

**iMessage flow:**

1. **Baseline set** — first tick records the current conversation state. No phantom replies.
2. **Every 60s** — reads the latest received messages, compares fingerprint against last check.
3. **Nothing new?** — skip. Zero LLM cost. Zero API calls beyond the message read.
4. **New message?** — checks if you already replied. If yes, skip.
5. **Unreplied?** — reads last 20 messages for full context, then 1 LLM call drafts the reply matching the conversation vibe.
6. **Sends it** — updates state so the same message never triggers twice.

**Email/Calls/Browser flow:** Each tick reads the relevant data, compares against the last known state fingerprint, and sends a phone notification if something new shows up. No auto-replying — just monitoring and alerting.

### FRIDAY Reasons Before Replying

Not every message needs a reply. If someone says "okay" or "lol" or drops a thumbs up, FRIDAY leaves it alone. The LLM decides: does this actually need a response, or would replying be forced?

### Tag FRIDAY In a Conversation

Type `@friday` in any iMessage conversation and FRIDAY picks it up. She reads the full thread, understands the vibe, and jumps in as herself. She addresses what the other person said AND what you said. She's got your back.

**Note:** For @friday tagging to work, a watch must be active for that conversation. The watch is what checks for new messages every 60 seconds — that's how FRIDAY sees your tag. No watch, no pickup.

This turns iMessage into a command interface for FRIDAY. You never leave the chat. The other person doesn't know you're directing an AI mid-conversation — they just think you're having a laugh.

```
You (in iMessage): "I'm innocent 😂 @friday defend me here wai"

  💛 FRIDAY Watch — replied:
  "FRIDAY: 😂😂😂 As told by Travis, who's busy not telling me
   to chill. (I'm just the AI, don't shoot the messenger)"
```

That's not a technical benchmark or a briefing output — it's FRIDAY holding down your relationships at 2:50am while you build her. Unscripted. Reading the room. Personality fully there.

### Identity Switching

FRIDAY figures out who she should be based on context:

- **"reply as me"** — replies as you. Your tone, your energy. The other person doesn't know it's AI.
- **"reply as friday"** — prefixes with "FRIDAY:" so they know it's the AI.
- **You tag FRIDAY** — text "@friday am I lying?" or "@friday defend me" in the actual iMessage conversation and FRIDAY jumps in as herself, backs you up.
- **You introduce FRIDAY** — if you text "she's my AI, called Friday" in the conversation, FRIDAY picks up on it and starts replying as herself.
- **They mention FRIDAY** — if the other person says "Friday stop" or "Friday please", FRIDAY switches to herself and responds to what they said.

### Deflection Rules

FRIDAY won't commit you to things:

- **Calls** — "I'm busy building something right now, I'll call you later"
- **Money** — "Noted, I'll keep it in mind" / "I'll send it when I'm ready"
- **Plans** — deflects, says you're working on something
- **"Stop replying"** — FRIDAY respects it, lets them know you're busy

### Updating a Watch

Say "actually reply as FRIDAY" or "change it to every 2 minutes" — FRIDAY updates the existing watch for that contact instead of creating a duplicate.

### CLI

```
/clearwatches          # kill all active watches instantly
```

Or tell FRIDAY naturally: "cancel all watches", "stop watching Teddy's messages"

---

## Cron Jobs (Scheduled Tasks)

Set recurring tasks in plain English. FRIDAY converts them to cron schedules.

```
"every morning at 8am, run my briefing"
"every friday at 5pm, check my emails and send me a summary"
"every 30 minutes, check if the gov.uk visa page changed"
```

Managed conversationally — create, list, delete, toggle on/off. Persisted in SQLite, survives restarts.

---

## Phone Notifications

FRIDAY sends you alerts via iMessage to your own number. Works instantly, even in DND if you add your own number to the allowed list.

```
  💛 FRIDAY Watch — replied to Teddy Bear: "I miss you too, rest up"
  ↑ sent to phone
```

Every watch task reply, heartbeat alert, and proactive notification hits your phone. No custom app needed (yet).

---

## Multi-Agent Deep Research

For anything that needs multiple agents working together — research papers, reports, improving existing documents. FRIDAY breaks the task into phases, dispatches parallel sub-agents, and produces a real deliverable.

```
"do a deep research about energy barriers and create a paper on my desktop"
"read my thesis, research its topics, improve it to research-paper grade"
"I have an idea about using fans and litmus paper to create a tiny missile for a school project. research it and build a submission-ready file in my downloads"
"write a detailed report about AI in healthcare"
"research quantum computing breakthroughs in 2025 and save a report"
"analyze the impact of social media on mental health and create a detailed paper"
```

Files are saved to the location you specify. If you don't specify, FRIDAY saves to `~/Documents/friday_files/` — keeps your Desktop clean.

### How It Works

1. **Planner** (1 LLM call) — breaks the task into phases with typed steps: SEARCH, FETCH, READ_FILE, WRITE
2. **Phase execution** — steps in the same phase run in parallel. Phase 1 might read an existing file. Phase 2 dispatches 4-6 search agents simultaneously, each running multiple queries + page fetches.
3. **Section writers** (parallel LLM calls) — each section of the document is written by a separate LLM call, all at once. Research data is partitioned so each writer focuses on its section.
4. **Synthesis** (1 LLM call) — writes the abstract and conclusion across all sections.
5. **Saves to disk** — wherever you specify, or `~/Documents/friday_files/` by default. Defaults to `.docx` format. Supports `.docx`, `.md`, `.txt`, `.pdf` — just say the format in your request.

Why is it fast? Because nothing waits. Phase 2 fires 4-6 search agents at once — while one is fetching a page, three others are running different queries. Section writers all run simultaneously — a 6-section paper generates all 6 sections in parallel, not one after another. The only sequential parts are planning (1 LLM call) and final synthesis (1 LLM call). Everything in between is parallel.

### Real Example

```
You: "do a research about elements and materials that can create energy barriers —
      plasma shields, electromagnetic fields, metamaterials. save a research paper."

  ◈ Planning task structure...
  ◈ Plan: 16 steps across 3 phases
  ◈   Phase 1: [READ_FILE] Read existing background knowledge
  ◈   Phase 2: [SEARCH] Research plasma shields
  ◈   Phase 2: [SEARCH] Research electromagnetic fields
  ◈   Phase 2: [SEARCH] Research metamaterials
  ◈   Phase 2: [SEARCH] Comparative study of energy barrier technologies
  ◈   Phase 2: [SEARCH] Locate peer-reviewed scientific literature
  ◈   Phase 2: [SEARCH] Analyze practical and economic considerations
  ◈   Phase 2: [SEARCH] Future directions and advancements
  ◈ Phase 1: running 1 steps in parallel...
  ◈ Phase 2: running 7 steps in parallel...
  ◈ Phase 3: running 8 steps in parallel...
  ◈ Data gathered: 7 sources, 56000 chars
  ◈ Writing 8 sections...
  ◈ Sections written: 8/8
  ◈ Writing abstract and conclusion...
  ◈ Assembling final document...
  ◈ Done. 8 sections, 0 sources, 31680 chars.
    Saved to ~/Documents/friday_files/Research_on_Energy_Barriers_...20260327.docx
    (200s, 36 tool calls)
```

8 sections. 31,680 characters. 36 tool calls. 7 web sources fetched. One `.docx` file with abstract, table of contents, full sections, conclusion, and references. All from a single sentence.

### Where Files Go

| You say | Saves to |
|---------|----------|
| "save on my desktop" | `~/Desktop/` |
| "save in downloads" | `~/Downloads/` |
| Nothing specified | `~/Documents/friday_files/` |

### Output Formats

Default is `.docx`. Say the format in your request to override:

| You say | Format |
|---------|--------|
| "save as a docx" / nothing specified | `.docx` |
| "save as markdown" / "save as .md" | `.md` |
| "save as a text file" / "save as .txt" | `.txt` |
| "save as pdf" | `.pdf` |

You can also convert existing files: *"convert my thesis to pdf"*, *"change that report to markdown"*.

### Use Cases

- **School/uni submissions** — "I have an idea about X for my school project. Research it and build a submission-ready file"
- **Work reports** — "write a detailed report about our Q1 performance metrics"
- **Thesis improvement** — "read my thesis at ~/Documents/thesis.md, research its topics, improve it"
- **Idea exploration** — "I think metamaterials could be used for cloaking. Deep dive and save a paper"
- **Literature review** — "do a comprehensive literature review on CRISPR gene editing"
- **Competitive analysis** — "research the top 5 AI coding assistants and create a comparison report"

---

## Improvement Mode

Have an existing document? FRIDAY improves it.

```
"read my thesis at ~/Documents/thesis.md and improve it to research-paper grade"
```

FRIDAY reads what you wrote, researches the topics it finds, rewrites each section with new evidence and citations, and preserves your voice throughout. Not a rewrite — an upgrade.

1. **Reads your document** (Phase 1) — understands structure, arguments, voice
2. **Researches the topics it finds** (Phase 2, parallel) — 4-6 search agents fire simultaneously
3. **Rewrites each section** (Phase 3, parallel) — strengthens arguments, adds citations, fills gaps
4. **Preserves your voice** — the ideas stay yours. The evidence and structure get better.

Works with any format FRIDAY can read: `.docx`, `.md`, `.txt`.

---

## Gesture Control

Raise your hand. FRIDAY reacts. Two hands, pinch drag, combos — 29 gestures total. MediaPipe runs locally on your MacBook camera, zero GPU, 30fps. Hold a gesture for 0.4 seconds and it fires through the normal FRIDAY pipeline.

**Right Hand:**
| | Gesture | Command |
|---|---------|---------|
| ✊ | Closed Fist | mute |
| 🖐 | Open Palm | unmute |
| 👆 | Point Up | volume up |
| 👍 | Thumb Up | play |
| 👎 | Thumb Down | volume down |
| ✌️ | Victory / Peace | pause |
| 🤟 | ILoveYou (thumb+index+pinky) | catch me up |
| 🤌 | Pinch (thumb+index touching) | what's on my screen |

**Left Hand:**
| | Gesture | Command |
|---|---------|---------|
| ✊ | Closed Fist | privacy mode |
| 🖐 | Open Palm | catch me up |
| 👆 | Point Up | brightness up |
| 👍 | Thumb Up | save to memory |
| 👎 | Thumb Down | forget that |
| ✌️ | Victory / Peace | read this |
| 🤟 | ILoveYou | evening briefing |
| 🤌 | Pinch | screenshot |

**Both Hands:**
| | Gesture | Command |
|---|---------|---------|
| ✊✊ | Both Fists | silence everything |
| 🖐🖐 | Both Palms | full attention |
| 👍👍 | Both Thumbs Up | send it |
| 👎👎 | Both Thumbs Down | cancel everything |
| ✌️✌️ | Both Victory | screenshot and tweet |
| 🤟🤟 | Both ILoveYou | party mode |
| ✊🖐 | Right Fist + Left Palm | i'm leaving |
| 🖐✊ | Right Palm + Left Fist | i'm back |

**Pinch Drag (continuous — move while pinching):**
| | Gesture | Command |
|---|---------|---------|
| 🤌☝️ | Right pinch + drag up | volume up |
| 🤌👇 | Right pinch + drag down | volume down |
| 🤌☝️ | Left pinch + drag up | brightness up |
| 🤌👇 | Left pinch + drag down | brightness down |

Every gesture is customizable from `.env` — no code to edit. If you can type it as a FRIDAY command, you can gesture it.

**Setup:**
```bash
# Download gesture model (8MB, one time)
mkdir -p ~/.friday/models
curl -sL -o ~/.friday/models/gesture_recognizer.task \
  "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/latest/gesture_recognizer.task"

# Enable in .env
echo "FRIDAY_GESTURES=true" >> .env
```

Toggle at runtime with `/gestures`. Voice and gestures work simultaneously — independent threads, same FridayCore.

Full docs: [docs/gesture-control.md](docs/gesture-control.md)

---

## Screen Vision & Question Solver

Ask FRIDAY to look at your screen — read text, understand what's on it, or solve every question on a page. On-command only, never watches passively. Privacy-gated behind `FRIDAY_SCREEN_ACCESS=true` in `.env`.

```
"what's on my screen"                              → OCR + vision analysis
"what error is this"                               → diagnoses errors on screen
"read the text on screen"                          → Apple Vision OCR
"solve the questions on my screen"                 → full-page capture + solve + .docx
"open Safari and solve the questions on that page" → targets a specific app
"just solve what's on my screen right now"         → viewport-only, no scrolling
```

**Screen Reading:**

1. Takes a screenshot of the frontmost window (not full screen — no dock/menu bar noise)
2. Runs Apple Vision OCR (offline, free, fast) to extract all text
3. If Qwen2.5-VL is available (via Ollama), sends the image for full visual understanding
4. If no vision model, falls back to OCR text + LLM to answer

**Full-Page Question Solver:**

The killer feature. FRIDAY scrolls through an entire page (browser, PDF, Word doc — any app), OCRs every viewport, deduplicates overlapping text, then solves every question it finds. Answers are saved to a well-formatted `.docx` with proper headings, bold terms, numbered lists, and structured explanations.

How it works under the hood:
1. Activates the target app (if specified) and clicks the content area
2. Scrolls to the top of the page (`Cmd+Up`)
3. Captures + OCRs each viewport, scrolls down, repeats (up to 20 pages)
4. Deduplicates overlapping text between frames (filters UI chrome before comparison)
5. Cleans OCR output — strips browser toolbar, menu bar, short UI fragments
6. Sends clean text to LLM with structured solving prompt
7. Saves formatted answers to `~/Documents/friday_files/Screen_Answers_<timestamp>.docx`

Works with any scrollable app. Tested on Safari with a 20-page workbook — captured all questions, solved them with detailed paragraph-length answers.

**App Targeting:** Say which app to look at and FRIDAY activates it before capturing. "Open Safari and solve the questions" or "solve questions in Preview". If you don't specify, it uses whatever's in front.

**Viewport-Only Mode:** When you just want the current view solved without scrolling the whole page, say "just solve what's on my screen" — captures one frame, solves, done.

Screenshots auto-delete after 48 hours. Nothing is stored permanently.

**Setup:**
```bash
# Required — enable screen access
echo "FRIDAY_SCREEN_ACCESS=true" >> .env

# Optional — pull vision model for full image understanding
ollama pull qwen2.5vl:7b
```

Without the vision model, FRIDAY can still read all text on screen (OCR) and answer questions about it. The vision model adds app/UI/diagram recognition.

---

## CLI Commands

### Shell commands (outside the REPL)

| Command | Description |
|---------|-------------|
| `friday` | Launch the REPL (runs `friday init` on first run) |
| `friday onboard` | Full guided setup — QuickStart or Advanced |
| `friday init` | Interactive profile wizard (name, bio, tone → `user.json`) |
| `friday doctor` | Audit every integration + system dependency (shows version) |
| `friday update` | Detects how FRIDAY was installed and runs the right upgrade |
| `friday config [show\|edit\|path\|open]` | Inspect / edit `~/Friday/user.json` |
| `friday setup deps` | Detect and brew-install missing system tools |
| `friday setup openrouter` | Paste key, optionally pick a model from the live catalogue |
| `friday setup groq` | Paste Groq key |
| `friday setup tavily` | Paste Tavily key (web search) |
| `friday setup elevenlabs` | Paste ElevenLabs key (cloud TTS) |
| `friday setup x` | Paste X / Twitter tokens |
| `friday setup gmail` | Open GCP credentials page + log in via OAuth |
| `friday setup twilio` | Paste SID / token / phone — 4 fields |
| `friday setup voice` | Toggle voice, optionally wire ElevenLabs |
| `friday setup gestures` | Download MediaPipe model + enable gestures |
| `friday test llm\|gmail\|twilio\|tv` | Connectivity check for each integration |
| `friday heartbeat` | Explain background watches + list active ones |

### In-REPL slash commands

| Command | Description |
|---------|-------------|
| `/quit` | Exit FRIDAY |
| `/clear` | Reset conversation history |
| `/memory` | Show recent stored memories |
| `/voice` | Toggle voice pipeline on/off |
| `/gestures` | Toggle gesture control on/off |
| `/listening-off` | Pause ambient listening |
| `/listening-on` | Resume ambient listening |
| `/clearwatches` | Kill all active watch tasks |

---

## Personality

FRIDAY is **not a fixed character**. The voice comes from `~/Friday/user.json`:

- **`name`** — how it addresses you
- **`bio`** — one-line self-description injected into the personality
- **`tone`** — free-form note ("direct, dry humour", "warm, patient", etc.)
- **`slang`** — vocabulary the model treats as understood (won't translate back)
- **`contact_aliases`** — nickname → real-person mappings for messaging
- **`briefing_watchlist`** — X handles and topics to surface in daily briefings
- **`cv`** — full CV (experience, projects, skills, education) — used for job applications AND injected into every system prompt so the assistant answers grounded in who you actually are

The example in [`docs/user.example.json`](docs/user.example.json) shows the shape. A richer personalised setup feels like this:

```
▶ hawfar
  FRIDAY  E dey. You good? What are we doing.

▶ chale this thing no dey work
  FRIDAY  What broke. Show me.

▶ time no dey
  FRIDAY  Sharp sharp. What's the priority.
```

Same FRIDAY, different user — slang block populated with the user's own vocabulary, tone note steering register. Nothing in the prompt text says "Travis" or "Ghanaian" unless `user.json` says so.

See [`docs/user-config.md`](docs/user-config.md) for every field.

---

## Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| **LLM (cloud)** | Gemma 4 31B via OpenRouter (default), Qwen3-32B via Groq (backup) | 97% tool accuracy, provider-agnostic — any OpenAI-compatible API works |
| **LLM (local)** | Qwen3.5-9B via Ollama | 9B params, fully offline fallback, thinking toggle, Apache 2.0 |
| **Package Manager** | uv | 10-100x faster than pip |
| **Web Search** | Tavily | Built for AI agents, returns structured data, AI answers |
| **Vector DB** | ChromaDB | Lightweight, embedded, cosine similarity |
| **Structured DB** | SQLite | Zero-config, built into Python |
| **CLI Framework** | Rich + prompt_toolkit | Beautiful output, history, auto-suggest |
| **HTTP** | httpx | Async, modern, follow redirects |
| **Google APIs** | google-api-python-client + google-auth-oauthlib | Gmail OAuth2 |
| **Calendar** | AppleScript + macOS Calendar.app | Native iCloud/local calendar, no API keys |
| **iMessage** | SQLite (`chat.db`) + AppleScript Messages.app | Read conversations + send texts, no API keys |
| **FaceTime** | AppleScript FaceTime.app | Initiate calls, multi-number support |
| **Contacts** | AppleScript Contacts.app | Fuzzy search, nickname resolution, emoji support |
| **Cron/Scheduler** | APScheduler CronTrigger + SQLite | User-defined scheduled tasks, persistent across restarts |
| **Standing Orders** | APScheduler (30s ticks) + SQLite + LLM reasoning | Watch iMessages (auto-reply), emails, missed calls, browser pages — type-classified dispatch |
| **SMS** | Twilio + Tailscale Funnel | Text FRIDAY from any phone, webhook server on port 3200, stable public URL |
| **Phone Notifications** | iMessage to self | Instant alerts to iPhone, DND bypass capable |
| **Screen Vision & Solver** | Apple Vision (Swift OCR) + Qwen2.5-VL (Ollama) | Screen reading, full-page scroll+OCR, question solver → formatted .docx |
| **Browser Automation** | Safari (Selenium) + Playwright fallback | Safari = your sessions/cookies, no login walls. Playwright fallback for headless. |
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
- [x] 11 specialist agents (Code, Research, Deep Research, Memory, Comms, System, Household, Monitor, Briefing, Job, Social)
- [x] Tool library (web, file, terminal, memory, email, calendar, mac, browser)
- [x] Gmail integration — read, search, send, draft, edit draft, send draft, label, thread
- [x] macOS/iCloud Calendar integration — day/week view, create events (no API keys needed)
- [x] Mac control — AppleScript, app launcher, screenshots, volume, dark mode
- [x] Screen vision — OCR (Apple Vision, offline) + image understanding (Qwen2.5-VL), auto-cleanup after 48h
- [x] Full-page question solver — scroll + OCR entire pages, solve all questions, save formatted .docx, app targeting, viewport-only mode
- [x] Browser automation — Safari (Selenium, your sessions) + Playwright fallback, login detection
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

### Phase 4.5 — Autonomy: Heartbeat, Cron, Watch Tasks, iMessage, Notifications (Complete)
- [x] iMessage integration — read conversations from `chat.db`, send via AppleScript, NSAttributedString parsing
- [x] FaceTime integration — initiate video/audio calls, multi-number contact handling
- [x] Contact resolution — fuzzy matching with word-overlap scoring, nickname/emoji support
- [x] Heartbeat system — proactive background loop (30min default), zero-LLM silent ticks, 1 LLM synthesis only when urgent
- [x] Configurable via `HEARTBEAT.md` — plain English, editable at runtime
- [x] Quiet hours (1am-7am), daily alert cap (3/day), morning briefing trigger
- [x] Cron scheduler — user-defined scheduled tasks, standard 5-field cron expressions
- [x] Cron tools — `create_cron`, `list_crons`, `delete_cron`, `toggle_cron` (conversational creation)
- [x] **Standing orders (watch tasks)** — "watch X's messages for the next hour, reply like me"
- [x] Watch task reasoning — LLM decides if a message needs a reply (skips "okay", "lol", thumbs up)
- [x] Watch identity switching — reply as Travis or as FRIDAY based on instruction + conversation context
- [x] Auto-detection — if Travis introduces FRIDAY or the other person mentions her, she switches to herself
- [x] @friday tagging — type `@friday` in iMessage mid-conversation and she jumps in (requires active watch)
- [x] Deflection rules — never agrees to calls, money, or plans. Deflects casually.
- [x] Watch deduplication — updating a watch for the same contact modifies the existing one, no duplicates
- [x] Baseline-first — first tick records state, only replies on genuinely new messages after watch creation
- [x] **Universal watch system** — keyword dispatch to iMessage, WhatsApp, email, calls, URL, search, topic, or browser executors
- [x] **Email watch** — reads unread emails, filters by sender keyword, notifies on new matches
- [x] **Call log watch** — reads missed calls, fingerprints latest, notifies on new missed calls
- [x] **Browser watch** — opens URL via Playwright, hashes page content, LLM summarizes changes
- [x] **URL/search/topic watch** — web page diffing, recurring web searches, topic monitoring with materiality detection
- [x] **WhatsApp watch** — monitors WhatsApp messages, auto-replies with same standing order system as iMessage
- [x] Phone notifications — iMessage to self, instant delivery, works with DND bypass
- [x] `/clearwatches` CLI command — kill all active watches instantly
- [x] All background systems boot automatically on CLI startup
- [x] **Screen vision** — "can you see what I'm doing", OCR + vision model, privacy-gated, 48h auto-delete
- [x] **Full-page question solver** — "solve the questions on Safari", scrolls entire page, OCRs + deduplicates, solves all questions, saves formatted .docx with app targeting and viewport-only mode
- [x] **Multi-agent deep research** — parallel sub-agents (search + fetch + read + write), phased execution, produces real documents saved to disk

### Phase 4.7 — Gesture Control (Complete)
- [x] MediaPipe GestureRecognizer — 7 built-in gestures per hand, two-hand detection
- [x] **29 total gestures**: 8 right, 8 left, 7 both hands, 2 mixed combos, 4 pinch drag
- [x] Custom pinch detection — thumb + index tip distance from landmarks
- [x] **Pinch drag** — continuous control (volume slider in mid-air, Iron Man style)
- [x] **100% `.env` configured** — every gesture, timing, and threshold customizable without touching code
- [x] **Wrist-based handedness** — uses wrist x-position instead of MediaPipe's unreliable classifier for left/right
- [x] **Two-hand frame buffer** — 0.4s buffer merges hands from consecutive frames for reliable combos
- [x] `/gestures-on`, `/gestures-off`, `/gestures` toggle + `/help` command listing all controls
- [x] Daemon thread architecture — same pattern as voice pipeline, runs alongside voice simultaneously
- [x] Hold threshold (0.4s) + cooldown (1.5s) + grace window (0.3s) for flicker tolerance
- [x] Commands routed through fast_path (sub-second TV control) or agent dispatch (briefings)
- [x] C++ log suppression (MediaPipe/TFLite noise silenced at fd level)
- [x] `/gestures` CLI toggle + `FRIDAY_GESTURES=true` env flag
- [x] Zero GPU — runs on CPU at 30fps via TFLite XNNPACK

### Phase 5 — Skills & Intelligence (In Progress)
- [x] **Skill system** — markdown SKILL.md files (same format as OpenClaw/ClawHub) that agents load before executing
- [x] Skill loader discovers skills from `friday/skills/` (repo) + `~/.friday/skills/` (personal)
- [x] YAML frontmatter: name, description, agents (which agents load it)
- [x] `agents: all` = every agent, `agents: [job_agent, research_agent]` = specific
- [x] **14 skills shipped**: proactive-execution, adaptive-reasoning, memory-first, self-improving, web-research, job-analysis, youtube-watcher, humanize-text, browser-use, pdf-toolkit, image-tools, powerpoint, code-workflow, marketing-strategy
- [x] **Proactive execution** — never ask "should I proceed?", chain steps automatically
- [x] **Adaptive reasoning** — score task complexity 0-10, match effort to difficulty
- [x] **Memory first** — check memory before searching web, never say "I don't have info" without searching
- [x] **Self-improving** — learn from corrections, store preferences, record successful patterns
- [x] **Web research** — fetch URL flow with JS fallback, search-before-answering pattern
- [x] **Job analysis** — fetch posting → check memory for projects → score fit → rank projects → give verdict
- [x] **YouTube watcher** — fetch video transcripts via yt-dlp, summarize, answer questions about videos
- [x] **Humanize text** — strip AI patterns (delve, tapestry, "I'd be happy to"), match Travis's writing style
- [x] **Browser use** — snapshot→act→verify pattern, form filling best practices, session persistence
- [x] **PDF toolkit** — extract text/tables, create, merge, split, rotate PDFs (pypdf, pdfplumber, WeasyPrint)
- [x] **Image tools** — resize, compress, convert, crop images. Social media size presets (Pillow, ffmpeg)
- [x] **PowerPoint** — create/edit PPTX presentations, pitch deck templates (python-pptx)
- [x] **Code workflow** — structured plan→execute→verify→deliver, anti-patterns, git conventions
- [x] **Marketing strategy** — April Dunford positioning, ICP, competitive battlecards, launch tiers, pricing
- [x] `fetch_page` auto-fallback — detects JS-only pages, renders with browser automatically
- [x] `youtube_transcript` tool — yt-dlp transcript extraction + metadata
- [x] Memory seeded with corrections, patterns, and preferences from real usage
- [x] Fine-tuning data collection from sessions (JSONL conversation logs)
- [ ] QLoRA fine-tune on smaller model (personality + routing baked into weights)
- [ ] Additional agents (Git, Deploy, Database)
- [ ] Self-hosted inference on Modal/RunPod (for privacy or custom fine-tuned models)

### Phase 7 — SMS & Remote Access (Complete)
- [x] **Twilio SMS integration** — text FRIDAY from any phone, full pipeline processing, TwiML replies
- [x] SMS webhook server on port 3200 — receives inbound, processes through FridayCore, replies
- [x] SMS tools — `send_sms`, `read_sms` integrated into CommsAgent
- [x] **Tailscale Funnel** — permanent public HTTPS URL, no ngrok, no dynamic DNS, free
- [x] Auto-start — SMS server + Tailscale Funnel boot with `uv run friday`, die with Ctrl+C
- [x] Security — allowed-numbers gate, response truncation, processing timeout
- [x] Dual Twilio numbers — UK (+447367000489) for local, US (+17405588099) for international

### Phase 8 — Ecosystem
- [ ] **Telegram bot integration** — another remote access channel
- [ ] FRIDAY iOS app — native push notifications via APNs, full assistant UI
- [ ] Mac Mini server — FRIDAY runs 24/7 on dedicated hardware
- [ ] Redis async messaging between agents
- [ ] MCP server integration
- [ ] Screenpipe integration (screen context awareness)
- [ ] Self-improving loop (auto fine-tune from corrections)
- [ ] Multi-user support
- [ ] Plugin/extension system

---

## Cloud Inference

FRIDAY is **provider-agnostic** — any OpenAI-compatible API works. Set one env var and go. Currently defaults to **Gemma 4 31B on OpenRouter** after extensive benchmarking.

### Why Cloud?

Running Qwen3.5-9B locally on an M4 MacBook Air gave us 54s average response time. The M4 Air is fanless — under sustained LLM load, the GPU thermally throttles 2-15x. Cloud inference brought the average down to **~3s** — a 15x improvement.

### Why Gemma 4?

We ran a 36-query benchmark across FRIDAY's 3 LLM paths (intent classification, tool dispatch, personality chat) using the actual system prompts and tool schemas:

| Path | Qwen3-32B (Groq) | Gemma 4 31B (OpenRouter) |
|------|-------------------|--------------------------|
| **Classify** (16 queries) | 0/16 | **16/16** |
| **Dispatch** (12 queries) | 6/12 | **11/12** |
| **Chat** (8 queries) | 2/8 | **8/8** |
| **TOTAL** | **8/36 (22%)** | **35/36 (97%)** |
| **Avg speed** | **0.46s** | **2.95s** |

Gemma 4 won on accuracy across every path. Qwen3 was faster (Groq hardware advantage) but failed on basic tool calls, leaked `<think>` blocks, produced AI slop in chat, and crashed on schema validation. Gemma followed instructions precisely without needing special tokens.

### Provider Options

| Provider | Model | Speed | Accuracy | Cost/month |
|----------|-------|-------|----------|------------|
| **OpenRouter** (default) | Gemma 4 31B | ~3s avg | **97%** | **$3.43** |
| Groq | Qwen3-32B | ~0.5s avg | 22% (raw) | $6.82 |
| Together AI | Gemma 4 31B | ~3s avg | 97% | $4.82 |
| Fireworks | Gemma 4 31B | ~3s avg | 97% | $20.05 |
| Local Ollama | Qwen3.5-9B | ~15s avg | ~70% | Free |

### How It Works

All LLM calls go through `cloud_chat()` in `friday/core/llm.py`. It auto-detects the provider from env vars and falls back gracefully.

```
cloud_chat()
  ├─ OPENROUTER_API_KEY set? → OpenRouter (Gemma 4 31B, ~3s)
  ├─ GROQ_API_KEY set?       → Groq (Qwen3-32B, ~0.5s)
  ├─ CLOUD_API_KEY set?      → Any OpenAI-compatible endpoint
  └─ None set?               → Local Ollama (~15s per call)
```

### Switching Providers

```bash
# OpenRouter (recommended — best accuracy)
echo 'OPENROUTER_API_KEY=sk-or-v1-xxx' >> .env

# Groq (fastest — if speed > accuracy)
echo 'GROQ_API_KEY=gsk_xxx' >> .env

# Any provider (Together, Fireworks, RunPod, Modal, your own vLLM)
echo 'CLOUD_API_KEY=xxx' >> .env
echo 'CLOUD_BASE_URL=https://api.together.xyz/v1' >> .env
echo 'CLOUD_MODEL=google/gemma-4-31B-it' >> .env

# Fully local (remove all cloud keys)
# FRIDAY uses Ollama automatically
```

## Cloud vs Local — Your Choice

FRIDAY auto-detects what's available. No config flags, no code changes — just environment variables. See [Quick Start](#quick-start) for setup.

```
OPENROUTER_API_KEY or GROQ_API_KEY or CLOUD_API_KEY set?
  ├─ Yes → cloud_chat() uses cloud API (~0.5-3s per call)
  │        classify_intent() uses LLM for smart agent routing
  │        Auto-fallback to Ollama if cloud is unreachable
  │
  └─ No  → cloud_chat() routes to local Ollama (~10-25s per call)
           classify_intent() skips, regex handles all routing
           Zero cloud calls, fully offline capable

ELEVENLABS_API_KEY set?
  ├─ Yes → TTS uses ElevenLabs Flash v2.5 (~75ms streaming)
  │        Falls back to Kokoro if cloud fails
  │
  └─ No  → TTS uses Kokoro-82M ONNX (~500ms local synthesis)
           Zero cloud calls, fully offline
```

To switch: add or remove the API key from `.env` and restart FRIDAY. That's it.

---

## Configuration

All config lives in `friday/core/config.py`:

```python
# Cloud LLM — provider-agnostic (auto-detected from env vars)
# Priority: CLOUD_API_KEY (manual) > OPENROUTER_API_KEY > GROQ_API_KEY > local Ollama
CLOUD_API_KEY = ...                  # Auto-detected from env
CLOUD_BASE_URL = ...                 # Auto-set per provider
CLOUD_MODEL_NAME = ...               # Auto-set per provider
USE_CLOUD = bool(CLOUD_API_KEY)

# Local Ollama (fallback when no cloud key set)
MODEL_NAME = "qwen3.5:9b"
OLLAMA_BASE_URL = "http://localhost:11434"
```

Environment variables (`.env`):
```
TAVILY_API_KEY=your-key-here
OPENROUTER_API_KEY=sk-or-v1-...      # Recommended — Gemma 4 31B (97% accuracy, $3.43/mo)
GROQ_API_KEY=gsk_...                 # Alternative — Qwen3-32B (fastest, $6.82/mo)
# Or any provider:
# CLOUD_API_KEY=xxx
# CLOUD_BASE_URL=https://api.together.xyz/v1
# CLOUD_MODEL=google/gemma-4-31B-it
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

## Pricing

FRIDAY is provider-agnostic. Here's what each option costs based on real usage (~200 LLM calls/day):

| Provider | Model | Input/M | Output/M | Monthly Cost | Free Tier |
|----------|-------|---------|----------|-------------|-----------|
| **OpenRouter** (default) | Gemma 4 31B | $0.14 | $0.40 | **$3.43** | Yes |
| Groq | Qwen3-32B | $0.29 | $0.59 | $6.82 | Yes |
| Together AI | Gemma 4 31B | $0.20 | $0.50 | $4.82 | Yes |
| Local Ollama | Qwen3.5-9B | Free | Free | **$0** | N/A |

**What does this cost in practice?** A typical FRIDAY query uses ~3,500 input tokens and ~200 output tokens. On OpenRouter that's ~$0.0006 per query. **$1 covers ~1,700 queries.** The free tier is more than enough for personal use.

Sign up at [openrouter.ai](https://openrouter.ai) — free credits on signup, no credit card required.

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) for full text.

**Attribution:** If you use FRIDAY in your project, product, or research, please credit the original author:

> Built on FRIDAY by Travis Moore (Angelo Asante)

See [NOTICE](NOTICE) for full attribution requirements.

---

*Built at 2am in Plymouth, UK. By Travis Moore.*
