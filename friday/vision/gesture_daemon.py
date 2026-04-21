"""Standalone gesture daemon.

Runs the MediaPipe gesture listener as a long-running process.
When a gesture fires, it executes the mapped FRIDAY command through FridayCore.

Used by the macOS app — spawns this as a subprocess on /gestures-on,
kills it on /gestures-off. Independent of the Swift app's state.

Usage:
    uv run python -m friday.vision.gesture_daemon
"""

import asyncio
import logging
import signal
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("gesture_daemon")


def main() -> None:
    from friday.core.orchestrator import FridayCore
    from friday.vision.gesture_listener import GestureListener

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    friday = FridayCore()
    listener = GestureListener(friday, loop)
    listener.start()

    log.info("Gesture daemon started. Camera is live. Ctrl+C to stop.")
    print("GESTURE_READY", flush=True)  # signal to Swift that we're up

    def shutdown(*_):
        log.info("Gesture daemon stopping…")
        try:
            listener.stop()
        finally:
            loop.stop()
            sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        shutdown()
    finally:
        listener.stop()


if __name__ == "__main__":
    main()
