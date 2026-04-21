# FRIDAY macOS App

SwiftUI menu bar app that drives the FRIDAY AI OS.

## Setup in Xcode

1. **Open Xcode** → File → New → Project
2. Pick **macOS → App**
3. Settings:
   - Product Name: `Friday`
   - Team: your Apple ID (free is fine for local dev)
   - Organization Identifier: `com.travis.friday` (or whatever)
   - Interface: **SwiftUI**
   - Language: **Swift**
   - Uncheck "Use Core Data" and "Include Tests"
4. Save location: **`/Users/travismoore/Desktop/JARVIS/Friday-mac`** (this folder)
5. Xcode creates `Friday.xcodeproj` and a starter `FridayApp.swift`
6. **Replace Xcode's default files with the ones already in this folder:**
   - Drag `FridayApp.swift`, `MenuBarContent.swift`, `FridayClient.swift`, `SettingsView.swift` into the project navigator
   - Let Xcode overwrite the default `FridayApp.swift` and `ContentView.swift` (delete ContentView.swift if it's not used)
7. **Info.plist settings** (Project → Friday target → Info tab):
   - Add key `LSUIElement` → Boolean → `YES` (hides dock icon — this is a menu bar app)
   - Add key `NSAppleEventsUsageDescription` → String → "FRIDAY needs to control other apps on your behalf."
8. Press **⌘R** to run

## What You Should See

- A green lightning bolt icon in your menu bar
- Click it → command bar pops up
- Type "yo" → press Enter → FRIDAY responds via shelling out to `uv run`

## Current Architecture

```
SwiftUI App
    │
    │  Process.run("uv run python -m friday.core.oneshot_runner")
    │
    ▼
FridayCore (Python, from ~/Desktop/JARVIS)
```

The shell-out is temporary. Next step: local WebSocket server in FridayCore, Swift client connects via URLSession/Starscream.

## Files

- `FridayApp.swift` — app entry point, MenuBarExtra scene
- `MenuBarContent.swift` — the UI that appears on menu bar click
- `FridayClient.swift` — bridge to FridayCore (Python shell-out for now)
- `SettingsView.swift` — preferences window (repo path, account connections)

## Next Steps (in order)

1. Get the app building and running — test the shell-out with a simple command
2. Create `friday/core/oneshot_runner.py` in the Python repo — reads stdin, runs `FridayCore.process()`, prints result
3. Replace shell-out with WebSocket server on port 18789
4. Add streaming responses (tokens appear live as they arrive)
5. Add global hotkey (Cmd+Shift+F) via `HotKey` package
6. Add native notifications via `UserNotifications` framework
7. Package Python runtime inside the app bundle (PyInstaller or embedded framework)
