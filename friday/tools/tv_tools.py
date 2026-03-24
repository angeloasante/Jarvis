"""LG TV control tools — WebOS local API + WakeOnLan.

Controls LG TV over local WiFi. No cloud. No LG account.
Requires one-time pairing: uv run python -m friday.tools.tv_tools

Full command suite:
  Power:    on (WOL), off, screen_off, screen_on
  Volume:   set, adjust, mute/unmute
  Media:    play, pause, stop, rewind, fastforward
  Apps:     launch, close, list
  Input:    switch HDMI/sources
  Remote:   full button set (nav, media, numbers, colours)
  Text:     type into search bars via IME
  Screen:   screen on/off (ambient mode)
  Notify:   send toast notifications to TV
  Audio:    switch audio output (TV speakers, soundbar, etc.)
  Status:   current state (on/off, volume, app, muted)

Env vars (.env):
  LG_TV_IP=192.168.1.xx
  LG_TV_MAC=AA:BB:CC:DD:EE:FF
  LG_TV_CLIENT_KEY=<from pairing>
"""

import asyncio
import os
from typing import Optional

from friday.core.types import ToolResult, ToolError, ErrorCode, Severity
from friday.core.config import *  # Ensures .env is loaded

TV_IP = os.environ.get("LG_TV_IP", "")
TV_MAC = os.environ.get("LG_TV_MAC", "")
TV_CLIENT_KEY = os.environ.get("LG_TV_CLIENT_KEY", "")

# Known app IDs on webOS
APP_IDS = {
    "netflix": "netflix",
    "youtube": "youtube.leanback.v4",
    "spotify": "spotify-beehive",
    "prime": "com.amazon.amazonvideo.livingroom",
    "amazon": "com.amazon.amazonvideo.livingroom",
    "disney": "com.disney.disneyplus-prod",
    "disney+": "com.disney.disneyplus-prod",
    "apple tv": "com.apple.appletv",
    "appletv": "com.apple.appletv",
    "browser": "com.webos.app.browser",
    "hdmi1": "com.webos.app.hdmi1",
    "hdmi2": "com.webos.app.hdmi2",
    "hdmi3": "com.webos.app.hdmi3",
    "hdmi4": "com.webos.app.hdmi4",
    "live tv": "com.webos.app.livetv",
    "settings": "com.webos.app.settings",
}

# Reverse lookup: app_id → friendly name
APP_NAMES = {}
for name, app_id in APP_IDS.items():
    if app_id not in APP_NAMES:
        APP_NAMES[app_id] = name.title()

# Full set of valid remote buttons (everything pywebostv InputControl supports)
VALID_BUTTONS = {
    # Navigation
    "up", "down", "left", "right", "ok", "back", "home", "menu", "exit",
    "dash", "info",
    # Media
    "play", "pause", "stop", "rewind", "fastforward",
    "volume_up", "volume_down", "channel_up", "channel_down", "mute",
    # Colour buttons (BBC iPlayer, Freeview, etc.)
    "red", "green", "yellow", "blue",
    # Number pad
    "num_0", "num_1", "num_2", "num_3", "num_4",
    "num_5", "num_6", "num_7", "num_8", "num_9",
    # Special
    "asterisk", "cc",
}

_client = None
_store = {}


def _check_config() -> Optional[ToolError]:
    """Check if TV is configured."""
    if not TV_IP:
        return ToolError(
            code=ErrorCode.CONFIG_MISSING,
            message="LG_TV_IP not set in .env. Add your TV's local IP address.",
            severity=Severity.HIGH,
            recoverable=False,
        )
    return None


def _get_client():
    """Connect to the TV. Returns client or None."""
    global _client, _store

    if not TV_IP:
        return None

    try:
        from pywebostv.connection import WebOSClient

        if TV_CLIENT_KEY:
            _store = {"client_key": TV_CLIENT_KEY}

        client = WebOSClient(TV_IP, _store)
        client.connect()

        for status in client.register(_store):
            if status == WebOSClient.REGISTERED:
                _client = client
                return client
        return None
    except Exception:
        return None


def _not_reachable(action: str = "command") -> ToolResult:
    return ToolResult(
        success=False,
        error=ToolError(
            code=ErrorCode.NETWORK_ERROR,
            message=f"TV not reachable for {action}. Is it on?",
            severity=Severity.MEDIUM,
            recoverable=True,
        ),
    )


