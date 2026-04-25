# FRIDAY

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Built by](https://img.shields.io/badge/Built%20by-Travis%20Moore-green.svg)](https://github.com/angeloasante)
[![PyPI](https://img.shields.io/badge/pip%20install-friday--os-green.svg)](https://pypi.org/project/friday-os/)

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

Tony Stark had JARVIS. This is FRIDAY. A personal AI OS built from scratch — **134 tools across 23 modules**, 11 specialist agents, voice, gesture control, persistent memory, local + cloud inference. You talk to it like a person. It gets things done without you having to explain yourself twice.

Apache 2.0. Use it. Build on it.

---

## Contents

- [Install](#install) · [What FRIDAY does](#what-friday-does) · [Deep dives](#deep-dives)
- [Integrations](#integrations) · [Personality](#personality) · [Design](#design-philosophy) · [Pricing](#pricing)
- [Changelog](CHANGELOG.md) · [License](#license)

---

## Install

One line on macOS or Linux. Installs `uv` if missing, puts FRIDAY in an isolated environment, runs first-time setup.

```bash
curl -fsSL https://raw.githubusercontent.com/angeloasante/Jarvis/main/install.sh | sh
```

Or pick a package manager you already have:

| Pathway | Command | Isolation |
|---|---|---|
| **curl one-liner** *(recommended)* | `curl -fsSL .../install.sh \| sh` | ✓ |
| **uv tool** | `uv tool install friday-os` | ✓ |
| **pipx** | `pipx install friday-os` | ✓ |
| **pip** | `pip install --user friday-os` | ✗ |
| **source** | `git clone … && uv sync && uv run friday` | ✓ |

After install: `friday onboard` walks you through profile + integrations + health check. Everything you know about yourself lives in one file at `~/Friday/user.json`.

Deep dive → **[docs/install.md](docs/install.md)**.

### Updating

One command regardless of install method:

```bash
friday update
```

It detects how you installed (curl / uv tool / pipx / pip / source / Mac app) and runs the right upgrade. Pulls the full tree — new files, new agents, new tools, new features — not just a version bump.

---

## What FRIDAY does

```
You: "man, you good?"
FRIDAY: Always. What's the play?                    ← <1ms, zero LLM

You: "check my emails"
FRIDAY: Say less. Working on it in the background.
  ◈ checking emails
FRIDAY (12s) You've got 4 unread. One from Stripe   ← direct dispatch
  (critical) — payment webhook failing on prod...

You: "catch me up"
FRIDAY: On it. Keep chatting, I'll holler when done.
  ◈ checking emails + calendar + x in parallel
  ◈ ✓ done
FRIDAY (32s) Three things. Global Talent page updated,
  your MP tweeted about digital infrastructure,
  calendar's empty...

You: "watch my partner's messages for the next hour, reply as friday"
FRIDAY: Got it. Watching every 60 seconds.
  💛 FRIDAY Watch — replied:
  "FRIDAY: She's building me right now, I'll let her
  know you texted."

You (in iMessage): "I'm innocent 😂 @friday defend me here wai"
  💛 FRIDAY Watch — tagged mid-conversation, jumped in.
```

That last one actually happens. `@friday` mid-chat, FRIDAY picks it up, replies in your thread. The other person thinks you're having a laugh.

### Capabilities at a glance

| Capability | Tools | Details |
|---|---:|---|
| **Comms** | 20 | Gmail (read/search/draft/send/thread), Google Calendar, iMessage, WhatsApp, Twilio SMS, X/Twitter |
| **Mac control** | 10 | Apps, AppleScript, screenshots, volume, dark mode, music |
| **Browser** | 18 | Navigate, click, fill forms, scroll, upload, JS execute, login detection |
| **TV / smart home** | 20 | LG WebOS — power, volume, mute, launch apps, remote, screen casting, sub-500ms fast-path |
| **Screen vision** | 6 | Apple Vision OCR, VLM queries, full-page scroll capture, solve-on-page |
| **Files + PDF** | 13 | Read/write/search files, PDF read/write/merge/split/rotate/encrypt/watermark |
| **Web research** | 3 | Tavily search, page fetch, YouTube transcripts |
| **Autonomy** | 10+ | Heartbeat, cron, watch tasks (standing orders), monitors, briefings |
| **Memory** | 3 | ChromaDB vector + SQLite structured, auto-learn from corrections |
| **Other** | 30+ | Jobs/CV, GitHub, screencast, terminal, call history |

**Full tool inventory (134 total, run `friday doctor` to verify):** click through to the deep dives below for every agent, tool, and setup.

---

## Deep dives

Every major subsystem has its own doc. Read the ones relevant to what you're doing.

| Topic | Doc | In one line |
|---|---|---|
| Installing + onboarding | [docs/install.md](docs/install.md) | Five pathways, `friday onboard`, `friday doctor`, `friday update` |
| System architecture | [docs/architecture.md](docs/architecture.md) | 7-tier routing, system-prompt assembly, provider abstraction |
| Project structure | [docs/project-structure.md](docs/project-structure.md) | Map of the codebase for contributors |
| CLI commands | [docs/cli-commands.md](docs/cli-commands.md) | Every shell command + REPL slash command |
| Agents | [docs/agents.md](docs/agents.md) | All 10 specialist agents, scopes, tools, routing |
| Memory | [docs/memory.md](docs/memory.md) | ChromaDB + SQLite, auto-learn from corrections |
| Standing orders | [docs/watch-tasks.md](docs/watch-tasks.md) | Autonomous message watch + auto-reply |
| Cron | [docs/cron.md](docs/cron.md) | Natural-language scheduled tasks |
| Notifications | [docs/notifications.md](docs/notifications.md) | iMessage-to-self + Twilio SMS push |
| Telegram | [docs/telegram.md](docs/telegram.md) | Rich-media channel (50 MB/file), long-polling, no tunnel |
| Deep research | [docs/deep-research.md](docs/deep-research.md) | Multi-agent parallel → full document output |
| Improvement mode | [docs/improvement-mode.md](docs/improvement-mode.md) | Correction capture, task-aware skill selection, self-improving patterns |
| Screen vision | [docs/screen-vision.md](docs/screen-vision.md) | OCR + VLM + page solver → `.docx` |
| Gesture control | [docs/gesture-control.md](docs/gesture-control.md) | 29 MediaPipe gestures, Iron-Man pinch drag |
| Voice pipeline | [docs/voice-pipeline.md](docs/voice-pipeline.md) | Engineering deep-dive — VAD/STT/trigger/streaming TTS, latency budget, anti-feedback |
| Personality | [docs/user-config.md](docs/user-config.md) | `~/Friday/user.json` — name, bio, tone, slang, CV |
| Tech stack | [docs/tech-stack.md](docs/tech-stack.md) | Every dep with version + why it was chosen |
| LLM providers | [docs/llm-providers.md](docs/llm-providers.md) | OpenRouter, Groq, Anthropic, any OpenAI-compatible, Ollama |

---

## Integrations

Each one is a one-shot wizard. Paste your API key (or log in via OAuth) and it's connected. Full walkthrough per integration below.

| Service | Command | What it enables | Guide |
|---|---|---|---|
| **OpenRouter** *(recommended LLM)* | `friday setup openrouter` | Widest model selection, free tier, live model picker | [docs/setup-openrouter-groq.md](docs/setup-openrouter-groq.md) |
| **Groq** *(fastest LLM)* | `friday setup groq` | Sub-100ms latency, ~500 tok/s | [docs/setup-openrouter-groq.md](docs/setup-openrouter-groq.md) |
| **Ollama** *(local LLM)* | see guide | Fully local inference, privacy, offline | [docs/ollama-setup.md](docs/ollama-setup.md) |
| **Tavily** *(web search — primary)* | `friday setup tavily` | Agent-optimised web search, research + briefings | [docs/setup-tavily.md](docs/setup-tavily.md) |
| **Firecrawl** *(web search fallback + scrape)* | `friday setup firecrawl` | Auto-fallback when Tavily caps out; also upgrades fetch_page output. 500 free credits, no card. | — |
| **Gmail + Calendar** | `friday setup gmail` | Read/search/draft/send mail, calendar events — bundled OAuth, just sign in | [docs/setup-google.md](docs/setup-google.md) |
| **Twilio SMS** | `friday setup twilio` | Text FRIDAY from any phone, outbound SMS | [docs/sms-setup.md](docs/sms-setup.md) |
| **Telegram** | `friday setup telegram` | Second channel, 50 MB/file rich media, voice notes with audio-tag emotion (Eleven v3), cross-channel SMS → Telegram delivery of docs/images/voice. No tunnel, free. | [docs/telegram.md](docs/telegram.md) |
| **ElevenLabs TTS** | `friday setup elevenlabs` | Cloud voice (~75ms live, Eleven v3 with audio tags for voice notes). Optional — Kokoro runs locally if you skip. | [docs/setup-voice.md](docs/setup-voice.md) |
| **X (Twitter)** | `friday setup x` | Post, mentions, search, retweets, likes | — |
| **WhatsApp** | see guide | Read/send WhatsApp via local Baileys bridge | [docs/whatsapp-setup.md](docs/whatsapp-setup.md) |
| **Voice** | `friday setup voice` | Always-on ambient listen, wake word "Friday". Optional WebSocket input streaming (`FRIDAY_TTS_INPUT_STREAMING=true`) for token-by-token TTS. Engineering deep-dive in [docs/voice-pipeline.md](docs/voice-pipeline.md). | [docs/setup-voice.md](docs/setup-voice.md) |
| **Gestures** | `friday setup gestures` | Camera-based hand control, 29 gestures | [docs/gesture-control.md](docs/gesture-control.md) |

Run `friday doctor` any time to see which integrations are live and which aren't.

---

## Personality

FRIDAY isn't a fixed character. The voice comes from **`~/Friday/user.json`** — a single file FRIDAY injects into every system prompt so the assistant actually knows who it's talking to. Fields include name, bio, tone note, slang vocabulary, contact nickname aliases, briefing watchlist, and a full CV section used by the job agent.

The same file drives:
- **Voice transcripts** — console shows `🎤 Ada:` not `🎤 User:`
- **Reply drafting** — when FRIDAY writes messages for you, it matches your tone
- **Job applications** — CV fields populate every form
- **Briefings** — watchlist decides what X handles + topics to surface

Edit it any time: `friday config edit` · `friday config open` · or Mac app → Settings → Profile. Full schema + example → **[docs/user-config.md](docs/user-config.md)**.

---

## Design philosophy

1. **Speed first, local always available** — cloud inference via Groq/OpenRouter for sub-second LLM calls. Automatic fallback to local Ollama when offline. Remove the API key and everything runs on your machine.
2. **Agents are specialists** — each agent gets focused context and tools. No god-agent.
3. **Memory is identity** — FRIDAY remembers you. That's what makes it personal.
4. **Speed over perfection** — streaming, think control, fast routing. Latency kills the vibe.
5. **Personality is not optional** — a tool without personality is just a tool.

---

## Pricing

FRIDAY is free + open source. You pay only for the LLM provider you pick.

| Provider | Model | $/M prompt | $/M output | ~Monthly *(200 queries/day)* | Free tier |
|---|---|---:|---:|---:|:-:|
| **OpenRouter** *(recommended)* | Gemma 4 31B | $0.14 | $0.40 | **~$3.43** | ✓ |
| Groq | Qwen3-32B | $0.29 | $0.59 | ~$6.82 | ✓ |
| Together AI | Gemma 4 31B | $0.20 | $0.50 | ~$4.82 | ✓ |
| **Local Ollama** | Qwen3.5-9B | — | — | **$0** | n/a |

A typical FRIDAY query uses ~3,500 input + ~200 output tokens → ~$0.0006 on OpenRouter. **$1 covers ~1,700 queries.** Free tiers cover normal personal use.

Sign up at [openrouter.ai](https://openrouter.ai) — free credits on signup, no card required.

---

## Changelog

Version history, phases, and per-release notes: **[CHANGELOG.md](CHANGELOG.md)**.

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) for full text.

**Attribution:** If you use FRIDAY in your project, product, or research, please credit the original author:

> Built on FRIDAY by Travis Moore (Angelo Asante)

See [NOTICE](NOTICE) for full attribution requirements.

---

*Built at 2am in Plymouth, UK. By Travis Moore.*
