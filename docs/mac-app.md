# FRIDAY macOS App

The native SwiftUI app that wraps FridayCore. It's **not** a browser window pointing at a server — it's a real macOS app with a menu-bar popover, a full-window chat, settings, onboarding, and a bundled Python runtime. No `uv`, no repo, no terminal required once shipped.

This doc covers the whole app: architecture, menu-bar integration, streaming bridge, onboarding, persistence, and build pipeline. For the product vision (wow moments, feature roadmap) see [app-spec.md](app-spec.md).

---

## At a glance

```
┌───────────────────────────────────────────────────────────────┐
│  Menu bar  ▸  ⚡  (NSStatusItem, always present)             │
│                │                                              │
│                ▼  click → NSPopover (MenuBarContent.swift)    │
│  ┌──────────────────────────────┐                             │
│  │ Gemma 4 ▾       □  ⤢         │  ← model picker + controls │
│  │ ──────────────────────────── │                             │
│  │ FRIDAY     just now          │                             │
│  │ On it. Keep chatting …       │  ← streamed token-by-token │
│  │ ──────────────────────────── │                             │
│  │ ⌘  [ ask FRIDAY …      ]  ↑ │  ← ⌘ opens command palette │
│  └──────────────────────────────┘                             │
│                                                               │
│  Main window ▸  ⌘N / click dock icon                          │
│  ┌──────────┬────────────────────────────────────────────────┐│
│  │ FRIDAY   │  top bar: model picker · new chat · export    ││
│  │ + new    │  ──────────────────────────────────────────── ││
│  │ ⚙ Sett.  │   user bubble                                 ││
│  │          │   FRIDAY ● (streaming dots while working)      ││
│  │ chat 1   │   …assistant reply with media previews…       ││
│  │ chat 2   │  ──────────────────────────────────────────── ││
│  │ …        │   ⌘  [ reply …                         ]  ↑   ││
│  │──────────│                                                ││
│  │ 👤 Name  │  ← signed-in Gmail profile (or Sign in CTA)    ││
│  │ addr…    │                                                ││
│  └──────────┴────────────────────────────────────────────────┘│
│                                                               │
│  ↓  every chat turn shells out to                             │
│                                                               │
│  Resources/python/bin/python3  -u  -m  friday.core.oneshot_runner  "<input>"
│                                                               │
│       emits NDJSON events on stdout, one per line:            │
│       {"event":"chunk","text":"On "}                          │
│       {"event":"chunk","text":"it."}                          │
│       {"event":"media","path":"/Users/…/report.docx"}         │
│       {"event":"done"}                                        │
└───────────────────────────────────────────────────────────────┘
```

Everything the CLI can do, the app can do, because the app **is** the CLI — same `friday.*` modules, same agents, same memory, same skills. The Swift layer is a thin UI + bridge.

---

## Architecture

### Processes

| Process | Code | Lifetime | Purpose |
|---|---|---|---|
| `Friday.app` | Swift + AppKit + SwiftUI | While UI is open | Menu bar, windows, onboarding, chat state |
| `python3 -m friday.core.oneshot_runner` | Python (bundled) | Per chat turn | One request → streamed NDJSON → exit |
| WhatsApp bridge (optional) | Node / Baileys | Background daemon | QR pairing + message relay |

There's no long-lived backend server. Every message spawns a fresh Python process, which keeps memory pressure low on the Mac and makes crashes isolated — one bad turn can't kill your chat history.

### Swift side (source tree)

