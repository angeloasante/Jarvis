# FRIDAY Tech Stack

FRIDAY is a Python 3.12 personal-AI OS for macOS with a SwiftUI wrapper, a Node.js bridge for WhatsApp, and a mix of local (Apple Silicon) and cloud model inference. The philosophy across the stack is the same: prefer boring, well-known tools with good offline stories, keep dependencies pinned to lower bounds in `pyproject.toml`, and abstract any external provider behind a swap point so the system keeps working when a key expires or a service goes down.

## Layer → What we use → Why

| Layer | What we use | Why |
|---|---|---|
| LLM inference (cloud) | `openai>=2.29.0` client pointed at OpenRouter / Groq / Anthropic-compatible endpoints | One OpenAI-compatible client covers every major provider; no vendor lock |
| LLM inference (local) | `ollama>=0.6.1` + llama.cpp backends | Native thinking control, auto-GGUF, runs on unified memory |
| Vector store | `chromadb>=1.5.5` (persistent client) | Embedded, no server, single file on disk, good enough for <1M vectors |
| Structured storage | stdlib `sqlite3` | Ships with Python, zero-install, rows are copy-pasteable |
| Python runtime | 3.12+, `uv` toolchain | Fast resolver, `uv run` replaces venvs, `python-build-standalone` for the Mac app |
| Packaging | `setuptools` via `pyproject.toml`, `friday-os` on PyPI | Stable, well-understood, works with `uv tool install` |
| HTTP | `httpx>=0.28.1` | Async-native, HTTP/2, drop-in for `requests` |
| Browser | `playwright>=1.58.0` (+ Safari AppleScript fallback) | Aria-snapshot-based refs, stable selectors, Safari for the signed-in case |
| STT | `silero-vad` + `mlx-whisper>=0.4.0` | Local, Apple Silicon GPU, no audio leaves the device |
| TTS cloud | ElevenLabs Flash v2.5 (direct HTTPS stream) | ~75 ms first byte, real-time PCM chunks |
| TTS local | `kokoro-onnx>=0.4.0` + `onnxruntime>=1.19.0` | Fully offline fallback when the ElevenLabs key is absent |
| Screen OCR | `pyobjc-framework-quartz>=10.0` + Apple `Vision` framework | Free, native, no model download |
| Vision model | Qwen2.5-VL via Ollama (local) or cloud VLM | Same `cloud_chat` abstraction, swap by config |
| Gesture | `mediapipe>=0.10.0` + `opencv-python>=4.8.0` | CPU-only, ~30 fps on M-series, 7 built-in gestures plus custom pinch |
| Scheduling | `apscheduler>=3.11.2` + custom async polling | Cron for user jobs, tight loop for heartbeat / watch tasks |
| PDF read | `pypdf>=6.9.1`, `pdfplumber>=0.11.9` | pypdf for stream ops, pdfplumber for tables |
| PDF write | `weasyprint>=63.0` + `jinja2>=3.1.6` | HTML/CSS → PDF, good for CV + research docs |
| DOCX | `python-docx>=1.2.0` | The only mature option, styles and runs |
| Google APIs | `google-api-python-client>=2.193.0`, `google-auth-oauthlib>=1.3.0` | Gmail + Calendar, first-party OAuth flow |
| iMessage | AppleScript + read-only SQLite on `chat.db` | No API exists, direct DB read plus osascript send |
| WhatsApp | Baileys (`@whiskeysockets/baileys`) + Express, Python talks over localhost HTTP | Baileys is the only working unofficial client; keep it in Node to match its ecosystem |
| SMS | `twilio>=9.10.4` | Text FRIDAY from anywhere, also inbound webhooks |
| X | `tweepy>=4.16.0` | Stable v2 client, handles pagination and rate limits |
| TV | `pywebostv>=0.8.9` + `wakeonlan>=3.1.0` | LG WebOS websocket control, WOL for cold boot |
| Mac app | SwiftUI + NSStatusItem, bundled Python 3.12 via python-build-standalone | Native menu bar, no Electron, end users don't need Python |
| Terminal UI | `rich>=14.3.3`, `prompt-toolkit>=3.0.52` | REPL, history, auto-suggest, coloured output |
| Search | `tavily-python>=0.7.23` | One API for whole-web answers |
| Video / fal | `fal-client>=0.13.2` | Hosted inference for heavier model runs |

---

## 1. LLM inference

FRIDAY uses a single abstraction — `friday/core/llm.py` — that exposes two functions and normalises responses to the same dict shape regardless of backend.

