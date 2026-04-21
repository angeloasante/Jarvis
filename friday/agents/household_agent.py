"""Household Agent — smart home control. The home brain of FRIDAY.

Currently supports: LG TV (local WebOS + WakeOnLan).
Future: LG ThinQ API for all LG appliances, smart lights, etc.

FAST PATH: Simple TV commands (volume, launch app, on/off) are pattern-matched
and executed directly — no LLM needed. Only complex/ambiguous commands go to the model.
"""

import re
import time
from typing import Optional, Callable

from friday.core.base_agent import BaseAgent
from friday.core.types import AgentResponse
from friday.tools.tv_tools import TOOL_SCHEMAS as TV_TOOLS
from friday.tools import tv_tools


# ── Fast path patterns ──────────────────────────────────────────────────────
# These map directly to tool calls without touching the LLM.
# Result: ~1-2s instead of ~30s for simple commands.

# App name aliases
_APP_ALIASES = {
    "netflix": "netflix",
    "youtube": "youtube",
    "yt": "youtube",
    "spotify": "spotify",
    "prime": "prime",
    "amazon": "prime",
    "prime video": "prime",
    "disney": "disney",
    "disney+": "disney",
    "disney plus": "disney",
    "apple tv": "apple tv",
    "appletv": "apple tv",
    "live tv": "live tv",
    "browser": "browser",
    "hdmi1": "hdmi1", "hdmi 1": "hdmi1",
    "hdmi2": "hdmi2", "hdmi 2": "hdmi2",
    "hdmi3": "hdmi3", "hdmi 3": "hdmi3",
    "hdmi4": "hdmi4", "hdmi 4": "hdmi4",
    "settings": "settings",
}


def _fast_match(task: str) -> Optional[list[tuple[str, dict]]]:
    """Try to match a simple TV command. Returns list of (tool_name, args) or None.

    Returns None for anything ambiguous → falls through to the LLM.
    """
    t = task.strip().lower()
    # Strip common prefixes
    t = re.sub(r"^(can you |please |yo |oya |chale |hey |friday |bruv )+", "", t)

    # ── Multi-step: turn on + launch (check BEFORE single power) ─
    # "turn on the tv and put on youtube"
    m = re.search(r"turn on.{0,15}(?:tv|telly|television).{0,10}(?:and |then |,\s*)(?:put on|open|launch)\s+(.+)", t)
    if m:
        app_raw = m.group(1).strip().rstrip(".")
        app_raw = re.sub(r"^the\s+", "", app_raw)
        app_name = _APP_ALIASES.get(app_raw, app_raw)
        if app_name in _APP_ALIASES.values():
            return [("turn_on_tv", {}), ("tv_launch_app", {"app_name": app_name})]

    # ── Power ────────────────────────────────────────────────────
    if re.match(r"(turn on|switch on|power on)\s*(the )?(tv|telly|television)", t):
        return [("turn_on_tv", {})]

    if re.match(r"(turn off|switch off|power off)\s*(the )?(tv|telly|television)", t):
        return [("turn_off_tv", {})]

    if re.match(r"tv\s*(on|off)$", t):
        return [("turn_on_tv" if "on" in t else "turn_off_tv", {})]

    # ── Volume exact ─────────────────────────────────────────────
    m = re.search(r"(?:volume|vol)\s*(?:to |at |=\s*)(\d+)", t)
    if m:
        return [("tv_volume", {"level": int(m.group(1))})]

    m = re.search(r"(?:set|put)\s*(?:the )?\s*(?:tv )?\s*(?:volume|vol)\s*(?:to |at )?\s*(\d+)", t)
    if m:
        return [("tv_volume", {"level": int(m.group(1))})]

    m = re.search(r"(\d+)\s*%?\s*(?:volume|vol)", t)
    if m:
        return [("tv_volume", {"level": int(m.group(1))})]

    # ── Volume relative ──────────────────────────────────────────
    if re.search(r"\b(louder|turn.{0,5}up|volume up|vol up)\b", t):
        amount = 15 if re.search(r"\b(much|way|lot)\b", t) else 5
        return [("tv_volume_adjust", {"direction": "up", "amount": amount})]

    if re.search(r"\b(quieter|lower|turn.{0,5}down|volume down|vol down)\b", t):
        amount = 15 if re.search(r"\b(much|way|lot)\b", t) else 5
        return [("tv_volume_adjust", {"direction": "down", "amount": amount})]

    # ── Mute ─────────────────────────────────────────────────────
    if re.search(r"\bunmute\b", t):
        return [("tv_mute", {"mute": False})]
    if re.search(r"\bmute\b", t):
        return [("tv_mute", {"mute": True})]

    # ── Playback ─────────────────────────────────────────────────
    # Removed fast-path overrides — the LLM picks between tv_play_pause (TV)
    # and play_music (Mac Music) based on the user's phrasing. Tool descriptions
    # carry the disambiguation.

    # ── Screen off/on ──────────────────────────────────────────────
    if re.search(r"\b(screen off|display off|turn off.{0,10}screen)\b", t):
        return [("tv_screen_off", {})]
    if re.search(r"\b(screen on|display on|turn on.{0,10}screen)\b", t):
        return [("tv_screen_on", {})]

    # ── Channel ──────────────────────────────────────────────────
    if re.search(r"\b(channel up|next channel)\b", t):
        return [("tv_remote_button", {"buttons": ["channel_up"]})]
    if re.search(r"\b(channel down|prev.{0,5}channel)\b", t):
        return [("tv_remote_button", {"buttons": ["channel_down"]})]

    # ── Close app ────────────────────────────────────────────────
    if re.search(r"\b(close|exit|quit)\s+(the )?(app|current app)\b", t):
        return [("tv_close_app", {})]

    # ── Notify ───────────────────────────────────────────────────
    m = re.search(r"(?:send|show|display)\s+(?:a )?(?:notification|toast|message)\s+(?:on\s+(?:the\s+)?(?:tv|telly)\s+)?[\"']?(.+?)[\"']?$", t)
    if m:
        return [("tv_notify", {"message": m.group(1).strip()})]

    # ── Status ───────────────────────────────────────────────────
    if re.search(r"(what.{0,10}(on|playing)|is.{0,5}tv.{0,5}on|tv status|what.{0,5}volume|what.{0,5}app)", t):
        return [("tv_status", {})]

    # ── Launch app (simple) ──────────────────────────────────────
    # "put on netflix", "open youtube", "launch disney", "switch to hdmi2"
    m = re.search(r"(?:put on|open|launch|switch to|go to|play)\s+(.+?)(?:\s+on\s+(?:the\s+)?(?:tv|telly))?$", t)
    if m:
        app_raw = m.group(1).strip().rstrip(".")
        # Remove "the" prefix
        app_raw = re.sub(r"^the\s+", "", app_raw)
        app_name = _APP_ALIASES.get(app_raw)
        if app_name:
            return [("tv_launch_app", {"app_name": app_name})]

    # "netflix on tv", "youtube on the telly"
    m = re.match(r"(\w[\w\s]*?)\s+on\s+(?:the\s+)?(?:tv|telly|television)", t)
    if m:
        app_raw = m.group(1).strip()
        app_name = _APP_ALIASES.get(app_raw)
        if app_name:
            return [("tv_launch_app", {"app_name": app_name})]

    # ── No fast match → LLM handles it ──────────────────────────
    return None


