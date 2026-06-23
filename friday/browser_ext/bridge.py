"""WebSocket bridge between FRIDAY and the Chrome extension.

The extension connects to ws://127.0.0.1:3210 with an auth token, sends
periodic heartbeats listing the user's open tabs, and processes commands
the bridge pushes from the action queue.

Design constraints:
- One extension at a time — second connection replaces the first.
- Auth token lives in ``~/Friday/.env`` as ``FRIDAY_BROWSER_EXT_TOKEN``.
  Auto-generated on first start. Extension prompts the user for it on
  install via its popup.
- Token is checked once on the ``hello`` message; afterwards the socket
  stays trusted for its lifetime.
- Actions are awaited via per-action ``asyncio.Future`` — no polling.

Used by:
    friday/tools/browser_ext_tools.py
        await bridge.send_action({"action": "navigate", "metadata": {...}})
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import websockets

# Triggers config.py's _load_layered_env so ~/Friday/.env is read.
from friday.core import config  # noqa: F401
from friday.browser_ext.protocol import (
    WS_HOST, WS_PORT,
    MSG_HELLO, MSG_HEARTBEAT, MSG_RESULT, MSG_SNAPSHOT, MSG_DOM_EVENT,
    ACT_PING,
)

log = logging.getLogger("friday.browser_ext")


# ── Token management ────────────────────────────────────────────────────────

def _env_path() -> Path:
    return Path.home() / "Friday" / ".env"


def _read_or_create_token() -> str:
    """Look up the token in env / ~/Friday/.env. Mint one if missing.

    The minted token is written back to ~/Friday/.env so it survives
    restarts and the user can copy it into the extension popup once.
    """
    existing = os.getenv("FRIDAY_BROWSER_EXT_TOKEN", "").strip()
    if existing:
        return existing

    token = secrets.token_urlsafe(24)  # ~32-char URL-safe string
    try:
        path = _env_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Append a single line — first-write-wins on subsequent boots.
        with path.open("a") as f:
            f.write(f"\nFRIDAY_BROWSER_EXT_TOKEN={token}\n")
        os.environ["FRIDAY_BROWSER_EXT_TOKEN"] = token
        log.info("Minted new browser-ext token → %s", path)
    except Exception as e:
        log.warning("Couldn't persist browser-ext token (%s) — using in-memory only", e)
    return token


# ── Bridge ──────────────────────────────────────────────────────────────────

class BrowserBridge:
    """Async WebSocket server. Tools call ``send_action`` and await the
    returned future for the result.
    """

    HEARTBEAT_STALE_S = 30.0     # extension is stale if no heartbeat within this
    ACTION_DEFAULT_TIMEOUT_S = 15.0

    def __init__(self):
        self._token: str = _read_or_create_token()
        self._ws: Optional[websockets.ServerConnection] = None
        self._connected_at: float = 0.0
        self._last_heartbeat_at: float = 0.0
        self._extension_name: str = ""
        self._extension_version: str = ""
        self._open_tabs: list[dict] = []
        self._pending: dict[str, asyncio.Future] = {}
        self._server: Optional[websockets.Server] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ── public state ─────────────────────────────────────────────────────

    @property
    def token(self) -> str:
        return self._token

    def is_connected(self) -> bool:
        if self._ws is None:
            return False
        if self._last_heartbeat_at == 0:
            return True  # just connected, no heartbeat yet
        return (time.time() - self._last_heartbeat_at) < self.HEARTBEAT_STALE_S

    def status(self) -> dict:
        return {
            "connected": self.is_connected(),
            "extension": self._extension_name,
            "version": self._extension_version,
            "connected_at": self._connected_at,
            "last_heartbeat_at": self._last_heartbeat_at,
            "tabs_open": len(self._open_tabs),
            "tabs": self._open_tabs[:10],
            "port": WS_PORT,
        }

    # ── lifecycle ────────────────────────────────────────────────────────

    async def serve(self) -> None:
        """Start the WebSocket server. Returns once it's listening."""
        self._loop = asyncio.get_running_loop()
        self._server = await websockets.serve(
            self._handle_client, WS_HOST, WS_PORT,
            ping_interval=20, ping_timeout=10,
        )
        log.info(":: browser-ext bridge listening on ws://%s:%d", WS_HOST, WS_PORT)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    # ── client handler ───────────────────────────────────────────────────

    async def _handle_client(self, ws):
        # First message must be {"type": "hello", "token": "...", ...}
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            hello = json.loads(raw)
        except Exception as e:
            log.warning("ext rejected — bad/no hello: %s", e)
            await ws.close(code=1008, reason="hello required")
            return

        if hello.get("type") != MSG_HELLO:
            await ws.close(code=1008, reason="hello required first")
            return
        if hello.get("token") != self._token:
            log.warning("ext rejected — bad token (got %r)", str(hello.get("token"))[:8])
            await ws.close(code=1008, reason="bad token")
            return

        # Replace any previous connection
        if self._ws is not None:
            try:
                await self._ws.close(code=4000, reason="superseded")
            except Exception:
                pass

        self._ws = ws
        self._connected_at = time.time()
        self._last_heartbeat_at = time.time()
        self._extension_name = hello.get("name", "browser-bridge")
        self._extension_version = hello.get("version", "?")
        log.info(":: extension connected — %s v%s",
                 self._extension_name, self._extension_version)

        # Confirm
        await ws.send(json.dumps({"type": "hello_ack", "ok": True}))

        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                await self._handle_message(msg)
        except websockets.ConnectionClosed:
            pass
        finally:
            log.info(":: extension disconnected")
            if self._ws is ws:
                self._ws = None
            # Wake any pending futures with a connection-closed error
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("extension disconnected"))
            self._pending.clear()

    async def _handle_message(self, msg: dict) -> None:
        t = msg.get("type")
        if t == MSG_HEARTBEAT:
            self._last_heartbeat_at = time.time()
            self._open_tabs = msg.get("tabs") or []
        elif t == MSG_RESULT:
            mid = msg.get("id")
            fut = self._pending.pop(mid, None) if mid else None
            if fut and not fut.done():
                fut.set_result(msg)
        elif t == MSG_SNAPSHOT:
            # Snapshots are unsolicited summaries of a tab; tools that
            # care can poll status() / pull from a future cache.
            log.debug("snapshot from tab %s", msg.get("tab_id"))
        elif t == MSG_DOM_EVENT:
            log.debug("dom event from tab %s", msg.get("tab_id"))
        else:
            log.debug("unhandled msg type %r", t)

    # ── public action API ────────────────────────────────────────────────

    async def send_action(self, action: str, metadata: dict | None = None,
                          *, timeout: float | None = None) -> dict:
        """Push an action to the extension and await its result.

        Returns the full result message ({"type": "result", "id": ...,
        "ok": bool, "data": ..., "error": ...}). Raises ConnectionError
        if the extension isn't connected, asyncio.TimeoutError on timeout.
        """
        if not self.is_connected() or self._ws is None:
            raise ConnectionError("browser extension not connected")

        action_id = str(uuid.uuid4())
        payload = {
            "id": action_id,
            "action": action,
            "metadata": metadata or {},
        }
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[action_id] = fut

        try:
            await self._ws.send(json.dumps(payload))
        except Exception:
            self._pending.pop(action_id, None)
            raise

        try:
            return await asyncio.wait_for(
                fut, timeout=timeout or self.ACTION_DEFAULT_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            self._pending.pop(action_id, None)
            raise

    async def ping(self) -> float:
        """Round-trip a ping → pong. Returns latency in seconds."""
        t0 = time.time()
        await self.send_action(ACT_PING, timeout=5)
        return time.time() - t0


# ── module-level singleton ──────────────────────────────────────────────────

bridge = BrowserBridge()


def start_bridge(loop: asyncio.AbstractEventLoop) -> None:
    """Schedule the bridge server on ``loop``. Idempotent — safe to call
    multiple times. Designed to be called from FRIDAY's CLI boot path."""
    if bridge._server is not None:
        return
    asyncio.run_coroutine_threadsafe(bridge.serve(), loop)


def stop_bridge() -> None:
    if bridge._server is None or bridge._loop is None:
        return
    asyncio.run_coroutine_threadsafe(bridge.stop(), bridge._loop)