# ═════════════════════════════════════════════════════════════════════════════
# POWER
# ═════════════════════════════════════════════════════════════════════════════


async def turn_on_tv() -> ToolResult:
    """Turn on the LG TV using WakeOnLan magic packet."""
    config_err = _check_config()
    if config_err:
        return ToolResult(success=False, error=config_err)

    if not TV_MAC:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.CONFIG_MISSING,
                message="LG_TV_MAC not set in .env.",
                severity=Severity.HIGH,
                recoverable=False,
            ),
        )

    try:
        from wakeonlan import send_magic_packet

        await asyncio.to_thread(send_magic_packet, TV_MAC)
        return ToolResult(
            success=True,
            data={"action": "power_on", "mac": TV_MAC, "note": "WOL sent. TV boots in ~5s."},
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=ToolError(code=ErrorCode.NETWORK_ERROR, message=f"WOL failed: {e}",
                            severity=Severity.MEDIUM, recoverable=True),
        )


async def turn_off_tv() -> ToolResult:
    """Turn off the LG TV."""
    config_err = _check_config()
    if config_err:
        return ToolResult(success=False, error=config_err)

    client = await asyncio.to_thread(_get_client)
    if not client:
        return _not_reachable("power_off")

    try:
        from pywebostv.controls import SystemControl
        await asyncio.to_thread(SystemControl(client).power_off)
        return ToolResult(success=True, data={"action": "power_off"})
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=str(e),
            severity=Severity.MEDIUM, recoverable=True))


async def tv_screen_off() -> ToolResult:
    """Turn off the TV screen only (ambient mode). Audio keeps playing."""
    config_err = _check_config()
    if config_err:
        return ToolResult(success=False, error=config_err)

    client = await asyncio.to_thread(_get_client)
    if not client:
        return _not_reachable("screen_off")

    try:
        from pywebostv.controls import SystemControl
        await asyncio.to_thread(SystemControl(client).screen_off)
        return ToolResult(success=True, data={"action": "screen_off", "note": "Screen off, audio still playing."})
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Screen off failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


async def tv_screen_on() -> ToolResult:
    """Turn the TV screen back on after screen_off."""
    config_err = _check_config()
    if config_err:
        return ToolResult(success=False, error=config_err)

    client = await asyncio.to_thread(_get_client)
    if not client:
        return _not_reachable("screen_on")

    try:
        from pywebostv.controls import SystemControl
        await asyncio.to_thread(SystemControl(client).screen_on)
        return ToolResult(success=True, data={"action": "screen_on"})
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Screen on failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


# ═════════════════════════════════════════════════════════════════════════════
# VOLUME
# ═════════════════════════════════════════════════════════════════════════════


async def tv_volume(level: int) -> ToolResult:
    """Set TV volume (0-100) with verification."""
    config_err = _check_config()
    if config_err:
        return ToolResult(success=False, error=config_err)

    level = max(0, min(100, level))
    client = await asyncio.to_thread(_get_client)
    if not client:
        return _not_reachable("volume")

    try:
        from pywebostv.controls import MediaControl
        mc = MediaControl(client)
        await asyncio.to_thread(mc.set_volume, level)

        await asyncio.sleep(0.3)
        vol_info = await asyncio.to_thread(mc.get_volume)
        actual = vol_info.get("volume", vol_info) if isinstance(vol_info, dict) else vol_info

        if actual != level:
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=f"TV reports volume={actual}, not {level}.",
                severity=Severity.MEDIUM, recoverable=True))

        return ToolResult(success=True, data={"volume": actual, "verified": True})
    except Exception as e:
        return ToolResult(success=False, data=str(e))


async def tv_volume_adjust(direction: str = "up", amount: int = 5) -> ToolResult:
    """Adjust TV volume up or down by a relative amount."""
    config_err = _check_config()
    if config_err:
        return ToolResult(success=False, error=config_err)

    client = await asyncio.to_thread(_get_client)
    if not client:
        return _not_reachable("volume_adjust")

    try:
        from pywebostv.controls import MediaControl
        mc = MediaControl(client)
        vol_info = await asyncio.to_thread(mc.get_volume)
        current = vol_info.get("volume", 0) if isinstance(vol_info, dict) else vol_info

        new_level = max(0, current - amount) if direction.lower() == "down" else min(100, current + amount)
        await asyncio.to_thread(mc.set_volume, new_level)

        await asyncio.sleep(0.3)
        vol_check = await asyncio.to_thread(mc.get_volume)
        actual = vol_check.get("volume", vol_check) if isinstance(vol_check, dict) else vol_check

        return ToolResult(success=True, data={
            "previous_volume": current, "new_volume": actual,
            "direction": direction, "adjusted_by": amount,
            "verified": actual == new_level,
        })
    except Exception as e:
        return ToolResult(success=False, data=str(e))