```
Friday-mac/Friday/Friday/
├── FridayApp.swift            — @main, NSApplicationDelegate, status item, popover
├── FridayClient.swift         — subprocess spawner + NDJSON line-reader
├── MenuBarContent.swift       — popover UI (chat card, 380pt wide)
├── SettingsView.swift         — native Cmd+, preferences window
├── Commands.swift             — slash commands + natural-language matching
├── MediaPreview.swift         — renders docx / pdf / image paths in chat
├── MainWindow/
│   ├── MainWindowView.swift   — chat-first window (sidebar ↔ settings modes)
│   ├── ChatView.swift         — full-window chat (same logic as popover)
│   ├── HomeView.swift         — settings landing pane
│   └── IntegrationsView.swift — per-service cards (Gmail, Twilio, X, TV…)
├── Onboarding/
│   └── OnboardingView.swift   — 5 steps: welcome → LLM → Gmail → WhatsApp → done
├── Services/
│   ├── OnboardingState.swift  — UserDefaults + Keychain source of truth
│   ├── ChatStore.swift        — in-memory chats + ~/Library/Application Support/Friday/chats.json
│   ├── GmailAuth.swift        — drives friday/tools/google_auth.py, parses AUTHENTICATED line
│   └── WhatsAppBridge.swift   — polls local Baileys HTTP bridge for QR / status
└── Components/
    ├── AsyncBrandLogo.swift
    └── BrandIcon.swift
```

### Python side (hit from the app)

Only the standard repo — the app doesn't fork the code, it just calls into it:

- `friday/core/oneshot_runner.py` — the single entry point the app invokes
- `friday/core/config.py` — layered `.env` loader (bundle → `~/.friday/.env` → repo `.env`)
- `friday/tools/google_auth.py` — writes token to `~/.friday/google_token.json`, emits `AUTHENTICATED: {email}|{name}` on success
- Everything else is unchanged from the CLI

---

## Menu bar integration

The menu bar is an `NSStatusItem` with a tinted `bolt.fill` symbol. We deliberately **don't** use SwiftUI's `MenuBarExtra` — it dismisses the popover on focus loss, which destroys the text field mid-typing. `NSPopover` with `.transient` behavior gives us "close on click outside the app, stay open while typing."

### Life cycle ([FridayApp.swift](../Friday-mac/Friday/Friday/FridayApp.swift))

```swift
NSApp.setActivationPolicy(.regular)          // dock icon + menu bar + main window
statusItem = NSStatusBar.system.statusItem(withLength: .variableLength)
statusItem.button?.image = bolt.tinted(.systemGreen)
statusItem.button?.action = #selector(togglePopover(_:))

popover = NSPopover()
popover.behavior = .transient
popover.contentViewController = NSHostingController(rootView: MenuBarContent())
```

Clicking the bolt toggles the popover and activates the app so the text field can actually receive keystrokes. A global `NSEvent.addGlobalMonitorForEvents` catches clicks outside the popover and closes it.

### Popover UI ([MenuBarContent.swift](../Friday-mac/Friday/Friday/MenuBarContent.swift))

- 380pt wide, min 220pt tall, grows to a max of 360pt for scrolling chat.
- Dark glass background (NSPopover vibrancy + gradient overlay).
- Top bar: model picker pill + clear/expand buttons.
- Empty state: gradient orb + "Ask anything."
- Chat area: user bubbles (right-aligned pills), FRIDAY responses with the rainbow avatar + relative timestamp + inline `MediaPreview`s.
- Input bar: `⌘` button → command palette, text field, circular send button.

### Slash and natural-language commands

`Commands.swift` matches either `/clear`, `/quit`, `/voice`, `/gestures` style slashes **or** phrases like "clear the chat". Matches are handled locally by `CommandExecutor` without hitting Python. Unmatched input falls through to the streaming pipeline.

---

## Main window (chat-first)

