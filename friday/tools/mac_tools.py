"""Mac control tools — AppleScript, app launcher, screenshots.

macOS only. Used for system automation, app control, and screen capture.
"""

import asyncio
import base64
import tempfile
from pathlib import Path
from typing import Optional

from friday.core.types import ToolResult, ToolError, ErrorCode, Severity

# Apps that are safe to open without confirmation
_DEFAULT_SAFE_APPS = {
    "cursor", "visual studio code", "code", "terminal", "iterm",
    "safari", "google chrome", "chrome", "firefox", "arc",
    "finder", "notes", "calendar", "mail", "reminders",
    "spotify", "slack", "zoom", "notion", "discord",
    "activity monitor", "system preferences", "system settings",
    "preview", "textedit", "calculator",
    # Media + communication
    "music", "apple music", "tv", "apple tv", "podcasts",
    "messages", "imessage", "facetime", "photos", "quicktime player",
    # Extras
    "whatsapp", "telegram", "signal", "figma", "linear", "xcode",
}


def _user_country() -> str:
    """ISO-2 country code from user config, with a safe default."""
    try:
        from friday.core.user_config import USER
        return USER.country_code or "US"
    except Exception:
        return "US"


def _safe_apps() -> set[str]:
    """Resolve the current allow-list: defaults ∪ user-configured.

    The macOS Swift app writes FRIDAY_ALLOWED_APPS as a comma-separated
    list of app names (from Settings → Allowed Apps). We lowercase them
    so the substring check behaves the same as before.
    """
    import os
    env = os.environ.get("FRIDAY_ALLOWED_APPS", "").strip()
    if not env:
        return _DEFAULT_SAFE_APPS
    extras = {name.strip().lower() for name in env.split(",") if name.strip()}
    # Union so built-in defaults still work if the user only adds extras.
    return _DEFAULT_SAFE_APPS | extras


# Back-compat alias — old callers read SAFE_APPS directly.
SAFE_APPS = _DEFAULT_SAFE_APPS

# Map user-spoken aliases to the real macOS app bundle name used by `open -a`.
APP_ALIASES = {
    "apple music": "Music",
    "imessage": "Messages",
    "apple tv": "TV",
    "google chrome": "Google Chrome",
    "vs code": "Visual Studio Code",
    "vscode": "Visual Studio Code",
    "code": "Visual Studio Code",
    "quicktime": "QuickTime Player",
    "system settings": "System Settings",
    "system preferences": "System Settings",
}

FRIDAY_SCREENSHOTS = Path.home() / "Downloads" / "friday_screenshots"


async def run_applescript(script: str) -> ToolResult:
    """Execute AppleScript for Mac control. Use for app automation, system settings, UI control."""
    try:
        # Escape for shell — use stdin instead of -e to avoid quoting issues
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=script.encode()),
            timeout=15,
        )

        stdout_str = stdout.decode(errors="replace").strip()
        stderr_str = stderr.decode(errors="replace").strip()

        if proc.returncode == 0:
            return ToolResult(
                success=True,
                data={"output": stdout_str, "script": script[:200]},
            )
        else:
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.COMMAND_FAILED,
                    message=f"AppleScript error: {stderr_str}",
                    severity=Severity.MEDIUM,
                    recoverable=False,
                    context={"script": script[:200]},
                ),
            )
    except asyncio.TimeoutError:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.PROCESS_TIMEOUT,
                message="AppleScript timed out after 15s",
                severity=Severity.MEDIUM,
                recoverable=True,
            ),
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=str(e),
                severity=Severity.HIGH,
                recoverable=False,
            ),
        )