async def tv_mute(mute: bool = True) -> ToolResult:
    """Mute or unmute the TV."""
    config_err = _check_config()
    if config_err:
        return ToolResult(success=False, error=config_err)

    client = await asyncio.to_thread(_get_client)
    if not client:
        return _not_reachable("mute")

    try:
        from pywebostv.controls import MediaControl
        await asyncio.to_thread(MediaControl(client).mute, mute)
        return ToolResult(success=True, data={"muted": mute})
    except Exception as e:
        return ToolResult(success=False, data=str(e))


# ═════════════════════════════════════════════════════════════════════════════
# MEDIA PLAYBACK
# ═════════════════════════════════════════════════════════════════════════════


async def tv_play_pause(action: str = "play") -> ToolResult:
    """Play, pause, stop, rewind, or fast-forward content on the TV."""
    config_err = _check_config()
    if config_err:
        return ToolResult(success=False, error=config_err)

    valid = {"play", "pause", "stop", "rewind", "fastforward"}
    action = action.lower().strip()
    if action == "resume":
        action = "play"
    if action in ("fast forward", "ff"):
        action = "fastforward"

    if action not in valid:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"Invalid action '{action}'. Valid: {sorted(valid)}",
            severity=Severity.LOW, recoverable=True))

    client = await asyncio.to_thread(_get_client)
    if not client:
        return _not_reachable("media")

    try:
        from pywebostv.controls import MediaControl
        mc = MediaControl(client)
        # MediaControl uses fast_forward, not fastforward
        method_name = "fast_forward" if action == "fastforward" else action
        await asyncio.to_thread(getattr(mc, method_name))
        return ToolResult(success=True, data={"action": action})
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Media control failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


# ═════════════════════════════════════════════════════════════════════════════
# APPS
# ═════════════════════════════════════════════════════════════════════════════


async def tv_launch_app(app_name: str) -> ToolResult:
    """Launch an app on the TV with verification."""
    config_err = _check_config()
    if config_err:
        return ToolResult(success=False, error=config_err)

    client = await asyncio.to_thread(_get_client)
    if not client:
        return _not_reachable("launch_app")

    app_id = APP_IDS.get(app_name.lower().strip(), app_name)

    try:
        from pywebostv.controls import ApplicationControl
        ac = ApplicationControl(client)
        apps = await asyncio.to_thread(ac.list_apps)
        app_obj = next((a for a in apps if a["id"] == app_id), None)

        if not app_obj:
            available = ", ".join(sorted(APP_IDS.keys()))
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=f"App '{app_name}' not found. Available: {available}",
                severity=Severity.MEDIUM, recoverable=True))

        await asyncio.to_thread(ac.launch, app_obj)

        # Verify
        await asyncio.sleep(2)
        current = await asyncio.to_thread(ac.get_current)
        if current != app_id:
            await asyncio.sleep(3)
            current = await asyncio.to_thread(ac.get_current)

        ok = current == app_id
        return ToolResult(
            success=ok,
            data={"launched": app_name, "app_id": app_id, "verified": ok,
                  "current_app": APP_NAMES.get(current, current) if not ok else app_name},
            error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=f"TV showing '{APP_NAMES.get(current, current)}' not '{app_name}'",
                severity=Severity.MEDIUM, recoverable=True) if not ok else None,
        )
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Launch failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


async def tv_close_app(app_name: str = "") -> ToolResult:
    """Close the current or a specific app on the TV."""
    config_err = _check_config()
    if config_err:
        return ToolResult(success=False, error=config_err)

    client = await asyncio.to_thread(_get_client)
    if not client:
        return _not_reachable("close_app")

    try:
        from pywebostv.controls import ApplicationControl
        ac = ApplicationControl(client)

        if app_name:
            app_id = APP_IDS.get(app_name.lower().strip(), app_name)
        else:
            app_id = await asyncio.to_thread(ac.get_current)

        await asyncio.to_thread(ac.close, {"id": app_id})
        return ToolResult(success=True, data={"closed": app_name or app_id})
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Close failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


