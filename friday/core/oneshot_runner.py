"""One-shot runner — streams FRIDAY's pipeline to stdout as NDJSON events.

Each event is a single JSON object on its own line, flushed immediately.
The Swift app reads stdout line-by-line and updates the chat in real time.

Event types:
    {"event": "chunk",  "text": "..."}     — assistant text fragment
    {"event": "media",  "path": "..."}     — file path produced by a tool
    {"event": "status", "text": "..."}     — short progress line ("searching web")
    {"event": "done"}                      — pipeline finished, no more events
    {"event": "error",  "text": "..."}     — fatal error

Usage:
    echo "take a screenshot" | uv run python -m friday.core.oneshot_runner
    uv run python -m friday.core.oneshot_runner "take a screenshot"

`--final` emits a single JSON object instead (back-compat for non-streaming
callers — kept minimal but still works).
"""

import asyncio
import json
import logging
import sys
import threading

# Silence Python logging on stdout — only NDJSON events should appear there.
logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s: %(message)s",
    stream=sys.stderr,
)


def _emit(event: str, **payload) -> None:
    """Write one NDJSON event line and flush so the consumer sees it now."""
    line = json.dumps({"event": event, **payload}, ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


async def run_stream(user_input: str) -> None:
    """Run a command and stream events to stdout."""
    from friday.core.orchestrator import FridayCore

    friday = FridayCore()

    # 1. Fast path — instant canned answer for greetings, TV commands, etc.
    fast_result = await friday.fast_path(user_input)
    if fast_result is not None:
        _emit("chunk", text=fast_result)
        _emit("done")
        return

    # 2. Streaming pipeline. dispatch_background fires events to on_update.
    done = threading.Event()
    sent_anything = {"value": False}

    def on_update(msg: str) -> None:
        if msg.startswith("CHUNK:"):
            text = msg[6:]
            if text:
                _emit("chunk", text=text)
                sent_anything["value"] = True
        elif msg.startswith("MEDIA:"):
            path = msg[6:]
            if path:
                _emit("media", path=path)
                sent_anything["value"] = True
        elif msg.startswith("STATUS:"):
            _emit("status", text=msg[7:])
        elif msg.startswith("ACK:"):
            _emit("status", text=msg[4:])
        elif msg.startswith("DONE:"):
            done.set()
        elif msg.startswith("ERROR:"):
            _emit("error", text=msg[6:])
            done.set()

    friday.dispatch_background(user_input, on_update=on_update)
    # 4 minutes — deep research / job applications can be long-running
    done.wait(timeout=240)

    # If nothing was emitted, surface that honestly so the UI doesn't show silence.
    if not sent_anything["value"]:
        _emit("chunk", text="(no response)")
    _emit("done")


async def run_final(user_input: str) -> dict:
    """Back-compat: collect everything and return a single result."""
    from friday.core.orchestrator import FridayCore

    friday = FridayCore()

    fast_result = await friday.fast_path(user_input)
    if fast_result is not None:
        return {"text": fast_result, "media": []}

    collected_text: list[str] = []
    collected_media: list[str] = []
    done = threading.Event()

    def on_update(msg: str) -> None:
        if msg.startswith("CHUNK:"):
            collected_text.append(msg[6:])
        elif msg.startswith("MEDIA:"):
            path = msg[6:]
            if path not in collected_media:
                collected_media.append(path)
        elif msg.startswith("DONE:") or msg.startswith("ERROR:"):
            done.set()

    friday.dispatch_background(user_input, on_update=on_update)
    done.wait(timeout=240)
    text = "".join(collected_text).strip() or "Done."
    return {"text": text, "media": collected_media}


def main() -> None:
    args = sys.argv[1:]
    final_mode = "--final" in args
    args = [a for a in args if a != "--final"]

    if args:
        user_input = " ".join(args).strip()
    else:
        user_input = sys.stdin.read().strip()

    if not user_input:
        if final_mode:
            print(json.dumps({"text": "Empty input.", "media": []}))
        else:
            _emit("error", text="empty input")
            _emit("done")
        sys.exit(1)

    try:
        if final_mode:
            result = asyncio.run(run_final(user_input))
            print(json.dumps(result))
        else:
            asyncio.run(run_stream(user_input))
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        if final_mode:
            print(json.dumps({"text": f"Error: {e}", "media": []}))
        else:
            _emit("error", text=str(e))
            _emit("done")
        sys.exit(1)


if __name__ == "__main__":
    main()
