"""FRIDAY CLI — text + voice interface."""

import asyncio
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
from friday.background.monitor_scheduler import get_monitor_scheduler


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
    voice_flag = "--voice" in sys.argv
    voice_status = "[bold green]ACTIVE[/bold green]" if voice_flag else "[dim]off (--voice)[/dim]"
    console.print(f"  Status: [bold green]ONLINE[/bold green]  |  Model: [green]qwen3.5:9b[/green]  |  Voice: {voice_status}", style=DG)
    console.print()
    console.print(Rule(style=G))
    console.print()
    cmds = "  /quit [dim]exit[/dim]  |  /clear [dim]reset[/dim]  |  /memory [dim]recall[/dim]"
    if not voice_flag:
        cmds += "  |  /voice [dim]toggle[/dim]"
    console.print(cmds, style=DG)
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

    # Start background monitor scheduler
    try:
        scheduler = get_monitor_scheduler()
        await scheduler.start()
    except Exception:
        pass  # Non-critical — FRIDAY works fine without monitors

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

        if user_input == "/quit":
            if voice_pipeline:
                voice_pipeline.stop()
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
    asyncio.run(main())


if __name__ == "__main__":
    run()