async def tv_list_apps() -> ToolResult:
    """List all installed apps on the TV."""
    config_err = _check_config()
    if config_err:
        return ToolResult(success=False, error=config_err)

    client = await asyncio.to_thread(_get_client)
    if not client:
        return _not_reachable("list_apps")

    try:
        from pywebostv.controls import ApplicationControl
        apps = await asyncio.to_thread(ApplicationControl(client).list_apps)
        app_list = [{"id": a["id"], "title": a.get("title", a["id"])} for a in apps]
        return ToolResult(success=True, data={"apps": app_list, "count": len(app_list)})
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"List apps failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


# ═════════════════════════════════════════════════════════════════════════════
# INPUT / SOURCES
# ═════════════════════════════════════════════════════════════════════════════


async def tv_list_sources() -> ToolResult:
    """List available input sources (HDMI ports, antenna, etc.)."""
    config_err = _check_config()
    if config_err:
        return ToolResult(success=False, error=config_err)

    client = await asyncio.to_thread(_get_client)
    if not client:
        return _not_reachable("list_sources")

    try:
        from pywebostv.controls import SourceControl
        sources = await asyncio.to_thread(SourceControl(client).list_sources)
        src_list = [{"id": s.get("id", ""), "label": s.get("label", s.get("id", ""))} for s in sources]
        return ToolResult(success=True, data={"sources": src_list, "count": len(src_list)})
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"List sources failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


async def tv_set_source(source_id: str) -> ToolResult:
    """Switch TV input source (e.g. HDMI_1, HDMI_2, COMP_1)."""
    config_err = _check_config()
    if config_err:
        return ToolResult(success=False, error=config_err)

    client = await asyncio.to_thread(_get_client)
    if not client:
        return _not_reachable("set_source")

    try:
        from pywebostv.controls import SourceControl
        sc = SourceControl(client)
        sources = await asyncio.to_thread(sc.list_sources)
        source = next((s for s in sources if s.get("id", "").lower() == source_id.lower()), None)
        if not source:
            available = [s.get("id", "") for s in sources]
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=f"Source '{source_id}' not found. Available: {available}",
                severity=Severity.MEDIUM, recoverable=True))

        await asyncio.to_thread(sc.set_source, source)
        return ToolResult(success=True, data={"source": source_id})
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Set source failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


# ═════════════════════════════════════════════════════════════════════════════
# REMOTE CONTROL (full button set)
# ═════════════════════════════════════════════════════════════════════════════


async def tv_remote_button(buttons: list[str], delay: float = 0.5) -> ToolResult:
    """Send remote control button presses to the TV.

    Full button set:
      Navigation: up, down, left, right, ok, back, home, menu, exit, dash, info
      Media:      play, pause, stop, rewind, fastforward
      Volume:     volume_up, volume_down, mute
      Channels:   channel_up, channel_down
      Colours:    red, green, yellow, blue (for BBC iPlayer, Freeview, etc.)
      Numbers:    num_0 through num_9
      Special:    asterisk, cc (closed captions)

    IMPORTANT: Always disconnect_input after use — leaving it connected
    can make the physical remote stop working.
    """
    config_err = _check_config()
    if config_err:
        return ToolResult(success=False, error=config_err)

    invalid = [b for b in buttons if b.lower() not in VALID_BUTTONS]
    if invalid:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"Invalid buttons: {invalid}. Valid: {sorted(VALID_BUTTONS)}",
            severity=Severity.LOW, recoverable=True))

    client = await asyncio.to_thread(_get_client)
    if not client:
        return _not_reachable("remote")

    try:
        from pywebostv.controls import InputControl
        ic = InputControl(client)
        await asyncio.to_thread(ic.connect_input)

        pressed = []
        for btn in buttons:
            btn_lower = btn.lower()
            await asyncio.to_thread(getattr(ic, btn_lower))
            pressed.append(btn_lower)
            if delay > 0 and btn != buttons[-1]:
                await asyncio.sleep(delay)

        await asyncio.to_thread(ic.disconnect_input)
        return ToolResult(success=True, data={"buttons_pressed": pressed})
    except Exception as e:
        # Always try to disconnect on error
        try:
            await asyncio.to_thread(ic.disconnect_input)
        except Exception:
            pass
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Remote failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