async def open_application(
    app: str,
    path: str = None,
    new_window: bool = False,
) -> ToolResult:
    """Open a macOS application. Optionally open a file/folder with it.

    Only opens apps from the safe list without confirmation.
    """
    app_lower = app.lower().strip()
    safe = _safe_apps()

    if not any(s in app_lower for s in safe):
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.VALIDATION_ERROR,
                message=f"'{app}' is not in the allowed apps list. Add it under Settings → Allowed Apps.",
                severity=Severity.MEDIUM,
                recoverable=True,
                context={"app": app, "safe_apps": sorted(safe)},
            ),
        )

    # Normalise aliases: "apple music" → "Music", "imessage" → "Messages", etc.
    real_app = APP_ALIASES.get(app_lower, app)
    cmd_parts = ["open", "-a", real_app]
    if new_window:
        cmd_parts.append("-n")
    if path:
        cmd_parts.append(str(Path(path).expanduser()))

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd_parts,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)

        if proc.returncode == 0:
            return ToolResult(
                success=True,
                data={"app": app, "path": path, "opened": True},
            )
        else:
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.COMMAND_FAILED,
                    message=f"Failed to open {app}: {stderr.decode(errors='replace')}",
                    severity=Severity.MEDIUM,
                    recoverable=False,
                ),
            )
    except Exception as e:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=str(e),
                severity=Severity.MEDIUM,
                recoverable=False,
            ),
        )


async def take_screenshot(
    save_path: str = None,
    region: dict = None,
) -> ToolResult:
    """Take a screenshot of the screen. Optionally capture a specific region.

    region: {"x": 0, "y": 0, "w": 1920, "h": 1080}
    Returns the file path of the saved screenshot.
    """
    FRIDAY_SCREENSHOTS.mkdir(parents=True, exist_ok=True)

    if not save_path:
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = str(FRIDAY_SCREENSHOTS / f"screenshot_{ts}.png")

    try:
        if region:
            cmd = [
                "screencapture", "-x",
                "-R", f"{region['x']},{region['y']},{region['w']},{region['h']}",
                save_path,
            ]
        else:
            cmd = ["screencapture", "-x", save_path]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)

        if proc.returncode != 0:
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.COMMAND_FAILED,
                    message=f"Screenshot failed: {stderr.decode(errors='replace')}",
                    severity=Severity.MEDIUM,
                    recoverable=True,
                ),
            )

        file_size = Path(save_path).stat().st_size

        return ToolResult(
            success=True,
            data={
                "saved_path": save_path,
                "size_bytes": file_size,
            },
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=str(e),
                severity=Severity.MEDIUM,
                recoverable=False,
            ),
        )


async def get_system_info() -> ToolResult:
    """Get basic Mac system info — hostname, OS version, CPU, memory, disk."""
    try:
        commands = {
            "hostname": "hostname",
            "os_version": "sw_vers -productVersion",
            "cpu": "sysctl -n machdep.cpu.brand_string",
            "memory_gb": "sysctl -n hw.memsize",
            "disk_usage": "df -h / | tail -1",
            "uptime": "uptime",
        }

        info = {}
        for key, cmd in commands.items():
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            val = stdout.decode(errors="replace").strip()
            if key == "memory_gb":
                try:
                    info[key] = f"{int(val) / (1024**3):.0f} GB"
                except ValueError:
                    info[key] = val
            else:
                info[key] = val

        return ToolResult(success=True, data=info)
    except Exception as e:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=str(e),
                severity=Severity.LOW,
                recoverable=True,
            ),
        )


async def set_volume(level: int) -> ToolResult:
    """Set system volume (0-100)."""
    if not 0 <= level <= 100:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.VALIDATION_ERROR,
                message=f"Volume must be 0-100, got {level}",
                severity=Severity.LOW,
                recoverable=True,
            ),
        )

    # macOS volume is 0-7 scale via osascript
    mac_vol = round(level / 100 * 7)
    return await run_applescript(f'set volume output volume {level}')


async def toggle_dark_mode() -> ToolResult:
    """Toggle macOS dark mode on/off."""
    script = '''
    tell application "System Events"
        tell appearance preferences
            set dark mode to not dark mode
            return dark mode as string
        end tell
    end tell
    '''
    return await run_applescript(script)