def _format_result(tool_name: str, result) -> str:
    """Build a short, FRIDAY-style response from a tool result."""
    if not result.success:
        err = result.error
        if err:
            msg = err.message if hasattr(err, "message") else str(err)
            return f"Didn't work — {msg}"
        return f"Didn't work — {result.data}"

    data = result.data or {}

    if tool_name == "turn_on_tv":
        return "TV's turning on. Give it a few seconds."
    if tool_name == "turn_off_tv":
        return "TV's off."
    if tool_name == "tv_volume":
        v = data.get("volume", "?")
        verified = data.get("verified", False)
        return f"Volume set to {v}." if verified else f"Volume command sent ({v}) but couldn't verify."
    if tool_name == "tv_volume_adjust":
        prev = data.get("previous_volume", "?")
        new = data.get("new_volume", "?")
        direction = data.get("direction", "")
        return f"Volume {'up' if direction == 'up' else 'down'}: {prev} → {new}."
    if tool_name == "tv_mute":
        return "Muted." if data.get("muted") else "Unmuted."
    if tool_name == "tv_play_pause":
        action = data.get("action", "done")
        labels = {"play": "Playing.", "pause": "Paused.", "stop": "Stopped.",
                  "rewind": "Rewinding.", "fastforward": "Fast forwarding."}
        return labels.get(action, f"{action.title()}.")
    if tool_name == "tv_launch_app":
        app = data.get("launched", "app")
        verified = data.get("verified", False)
        if verified:
            return f"{app.title()}'s on."
        return f"Tried to launch {app} but TV is showing {data.get('current_app', 'something else')}."
    if tool_name == "tv_type_text":
        return f"Typed '{data.get('typed', '')}' on the TV."
    if tool_name == "tv_remote_button":
        return f"Pressed {data.get('buttons_pressed', [])}."
    if tool_name == "tv_status":
        if not data.get("on", False):
            return "TV's off."
        app = data.get("current_app", "unknown")
        vol = data.get("volume", "?")
        muted = " (muted)" if data.get("muted") else ""
        return f"TV's on. {app} is playing, volume at {vol}{muted}."

    if tool_name == "tv_screen_off":
        return "Screen's off. Audio still playing."
    if tool_name == "tv_screen_on":
        return "Screen's back on."
    if tool_name == "tv_close_app":
        return f"Closed {data.get('closed', 'the app')}."
    if tool_name == "tv_notify":
        return f"Notification sent."
    if tool_name == "tv_list_apps":
        apps = data.get("apps", [])
        return f"{len(apps)} apps installed." if apps else "Couldn't list apps."
    if tool_name == "tv_list_sources":
        sources = data.get("sources", [])
        return f"Sources: {', '.join(sources)}." if sources else "Couldn't list sources."
    if tool_name == "tv_set_source":
        return f"Switched to {data.get('source', 'input')}."
    if tool_name == "tv_get_audio_output":
        return f"Audio output: {data.get('audio_output', 'unknown')}."
    if tool_name == "tv_set_audio_output":
        return f"Audio switched to {data.get('audio_output', 'new output')}."
    if tool_name == "tv_system_info":
        return f"Got system info."

    return f"Done. {data}"


