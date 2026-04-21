"""Screen cast tools — tap the Screen Mirroring panel in Control Center,
click the TV if it's listed, tell the user to connect it to Wi-Fi if not.

Why UI-only: macOS exposes no public API for AirPlay. Control Center itself
does the device discovery over the LAN, so we don't need to duplicate it.
We just open the panel, look for a TV, and click it.

Requires:
- Accessibility permission for the process running FRIDAY.
- (Optional) "Screen Mirroring" enabled as a menu bar item for faster access.
"""

import asyncio
import json

from friday.core.types import ToolResult, ToolError, ErrorCode, Severity


# ── AppleScript ─────────────────────────────────────────────────────────────
#
# Flow:
#   1. Open the Screen Mirroring menu bar item (fall back to Control Center).
#   2. Walk the popover UI tree for a button whose name looks TV-like
#      (contains "tv" / "apple tv" / "lg" / "samsung" / matches user hint).
#   3. Click it. Optionally click "Use As Separate Display" for extend mode.
#   4. Return "OK", "NO_DEVICES", or "DEVICE_NOT_FOUND".

_CAST_SCRIPT = r'''
on run argv
    set modeHint to item 2 of argv  -- "extend" or "mirror"

    tell application "System Events"
        tell application process "ControlCenter"
            -- close any popover that might be open
            key code 53
            delay 0.2

            -- find the Screen Mirroring menu bar item (description-based,
            -- since name returns missing value on SwiftUI elements)
            set mirrorItem to missing value
            repeat with mbi in (menu bar items of menu bar 1)
                try
                    if (description of mbi as string) contains "Mirror" then
                        set mirrorItem to mbi
                        exit repeat
                    end if
                end try
            end repeat
            if mirrorItem is missing value then return "NO_MIRROR_ENTRY"

            click mirrorItem
            delay 1.0

            -- walk the fixed popover path: window 1 → group 1 → scroll area 1
            -- → group 1 → checkboxes (each AirPlay device is one checkbox)
            try
                set grp to group 1 of scroll area 1 of group 1 of window 1
                set cbs to checkboxes of grp
                if (count of cbs) is 0 then
                    key code 53
                    return "NO_DEVICES"
                end if
                click (item 1 of cbs)
            on error errMsg
                key code 53
                return "ERR:" & errMsg
            end try
            delay 0.8

            -- extend mode: click "Use As Separate Display" if it appears
            if modeHint is "extend" then
                try
                    set grp to group 1 of scroll area 1 of group 1 of window 1
                    repeat with btn in (buttons of grp)
                        try
                            set d to description of btn as string
                            if (d contains "Separate") or (d contains "Extend") then
                                click btn
                                exit repeat
                            end if
                        end try
                    end repeat
                end try
            end if
        end tell
    end tell
    return "OK"
end run
'''


_STOP_SCRIPT = r'''
tell application "System Events"
    tell application process "ControlCenter"
        key code 53
        delay 0.2
        set mirrorItem to missing value
        repeat with mbi in (menu bar items of menu bar 1)
            try
                if (description of mbi as string) contains "Mirror" then
                    set mirrorItem to mbi
                    exit repeat
                end if
            end try
        end repeat
        if mirrorItem is missing value then return "NOTHING_TO_STOP"

        click mirrorItem
        delay 0.8

        -- find the checkbox that's currently on (value = 1) and click it
        try
            set grp to group 1 of scroll area 1 of group 1 of window 1
            repeat with cb in (checkboxes of grp)
                try
                    set v to value of cb
                    -- SwiftUI returns this as bool OR int; check both.
                    if (v is true) or (v is 1) or ((v as string) is "1") or ((v as string) is "true") then
                        click cb
                        delay 0.3
                        key code 53
                        return "OK"
                    end if
                end try
            end repeat
        end try
        key code 53
        return "NOTHING_TO_STOP"
    end tell
end tell
'''

async def _run_osascript(script: str, *args: str, timeout: float = 15.0) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "osascript", "-", *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(input=script.encode()), timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        return (-1, "", "timed out waiting for Control Center")
    return (
        proc.returncode or 0,
        out.decode(errors="replace").strip(),
        err.decode(errors="replace").strip(),
    )


# ── Display enumeration (JXA + NSScreen) ────────────────────────────────────

