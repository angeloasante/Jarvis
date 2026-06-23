# Location Spoofer

Spoof your iPhone's GPS location from your Mac over USB. Affects **everything** system-wide — Find My, WhatsApp, Maps, Weather, all of it.

Uses Apple's own `com.apple.dt.simulatelocation` protocol (the same one Xcode uses internally). No jailbreak needed.

## Requirements

- **macOS** with USB cable connected to iPhone
- **iPhone** with **Developer Mode** enabled (Settings > Privacy & Security > Developer Mode)
- **Python 3.10+**
- **Xcode** (required for iOS 17+/26)
- **pymobiledevice3** (optional, for automatic spoofing on iOS 16 and earlier)

## iOS Version Compatibility

| iOS Version | Method | Automatic? |
|-------------|--------|------------|
| iOS 16 and earlier | pymobiledevice3 (direct USB) | Yes |
| iOS 17+ / 26 | Xcode GUI (Debug > Simulate Location) | No — manual steps |

**Why iOS 17+ requires manual steps:** Apple moved the simulatelocation service behind encrypted RemoteXPC tunnels using PSK SSL ciphers. No open-source tool (pymobiledevice3, libimobiledevice) currently supports this. Apple's `xcrun devicectl` does NOT have a location simulation subcommand — it was never added.

## Setup

```bash
# (Optional) Install pymobiledevice3 for iOS 16 automatic support
pip install pymobiledevice3

# Enable Developer Mode on iPhone (if not already)
# Settings > Privacy & Security > Developer Mode > ON > Reboot > Confirm

# For pymobiledevice3 only: Mount the Developer Disk Image (required once per boot)
sudo pymobiledevice3 mounter auto-mount
```

## Usage

```bash
# Spoof to a preset location
python spoof.py --preset london
python spoof.py --preset kumasi

# Spoof to custom coordinates
python spoof.py --lat 48.8566 --lon 2.3522

# Reset to real location
python spoof.py --reset

# Interactive mode — pick from presets or enter custom coords
python spoof.py

# Just generate GPX file (skip automatic methods)
python spoof.py --preset paris --gpx-only

# Keep spoofing (re-sends every N seconds, iOS 16 only)
python spoof.py --lat 48.8566 --lon 2.3522 --hold 10

# List all preset locations
python spoof.py --list
```

## How It Works

### Method 1: `pymobiledevice3` (iOS 16 and earlier)
- Direct USB connection via `com.apple.dt.simulatelocation`
- Fully automatic — just run the script
- Fails on iOS 17+ due to encrypted tunnel restrictions

### Method 2: Xcode GUI (iOS 17+ / all versions)
- Script generates a GPX file with your coordinates
- You apply it via Xcode's Debug > Simulate Location > Custom Location
- Requires running any app on your device in a debug session first
- Works on **all** iOS versions but requires manual steps

The script tries Method 1 first and falls back to Method 2 automatically.

## Limitations

- **Requires USB connection** — location resets if you unplug
- **Resets on reboot** — not persistent across restarts
- **Developer Mode must be on** — visible in Settings
- **iOS 17+**: No automated solution exists — Xcode GUI is the only option
- WiFi toggling can sometimes trigger GPS recalibration
- `isSimulatedBySoftware` API exists (iOS 15+) — apps *can* detect it, but most don't check
- **Xcode method**: Location only stays spoofed while a debug session is active
