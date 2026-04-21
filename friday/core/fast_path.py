"""Fast path — direct tool calls with zero LLM involvement.

Pattern-match common commands → call tools directly → canned response.
Sub-second. No LLM calls at all.
"""

import re


# ── Greeting patterns ────────────────────────────────────────────────────────

_GREETINGS = [
    # Standalone prefix words — "man", "bro", "fam" etc. with nothing after
    (r"^(man|bro|bruv|fam|mate|boss|chief|dawg|guy|g)[\s!?.]*$", "Yo. What's good?"),
    (r"^(you good|u good|you alright|u alright|you straight)", "Always. What's the play?"),
    (r"^(hawfar|how far)", "E dey. What we doing?"),
    (r"^(yo|oya|hey friday|hey)[\s!?.]*$", "What's good?"),
    (r"^(hello|hi|sup|wassup|wag1|wagwan|what'?s good|whats good)[\s!?.]*$", "Yo. What we on?"),
    (r"^(good morning|morning)[\s!?.]*$", "Morning. Let's get it."),
    (r"^(good night|night|gn)[\s!?.]*$", "Rest up. We go again tomorrow."),
    (r"^(thanks|thank you|cheers|safe|bet)[\s!?.]*$", "Anytime."),
    (r"^(dey there)", "Dey here. What you need?"),
    (r"^(chale)", "Chale. Talk to me."),
    (r"^(how are you|how you doing|how you dey|how body)[\s!?.]*$", "Dey here. What's the move?"),
    (r"^(hello mate|hi mate|hey mate)[\s!?.]*$", "Yo. What we on?"),
]


async def fast_path(user_input: str, conversation: list[dict]) -> str | None:
    """Pattern-match common commands → call tools directly → canned response.

    Returns response string if handled, None if LLM should take over.
    This skips ALL LLM calls. Regex → tool → done. Sub-second.
    """
    s = user_input.strip().lower()

    # Greetings — instant canned responses, no LLM
    greeting = re.sub(r"^(man|bro|bruv|g|fam|mate|boss|chief|dawg|guy)[,!.\s]+", "", s).strip()
    greeting = re.sub(r"[,!.\s]+(man|bro|bruv|g|fam|mate|boss|chief|dawg|guy)[\s!?.]*$", "", greeting).strip()

    for pattern, reply in _GREETINGS:
        if re.match(pattern, s) or re.match(pattern, greeting):
            conversation.append({"role": "user", "content": user_input})
            conversation.append({"role": "assistant", "content": reply})
            return reply

    result = await match_fast(s)
    if result is None:
        return None

    response, _ = result
    conversation.append({"role": "user", "content": user_input})
    conversation.append({"role": "assistant", "content": response})
    return response