async def type_text(
    text: str,
    app: str = "",
    submit: bool = False,
    new_document: bool = False,
) -> ToolResult:
    """Type text into the focused window (or a specific app's frontmost window).

    Args:
        text: The string to type.
        app: Optional app name to activate first (e.g. "Notes", "Messages").
        submit: If True, press Return after typing (to submit a search / send a message).
        new_document: If True, press Cmd+N BEFORE typing. Required for apps like
            Notes, TextEdit, Pages where the default state is a note LIST, not an
            editable document.
    """
    if not text:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.VALIDATION_ERROR,
                message="text is empty",
                severity=Severity.LOW,
                recoverable=False,
            ),
        )

    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    activate_block = f'tell application "{app}" to activate\ndelay 0.6\n' if app else ''
    new_doc_block = '\nkeystroke "n" using command down\ndelay 0.5' if new_document else ''
    submit_block = '\nkey code 36' if submit else ''  # key code 36 = Return

    script = f'''
{activate_block}tell application "System Events"{new_doc_block}
    keystroke "{escaped}"{submit_block}
end tell
return "TYPED"
'''
    result = await run_applescript(script)
    if result.success:
        result.data = {
            "typed": text,
            "app": app or "(focused)",
            "submitted": submit,
            "new_document": new_document,
        }
    return result


async def _itunes_search(term: str) -> dict | None:
    """Query Apple's public iTunes Search API for the top song match.

    Returns dict with trackName / artistName / trackViewUrl, or None.
    """
    import urllib.parse
    import urllib.request

    url = (
        "https://itunes.apple.com/search?"
        + urllib.parse.urlencode({
            "term": term,
            "entity": "song",
            "limit": 1,
            "country": _user_country(),
        })
    )
    try:
        loop = asyncio.get_event_loop()
        def _fetch():
            req = urllib.request.Request(url, headers={"User-Agent": "FRIDAY/1.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                return resp.read().decode()
        body = await loop.run_in_executor(None, _fetch)
        import json as _json
        data = _json.loads(body)
        results = data.get("results") or []
        return results[0] if results else None
    except Exception:
        return None


async def open_url(url: str, browser: str = "") -> ToolResult:
    """Open a URL in the user's browser via `open` — fast and lightweight.

    Use this for 'open/go to [url]' or 'open youtube/twitter/etc and search X'
    type chains where a URL is enough. NO browser automation needed.

    Args:
        url: Full URL (https:// prefix added if missing).
        browser: Optional — 'Safari' / 'Google Chrome' / 'Arc'. Defaults to system default.
    """
    if not url:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.VALIDATION_ERROR,
                message="url is empty",
                severity=Severity.LOW,
                recoverable=False,
            ),
        )
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    cmd = ["open"]
    if browser:
        cmd += ["-a", browser]
    cmd.append(url)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode == 0:
            return ToolResult(success=True, data={"url": url, "browser": browser or "(default)"})
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=f"Failed to open {url}: {stderr.decode(errors='replace')}",
                severity=Severity.MEDIUM,
                recoverable=True,
            ),
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=str(e),
                severity=Severity.MEDIUM,
                recoverable=False,
            ),
        )


async def get_music_status() -> ToolResult:
    """Return the current playback state of Mac audio apps in one shot.

    Checks Music.app (Apple Music) and Spotify in parallel. Returns a
    dict like:
        {
          "music_app": {"state": "playing|paused|stopped", "track": "...",
                        "artist": "...", "running": True|False},
          "spotify":   {"state": "playing|paused|stopped", "track": "...",
                        "artist": "...", "running": True|False},
          "any_playing": True|False,
        }

    Used by household_agent to disambiguate "pause the music" — the LLM
    checks this against tv_status, then pauses whichever surface is
    actually playing. Also surfaces "currently on Music.app" so the
    agent can answer "what am I listening to" without guessing.
    """
    # Pipe-delimited output. Python parses it. Format per app:
    #   music_app|<state>|<running>|<track>|<artist>
    #   spotify|<state>|<running>|<track>|<artist>
    # Separator between the two apps: a literal ";;"  (unlikely in metadata).
    # AppleScript can't `tell application <variable>` — each app needs a
    # literal tell block. But if an app isn't installed, its literal tell
    # block won't even parse. So we build the script dynamically, adding
    # the Spotify block only when Spotify.app is present on disk.
    from pathlib import Path as _Path
    spotify_installed = (
        _Path("/Applications/Spotify.app").exists()
        or _Path.home().joinpath("Applications/Spotify.app").exists()
    )

    spotify_block = ""
    if spotify_installed:
        spotify_block = '''
if my isAppRunning("Spotify") then
    try
        tell application "Spotify"
            set ps to (player state as text)
            set t to ""
            set a to ""
            if ps is "playing" or ps is "paused" then
                try
                    set t to name of current track
                end try
                try
                    set a to artist of current track
                end try
            end if
        end tell
        set spotLine to "spotify|" & ps & "|true|" & t & "|" & a
    end try
end if
'''

    script = f'''
on isAppRunning(appName)
    tell application "System Events"
        return (exists (processes where name is appName))
    end tell
end isAppRunning

set musicLine to "music_app|stopped|false||"
set spotLine  to "spotify|not_installed|false||"

if my isAppRunning("Music") then
    try
        tell application "Music"
            set ps to (player state as text)
            set t to ""
            set a to ""
            if ps is "playing" or ps is "paused" then
                try
                    set t to name of current track
                end try
                try
                    set a to artist of current track
                end try
            end if
        end tell
        set musicLine to "music_app|" & ps & "|true|" & t & "|" & a
    end try
end if
{spotify_block}
return musicLine & ";;" & spotLine
'''
    r = await run_applescript(script)
    if not r.success:
        return r
    raw = (r.data or {}).get("output", "").strip()
    out: dict = {}
    for line in raw.split(";;"):
        parts = line.split("|", 4)
        if len(parts) < 5:
            continue
        tag, state, running, track, artist = parts
        out[tag] = {
            "state": state,
            "running": running.lower() == "true",
            "track": track,
            "artist": artist,
        }
    out["any_playing"] = any(
        (out.get(k) or {}).get("state") == "playing"
        for k in ("music_app", "spotify")
    )
    return ToolResult(success=True, data=out)


