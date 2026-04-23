"""FRIDAY CLI — text + voice interface."""

import asyncio
import os
import random
import sys
import time

from rich.console import Console
from rich.rule import Rule
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.formatted_text import HTML

from friday.core.orchestrator import FridayCore
from friday.core.config import DATA_DIR
# monitor_scheduler removed — heartbeat handles all watches now (URL, search, topic)
from friday.background.heartbeat import get_heartbeat_runner
from friday.background.cron_scheduler import get_cron_scheduler


console = Console()
HISTORY_FILE = DATA_DIR / ".friday_history"

# Colors
G = "green"
DG = "dim green"
BG = "bold green"

# Casual status quips — makes live updates feel natural
_BG_ACK = [
    "On it. Keep chatting, I'll holler when it's done.",
    "Say less. Working on it in the background.",
    "Got you. I'll hit you when it's ready.",
    "Running it now. You can keep typing.",
    "Bet. Give me a sec to pull everything.",
]


def print_banner():
    console.print()
    console.print(Rule(style=G))
    console.print()

    lines = [
        "  ███████╗██████╗ ██╗██████╗  █████╗ ██╗   ██╗",
        "  ██╔════╝██╔══██╗██║██╔══██╗██╔══██╗╚██╗ ██╔╝",
        "  █████╗  ██████╔╝██║██║  ██║███████║ ╚████╔╝ ",
        "  ██╔══╝  ██╔══██╗██║██║  ██║██╔══██║  ╚██╔╝  ",
        "  ██║     ██║  ██║██║██████╔╝██║  ██║   ██║   ",
        "  ╚═╝     ╚═╝  ╚═╝╚═╝╚═════╝ ╚═╝  ╚═╝   ╚═╝   ",
    ]
    for line in lines:
        console.print(line, style=BG)

    console.print()
    console.print("  Personal AI Operating System v0.3", style=DG)
    console.print(f"  Status: [bold green]ONLINE[/bold green]  |  /help [dim]for commands[/dim]", style=DG)
    console.print()
    console.print(Rule(style=G))
    console.print()


def dispatch_background_agent(friday: FridayCore, user_input: str):
    """Dispatch work in background — streams response or shows agent progress.

    For conversational queries: streams response inline (no "On it" message).
    For agent work: shows acknowledgment + live status + streamed synthesis.
    """
    t0 = time.monotonic()
    state = {"header_printed": False, "is_agent": False}

    def on_update(msg: str):
        if msg.startswith("ACK:"):
            # Agent work acknowledged — tell user we're on it
            state["is_agent"] = True
            ack_detail = msg[4:]
            console.print(f"  [bold green]FRIDAY[/bold green] [green]{random.choice(_BG_ACK)}[/green]")
            console.print()
        elif msg.startswith("STATUS:"):
            status_text = msg[7:]
            console.print(f"  [dim green]  ◈ {status_text}[/dim green]")
        elif msg.startswith("CHUNK:"):
            chunk = msg[6:]
            if not state["header_printed"]:
                if state["is_agent"]:
                    elapsed = time.monotonic() - t0
                    console.print()
                    console.print(f"  [bold green]FRIDAY[/bold green] [dim green]({elapsed:.0f}s)[/dim green] ", end="")
                else:
                    console.print(f"  [bold green]FRIDAY[/bold green] ", end="")
                state["header_printed"] = True
            # Stream chunk with newline indentation
            lines = chunk.split("\n")
            for i, line in enumerate(lines):
                if i > 0:
                    console.print()
                    console.print("  ", end="")
                console.print(f"[green]{line}[/green]", end="")
        elif msg.startswith("DONE:"):
            if state["header_printed"]:
                elapsed = time.monotonic() - t0
                if not state["is_agent"]:
                    console.print(f"  [dim green]({elapsed:.1f}s)[/dim green]")
                else:
                    console.print()
                console.print()
        elif msg.startswith("ERROR:"):
            error = msg[6:]
            console.print(f"\n  [red]✗ Error: {error}[/red]\n")

    friday.dispatch_background(user_input, on_update=on_update)