# ═════════════════════════════════════════════════════════════════════════════
# TEXT INPUT (IME)
# ═════════════════════════════════════════════════════════════════════════════


async def tv_type_text(text: str, submit: bool = True) -> ToolResult:
    """Type text into the TV's on-screen keyboard (search bars, text fields).

    Uses WebOS IME to insert text directly — no virtual keyboard navigation.

    Args:
        text: The text to type
        submit: If True, press Enter after typing (default True)
    """
    config_err = _check_config()
    if config_err:
        return ToolResult(success=False, error=config_err)

    client = await asyncio.to_thread(_get_client)
    if not client:
        return _not_reachable("type_text")

    try:
        from pywebostv.controls import InputControl
        ic = InputControl(client)
        await asyncio.to_thread(ic.connect_input)

        await asyncio.to_thread(ic.type, text)
        if submit:
            await asyncio.sleep(0.5)
            await asyncio.to_thread(ic.enter)

        await asyncio.to_thread(ic.disconnect_input)
        return ToolResult(success=True, data={"typed": text, "submitted": submit})
    except Exception as e:
        try:
            await asyncio.to_thread(ic.disconnect_input)
        except Exception:
            pass
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Text input failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


# ═════════════════════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ═════════════════════════════════════════════════════════════════════════════


async def tv_notify(message: str) -> ToolResult:
    """Send a toast notification to the TV screen."""
    config_err = _check_config()
    if config_err:
        return ToolResult(success=False, error=config_err)

    client = await asyncio.to_thread(_get_client)
    if not client:
        return _not_reachable("notify")

    try:
        from pywebostv.controls import SystemControl
        await asyncio.to_thread(SystemControl(client).notify, message)
        return ToolResult(success=True, data={"message": message})
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Notification failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


# ═════════════════════════════════════════════════════════════════════════════
# AUDIO OUTPUT
# ═════════════════════════════════════════════════════════════════════════════


async def tv_get_audio_output() -> ToolResult:
    """Get current audio output device (TV speakers, soundbar, etc.)."""
    config_err = _check_config()
    if config_err:
        return ToolResult(success=False, error=config_err)

    client = await asyncio.to_thread(_get_client)
    if not client:
        return _not_reachable("audio_output")

    try:
        from pywebostv.controls import MediaControl
        output = await asyncio.to_thread(MediaControl(client).get_audio_output)
        return ToolResult(success=True, data={"audio_output": output})
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Get audio output failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


async def tv_set_audio_output(output: str) -> ToolResult:
    """Switch audio output (e.g. 'tv_speaker', 'external_arc', 'external_optical')."""
    config_err = _check_config()
    if config_err:
        return ToolResult(success=False, error=config_err)

    client = await asyncio.to_thread(_get_client)
    if not client:
        return _not_reachable("set_audio_output")

    try:
        from pywebostv.controls import MediaControl
        await asyncio.to_thread(MediaControl(client).set_audio_output, output)
        return ToolResult(success=True, data={"audio_output": output})
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Set audio output failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


# ═════════════════════════════════════════════════════════════════════════════
# SYSTEM INFO
# ═════════════════════════════════════════════════════════════════════════════


async def tv_system_info() -> ToolResult:
    """Get TV system/software information."""
    config_err = _check_config()
    if config_err:
        return ToolResult(success=False, error=config_err)

    client = await asyncio.to_thread(_get_client)
    if not client:
        return _not_reachable("system_info")

    try:
        from pywebostv.controls import SystemControl
        info = await asyncio.to_thread(SystemControl(client).info)
        return ToolResult(success=True, data=info)
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"System info failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


# ═════════════════════════════════════════════════════════════════════════════
# STATUS
# ═════════════════════════════════════════════════════════════════════════════


async def tv_status() -> ToolResult:
    """Get current TV state — on/off, volume, muted, current app."""
    config_err = _check_config()
    if config_err:
        return ToolResult(success=False, error=config_err)

    client = await asyncio.to_thread(_get_client)
    if not client:
        return ToolResult(success=True, data={"on": False, "reachable": False})

    try:
        from pywebostv.controls import MediaControl, ApplicationControl

        vol_info = await asyncio.to_thread(MediaControl(client).get_volume)
        current_app_id = await asyncio.to_thread(ApplicationControl(client).get_current)
        current_app_name = APP_NAMES.get(current_app_id, current_app_id)

        vol_level = vol_info.get("volume", vol_info) if isinstance(vol_info, dict) else vol_info
        is_muted = vol_info.get("muted", False) if isinstance(vol_info, dict) else False

        return ToolResult(success=True, data={
            "on": True, "volume": vol_level, "muted": is_muted,
            "current_app": current_app_name, "current_app_id": current_app_id,
        })
    except Exception:
        return ToolResult(success=True, data={"on": False, "reachable": False})