- `chat(...)` — local Ollama (`ollama>=0.6.1`). Uses Ollama's native `think` parameter to actually disable the thinking pipeline for fast paths (~1–2 s) vs deep reasoning (~90 s otherwise). `keep_alive=-1` pins the model in VRAM so we don't pay reload cost.
- `cloud_chat(...)` — any OpenAI-compatible endpoint via the `openai>=2.29.0` SDK. Providers are auto-detected from `~/.friday/.env`:
  - `OPENROUTER_API_KEY` → `https://openrouter.ai/api/v1`, Gemma 4 31B.
  - `GROQ_API_KEY` → `https://api.groq.com/openai/v1`, `qwen/qwen3-32b`.
  - Explicit `CLOUD_API_KEY` + `CLOUD_BASE_URL` + `CLOUD_MODEL` wins if set.
- Falls back from cloud → local automatically on any exception.
- Tool-call schemas are wrapped into OpenAI format; responses are unwrapped back into the Ollama dict shape so callers (`extract_tool_calls`, `extract_text`) don't care where the text came from.
- A `_ThinkingFilter` strips `<think>...</think>` blocks from Qwen-family models in streamed and non-streamed responses.

Relevant files:
- `/Users/travismoore/Desktop/JARVIS/friday/core/llm.py`
- `/Users/travismoore/Desktop/JARVIS/friday/core/config.py`

**Swap notes.** Any OpenAI-compatible provider works with no code changes — set `CLOUD_API_KEY`, `CLOUD_BASE_URL`, `CLOUD_MODEL` and restart. To add native-protocol Anthropic or Gemini, add a new branch inside `cloud_chat` and reuse `_normalize_openai_response`.

## 2. Vector store — ChromaDB

`chromadb>=1.5.5` is used in persistent-client mode from `/Users/travismoore/Desktop/JARVIS/friday/memory/store.py`:

```python
self.chroma = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
self.collection = self.chroma.get_or_create_collection(
    name="friday_memories",
    metadata={"hnsw:space": "cosine"},
)
```

Chroma was picked over pgvector (needs Postgres, overkill for a single-user OS), Qdrant (needs a server or container), and FAISS (no metadata filtering). Chroma is embedded, keeps state as files on disk under `data/memory/chroma/`, and scales fine to the six-figure vector range a single user will ever hit.

**Swap notes.** To switch to Qdrant: replace `_init_chroma` in `memory/store.py` with `qdrant_client.QdrantClient(...)`, and rewrite `store()` / `search()` to use Qdrant's `upsert` and `search` methods. Nothing else in the codebase touches Chroma directly — the only public surface is `MemoryStore`.

## 3. Structured storage — SQLite

Standard-library `sqlite3` only. No ORM. The schema lives inline in `memory/store.py`'s `_init_sqlite`:

- `memories` — durable user facts, categorised and tagged.
- `sessions`, `agent_calls` — traces for debugging and reflection.
- `monitors`, `monitor_events`, `briefing_queue` — background watchers + their queued outputs.
- `projects` — GitHub sync cache.
- `cron_jobs`, `heartbeat_state`, `watch_tasks` — scheduling state.

Every row has an `id`/`created_at`. Single DB file at `data/memory/friday.db`. No migrations framework — schema is `CREATE TABLE IF NOT EXISTS`, additive changes only.

## 4. Python runtime — 3.12+ and `uv`

- `requires-python = ">=3.12"` in `pyproject.toml`.
- Dev workflow: `uv sync`, `uv run friday`, `uv tool install friday-os`.
- End users who install via PyPI get the same versions `uv` locks.
- The Mac app ships its own interpreter — see §17.

## 5. Packaging — setuptools + PyPI

