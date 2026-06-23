#!/usr/bin/env python3
"""iPhone Location Spoofer — set fake GPS system-wide.

This script tries two methods in order:
  1. pymobiledevice3 (iOS 16 and earlier) — direct USB, fully automatic
  2. Xcode GUI (iOS 17+/26) — generates GPX + instructions

iOS 17+ locked the simulatelocation service behind encrypted RemoteXPC
tunnels using PSK SSL ciphers. No open-source tool currently supports this.
Apple's `xcrun devicectl` does NOT have a location simulation subcommand.

For iOS 17+ the only working method is Xcode's Debug > Simulate Location
menu during an active debug session on your device.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile

# ── Preset locations ─────────────────────────────────────────────────────────

PRESETS = {
    "paris":     (48.8566,  2.3522,  "Paris, France"),
    "new_york":  (40.7128, -74.0060, "New York, USA"),
    "london":    (51.5074, -0.1278,  "London, UK"),
    "tokyo":     (35.6762, 139.6503, "Tokyo, Japan"),
    "dubai":     (25.2048,  55.2708, "Dubai, UAE"),
    "kumasi":    (6.6745,  -1.5716,  "Kumasi, Ghana"),
    "accra":     (5.6037,  -0.1870,  "Accra, Ghana"),
    "lagos":     (6.5244,   3.3792,  "Lagos, Nigeria"),
    "la":        (34.0522, -118.2437,"Los Angeles, USA"),
    "sf":        (37.7749, -122.4194,"San Francisco, USA"),
    "miami":     (25.7617, -80.1918, "Miami, USA"),
    "toronto":   (43.6532, -79.3832, "Toronto, Canada"),
    "berlin":    (52.5200,  13.4050, "Berlin, Germany"),
    "sydney":    (-33.8688, 151.2093,"Sydney, Australia"),
    "singapore": (1.3521,  103.8198, "Singapore"),
    "nairobi":   (-1.2921,  36.8219, "Nairobi, Kenya"),
}


# ── GPX generation ───────────────────────────────────────────────────────────

def make_gpx(lat: float, lon: float, name: str = "Spoofed") -> str:
    """Generate a GPX file for a single location."""
    return f"""<?xml version="1.0"?>
<gpx version="1.1" creator="FRIDAY Location Spoofer">
  <wpt lat="{lat}" lon="{lon}">
    <name>{name}</name>
  </wpt>