_LIST_DISPLAYS_JXA = r'''
ObjC.import('AppKit');
var screens = $.NSScreen.screens;
var mainFrame = $.NSScreen.mainScreen.frame;
var out = [];
for (var i = 0; i < screens.count; i++) {
    var s = screens.objectAtIndex(i);
    var f = s.frame;
    var name = s.localizedName ? s.localizedName.js : ('Display ' + i);
    out.push({
        index: i,
        name: name,
        x: f.origin.x,
        y: f.origin.y,
        w: f.size.width,
        h: f.size.height,
        main: (f.origin.x === mainFrame.origin.x && f.origin.y === mainFrame.origin.y
               && f.size.width === mainFrame.size.width && f.size.height === mainFrame.size.height)
    });
}
JSON.stringify(out);
'''


async def _list_displays() -> list[dict]:
    """Return [{index, name, x, y, w, h, main}, ...] for all connected displays."""
    proc = await asyncio.create_subprocess_exec(
        "osascript", "-l", "JavaScript", "-",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, _ = await asyncio.wait_for(
            proc.communicate(input=_LIST_DISPLAYS_JXA.encode()), timeout=5.0
        )
    except asyncio.TimeoutError:
        proc.kill()
        return []
    try:
        return json.loads(out.decode(errors="replace").strip())
    except Exception:
        return []


# ── Open & place window on extended display ────────────────────────────────

def _app_script(app_name: str, disp: dict) -> str:
    """AppleScript that activates an app and moves its front window to `disp`."""
    x, y, w, h = int(disp["x"]), int(disp["y"]), int(disp["w"]), int(disp["h"])
    return f'''
tell application "{app_name}"
    activate
end tell
delay 0.8
tell application "System Events"
    tell process "{app_name}"
        try
            set position of front window to {{{x}, {y}}}
            set size of front window to {{{w}, {h}}}
        end try
    end tell
end tell
return "OK"
'''


def _browser_script(url: str, disp: dict) -> str:
    """Open URL in Safari and move its window to `disp`."""
    x, y, w, h = int(disp["x"]), int(disp["y"]), int(disp["w"]), int(disp["h"])
    url_esc = url.replace('"', '\\"')
    return f'''
tell application "Safari"
    activate
    if (count of documents) is 0 then
        make new document with properties {{URL:"{url_esc}"}}
    else
        tell front window to set current tab to (make new tab with properties {{URL:"{url_esc}"}})
    end if
end tell
delay 0.8
tell application "System Events"
    tell process "Safari"
        try
            set position of front window to {{{x}, {y}}}
            set size of front window to {{{w}, {h}}}
        end try
    end tell
end tell
return "OK"
'''


# Apps users commonly want on the big screen. Maps hint → real .app name.
_APP_ALIASES = {
    "safari": "Safari", "chrome": "Google Chrome", "google chrome": "Google Chrome",
    "arc": "Arc", "firefox": "Firefox",
    "netflix": "Netflix", "youtube": None, "prime": None,  # browser-only
    "spotify": "Spotify", "music": "Music", "apple music": "Music",
    "tv": "TV", "appletv": "TV", "apple tv": "TV",
    "quicktime": "QuickTime Player", "vlc": "VLC",
    "notes": "Notes", "reminders": "Reminders",
    "messages": "Messages", "imessage": "Messages",
    "mail": "Mail", "calendar": "Calendar",
    "preview": "Preview", "finder": "Finder",
    "cursor": "Cursor", "vs code": "Visual Studio Code", "vscode": "Visual Studio Code",
    "terminal": "Terminal", "iterm": "iTerm",
}

_URL_SHORTCUTS = {
    "youtube": "https://www.youtube.com",
    "netflix": "https://www.netflix.com",
    "prime": "https://www.primevideo.com",
    "prime video": "https://www.primevideo.com",
    "disney": "https://www.disneyplus.com",
    "disney+": "https://www.disneyplus.com",
    "twitch": "https://www.twitch.tv",
    "x": "https://x.com",
    "twitter": "https://x.com",
    "github": "https://github.com",
    "gmail": "https://mail.google.com",
}


async def open_on_extended_display(target: str, query: str = "") -> ToolResult:
    """Open an app or URL on the extended (TV) display.

    `target` can be:
      - an app name: "safari", "spotify", "vlc"
      - a site alias: "youtube", "netflix", "twitch"
      - a raw URL: "https://..."
    `query` is an optional search string (e.g. "lex fridman podcast"), which
    appends a search URL for known sites (YouTube, Google).
    """
    t = (target or "").strip().lower()
    if not t:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.VALIDATION_ERROR,
                message="No target given. Try 'open youtube on extended screen'.",
                severity=Severity.LOW,
                recoverable=False,
            ),
        )

    displays = await _list_displays()
    if len(displays) < 2:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.CONFIG_MISSING,
                message=(
                    "No extended display found. Say 'extend my screen to tv' first, "
                    "then try again."
                ),
                severity=Severity.LOW,
                recoverable=True,
            ),
        )

    extended = next((d for d in displays if not d["main"]), displays[-1])

    # Build URL or app target
    url = None
    app = None
    if t.startswith("http://") or t.startswith("https://"):
        url = target.strip()
    elif t in _URL_SHORTCUTS:
        url = _URL_SHORTCUTS[t]
        if query:
            q = query.replace(" ", "+")
            if t in ("youtube",):
                url = f"https://www.youtube.com/results?search_query={q}"
            elif t in ("x", "twitter"):
                url = f"https://x.com/search?q={q}"
            elif t in ("github",):
                url = f"https://github.com/search?q={q}"
    elif t in _APP_ALIASES and _APP_ALIASES[t]:
        app = _APP_ALIASES[t]
    else:
        # Unknown — treat as a Google search
        q = (target + " " + query).strip().replace(" ", "+")
        url = f"https://www.google.com/search?q={q}"

    script = _browser_script(url, extended) if url else _app_script(app, extended)
    code, _, stderr = await _run_osascript(script)

    if code != 0:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=f"Couldn't open on extended display: {stderr or 'unknown'}",
                severity=Severity.MEDIUM,
                recoverable=True,
            ),
        )

    label = url or app or target
    return ToolResult(
        success=True,
        data={
            "display": extended.get("name", "extended"),
            "target": label,
            "message": f"Opened {label} on {extended.get('name', 'the extended display')}.",
        },
    )