async def main():
    print_banner()
    friday = FridayCore()

    # Start heartbeat (proactive background checks) — handles ALL watches:
    # iMessage, WhatsApp, email, calls, URL diffing, web search, topic tracking
    try:
        from friday.tools.notify import notify_phone_async
        heartbeat = get_heartbeat_runner(notify_fn=notify_phone_async)
        await heartbeat.start()
    except Exception:
        pass  # Non-critical

    # Start cron scheduler (user-defined scheduled tasks)
    try:
        from friday.tools.notify import notify_phone_async as _cron_notify
        cron = get_cron_scheduler(notify_fn=_cron_notify)
        await cron.start()
    except Exception:
        pass  # Non-critical

    # Sync GitHub projects in background
    try:
        from friday.background.github_sync import sync_github_background
        sync_github_background()
    except Exception:
        pass  # Non-critical — FRIDAY works without project context

    # Voice pipeline
    voice_pipeline = None
    if "--voice" in sys.argv:
        try:
            from friday.voice.pipeline import VoicePipeline
            loop = asyncio.get_event_loop()
            voice_pipeline = VoicePipeline(friday, loop)
            voice_pipeline.start()
        except Exception as e:
            console.print(f"  [red]✗ Voice failed to start: {e}[/red]")

    # Gesture control
    gesture_listener = None
    if os.environ.get("FRIDAY_GESTURES", "").lower() == "true":
        try:
            from friday.vision.gesture_listener import GestureListener
            loop = asyncio.get_event_loop()
            gesture_listener = GestureListener(friday, loop)
            gesture_listener.start()
        except Exception as e:
            console.print(f"  [red]✗ Gestures failed to start: {e}[/red]")

    # SMS server (Twilio — text FRIDAY from anywhere)
    if os.environ.get("TWILIO_ACCOUNT_SID") and os.environ.get("TWILIO_AUTH_TOKEN", "") != "your_auth_token_here":
        try:
            from friday.sms.server import start_server as start_sms
            sms_loop = asyncio.get_event_loop()
            start_sms(friday=friday, loop=sms_loop)
        except Exception as e:
            console.print(f"  [red]✗ SMS server failed: {e}[/red]")

    # Telegram bot — second channel for rich media (long-polling, no tunnel)
    if os.environ.get("TELEGRAM_BOT_TOKEN", "").strip():
        try:
            from friday.telegram import start_bot as start_telegram
            tg_loop = asyncio.get_event_loop()
            tg_bot = start_telegram(friday=friday, loop=tg_loop)
            if tg_bot:
                console.print("  [bold green]:: Telegram bot ACTIVE[/bold green]")
        except Exception as e:
            console.print(f"  [red]✗ Telegram bot failed: {e}[/red]")

    # Inbound SMS tunnel — started by `friday setup twilio`. Three possible
    # configs, in priority order: static ngrok domain > ephemeral ngrok URL
    # saved from the wizard > tailscale funnel URL. The wizard auto-
    # configures Twilio to point at whichever we end up with.
    ngrok_domain   = os.environ.get("NGROK_DOMAIN", "").strip()
    ngrok_ephemeral = os.environ.get("NGROK_PUBLIC_URL", "").strip()
    ts_funnel_url  = os.environ.get("TAILSCALE_FUNNEL_URL", "").strip()
    sms_port       = os.environ.get("SMS_PORT", "3200")

    if os.environ.get("TWILIO_ACCOUNT_SID"):
        try:
            import subprocess, time as _time
            if ngrok_domain:
                subprocess.run(["pkill", "-f", "ngrok http"], capture_output=True, timeout=3)
                _time.sleep(1)
                subprocess.Popen(
                    ["ngrok", "http", sms_port, "--domain", ngrok_domain],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                console.print(f"  [bold green]:: SMS webhook ACTIVE — https://{ngrok_domain}/sms[/bold green]")
            elif ngrok_ephemeral:
                # Ephemeral URLs change every ngrok restart — warn the user.
                console.print(f"  [yellow]:: Ephemeral ngrok URL saved ({ngrok_ephemeral}).[/yellow] "
                              f"Restart ngrok manually if SMS stops: [dim]ngrok http {sms_port}[/dim]")
            elif ts_funnel_url:
                # Tailscale funnel persists across reboots when backgrounded.
                console.print(f"  [bold green]:: SMS webhook ACTIVE — {ts_funnel_url}/sms[/bold green] (Tailscale Funnel)")
        except Exception:
            pass

    session: PromptSession = PromptSession(
        history=FileHistory(str(HISTORY_FILE)),
        auto_suggest=AutoSuggestFromHistory(),
    )

    while True:
        try:
            user_input = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: session.prompt(
                    HTML('<style fg="ansibrightgreen" bg="" bold="true">▶ </style>'),
                ),
            )
        except (EOFError, KeyboardInterrupt):
            console.print("\n  [dim green]Session terminated.[/dim green]\n")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        if user_input == "/help":
            console.print()
            console.print("  [bold green]Commands[/bold green]")
            console.print("  [green]/quit[/green]              Exit FRIDAY")
            console.print("  [green]/clear[/green]             Reset conversation history")
            console.print("  [green]/memory[/green]            Show recent stored memories")
            console.print("  [green]/help[/green]              This menu")
            console.print()
            console.print("  [bold green]Voice[/bold green]")
            console.print("  [green]/voice[/green]             Toggle voice pipeline on/off")
            console.print("  [green]/listening-on[/green]      Resume ambient mic listening")
            console.print("  [green]/listening-off[/green]     Pause ambient mic listening")
            console.print()
            console.print("  [bold green]Gesture Control[/bold green]")
            console.print("  [green]/gestures-on[/green]       Start camera + gesture detection")
            console.print("  [green]/gestures-off[/green]      Stop camera + gesture detection")
            console.print("  [green]/gestures[/green]          Toggle gestures on/off")
            console.print()
            console.print("  [bold green]Background[/bold green]")
            console.print("  [green]/clearwatches[/green]      Kill all active watch tasks")
            console.print()
            console.print("  [bold green]Messaging channels[/bold green]")
            console.print("  [green]/telegram[/green]          Show Telegram bot status + chat_id")
            console.print("  [green]/sms[/green]               Show SMS webhook status + Twilio tunnel")
            console.print()
            console.print("  [bold green]Agent Override[/bold green]")
            console.print("  [green]@comms[/green]             Force route to comms agent")
            console.print("  [green]@research[/green]          Force route to research agent")
            console.print("  [green]@household[/green]         Force route to TV / smart home")
            console.print("  [green]@system[/green]            Force route to system agent")
            console.print("  [green]@social[/green]            Force route to X / Twitter agent")
            console.print("  [green]@code[/green]              Force route to code agent")
            console.print("  [green]@job[/green]               Force route to job agent")
            console.print("  [green]@memory[/green]            Force route to memory agent")
            console.print()
            # Show current status
            voice_on = voice_pipeline and voice_pipeline._running
            gesture_on = gesture_listener and gesture_listener._running
            console.print(f"  [dim]Voice: {'ON' if voice_on else 'OFF'}  |  Gestures: {'ON' if gesture_on else 'OFF'}[/dim]")
            console.print()
            continue

        if user_input == "/quit":
            if voice_pipeline:
                voice_pipeline.stop()
            if gesture_listener:
                gesture_listener.stop()
            console.print("  [dim green]Session terminated.[/dim green]\n")
            break

        if user_input == "/clear":
            friday.conversation.clear()
            console.print("  [dim green]:: Conversation cleared[/dim green]\n")
            continue

        if user_input == "/memory":
            memories = friday.memory.get_recent(10)
            if memories:
                console.print()
                for m in memories:
                    console.print(f"  [green]>[/green] [dim][{m['category']}][/dim] {m['content'][:80]}")
            else:
                console.print("  [dim green]No memories stored yet.[/dim green]")
            console.print()
            continue

        if user_input == "/voice":
            if voice_pipeline and voice_pipeline._running:
                voice_pipeline.stop()
                voice_pipeline = None
                console.print("  [dim green]:: Voice OFF[/dim green]\n")
            else:
                try:
                    from friday.voice.pipeline import VoicePipeline
                    loop = asyncio.get_event_loop()
                    voice_pipeline = VoicePipeline(friday, loop)
                    voice_pipeline.start()
                    console.print("  [bold green]:: Voice ON[/bold green]\n")
                except Exception as e:
                    console.print(f"  [red]✗ Voice failed: {e}[/red]\n")
            continue

        if user_input in ("/gestures", "/gestures-on", "/gestures-off"):
            is_on = gesture_listener and gesture_listener._running
            # Decide action: explicit on/off or toggle
            want_on = (user_input == "/gestures-on") or (user_input == "/gestures" and not is_on)
            want_off = (user_input == "/gestures-off") or (user_input == "/gestures" and is_on)

            if want_off and is_on:
                gesture_listener.stop()
                gesture_listener = None
                console.print("  [dim green]:: Gestures OFF — camera released[/dim green]\n")
            elif want_on and not is_on:
                try:
                    from friday.vision.gesture_listener import GestureListener
                    loop = asyncio.get_event_loop()
                    gesture_listener = GestureListener(friday, loop)
                    gesture_listener.start()
                except Exception as e:
                    console.print(f"  [red]✗ Gestures failed: {e}[/red]\n")
            elif want_on and is_on:
                console.print("  [dim green]:: Gestures already ON[/dim green]\n")
            else:
                console.print("  [dim green]:: Gestures already OFF[/dim green]\n")
            continue

        if user_input == "/telegram":
            tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
            allowed = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
            if not tok:
                console.print("  [dim]:: Telegram not configured. Run:[/dim] "
                              "[cyan]friday setup telegram[/cyan]\n")
            else:
                try:
                    from friday.telegram.bot import _call
                    me = _call("getMe", timeout=5)
                    username = me["result"].get("username", "?") if me.get("ok") else "?"
                    status = "ACTIVE" if me.get("ok") else "DOWN"
                    console.print(f"  [dim green]:: Telegram {status}[/dim green] — bot @{username}")
                    console.print(f"  [dim]allowed chats: {allowed or 'OPEN (no lock)'}[/dim]\n")
                except Exception as e:
                    console.print(f"  [red]:: Telegram check failed: {e}[/red]\n")
            continue

        if user_input == "/sms":
            sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
            phone = os.environ.get("TWILIO_PHONE_NUMBER", "").strip()
            domain = os.environ.get("NGROK_DOMAIN", "").strip()
            ephemeral = os.environ.get("NGROK_PUBLIC_URL", "").strip()
            ts_url = os.environ.get("TAILSCALE_FUNNEL_URL", "").strip()
            if not sid:
                console.print("  [dim]:: SMS not configured. Run:[/dim] "
                              "[cyan]friday setup twilio[/cyan]\n")
            else:
                url = (f"https://{domain}" if domain else ephemeral or ts_url or "(no tunnel)")
                console.print(f"  [dim green]:: SMS ACTIVE[/dim green] — {phone}")
                console.print(f"  [dim]webhook: {url}/sms[/dim]\n")
            continue

        if user_input == "/clearwatches":
            from friday.memory.store import get_memory_store
            db = get_memory_store().db
            count = db.execute("SELECT COUNT(*) FROM watch_tasks WHERE active = 1").fetchone()[0]
            db.execute("UPDATE watch_tasks SET active = 0 WHERE active = 1")
            db.commit()
            console.print(f"  [dim green]:: Cleared {count} active watch task(s)[/dim green]\n")
            continue

        if user_input == "/listening-off":
            if voice_pipeline:
                voice_pipeline.set_listening(False)
                console.print("  [dim green]:: Listening paused — FRIDAY won't hear ambient audio[/dim green]\n")
            else:
                console.print("  [dim]:: Voice pipeline not running. Start with /voice[/dim]\n")
            continue

        if user_input == "/listening-on":
            if voice_pipeline:
                voice_pipeline.set_listening(True)
                console.print("  [bold green]:: Listening resumed — say \"Friday\" at any time[/bold green]\n")
            else:
                console.print("  [dim]:: Voice pipeline not running. Start with /voice[/dim]\n")
            continue

        try:
            # Fast path — direct tool calls, zero LLM (TV, volume, etc.)
            t0 = time.monotonic()
            fast_result = await friday.fast_path(user_input)
            if fast_result is not None:
                elapsed = time.monotonic() - t0
                console.print(f"  [bold green]FRIDAY[/bold green] [green]{fast_result}[/green]  [dim green]({elapsed:.1f}s)[/dim green]")
                console.print()
            else:
                # All other queries — LLM decides: agent dispatch or direct response
                dispatch_background_agent(friday, user_input)

        except Exception as e:
            console.print(f"\n  [red]✗ Error: {e}[/red]\n")


def run():
    # Admin commands: `friday init`, `friday config/doctor/setup/test/heartbeat …`
    # — run without booting FRIDAY.
    from friday.core.onboarding import (
        maybe_handle_admin_command as _profile_admin,
        needs_onboarding,
        run_onboarding,
        ensure_friday_dir,
    )
    from friday.core.setup_wizard import maybe_handle_admin_command as _wizard_admin

    for handler in (_profile_admin, _wizard_admin):
        admin_exit = handler(sys.argv)
        if admin_exit is not None:
            sys.exit(admin_exit)

    # Ensure ~/.friday/ + README exist so terminal users can find their config.
    ensure_friday_dir()

    # First run (no user.json yet) → run the wizard before booting.
    if needs_onboarding() and sys.stdin.isatty():
        run_onboarding()

    asyncio.run(main())


if __name__ == "__main__":
    run()