# ═════════════════════════════════════════════════════════════════════════════
# TOOL SCHEMAS (for LLM agent registration)
# ═════════════════════════════════════════════════════════════════════════════

TOOL_SCHEMAS = {
    # ── Power ──
    "turn_on_tv": {
        "fn": turn_on_tv,
        "schema": {"type": "function", "function": {
            "name": "turn_on_tv",
            "description": "Turn on the LG TV using WakeOnLan.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
    },
    "turn_off_tv": {
        "fn": turn_off_tv,
        "schema": {"type": "function", "function": {
            "name": "turn_off_tv",
            "description": "Turn off the LG TV.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
    },
    "tv_screen_off": {
        "fn": tv_screen_off,
        "schema": {"type": "function", "function": {
            "name": "tv_screen_off",
            "description": "Turn off the TV screen only. Audio keeps playing. Good for listening to Spotify on TV without the screen.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
    },
    "tv_screen_on": {
        "fn": tv_screen_on,
        "schema": {"type": "function", "function": {
            "name": "tv_screen_on",
            "description": "Turn the TV screen back on after screen_off.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
    },

    # ── Volume ──
    "tv_volume": {
        "fn": tv_volume,
        "schema": {"type": "function", "function": {
            "name": "tv_volume",
            "description": "Set TV volume to an exact level (0-100).",
            "parameters": {"type": "object", "properties": {
                "level": {"type": "integer", "description": "Volume level 0-100"},
            }, "required": ["level"]},
        }},
    },
    "tv_volume_adjust": {
        "fn": tv_volume_adjust,
        "schema": {"type": "function", "function": {
            "name": "tv_volume_adjust",
            "description": "Adjust TV volume up or down by a relative amount. Default: 5.",
            "parameters": {"type": "object", "properties": {
                "direction": {"type": "string", "enum": ["up", "down"]},
                "amount": {"type": "integer", "description": "Adjustment amount (default 5)"},
            }, "required": ["direction"]},
        }},
    },
    "tv_mute": {
        "fn": tv_mute,
        "schema": {"type": "function", "function": {
            "name": "tv_mute",
            "description": "Mute or unmute the TV.",
            "parameters": {"type": "object", "properties": {
                "mute": {"type": "boolean", "description": "True=mute, False=unmute"},
            }, "required": []},
        }},
    },

    # ── Media ──
    "tv_play_pause": {
        "fn": tv_play_pause,
        "schema": {"type": "function", "function": {
            "name": "tv_play_pause",
            "description": "Play, pause, stop, rewind, or fast-forward content.",
            "parameters": {"type": "object", "properties": {
                "action": {"type": "string", "enum": ["play", "pause", "stop", "rewind", "fastforward"]},
            }, "required": ["action"]},
        }},
    },

    # ── Apps ──
    "tv_launch_app": {
        "fn": tv_launch_app,
        "schema": {"type": "function", "function": {
            "name": "tv_launch_app",
            "description": "Launch an app. Supported: netflix, youtube, spotify, prime, disney, apple tv, browser, hdmi1-4, live tv, settings.",
            "parameters": {"type": "object", "properties": {
                "app_name": {"type": "string", "description": "App name (e.g. 'netflix', 'youtube', 'hdmi1')"},
            }, "required": ["app_name"]},
        }},
    },
    "tv_close_app": {
        "fn": tv_close_app,
        "schema": {"type": "function", "function": {
            "name": "tv_close_app",
            "description": "Close the current app or a specific app.",
            "parameters": {"type": "object", "properties": {
                "app_name": {"type": "string", "description": "App to close (blank = current app)"},
            }, "required": []},
        }},
    },
    "tv_list_apps": {
        "fn": tv_list_apps,
        "schema": {"type": "function", "function": {
            "name": "tv_list_apps",
            "description": "List all installed apps on the TV.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
    },

    # ── Sources ──
    "tv_list_sources": {
        "fn": tv_list_sources,
        "schema": {"type": "function", "function": {
            "name": "tv_list_sources",
            "description": "List available input sources (HDMI ports, antenna, etc.).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
    },
    "tv_set_source": {
        "fn": tv_set_source,
        "schema": {"type": "function", "function": {
            "name": "tv_set_source",
            "description": "Switch TV input source (e.g. HDMI_1, HDMI_2, COMP_1).",
            "parameters": {"type": "object", "properties": {
                "source_id": {"type": "string", "description": "Source ID from tv_list_sources"},
            }, "required": ["source_id"]},
        }},
    },

    # ── Remote ──
    "tv_remote_button": {
        "fn": tv_remote_button,
        "schema": {"type": "function", "function": {
            "name": "tv_remote_button",
            "description": (
                "Send remote button presses. Full set: "
                "Navigation: up/down/left/right/ok/back/home/menu/exit/dash/info. "
                "Media: play/pause/stop/rewind/fastforward/volume_up/volume_down/mute/channel_up/channel_down. "
                "Colours: red/green/yellow/blue. "
                "Numbers: num_0 to num_9. "
                "Special: asterisk, cc."
            ),
            "parameters": {"type": "object", "properties": {
                "buttons": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Buttons to press in order",
                },
                "delay": {"type": "number", "description": "Seconds between presses (default 0.5)"},
            }, "required": ["buttons"]},
        }},
    },

    # ── Text ──
    "tv_type_text": {
        "fn": tv_type_text,
        "schema": {"type": "function", "function": {
            "name": "tv_type_text",
            "description": "Type text into TV search bar or text field via IME. Navigate to the search bar first with tv_remote_button.",
            "parameters": {"type": "object", "properties": {
                "text": {"type": "string", "description": "Text to type"},
                "submit": {"type": "boolean", "description": "Press Enter after (default True)"},
            }, "required": ["text"]},
        }},
    },

    # ── Notifications ──
    "tv_notify": {
        "fn": tv_notify,
        "schema": {"type": "function", "function": {
            "name": "tv_notify",
            "description": "Send a toast notification to the TV screen.",
            "parameters": {"type": "object", "properties": {
                "message": {"type": "string", "description": "Notification text"},
            }, "required": ["message"]},
        }},
    },

    # ── Audio ──
    "tv_get_audio_output": {
        "fn": tv_get_audio_output,
        "schema": {"type": "function", "function": {
            "name": "tv_get_audio_output",
            "description": "Get current audio output device (TV speakers, soundbar, etc.).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
    },
    "tv_set_audio_output": {
        "fn": tv_set_audio_output,
        "schema": {"type": "function", "function": {
            "name": "tv_set_audio_output",
            "description": "Switch audio output (e.g. 'tv_speaker', 'external_arc', 'external_optical').",
            "parameters": {"type": "object", "properties": {
                "output": {"type": "string", "description": "Audio output name"},
            }, "required": ["output"]},
        }},
    },

    # ── System ──
    "tv_system_info": {
        "fn": tv_system_info,
        "schema": {"type": "function", "function": {
            "name": "tv_system_info",
            "description": "Get TV system/software information.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
    },

    # ── Status ──
    "tv_status": {
        "fn": tv_status,
        "schema": {"type": "function", "function": {
            "name": "tv_status",
            "description": "Get current TV state — on/off, volume, muted, current app.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
    },
}


# ── Pairing CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    """Run this once to pair with your LG TV.
    Usage: uv run python -m friday.tools.tv_tools
    """
    import sys

    if not TV_IP:
        print("Set LG_TV_IP in your .env first.")
        print("Find your TV's IP in your router admin page or TV settings → Network.")
        sys.exit(1)

    from pywebostv.connection import WebOSClient

    store = {}
    print(f"Connecting to TV at {TV_IP}...")

    try:
        client = WebOSClient(TV_IP, store)
        client.connect()

        for status in client.register(store):
            if status == WebOSClient.PROMPTED:
                print("\n>>> Check your TV — accept the pairing request <<<\n")
            elif status == WebOSClient.REGISTERED:
                key = store.get("client_key", "")
                print(f"\nPaired! Add this to your .env:")
                print(f"LG_TV_CLIENT_KEY={key}")
                break
    except ConnectionRefusedError:
        print(f"Connection refused. Is the TV on and at {TV_IP}?")
    except Exception as e:
        print(f"Failed: {e}")