async def play_music(
    query: str = "",
    action: str = "play",
) -> ToolResult:
    """Control the Mac Music app — search the library (or Apple Music cloud) for
    a track and play it, or pause/resume/skip/previous.

    For cloud tracks we use Apple's public iTunes Search API to resolve the
    query to a canonical Apple Music URL, then open it in Music — no UI typing.

    Args:
        query: Track name, artist, or "title by artist".
        action: "play" (default), "pause", "resume", "stop", "next", "previous".
    """
    action = (action or "play").strip().lower()

    if action in {"pause"}:
        return await run_applescript('tell application "Music" to pause\nreturn "PAUSED"')
    if action in {"resume"}:
        return await run_applescript(
            'tell application "Music"\nactivate\nplay\nend tell\nreturn "RESUMED"'
        )
    if action in {"stop"}:
        return await run_applescript('tell application "Music" to stop\nreturn "STOPPED"')
    if action in {"next", "skip"}:
        return await run_applescript(
            'tell application "Music" to next track\nreturn "NEXT"'
        )
    if action in {"previous", "prev", "back"}:
        return await run_applescript(
            'tell application "Music" to previous track\nreturn "PREV"'
        )

    # action == "play" — find a track matching the query and play it
    if not query:
        return await run_applescript(
            'tell application "Music"\nactivate\nplay\nend tell\nreturn "PLAYING"'
        )

    # Split "X by Y" into title + artist for a tighter match when both are known.
    q_raw = query.strip()
    title_part, artist_part = q_raw, ""
    lower_q = q_raw.lower()
    for sep in (" by ", " - ", " – "):
        if sep in lower_q:
            idx = lower_q.find(sep)
            title_part = q_raw[:idx].strip()
            artist_part = q_raw[idx + len(sep):].strip()
            break

    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    # Build candidate title strings to try in order. Only strip leading
    # articles ("I ", "a ", "the ") — that's the common spoken-vs-actual
    # mismatch. We intentionally do NOT shorten the tail, because plenty
    # of real songs have long titles and trimming them would match the
    # wrong track.
    def _title_variants(t: str) -> list[str]:
        t = t.strip()
        if not t:
            return []
        low = t.lower()
        out = [t]
        for lead in ("i ", "a ", "an ", "the "):
            if low.startswith(lead):
                stripped = t[len(lead):].strip()
                if stripped and stripped not in out:
                    out.append(stripped)
        return out

    title_candidates = _title_variants(title_part)
    # AppleScript literal list for the candidates
    as_list = ", ".join(f'"{esc(v)}"' for v in title_candidates) or '""'
    q = esc(q_raw)
    title_q = esc(title_part)
    artist_q = esc(artist_part)
    # Searches `library playlist 1` AND every user-made playlist.
    # User playlists can hold cloud-reference tracks that aren't directly
    # in the library listing — common when a user has added a song to
    # a playlist without explicitly "Add to Library". We check
    # every playlist so those are still reachable.
    script = f'''
set fullQ to "{q}"
set artistQ to "{artist_q}"
set titleVariants to {{{as_list}}}

tell application "Music"
    activate
    set matches to {{}}

    repeat with tQ in titleVariants
        set titleQ to contents of tQ

        -- 1. title + artist → strongest match, library first, then playlists
        if artistQ is not "" then
            try
                set matches to (every track whose name contains titleQ and artist contains artistQ) of library playlist 1
            end try
            if (count of matches) is 0 then
                try
                    repeat with p in (every user playlist)
                        try
                            set pm to (every track whose name contains titleQ and artist contains artistQ) of p
                            if (count of pm) > 0 then
                                set matches to pm
                                exit repeat
                            end if
                        end try
                    end repeat
                end try
            end if
        end if

        -- 2. title-only — library first, then every user playlist
        if (count of matches) is 0 and artistQ is "" then
            try
                set matches to (every track whose name contains titleQ) of library playlist 1
            end try
            if (count of matches) is 0 then
                try
                    repeat with p in (every user playlist)
                        try
                            set pm to (every track whose name contains titleQ) of p
                            if (count of pm) > 0 then
                                set matches to pm
                                exit repeat
                            end if
                        end try
                    end repeat
                end try
            end if
        end if

        if (count of matches) > 0 then exit repeat
    end repeat

    if (count of matches) > 0 then
        play item 1 of matches
        set t to item 1 of matches
        return "PLAYING_LIBRARY:" & (name of t) & " — " & (artist of t)
    end if
end tell
return "NOT_IN_LIBRARY"
'''
    lib_result = await run_applescript(script)
    lib_out = ""
    if lib_result.success and isinstance(lib_result.data, dict):
        lib_out = lib_result.data.get("output", "")

    if lib_out.startswith("PLAYING_LIBRARY:"):
        lib_result.data = {
            "action": "play",
            "source": "library",
            "track": lib_out.split(":", 1)[1],
        }
        return lib_result

    # Not in library — look up the track via iTunes Search API and open its
    # canonical Apple Music URL in Music. No UI typing, no focus fights.
    hit = await _itunes_search(q_raw)
    if not hit or not hit.get("trackViewUrl"):
        # iTunes Search API lags Apple Music's catalogue — indie / global
        # releases are often missing from Search even though they stream
        # fine via the Music app. Fallback: open the Music app's own
        # search page with the query so the user's tap becomes one
        # action instead of "not found".
        import urllib.parse as _up
        search_url = (
            f"music://music.apple.com/{_user_country().lower()}/search?"
            + _up.urlencode({"term": q_raw})
        )
        fallback_script = f'''
tell application "Music"
    activate
    open location "{search_url}"
end tell
return "OPENED_SEARCH"
'''
        fb = await run_applescript(fallback_script)
        if fb.success:
            return ToolResult(
                success=True,
                data={
                    "action": "opened_search",
                    "source": "apple_music_search",
                    "query": q_raw,
                    "message": (
                        f"iTunes Search didn't index '{q_raw}' — opened "
                        f"Apple Music search for it so you can tap the "
                        f"right track."
                    ),
                },
            )
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.NOT_FOUND,
                message=f"Couldn't find '{q_raw}' on Apple Music.",
                severity=Severity.LOW,
                recoverable=True,
            ),
        )

    https_url = hit["trackViewUrl"]  # e.g. https://music.apple.com/gb/album/.../12345?i=67890
    # Music app handles the music:// variant directly and begins playback.
    music_url = https_url.replace("https://music.apple.com", "music://music.apple.com")
    track_name = hit.get("trackName", "")
    artist_name = hit.get("artistName", "")
    display = f"{track_name} — {artist_name}" if track_name else q_raw

    # Navigate to the Apple Music track page. (Auto-playing cloud tracks via
    # AppleScript is unreliable — SwiftUI rows don't respond to AXPress or
    # synthesized clicks — so we stop at navigation and report honestly.)
    open_script = f'''
tell application "Music"
    activate
    open location "{music_url}"
end tell
delay 1.5
return "NAVIGATED_CLOUD"
'''
    open_result = await run_applescript(open_script)
    if open_result.success:
        return ToolResult(
            success=True,
            data={
                "action": "navigated",
                "source": "apple_music_cloud",
                "track": display,
                "url": https_url,
                "message": (
                    f"Found '{display}' on Apple Music and opened its track page. "
                    "Apple Music's cloud tracks don't start via AppleScript — "
                    "hit Play in Music to start it."
                ),
            },
        )
    return ToolResult(
        success=False,
        error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=f"Found '{display}' on Apple Music but couldn't open the page.",
            severity=Severity.LOW,
            recoverable=True,
        ),
    )