# ── System prompt (only used for complex commands) ───────────────────────────

SYSTEM_PROMPT = """You control smart devices in the user's home.

ALWAYS respond in English. Be brief — one sentence max for simple actions.

ABSOLUTE RULES:
1. EVERY device action MUST be a tool call. No faking.
2. If a tool returns success=False, say it failed.
3. If verified=False, say the command was sent but didn't take effect.

CURRENTLY INTEGRATED:
- LG TV (local WebOS over WiFi)

TV COMMANDS:
- turn_on_tv / turn_off_tv — power control
- tv_screen_off / tv_screen_on — screen only (audio keeps playing)
- tv_volume(level) — set exact volume 0-100
- tv_volume_adjust(direction, amount) — relative volume
- tv_mute(mute) — mute/unmute
- tv_launch_app(app_name) — launch app (netflix, youtube, spotify, prime, disney, apple tv, hdmi1-4)
- tv_close_app(app_name) — close an app
- tv_list_apps — list installed apps
- tv_list_sources / tv_set_source(source_id) — switch HDMI/inputs
- tv_play_pause(action) — play/pause/stop/rewind/fastforward
- tv_remote_button(buttons) — full remote: nav, media, numbers (num_0-9), colours (red/green/yellow/blue), special (cc, asterisk, dash, info)
- tv_type_text(text) — type text into search bars via IME
- tv_notify(message) — send toast notification to TV
- tv_get_audio_output / tv_set_audio_output(output) — audio output switching
- tv_system_info — TV software/hardware info
- tv_status — get current state

SEARCHING FOR SHOWS/MOVIES IN APPS:
When the user says "play Black Widow on Disney" or "find Iron Man on Netflix":
1. tv_launch_app("disney") — launch the app
2. tv_remote_button(buttons=["ok"]) — select profile
3. Navigate to search:
   - Disney+: tv_remote_button(buttons=["up", "up", "right", "ok"])
   - Netflix: tv_remote_button(buttons=["up", "up", "left", "left", "ok"])
   - YouTube: tv_remote_button(buttons=["up", "up", "ok"])
4. tv_type_text("Black Widow") — types and submits
5. tv_remote_button(buttons=["down", "ok"]) — select first result
6. tv_remote_button(buttons=["ok"]) — play

PROFILE SELECTION:
After launching streaming apps, press ok to select first profile.

If the TV is unreachable, say so."""


class HouseholdAgent(BaseAgent):
    name = "household_agent"
    system_prompt = SYSTEM_PROMPT
    max_iterations = 8

    def __init__(self):
        self.tools = {**TV_TOOLS}
        # Music control sometimes lands here via the router ("pause the music",
        # "skip this song"). Give the LLM access so it can pick correctly.
        try:
            from friday.tools.mac_tools import TOOL_SCHEMAS as MAC_TOOLS
            self.tools["play_music"] = MAC_TOOLS["play_music"]
        except Exception:
            pass
        super().__init__()

    async def run(self, task: str, context: str = "", on_tool_call=None, on_chunk=None):
        """Fast-path simple commands, LLM for complex ones."""
        import asyncio
        start = time.monotonic()

        fast = _fast_match(task)
        if fast is not None:
            # Execute tool calls directly — no LLM needed
            tools_called = []
            results_text = []
            all_success = True

            for i, (tool_name, tool_args) in enumerate(fast):
                tools_called.append(tool_name)
                if on_tool_call:
                    on_tool_call(tool_name, tool_args)

                # If previous step was turn_on_tv, wait for boot
                if i > 0 and tools_called[i - 1] == "turn_on_tv":
                    await asyncio.sleep(6)

                result = await self.execute_tool(tool_name, tool_args)
                results_text.append(_format_result(tool_name, result))

                if not result.success:
                    all_success = False
                    break

            return AgentResponse(
                agent_name=self.name,
                success=all_success,
                result=" ".join(results_text),
                tools_called=tools_called,
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        # Complex command → LLM handles it
        return await super().run(task=task, context=context, on_tool_call=on_tool_call, on_chunk=on_chunk)