async def match_fast(s: str):
    """Try to match input to a direct tool call. Returns (response, result) or None."""
    from friday.tools.tv_tools import (
        turn_on_tv, turn_off_tv, tv_volume, tv_volume_adjust,
        tv_mute, tv_launch_app, tv_play_pause, tv_screen_off,
        tv_screen_on, tv_status,
    )

    # ── TV Multi-step: "turn on tv and open youtube" ──
    m = re.search(
        r"^(?:turn|switch|power)\s+(?:on\s+)?(?:my\s+|the\s+)?(?:tv|telly|television)(?:\s+on)?"
        r"\s+(?:and|then|,)\s*(?:open|launch|put on|play|start)\s+"
        r"(netflix|youtube|spotify|disney\+?|disney|prime|prime video|apple tv|appletv)",
        s
    )
    if m:
        import asyncio
        app = m.group(1).strip()
        r1 = await turn_on_tv()
        if r1.success:
            await asyncio.sleep(6)  # Wait for TV to boot
            r2 = await tv_launch_app(app)
            return (f"TV's on. {app.title()}'s loading." if r2.success else f"TV's on but couldn't open {app}."), r2
        return (f"Couldn't turn on TV: {r1.error.message}" if r1.error else "Couldn't turn on TV."), r1

    # ── TV Power ──
    if re.match(r"^(turn on|switch on|power on)\s*(my |the )?(tv|telly|television)\s*[.!]?$", s):
        r = await turn_on_tv()
        return ("TV's turning on." if r.success else f"Couldn't turn on TV: {r.error.message}"), r

    if re.match(r"^(turn off|switch off|power off)\s*(my |the )?(tv|telly|television)\s*[.!]?$", s):
        r = await turn_off_tv()
        return ("TV's off." if r.success else f"Couldn't turn off TV: {r.error.message}"), r

    if re.match(r"^(?:my |the )?(tv|telly|television)\s+(on)\s*[.!]?$", s):
        r = await turn_on_tv()
        return ("TV's turning on." if r.success else f"Couldn't turn on TV: {r.error.message}"), r

    if re.match(r"^(?:my |the )?(tv|telly|television)\s+(off)\s*[.!]?$", s):
        r = await turn_off_tv()
        return ("TV's off." if r.success else f"Couldn't turn off TV: {r.error.message}"), r

    # ── TV Volume: "volume to 30" / "set volume to 30%" ──
    m = re.match(r"^(?:set\s+)?(?:tv\s+)?(?:volume|vol)\s+(?:to\s+)?(\d+)\s*%?\s*[.!]?$", s)
    if m:
        level = int(m.group(1))
        r = await tv_volume(level)
        return (f"Volume set to {level}." if r.success else f"Volume failed: {r.error.message}"), r

    # ── TV Volume: "turn it up/down" / "louder" / "quieter" ──
    if re.match(r"^(louder|turn\s*(it\s+)?up)\s*[.!]?$", s):
        r = await tv_volume_adjust("up", 10)
        return ("Turned it up." if r.success else "Couldn't adjust volume."), r

    if re.match(r"^(quieter|turn\s*(it\s+)?down)\s*[.!]?$", s):
        r = await tv_volume_adjust("down", 10)
        return ("Turned it down." if r.success else "Couldn't adjust volume."), r

    # ── TV Mute ──
    if re.match(r"^(mute|mute\s*(the )?(tv|telly))\s*[.!]?$", s):
        r = await tv_mute(True)
        return ("Muted." if r.success else "Couldn't mute."), r

    if re.match(r"^(unmute|unmute\s*(the )?(tv|telly))\s*[.!]?$", s):
        r = await tv_mute(False)
        return ("Unmuted." if r.success else "Couldn't unmute."), r

    # NOTE: bare "open netflix/spotify/youtube" (no "on tv") means the Mac app —
    # handled below (fast_path) or system_agent for unknown apps.

    # ── TV Apps on TV: "open youtube on my tv" ──
    m = re.match(
        r"^(?:open|launch|put|play|start)\s+"
        r"(netflix|youtube|spotify|disney\+?|disney|prime|prime video|apple tv|appletv)"
        r"\s+on\s+(?:my\s+|the\s+)?(?:tv|telly|television)\s*"
        r"(?:for me)?\s*[.!]?$", s
    )
    if m:
        app = m.group(1).strip()
        r = await tv_launch_app(app)
        return (f"{app.title()}'s loading." if r.success else f"Couldn't open {app}: {r.error.message}"), r

    # ── TV Pause/Resume ──
    # Only fire TV pause/resume when the user EXPLICITLY names tv/video/show/movie.
    # Bare "pause" / "pause the music" goes to the LLM so it can pick between
    # tv_play_pause (TV) and play_music (Mac Music).
    if re.match(r"^pause\s*(the\s+)?(tv|video|show|movie|telly)\s*[.!]?$", s):
        r = await tv_play_pause("pause")
        return ("Paused." if r.success else "Couldn't pause."), r

    if re.match(r"^(resume|unpause)\s*(the\s+)?(tv|video|show|movie|telly)\s*[.!]?$", s):
        r = await tv_play_pause("play")
        return ("Playing." if r.success else "Couldn't resume."), r

    # ── TV Screen off/on ──
    if re.match(r"^(screen off|turn off\s*(the )?screen)\s*[.!]?$", s):
        r = await tv_screen_off()
        return ("Screen off." if r.success else "Couldn't turn off screen."), r

    if re.match(r"^(screen on|turn on\s*(the )?screen)\s*[.!]?$", s):
        r = await tv_screen_on()
        return ("Screen on." if r.success else "Couldn't turn on screen."), r

    # ── TV Status ──
    if re.match(r"^(tv status|is\s*(my |the )?(tv|telly)\s+on|what'?s on\s*(the )?(tv|telly)?)\s*[.!]?$", s):
        r = await tv_status()
        if r.success and r.data:
            d = r.data
            return f"TV is {d.get('power', 'on')}. Volume {d.get('volume', '?')}. {d.get('app', 'No app')} is open.", r
        return ("TV seems off or unreachable." if not r.success else "TV is on."), r

    # ── Screen casting (AirPlay) ──
    # "extend my screen to [the] tv" / "cast to tv" / "mirror screen to tv"
    m = re.match(
        r"^(?:can you\s+|please\s+)?(extend|cast|mirror|share|project|send)\s+"
        r"(?:my\s+|the\s+)?(?:screen|display)\s+"
        r"(?:to|onto|on)\s+(?:my\s+|the\s+)?"
        r"(.+?)\s*[.!?]?$",
        s,
    )
    if m:
        from friday.tools.screencast_tools import cast_screen_to
        verb, target = m.group(1), m.group(2).strip()
        mode = "extend" if verb in ("extend", "project") else "mirror"
        r = await cast_screen_to(target, mode)
        if r.success:
            msg = r.data.get("message") if r.data else "Casting."
            return msg, r
        return (r.error.message if r.error else "Couldn't start casting."), r

    # "cast to [device]" — shorter form
    m = re.match(
        r"^(?:cast|mirror|airplay)\s+(?:to\s+)?(?:my\s+|the\s+)?(.+?)\s*[.!?]?$", s
    )
    if m and len(m.group(1).split()) <= 5:
        from friday.tools.screencast_tools import cast_screen_to
        target = m.group(1).strip()
        r = await cast_screen_to(target, "mirror")
        if r.success:
            msg = r.data.get("message") if r.data else "Mirroring."
            return msg, r
        return (r.error.message if r.error else "Couldn't mirror."), r

    # "stop casting" / "stop mirroring" / "stop airplay"
    if re.match(r"^stop\s+(cast(ing)?|mirror(ing)?|airplay|screen\s*share)\s*[.!?]?$", s):
        from friday.tools.screencast_tools import stop_screencast
        r = await stop_screencast()
        msg = r.data.get("message") if r.success and r.data else (r.error.message if r.error else "Stopped.")
        return msg, r

    # Note: "open X on extended/tv display" left to the LLM — too ambiguous to
    # regex-match without false positives on normal "open X on my mac" queries.

    # ── FaceTime: "facetime mom" / "call john on facetime" ──
    ft_match = re.match(
        r"^(?:facetime|face\s*time)\s+(.+?)(?:\s+audio)?(?:\s+only)?\s*[.!]?$", s
    )
    if not ft_match:
        ft_match = re.match(
            r"^(?:call|ring|phone)\s+(.+?)\s+(?:on\s+)?(?:facetime|face\s*time)\s*[.!]?$", s
        )
    if ft_match:
        from friday.tools.imessage_tools import start_facetime
        recipient = ft_match.group(1).strip()
        audio = "audio" in s
        r = await start_facetime(recipient=recipient, audio_only=audio)
        if r.success and r.data:
            if r.data.get("needs_choice"):
                # Multiple numbers — can't handle in fast path, fall through to agent
                return None
            name = r.data.get("recipient", recipient)
            call_type = r.data.get("type", "FaceTime")
            return f"Calling {name} on {call_type}.", r
        err = r.error.message if r.error else "Couldn't start FaceTime."
        return err, r

    # ── Mac app open: "open spotify" / "launch chrome" / "start notes" ──
    # Zero LLM calls — pure Python safe-list check + open -a <app>.
    # Unknown apps fall through to system_agent.
    m = re.match(
        r'^(?:open|launch|start)\s+(?:the\s+|my\s+)?(.+?)(?:\s+app(?:lication)?)?\s*[.!]?$',
        s
    )
    if m:
        from friday.tools.mac_tools import open_application, _safe_apps, APP_ALIASES
        app_raw = m.group(1).strip()
        safe = _safe_apps()
        if app_raw in safe or app_raw in APP_ALIASES:
            r = await open_application(app_raw)
            if r.success:
                display = APP_ALIASES.get(app_raw, app_raw).title()
                return f"Opening {display}.", r
            return r.error.message if r.error else "Couldn't open that app.", r

    return None
