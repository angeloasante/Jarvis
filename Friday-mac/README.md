# FRIDAY macOS App

Native SwiftUI app that wraps FridayCore. Menu-bar bolt, full-window chat with sidebar, streaming token-by-token responses, Gmail OAuth onboarding, and a bundled Python 3.12 runtime so end users don't need `uv` or the repo.

Full architecture, menu-bar integration, NDJSON protocol, onboarding and reset procedure, and build pipeline are documented in **[docs/mac-app.md](../docs/mac-app.md)**. Product vision and iOS plan are in **[docs/app-spec.md](../docs/app-spec.md)**.

---

## Developing against the repo

1. `open Friday/Friday.xcodeproj`
2. ⌘R with the Debug scheme — the app shells out to `uv run python -u -m friday.core.oneshot_runner …` in `~/Desktop/JARVIS`. If your repo lives somewhere else, set the `fridayRepoPath` key in `UserDefaults` or drop a symlink at `~/Desktop/JARVIS`.
3. Per-user secrets (LLM keys, Twilio, Gmail) are entered in the app's onboarding or Settings and persisted in Keychain — no `.env` edits required while iterating.

Xcode project settings that matter:

- **Info tab** → `NSAppleEventsUsageDescription` — "FRIDAY needs to control other apps on your behalf."
- **Entitlements** → `com.apple.security.files.user-selected.read-only`, `com.apple.security.get-task-allow`. The app is currently **not** fully sandboxed — UserDefaults land at `~/Library/Preferences/com.travis.Friday.plist`.
- **Signing** → your personal team is fine for local dev; the bundled Python binary isn't re-signed, so don't enable Hardened Runtime for Debug.

## Building a self-contained `.app`

```bash
./build_bundle.sh            # Debug
./build_bundle.sh release    # Release
```

The script downloads python-build-standalone 3.12 (once, cached under `build/`), installs FridayCore + its runtime deps into that interpreter, prunes test suites / `__pycache__`, and copies the result into `Friday.app/Contents/Resources/python/`. It then writes `Resources/friday_defaults.env` with the shared FRIDAY-team Tavily key so end users get web search out of the box.

Bundle sanity check runs at the end — imports `friday` from inside the `.app`, asserts the path is under `Resources/python/` (not the repo), and imports `friday.core.oneshot_runner.run_stream`.

### Deliberately NOT bundled (v1)

To keep the bundle slim, these heavy deps aren't shipped — users can install separately if they want the capability:

- `mediapipe`, `opencv-python` — gesture control (Swift + CoreML port coming)
- `playwright`, `selenium` — browser automation (Safari AppleScript fallback works for most flows)
- `mlx-whisper`, `kokoro-onnx`, `sounddevice`, `onnxruntime` — voice pipeline

Everything else ships: LLM routing + agents, email / calendar, iMessage / WhatsApp / SMS, TV control, X, research, memory, docx generation.

## Source layout

```
Friday-mac/
├── Friday/Friday/
│   ├── FridayApp.swift            @main, NSStatusItem + NSPopover
│   ├── FridayClient.swift         subprocess + NDJSON line-reader
│   ├── MenuBarContent.swift       popover chat UI
│   ├── SettingsView.swift         native Cmd+, preferences
│   ├── Commands.swift             slash + NL command matching
│   ├── MediaPreview.swift         docx / pdf / image previews in chat
│   ├── MainWindow/                full-window chat + settings panes
│   ├── Onboarding/                5-step flow
│   ├── Services/                  ChatStore, OnboardingState, GmailAuth, WhatsAppBridge
│   └── Components/                logo + brand icons
└── build_bundle.sh                Python bundling pipeline
```

## Resetting the app to a clean state

`defaults delete` alone races with `cfprefsd`'s cache. Reliable reset:

```bash
pkill -9 -f "Friday.app"
rm -f  ~/Library/Preferences/com.travis.Friday.plist
rm -rf ~/Library/Containers/com.travis.Friday
rm -rf "$HOME/Library/Application Support/Friday"
rm -f  ~/.friday/google_token.json
killall -u "$(whoami)" cfprefsd
open /Applications/Friday.app
```

After that, next launch shows onboarding from step 1.