</gpx>"""


def write_gpx(lat: float, lon: float, name: str = "Spoofed") -> str:
    """Write GPX to temp file, return path."""
    gpx = make_gpx(lat, lon, name)
    path = os.path.join(tempfile.gettempdir(), "friday_spoof_location.gpx")
    with open(path, "w") as f:
        f.write(gpx)
    return path


# ── Method 1: pymobiledevice3 (iOS 16 and earlier) ──────────────────────────

async def try_pymobiledevice3(lat: float, lon: float, hold: int = 0):
    """Try pymobiledevice3 direct USB (works on iOS 16 and earlier only).

    iOS 17+ will fail with InvalidServiceError because Apple moved the
    simulatelocation service behind encrypted tunnels that require PSK
    SSL ciphers not supported by Python's ssl module.
    """
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.simulate_location import DtSimulateLocation

        lockdown = await create_using_usbmux()
        ios_ver = lockdown.product_version
        print(f"  Connected to {lockdown.display_name} ({lockdown.product_type}, iOS {ios_ver})")

        # Warn if iOS 17+
        major = int(ios_ver.split(".")[0]) if ios_ver else 0
        if major >= 17:
            print(f"  ⚠️  iOS {ios_ver} detected — direct USB spoofing likely blocked")

        svc = DtSimulateLocation(lockdown=lockdown)
        await svc.connect()
        await svc.set(lat, lon)
        print(f"  ✅ Location set to: {lat}, {lon}")

        if hold > 0:
            try:
                while True:
                    await asyncio.sleep(hold)
                    await svc.set(lat, lon)
                    print(f"  🔄 Location refreshed: {lat}, {lon}")
            except (KeyboardInterrupt, asyncio.CancelledError):
                await svc.clear()
        else:
            input("  Press Enter to reset...")
            await svc.clear()
        await svc.close()
        return True
    except Exception as e:
        print(f"  ❌ pymobiledevice3 failed: {e}")
        return False


# ── Method 2: Xcode GUI (works on all iOS versions) ─────────────────────────

def spoof_via_xcode(lat: float, lon: float, name: str = "Spoofed"):
    """Create GPX and show Xcode instructions.

    This is the ONLY reliable method for iOS 17+/26. Xcode applies the
    GPX location to any connected device during a debug session.
    """
    gpx_path = write_gpx(lat, lon, name)

    # Save a persistent GPX to the spoofer directory too
    local_gpx = os.path.join(os.path.dirname(__file__), "current_location.gpx")
    with open(local_gpx, "w") as f:
        f.write(make_gpx(lat, lon, name))

    print(f"  📍 GPX file created: {gpx_path}")
    print(f"  Location: {lat}, {lon} ({name})")
    print()
    print("  ━━━ Xcode Setup (one-time) ━━━")
    print()
    print("  1. Open Xcode")
    print("  2. Create or open any iOS project")
    print("     (File > New > Project > iOS > App — name it anything)")
    print("  3. Select your iPhone as the run destination")
    print("  4. Hit ▶ Run to deploy the app to your phone")
    print()
    print("  ━━━ Spoof Location ━━━")
    print()
    print("  5. With the app running on your phone:")
    print("     Debug > Simulate Location > Custom Location...")
    print(f"  6. Enter:  Latitude: {lat}   Longitude: {lon}")
    print()
    print("  ━━━ Reset ━━━")
    print()
    print("  • Debug > Simulate Location > Don't Simulate Location")
    print("  • Or just stop the debug session / reboot phone")
    print()
    print("  💡 The spoofed location affects EVERYTHING system-wide")
    print("     (Find My, Maps, WhatsApp, Weather, etc.)")
    print("     as long as the debug session is active.")
    print()
    print(f"  💡 GPX also saved to: {local_gpx}")
    print("     You can drag this into Xcode's project navigator")
    print("     and select it from Debug > Simulate Location directly.")
    print()

    return gpx_path


# ── Main spoof logic ─────────────────────────────────────────────────────────

async def set_location(lat: float, lon: float, name: str = "Spoofed", hold: int = 0):
    """Try pymobiledevice3 first, fall back to Xcode GUI instructions."""

    print(f"\n  🎯 Target: {name} ({lat}, {lon})")
    print()

    # Method 1: Try pymobiledevice3 (iOS 16 and earlier)
    print("  [1/2] Trying pymobiledevice3 (direct USB)...")
    if await try_pymobiledevice3(lat, lon, hold):
        return

    print()

    # Method 2: Xcode GUI (always works, requires manual steps)
    print("  [2/2] Falling back to Xcode method (iOS 17+ requires this)...")
    print()
    spoof_via_xcode(lat, lon, name)


async def reset_location():
    """Reset location."""

    # Try pymobiledevice3 first
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.simulate_location import DtSimulateLocation

        lockdown = await create_using_usbmux()
        svc = DtSimulateLocation(lockdown=lockdown)
        await svc.connect()
        await svc.clear()
        await svc.close()
        print("  ✅ Location reset via pymobiledevice3.")
        return
    except Exception:
        pass

    # Manual fallback
    print("  ⚠️  Automatic reset not available on iOS 17+.")
    print()
    print("  To reset location:")
    print("    • Xcode > Debug > Simulate Location > Don't Simulate Location")
    print("    • Or stop the Xcode debug session")
    print("    • Or reboot your iPhone")


# ── Interactive mode ─────────────────────────────────────────────────────────

async def interactive():
    """Pick a preset or enter custom coordinates."""
    print("\n  Location Spoofer — Interactive Mode")
    print("  " + "=" * 40)
    print()

    sorted_presets = sorted(PRESETS.items(), key=lambda x: x[1][2])
    for i, (key, (lat, lon, name)) in enumerate(sorted_presets, 1):
        print(f"  {i:2d}. {name:<25s} ({lat:.4f}, {lon:.4f})")

    print(f"\n  {len(sorted_presets)+1:2d}. Custom coordinates")
    print(f"  {len(sorted_presets)+2:2d}. Reset to real location")
    print()

    try:
        choice = input("  Pick a number: ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return

    try:
        idx = int(choice)
    except ValueError:
        if choice.lower() in PRESETS:
            lat, lon, name = PRESETS[choice.lower()]
            print(f"\n  Spoofing to {name}...")
            await set_location(lat, lon, name)
            return
        print("  Invalid choice.")
        return

    if 1 <= idx <= len(sorted_presets):
        lat, lon, name = sorted_presets[idx - 1][1]
        print(f"\n  Spoofing to {name}...")
        await set_location(lat, lon, name)
    elif idx == len(sorted_presets) + 1:
        try:
            lat = float(input("  Latitude: ").strip())
            lon = float(input("  Longitude: ").strip())
        except (ValueError, KeyboardInterrupt, EOFError):
            print("  Invalid coordinates.")
            return
        print(f"\n  Spoofing to {lat}, {lon}...")
        await set_location(lat, lon)
    elif idx == len(sorted_presets) + 2:
        await reset_location()
    else:
        print("  Invalid choice.")


# ── CLI ──────────────────────────────────────────────────────────────────────

async def async_main():
    parser = argparse.ArgumentParser(
        description="Spoof iPhone GPS location from Mac.",
        epilog="Examples:\n"
               "  python spoof.py --preset london\n"
               "  python spoof.py --lat 48.8566 --lon 2.3522\n"
               "  python spoof.py --reset\n"
               "  python spoof.py                    # Interactive\n"
               "\n"
               "Note: iOS 17+ requires Xcode for location simulation.\n"
               "pymobiledevice3 works automatically on iOS 16 and earlier.\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--lat", type=float, help="Latitude")
    parser.add_argument("--lon", type=float, help="Longitude")
    parser.add_argument("--preset", type=str, choices=list(PRESETS.keys()),
                        help="Use a preset location")
    parser.add_argument("--reset", action="store_true", help="Reset to real GPS")
    parser.add_argument("--hold", type=int, default=0,
                        help="Re-send location every N seconds")
    parser.add_argument("--list", action="store_true", help="List all presets")
    parser.add_argument("--gpx-only", action="store_true",
                        help="Just generate the GPX file, don't try to apply")

    args = parser.parse_args()

    if args.list:
        print("\n  Available presets:")
        for key, (lat, lon, name) in sorted(PRESETS.items(), key=lambda x: x[1][2]):
            print(f"    {key:<12s} {name:<25s} ({lat:.4f}, {lon:.4f})")
        return

    if args.reset:
        await reset_location()
    elif args.preset:
        lat, lon, name = PRESETS[args.preset]
        print(f"  Spoofing to {name}...")
        if args.gpx_only:
            spoof_via_xcode(lat, lon, name)
        else:
            await set_location(lat, lon, name, hold=args.hold)
    elif args.lat is not None and args.lon is not None:
        if args.gpx_only:
            spoof_via_xcode(args.lat, args.lon)
        else:
            await set_location(args.lat, args.lon, hold=args.hold)
    elif args.lat is not None or args.lon is not None:
        print("Error: Need both --lat and --lon")
        sys.exit(1)
    else:
        await interactive()


if __name__ == "__main__":
    asyncio.run(async_main())