- Build backend: `setuptools>=69` (see `[build-system]` in `pyproject.toml`).
- Published as [`friday-os`](https://pypi.org/project/friday-os/) on PyPI, version `0.4.0` at time of writing.
- Console entry point `friday = "friday.cli:run"`.
- Package data bundles `friday/skills/**/*` and `friday/data/**/*.json` so pip-installed users get skills without cloning the repo.

## 6. Web / HTTP

`httpx>=0.28.1` is the primary client — used in `web_tools.py`, `heartbeat.py`, `tts.py`, `whatsapp_tools.py`. Async-native, supports streaming (important for ElevenLabs PCM), HTTP/2 for multiplexed calls. The `tavily-python` SDK wraps its own HTTP for web search; the Twilio, Google, and OpenAI SDKs bring their own clients.

## 7. Browser automation — Playwright

`playwright>=1.58.0` drives Chromium for scripted flows. Key choice: snapshots are built from `page.aria_snapshot()` not CSS, producing `@e5`-style refs that survive layout shuffles. `selenium>=4.41.0` is listed as a dep for historic CV/job workflows but isn't the default; new code should use Playwright.

Safari via AppleScript is the fallback when the user is already signed into a site and we don't want another browser profile — search for `osascript` in `/Users/travismoore/Desktop/JARVIS/friday/tools/browser_tools.py`.

## 8. Voice

### STT — Silero VAD + MLX Whisper
- `/Users/travismoore/Desktop/JARVIS/friday/voice/vad.py` wraps `silero-vad` (loaded via `silero_vad.load_silero_vad()`, runs on PyTorch CPU). 512-sample chunks at 16 kHz, threshold-based speech/silence state machine.
- `/Users/travismoore/Desktop/JARVIS/friday/voice/stt.py` wraps `mlx-whisper>=0.4.0`. Apple Silicon only — uses MLX for GPU-accelerated inference. First call downloads the model; `warmup()` runs 1 second of silence through it at startup.

### TTS cloud — ElevenLabs Flash v2.5
Direct HTTPS streaming POST to `/v1/text-to-speech/{voice_id}/stream`, output format `pcm_24000`. ~75 ms first-byte latency. Chunks are played through `sounddevice>=0.5.1` as they arrive. Default voice "George" (JBFqnCBsd6RMkjVDRZzb), override via `ELEVENLABS_VOICE_ID`.

### TTS local — Kokoro-82M ONNX
`kokoro-onnx>=0.4.0` + `onnxruntime>=1.19.0`. Model pulled from `onnx-community/Kokoro-82M-v1.0-ONNX` on Hugging Face Hub. Fully offline, ~1–2 s per sentence on M4. Includes a monkey-patch in `tts.py` to fix a style-tensor rank mismatch in the upstream library.

**Swap notes.** Auto-switches based on `ELEVENLABS_API_KEY`. To force local, leave it unset. To add a new cloud TTS (e.g. PlayHT), add a branch to the `Speaker` class in `voice/tts.py`.

## 9. Screen / vision

OCR uses `pyobjc-framework-quartz>=10.0` to bridge Apple's `Vision` framework — free, fully offline, and as accurate as Textract for most screen content. Image understanding (what's on screen, explain UI, read errors) goes through Ollama with Qwen2.5-VL as the local model, or any cloud VLM via `cloud_chat` when `USE_CLOUD` is set. Screenshots are written to `~/Downloads/friday_screenshots/` with a 48-hour TTL auto-clean on every capture.

Relevant files:
- `/Users/travismoore/Desktop/JARVIS/friday/tools/screen_tools.py`
- `/Users/travismoore/Desktop/JARVIS/friday/vision/`

## 10. Gesture

`mediapipe>=0.10.0` for hand-landmark detection (21 landmarks per hand, 2 hands max), `opencv-python>=4.8.0` for the capture loop. Purely local, CPU-only, ~30 fps on M-series MacBooks. The built-in 7-gesture classifier is supplemented with landmark-based pinch detection (threshold 0.06 normalised distance between thumb tip and index tip).

Relevant files:
- `/Users/travismoore/Desktop/JARVIS/friday/vision/gesture_engine.py`
- `/Users/travismoore/Desktop/JARVIS/friday/vision/gesture_daemon.py`

## 11. Scheduling

Two systems coexist:

- **`apscheduler>=3.11.2`** — user-defined cron jobs. `AsyncIOScheduler` with `CronTrigger.from_crontab(...)`. State persisted in the `cron_jobs` SQLite table so schedule survives restarts. See `/Users/travismoore/Desktop/JARVIS/friday/background/cron_scheduler.py`.
- **Custom async polling loop** — heartbeat (`friday/background/heartbeat.py`) and watch-task scheduler (`friday/background/monitor_scheduler.py`). These need sub-minute granularity and direct coupling to memory/briefing state, which APScheduler would make awkward.

## 12. PDF

### Read
- `pypdf>=6.9.1` — stream-level operations (extract, split, merge, rotate, encrypt, watermark).
- `pdfplumber>=0.11.9` — text and table extraction with layout.

### Write
- `weasyprint>=63.0` + `jinja2>=3.1.6` — used by the CV tool (`friday/tools/cv_tools.py`) and the deep-research agent to render Jinja-templated HTML to PDF. CSS Paged Media supports page-breaks, headers, footers — harder to do with ReportLab.

