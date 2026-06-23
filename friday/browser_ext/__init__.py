"""Chrome Extension bridge — talks to the user's real Chrome over WebSocket.

Complementary to ``friday/tools/browser_tools.py`` (Playwright). Use this
when the agent needs to act in the user's *actual* browser session —
logged-in sites, anti-bot pages, "fill the form on my screen". Use
Playwright for headless / parallel / unauthenticated tasks.

Public surface:
    start_bridge(loop)       — boot the WebSocket server alongside FRIDAY
    stop_bridge()            — graceful shutdown
    bridge                   — singleton ``BrowserBridge`` for tools to call
"""
from friday.browser_ext.bridge import bridge, start_bridge, stop_bridge

__all__ = ["bridge", "start_bridge", "stop_bridge"]