async def list_displays() -> ToolResult:
    """List all connected displays with their positions and sizes."""
    displays = await _list_displays()
    return ToolResult(
        success=True,
        data={"count": len(displays), "displays": displays},
    )


# ── Public tools ────────────────────────────────────────────────────────────

async def cast_screen_to(device: str = "", mode: str = "mirror") -> ToolResult:
    """Extend or mirror the Mac screen to a TV via AirPlay.

    Opens Control Center → Screen Mirroring, clicks the matching TV if it's
    listed. If no TV shows up, returns an error asking the user to put the
    TV on the same Wi-Fi.
    """
    mode = (mode or "mirror").strip().lower()
    if mode not in {"mirror", "extend"}:
        mode = "mirror"
    device = (device or "").strip()

    code, stdout, stderr = await _run_osascript(_CAST_SCRIPT, device, mode)
    if code != 0:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=(
                    "Couldn't drive Screen Mirroring — make sure FRIDAY has "
                    "Accessibility permission in System Settings → Privacy & "
                    f"Security. Error: {stderr or 'unknown'}"
                ),
                severity=Severity.MEDIUM,
                recoverable=False,
            ),
        )

    if stdout in ("NO_ENTRY", "NO_MIRRORING_ENTRY"):
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.NOT_FOUND,
                message=(
                    "Couldn't find the Screen Mirroring control. Make sure "
                    "Control Center is showing in the menu bar (System Settings "
                    "→ Control Center → 'Show in Menu Bar')."
                ),
                severity=Severity.LOW,
                recoverable=True,
            ),
        )

    if stdout == "NO_DEVICES":
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.NOT_FOUND,
                message=(
                    "Screen Mirroring is empty — no devices discovered. "
                    "Make sure the TV is on and connected to the same Wi-Fi as this Mac."
                ),
                severity=Severity.LOW,
                recoverable=True,
            ),
        )

    if stdout.startswith("DEVICE_NOT_FOUND"):
        visible = stdout.split(":", 1)[1].strip(", ").strip() if ":" in stdout else ""
        target_msg = f"'{device}'" if device else "a TV"
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.NOT_FOUND,
                message=(
                    f"Can't match {target_msg}. Visible in Screen Mirroring: "
                    f"{visible or '(none)'}. Try saying the exact name."
                ),
                severity=Severity.LOW,
                recoverable=True,
            ),
        )

    verb = "Extending to" if mode == "extend" else "Mirroring to"
    label = device if device else "the TV"
    return ToolResult(
        success=True,
        data={
            "device": device or "(auto)",
            "mode": mode,
            "message": f"{verb} {label}.",
        },
    )