## 13. DOCX

`python-docx>=1.2.0` — used for cover letters, research docs, and anything a recruiter might open in Word. Imports are lazy (`from docx import Document as DocxDocument` inside the function) to keep cold-start fast.

## 14. Google APIs

`google-api-python-client>=2.193.0` + `google-auth-oauthlib>=1.3.0` + `google-auth-httplib2>=0.3.0`. Shared auth helper at `/Users/travismoore/Desktop/JARVIS/friday/tools/google_auth.py` caches the OAuth token at `~/.friday/google_token.json`. Covers:

- Gmail — read/search/send, priority-sender flagging.
- Calendar — list events, create, delete.

## 15. Messaging

### iMessage
- **Read:** direct SQLite on `~/Library/Messages/chat.db`. Requires macOS Full Disk Access. Handles the `attributedBody` NSAttributedString binary blob for messages that don't store plain `text`.
- **Send:** `osascript` AppleScript via `subprocess`.
- Path: `/Users/travismoore/Desktop/JARVIS/friday/tools/imessage_tools.py`.

### WhatsApp
- **Bridge:** `@whiskeysockets/baileys ^7.0.0-rc.9` + `express ^5.2.1` + `pino ^10.3.1` + `qrcode-terminal ^0.12.0` in `/Users/travismoore/Desktop/JARVIS/friday/whatsapp/`. Python talks to it over `http://localhost:3100`.
- Auth state lives at `~/.friday/whatsapp/auth_state/` — never committed.
- Python client: `/Users/travismoore/Desktop/JARVIS/friday/tools/whatsapp_tools.py` uses `httpx` to call the bridge.

### SMS
`twilio>=9.10.4`. Outbound via `Client.messages.create(...)`, inbound via the webhook server at `/Users/travismoore/Desktop/JARVIS/friday/sms/server.py`.

### X (Twitter)
`tweepy>=4.16.0` — v2 API client. Handles search, post, read timeline.

## 16. TV control

`pywebostv>=0.8.9` — websocket protocol for LG WebOS TVs. Pairs once, stores a client key, then exposes `SystemControl` / `MediaControl` / `ApplicationControl`. `wakeonlan>=3.1.0` sends the magic packet when the TV is fully off. Config in `/Users/travismoore/Desktop/JARVIS/friday/tools/tv_tools.py`.

## 17. Mac app — SwiftUI + bundled Python

- **UI:** SwiftUI, `NSStatusItem` + `NSPopover` for the menu-bar bolt, a full-window chat with sidebar, native `Cmd+,` settings, 5-step onboarding.
- **IPC:** subprocess + NDJSON line-reader (`FridayClient.swift`). Shells out to `uv run python -u -m friday.core.oneshot_runner …` in dev, or to the bundled Python in release.
- **Bundled runtime:** [python-build-standalone](https://github.com/indygreg/python-build-standalone) 3.12.7, macOS arm64, `install_only` variant. Downloaded once, cached under `build/`, copied into `Friday.app/Contents/Resources/python/`. Users don't need Python, `uv`, or the repo.
- **Deliberately not bundled in v1** (kept slim): `mediapipe`, `opencv-python`, `playwright`, `selenium`, `mlx-whisper`, `kokoro-onnx`, `sounddevice`, `onnxruntime`. Users install separately for those features.
- **Build script:** `/Users/travismoore/Desktop/JARVIS/Friday-mac/build_bundle.sh`.

## 18. Dev tooling

- `rich>=14.3.3` — coloured terminal output, rules, tables, markdown rendering in REPL.
- `prompt-toolkit>=3.0.52` — REPL with file-backed history and auto-suggest.
- `python-dotenv>=1.2.2` — layered env loading (`friday_defaults.env` inside the .app, then `~/.friday/.env`, then repo `.env`, earlier wins).

---

## Caveats on the dep list

A few lines in `pyproject.toml` are load-bearing only partially:

- `selenium>=4.41.0` — listed but Playwright is the default browser driver. Kept for legacy job-application flows.
- `shellingham` — not currently in `pyproject.toml` despite an earlier plan; if terminal-detection lands, it will go here.
- `numpy>=1.26.0` — indirect via MLX, OpenCV, MediaPipe, Kokoro; pinned here to avoid resolution drift.
- `fal-client>=0.13.2` — only used for hosted video / heavy-model inference; safe to remove if you don't use it.