Opened on launch (the app is `.regular`, so there's always a dock icon + window). [MainWindowView.swift](../Friday-mac/Friday/Friday/MainWindow/MainWindowView.swift) renders either `OnboardingView` (first run) or a `NavigationSplitView`:

- **Sidebar — chats mode**: `FRIDAY` wordmark, `+ New chat` (⌘N), `⚙ Settings`, scrollable chat list, signed-in profile footer (Gmail name + email; falls back to a "Sign in" CTA that triggers Gmail OAuth).
- **Sidebar — settings mode**: back arrow, Home / Integrations / Allowed Apps / Accounts.
- **Detail**: `ChatView(chatID:)` or the active settings pane.

The titlebar is hidden (`.windowStyle(.hiddenTitleBar)`) and the toolbar commands are removed — traffic lights float over the sidebar, and `.padding(.top, 40)` on the header clears them.

### Streaming chat

[ChatView.swift](../Friday-mac/Friday/Friday/MainWindow/ChatView.swift) appends an empty assistant turn the moment the user hits send, then grows it as chunks arrive:

```swift
append(ChatTurn(role: .assistant, text: ""))
Task {
    await FridayClient.shared.sendStreaming(input) { event in
        switch event {
        case .chunk(let s): store.appendChunkToLastTurn(s, in: id)
        case .media(let p): store.appendMediaToLastTurn(p, in: id)
        case .done:         isProcessing = false; store.flush()
        ...
        }
    }
}
```

`ChatStore` ([ChatStore.swift](../Friday-mac/Friday/Friday/Services/ChatStore.swift)) batches chunk updates in memory and only writes `~/Library/Application Support/Friday/chats.json` at `.done` — no write storm per token.

---

## Swift ↔ Python bridge

[FridayClient.swift](../Friday-mac/Friday/Friday/FridayClient.swift) handles the subprocess + stdout reader.

### What it runs

If the app bundle has a Python at `Resources/python/bin/python3` (shipped builds):

```bash
Resources/python/bin/python3 -u -m friday.core.oneshot_runner "<input>"
```

If not (Xcode Debug against the repo):

```bash
/bin/zsh -lc "uv run python -u -m friday.core.oneshot_runner '<input>'"
  (cwd = fridayRepoPath, default /Users/$USER/Desktop/JARVIS)
```

### Environment injection

`OnboardingState.subprocessEnvironment()` layers the user's GUI-entered keys on top of the process env before spawning:

```
OPENROUTER_API_KEY / GROQ_API_KEY / GOOGLE_API_KEY   (from Keychain)
TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_PHONE_NUMBER
X_BEARER_TOKEN, TAVILY_API_KEY
LG_TV_HOST (if paired), FRIDAY_ALLOWED_APPS (comma-separated)
PYTHONUNBUFFERED=1       ← force line-flushed stdout
```

Keys managed by the FRIDAY team (Tavily today) ship inside the bundle as `Resources/friday_defaults.env`, so users don't see "TAVILY_API_KEY not set" for built-in capabilities. See [`friday/core/config.py`](../friday/core/config.py) `_load_layered_env`.

### NDJSON protocol

`oneshot_runner.py` emits one JSON object per line:

| Event | Payload | Consumer |
|---|---|---|
| `chunk` | `{"text": "…"}` | `store.appendChunkToLastTurn` |
| `media` | `{"path": "/Users/…/file.docx"}` | `MediaPreview` |
| `status` | `{"text": "checking calendar…"}` | reserved for future progress chips |
| `error` | `{"text": "…"}` | inserts `_Error: …_` into the chat |
| `done`  | —                             | marks turn complete, flushes store |

The Swift reader accumulates bytes in a `Data` buffer, slices on `0x0A` newlines, parses each line via `FridayEvent.parse`, and dispatches to the `@MainActor` handler. If the process exits without a `done`, the reader synthesizes one.

---

## Onboarding

Lives in [OnboardingView.swift](../Friday-mac/Friday/Friday/Onboarding/OnboardingView.swift). 5 steps, progress bar at top, back button where appropriate:

1. **Welcome** — FRIDAY pitch + "Get started"
2. **Choose your AI** — OpenRouter / Groq / Google AI / Ollama. Enters a `SecureField` for BYOK, optional "Test connection."
3. **Connect Gmail** — triggers `GmailAuth.connect()` which runs `friday/tools/google_auth.py`. On success Python prints `AUTHENTICATED: <email>|<name>` (via the `userinfo.profile` scope), parsed by Swift into `GmailProfile`.
4. **WhatsApp** — polls the local Baileys bridge; renders the QR image in-app; flips to ✅ when the bridge reports `connected`. Skippable.
5. **Ready** — "Open FRIDAY" → flips `hasCompletedOnboarding = true`.

### State persistence ([OnboardingState.swift](../Friday-mac/Friday/Friday/Services/OnboardingState.swift))

- **Flags + emails + app allowlist** → `UserDefaults.standard` (the plist at `~/Library/Preferences/com.travis.Friday.plist` if the app isn't sandboxed, or `~/Library/Containers/com.travis.Friday/Data/Library/Preferences/…` if it is).
- **Secrets** (LLM keys, Twilio, X bearer, Tavily user key) → Keychain via `SecItem*`, service `com.travis.Friday`, account = the storage key.
- **OAuth tokens** → `~/.friday/google_token.json`, written by Python.

### Full reset

`defaults delete` on its own can race with `cfprefsd`'s cache (the daemon can flush stale state back). The reliable incantation:

```bash
pkill -9 -f "Friday.app"                         # fully terminate the app
rm -f  ~/Library/Preferences/com.travis.Friday.plist
rm -rf ~/Library/Containers/com.travis.Friday
rm -rf "$HOME/Library/Application Support/Friday"
rm -f  ~/.friday/google_token.json
killall -u "$(whoami)" cfprefsd                   # flush the defaults cache
open /Applications/Friday.app
```

---

## Build pipeline

[Friday-mac/build_bundle.sh](../Friday-mac/build_bundle.sh) does the heavy lifting: downloads python-build-standalone 3.12, installs FridayCore + deps into that runtime, prunes tests and `__pycache__`, copies the whole thing into `Friday.app/Contents/Resources/python`, and writes `friday_defaults.env` with the FRIDAY-team Tavily key.

```bash
./build_bundle.sh            # Debug build
./build_bundle.sh release    # Release build
```

Post-build it does a sanity check — runs the *bundled* Python and asserts `friday.__file__` lives under `Resources/python/`, not the repo, and imports `friday.core.oneshot_runner.run_stream`.

Heavy deps are deliberately excluded from v1 to keep the bundle slim:
- `mediapipe` / `opencv-python` — gestures (Swift+CoreML port coming)
- `playwright` / `selenium` — browser (Safari AppleScript fallback works)
- `mlx-whisper` / `kokoro-onnx` / `sounddevice` / `onnxruntime` — voice

What **is** bundled: LLM routing, agents, email/calendar, iMessage/WhatsApp, SMS, TV control, X, research, memory, docx generation.

---

## Testing the app end-to-end

1. `open Friday-mac/Friday/Friday.xcodeproj`, ⌘R against the Debug scheme — this runs against the repo via `uv run`.
2. `./build_bundle.sh` once the Swift build has succeeded to produce a fully self-contained `.app`.
3. Verify the popover opens, the main window shows onboarding on first launch, Gmail OAuth returns a real name, a command streams token-by-token, and media previews render.

Known nonobvious behavior, not bugs:

- The popover only receives keystrokes once `NSApp.activate(ignoringOtherApps: true)` runs — that's already wired into `togglePopover`.
- The first launch after a build can be slow (Python cold cache + chroma init); second launches are fast.
- If the Debug build can't find `uv` or the repo, set `UserDefaults` key `fridayRepoPath` or drop a symlink at `~/Desktop/JARVIS`.

---

*See also: [app-spec.md](app-spec.md) for the product vision and wow moments, [progress.md](progress.md) for the build log, [gesture-control.md](gesture-control.md) and [sms-setup.md](sms-setup.md) for individual capability deep-dives.*