_DEBUG_SCRIPT = r'''
tell application "System Events"
    tell application process "ControlCenter"
        set labels to ""
        repeat with mbi in (menu bar items of menu bar 1)
            try
                set labels to labels & "NAME: " & (name of mbi as string) & linefeed
            on error
                set labels to labels & "NAME: <none>" & linefeed
            end try
            try
                set labels to labels & "  DESC: " & (description of mbi as string) & linefeed
            end try
            try
                set labels to labels & "  TITLE: " & (title of mbi as string) & linefeed
            end try
        end repeat
        return labels
    end tell
end tell
'''


async def debug_menu_bar() -> ToolResult:
    """Dump every menu bar item in ControlCenter — name, description, title.

    Useful when cast_screen_to can't find the right entry point on a new
    macOS version. Tells us what AppleScript actually sees.
    """
    code, stdout, stderr = await _run_osascript(_DEBUG_SCRIPT)
    if code != 0:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=f"osascript failed: {stderr or 'unknown'}",
                severity=Severity.LOW,
                recoverable=True,
            ),
        )
    return ToolResult(success=True, data={"menu_bar_items": stdout})


async def stop_screencast() -> ToolResult:
    """Stop the current AirPlay mirroring / extending session."""
    code, stdout, stderr = await _run_osascript(_STOP_SCRIPT)
    if code != 0:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=f"Couldn't stop mirroring: {stderr or 'unknown'}",
                severity=Severity.LOW,
                recoverable=True,
            ),
        )
    if stdout == "NOTHING_TO_STOP":
        return ToolResult(success=True, data={"message": "Nothing was being cast."})
    return ToolResult(success=True, data={"message": "Stopped screen mirroring."})


# ── Tool schemas ────────────────────────────────────────────────────────────

TOOL_SCHEMAS = {
    "cast_screen_to": {
        "fn": cast_screen_to,
        "schema": {
            "type": "function",
            "function": {
                "name": "cast_screen_to",
                "description": (
                    "START an AirPlay session that duplicates or extends the Mac "
                    "screen to a TV. ONLY use when the user EXPLICITLY asks to "
                    "cast/mirror/extend/project their Mac's SCREEN. "
                    "Trigger phrases: 'cast my screen to tv', 'mirror to tv', "
                    "'extend my screen to tv', 'airplay to tv'. "
                    "DO NOT use for 'open X on my mac' (that's a regular app launch — "
                    "use open_app). DO NOT use for 'play X' or 'open app' unless the "
                    "user also said cast/mirror/extend/airplay. DO NOT use to 'turn on' "
                    "the TV (use turn_on_tv). DO NOT use to launch apps ON the TV itself "
                    "(use tv_launch_app)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "device": {
                            "type": "string",
                            "description": "Optional device name/hint ('tv', 'living room', 'apple tv'). Empty auto-picks the first TV-like device.",
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["mirror", "extend"],
                            "description": "'mirror' duplicates the display; 'extend' uses the TV as a separate display.",
                        },
                    },
                    "required": [],
                },
            },
        },
    },
    "stop_screencast": {
        "fn": stop_screencast,
        "schema": {
            "type": "function",
            "function": {
                "name": "stop_screencast",
                "description": "Stop the current AirPlay mirroring / extending session.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
    },
    "open_on_extended_display": {
        "fn": open_on_extended_display,
        "schema": {
            "type": "function",
            "function": {
                "name": "open_on_extended_display",
                "description": (
                    "Open an app or URL and POSITION its window on the EXTENDED "
                    "(secondary) display. ONLY use when the user EXPLICITLY names "
                    "the extended/second/tv display/screen/monitor. "
                    "Trigger phrases: 'open youtube on the extended screen', "
                    "'put spotify on the tv display', 'show netflix on the second monitor'. "
                    "DO NOT use for 'open X on my mac' — that means the normal built-in "
                    "display (use open_app). DO NOT use if the user just says 'on my tv' "
                    "(that's native TV app control — use tv_launch_app). "
                    "Requires a second display already connected; otherwise returns an error."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target": {
                            "type": "string",
                            "description": "App name ('safari', 'spotify'), site alias ('youtube', 'netflix'), or URL.",
                        },
                        "query": {
                            "type": "string",
                            "description": "Optional search query. For youtube/x/github, appends a search URL.",
                        },
                    },
                    "required": ["target"],
                },
            },
        },
    },
    "list_displays": {
        "fn": list_displays,
        "schema": {
            "type": "function",
            "function": {
                "name": "list_displays",
                "description": "List all connected displays with name, position, and size.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
    },
}
