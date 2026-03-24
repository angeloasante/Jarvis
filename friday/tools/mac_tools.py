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
SAFE_APPS = {
    "cursor", "visual studio code", "code", "terminal", "iterm",
    "safari", "google chrome", "chrome", "firefox", "arc",
    "finder", "notes", "calendar", "mail", "reminders",
    "spotify", "slack", "zoom", "notion", "discord",
    "activity monitor", "system preferences", "system settings",
    "preview", "textedit", "calculator",
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
    app_lower = app.lower()

    if not any(safe in app_lower for safe in SAFE_APPS):
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.VALIDATION_ERROR,
                message=f"'{app}' is not in the safe apps list. Ask Travis to confirm.",
                severity=Severity.MEDIUM,
                recoverable=True,
                context={"app": app, "safe_apps": sorted(SAFE_APPS)},
            ),
        )

    cmd_parts = ["open", "-a", app]
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
                "description": "Open a macOS application. Optionally open a file with it.",
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
                "description": "Take a screenshot of the current screen. Returns file path.",
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
}