async def close_application(app: str) -> ToolResult:
    """Quit/close a macOS application by name."""
    if not app:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.VALIDATION_ERROR,
                message="app name required",
                severity=Severity.LOW,
                recoverable=False,
            ),
        )
    script = f'''
try
    tell application "{app}" to quit
    return "CLOSED"
on error errMsg
    return "ERR:" & errMsg
end try
'''
    result = await run_applescript(script)
    if result.success:
        result.data = {"app": app, "closed": True}
    return result


# ── Tool Schemas ─────────────────────────────────────────────────────────────

TOOL_SCHEMAS = {
    "run_applescript": {
        "fn": run_applescript,
        "schema": {
            "type": "function",
            "function": {
                "name": "run_applescript",
                "description": "Execute AppleScript for Mac automation — app control, system settings, UI automation.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "script": {"type": "string", "description": "AppleScript code to execute"},
                    },
                    "required": ["script"],
                },
            },
        },
    },
    "open_application": {
        "fn": open_application,
        "schema": {
            "type": "function",
            "function": {
                "name": "open_application",
                "description": (
                    "Open a macOS application on the Mac. DEFAULT for 'open X', "
                    "'launch X', 'open X on my mac' when the ONLY action is opening. "
                    "Examples: 'open safari', 'launch chrome', 'open finder'. "
                    "DO NOT use this alone when the user asks to do something AFTER "
                    "opening (search, play, type, navigate, paste, send, go to). "
                    "Those are multi-step — the dispatcher should answer NEEDS_AGENT "
                    "and let system_agent chain open + the second action. "
                    "DO NOT use cast_screen_to or open_on_extended_display here."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "app": {"type": "string", "description": "Application name (e.g. 'Cursor', 'Chrome', 'Finder')"},
                        "path": {"type": "string", "description": "File or folder to open with the app (optional)"},
                        "new_window": {"type": "boolean", "description": "Open in new window (default false)"},
                    },
                    "required": ["app"],
                },
            },
        },
    },
    "take_screenshot": {
        "fn": take_screenshot,
        "schema": {
            "type": "function",
            "function": {
                "name": "take_screenshot",
                "description": (
                    "Take a screenshot and return ONLY the saved file path. "
                    "Use this ONLY when the user explicitly wants a screenshot FILE "
                    "(to save, share, attach, AirDrop). "
                    "If the user wants to KNOW what's on screen, use ask_about_screen "
                    "instead — it does screenshot+describe in one call."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "save_path": {"type": "string", "description": "Where to save (default: /tmp/friday/)"},
                        "region": {
                            "type": "object",
                            "description": "Capture region: {x, y, w, h} in pixels",
                            "properties": {
                                "x": {"type": "integer"},
                                "y": {"type": "integer"},
                                "w": {"type": "integer"},
                                "h": {"type": "integer"},
                            },
                        },
                    },
                    "required": [],
                },
            },
        },
    },
    "get_system_info": {
        "fn": get_system_info,
        "schema": {
            "type": "function",
            "function": {
                "name": "get_system_info",
                "description": "Get Mac system info — hostname, OS version, CPU, memory, disk usage, uptime.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
    },
    "set_volume": {
        "fn": set_volume,
        "schema": {
            "type": "function",
            "function": {
                "name": "set_volume",
                "description": "Set system volume level (0-100).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "level": {"type": "integer", "description": "Volume level 0-100"},
                    },
                    "required": ["level"],
                },
            },
        },
    },
    "toggle_dark_mode": {
        "fn": toggle_dark_mode,
        "schema": {
            "type": "function",
            "function": {
                "name": "toggle_dark_mode",
                "description": "Toggle macOS dark mode on or off.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
    },
    "type_text": {
        "fn": type_text,
        "schema": {
            "type": "function",
            "function": {
                "name": "type_text",
                "description": (
                    "Type text via the keyboard into the focused window. Use this to "
                    "PASTE/TYPE into an app AFTER opening it. Examples: "
                    "'open notes and paste X' → open_application('Notes'), then "
                    "type_text(text='X', app='Notes', new_document=True). "
                    "'search youtube for X' → after navigating, type_text(text='X', submit=True). "
                    "IMPORTANT: set new_document=True for Notes/TextEdit/Pages — they "
                    "open on a note LIST or empty window, you need Cmd+N first. "
                    "Set submit=True to press Return after (send message, submit search)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to type."},
                        "app": {"type": "string", "description": "Optional app to activate first (e.g. 'Notes', 'Messages')."},
                        "submit": {"type": "boolean", "description": "Press Return after typing (default false)."},
                        "new_document": {"type": "boolean", "description": "Press Cmd+N first to create a new document (use for Notes, TextEdit, Pages)."},
                    },
                    "required": ["text"],
                },
            },
        },
    },
    "close_application": {
        "fn": close_application,
        "schema": {
            "type": "function",
            "function": {
                "name": "close_application",
                "description": "Quit a macOS app by name. Use for 'close X', 'quit X'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "app": {"type": "string", "description": "App name, e.g. 'Calculator', 'Safari'."},
                    },
                    "required": ["app"],
                },
            },
        },
    },
    "open_url": {
        "fn": open_url,
        "schema": {
            "type": "function",
            "function": {
                "name": "open_url",
                "description": (
                    "Open a URL in the browser (lightweight — uses `open` command, "
                    "no browser automation). USE THIS for 'open youtube and search X', "
                    "'open [site] and go to Y', 'open hacker news in safari'. "
                    "For 'open youtube and search X', pass the YouTube search URL: "
                    "'https://www.youtube.com/results?search_query=X'. "
                    "For plain 'open [site]', pass the site URL. "
                    "Use browser_navigate (Playwright) only when you need to click, "
                    "fill forms, or read page content afterwards."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Full URL (https:// added if missing)."},
                        "browser": {"type": "string", "description": "Optional: 'Safari', 'Google Chrome', 'Arc'. Defaults to system default."},
                    },
                    "required": ["url"],
                },
            },
        },
    },
    "get_music_status": {
        "fn": get_music_status,
        "schema": {
            "type": "function",
            "function": {
                "name": "get_music_status",
                "description": (
                    "Check whether Music.app (Apple Music) or Spotify is currently "
                    "playing on the Mac. Returns a dict with state + current track "
                    "for each app, plus a top-level 'any_playing' boolean. Use this "
                    "BEFORE pausing/resuming when the user says 'pause the music' "
                    "without specifying a surface — combined with tv_status, you can "
                    "tell whether the music is on the TV, Music.app, or Spotify, "
                    "and act on whichever is actually playing."
                ),
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
    },
    "play_music": {
        "fn": play_music,
        "schema": {
            "type": "function",
            "function": {
                "name": "play_music",
                "description": (
                    "Control the Mac Music app — play a specific song by name, or "
                    "pause/resume/skip. USE THIS (not open_application + type_text) "
                    "whenever the user asks to play a song. Examples: "
                    "'play i wish i had a girlfriend' → play_music(query='i wish i had a girlfriend'). "
                    "'play some drake' → play_music(query='drake'). "
                    "'pause the music' → play_music(action='pause'). "
                    "'skip this song' → play_music(action='next'). "
                    "First searches your local library; if nothing matches, opens the "
                    "Music app search box with the query so Apple Music results appear."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Track name, artist, or 'title - artist'. Leave blank for control actions.",
                        },
                        "action": {
                            "type": "string",
                            "enum": ["play", "pause", "resume", "stop", "next", "previous"],
                            "description": "'play' (default): finds & plays the query. Others are transport controls.",
                        },
                    },
                    "required": [],
                },
            },
        },
    },
}
