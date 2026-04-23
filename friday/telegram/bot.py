"""Telegram long-polling listener.

Runs as a daemon thread inside the main FRIDAY process. On each inbound
message it:
  1. Checks the chat is in the allowlist (TELEGRAM_ALLOWED_CHAT_IDS).
  2. Tries ``friday.fast_path(text)`` for instant hits (TV / volume / mute).
  3. Falls through to ``friday.dispatch_background(text)`` for the full
     7-tier pipeline, streams chunks back to the user.

Why polling instead of webhook:
  Polling doesn't need a public tunnel — it outbound-calls Telegram's
  servers. SMS already needs ngrok/Tailscale; Telegram shouldn't require
  the same, because the whole point of having two channels is redundancy.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import urllib.parse
import urllib.request
from threading import Event, Thread
from typing import Optional

log = logging.getLogger("friday.telegram")

_API = "https://api.telegram.org"


def _allowed_chats() -> set[str]:
    raw = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
    return {x.strip() for x in raw.split(",") if x.strip()}


def _token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def _call(method: str, params: dict | None = None, timeout: float = 35.0) -> dict:
    """GET on the Telegram Bot API. Returns the parsed JSON or {}."""
    tok = _token()
    if not tok:
        return {}
    url = f"{_API}/bot{tok}/{method}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        log.debug("Telegram %s failed: %s", method, e)
        return {}


def send_message(chat_id: int | str, text: str, parse_mode: str = "") -> bool:
    """Send a plain-text message. Returns True on success."""
    if not _token():
        return False
    params = {"chat_id": chat_id, "text": text[:4096]}
    if parse_mode:
        params["parse_mode"] = parse_mode
    r = _call("sendMessage", params)
    return bool(r.get("ok"))


class TelegramBot:
    """Long-polling listener. Mirrors the shape of VoicePipeline / SMS server."""

    def __init__(self, friday, loop: asyncio.AbstractEventLoop):
        self.friday = friday
        self.loop = loop
        self._running = False
        self._thread: Optional[Thread] = None
        self._offset: int = 0
        self._allowed = _allowed_chats()

    def start(self) -> None:
        if not _token():
            log.info("TELEGRAM_BOT_TOKEN not set — Telegram listener not started.")
            return
        self._running = True
        self._thread = Thread(target=self._run, name="friday-telegram", daemon=True)
        self._thread.start()

        # Who am I?
        me = _call("getMe", timeout=10)
        if me.get("ok"):
            u = me["result"].get("username", "?")
            log.info("Telegram bot @%s active (allowlist=%s)", u,
                     ",".join(self._allowed) or "OPEN")
        else:
            log.warning("Telegram getMe failed — bad token?")

    def stop(self) -> None:
        self._running = False

    def _run(self) -> None:
        # Drain any queued updates from before startup so we don't replay them.
        first = _call("getUpdates", {"timeout": 0, "offset": -1}, timeout=10)
        if first.get("ok") and first.get("result"):
            self._offset = first["result"][-1]["update_id"] + 1

        while self._running:
            try:
                payload = _call("getUpdates",
                                {"timeout": 25, "offset": self._offset},
                                timeout=35)
            except Exception as e:
                log.debug("poll error: %s", e)
                time.sleep(2)
                continue

            if not payload.get("ok"):
                time.sleep(2)
                continue

            for upd in payload.get("result", []):
                self._offset = upd["update_id"] + 1
                try:
                    self._handle(upd)
                except Exception as e:
                    log.exception("update handler error: %s", e)

    def _handle(self, upd: dict) -> None:
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        from_user = msg.get("from") or {}
        text = (msg.get("text") or msg.get("caption") or "").strip()

        if not chat_id:
            return

        # Allowlist enforcement — if configured, reject anyone not on it.
        if self._allowed and str(chat_id) not in self._allowed:
            log.warning("Telegram from unauthorised chat %s (user=%s)",
                        chat_id, from_user.get("username"))
            send_message(chat_id, "Unauthorised.")
            return

        # Slash-command bookkeeping
        if text.lower() == "/start":
            send_message(chat_id,
                         "FRIDAY online. Send me a message and I'll act on it.\n"
                         f"Your chat_id is {chat_id} — save it as "
                         f"TELEGRAM_ALLOWED_CHAT_IDS to lock it down.")
            return
        if text.lower() == "/id":
            send_message(chat_id, f"chat_id={chat_id}")
            return
        if not text:
            return

        log.info("Telegram %s: %s", chat_id, text[:80])
        Thread(target=self._process_and_reply,
               args=(chat_id, text), daemon=True,
               name="friday-telegram-process").start()

    def _process_and_reply(self, chat_id: int, text: str) -> None:
        # 1. fast_path — sub-second hits for TV / greetings / volume / mute
        try:
            fut = asyncio.run_coroutine_threadsafe(
                self.friday.fast_path(text), self.loop,
            )
            fast = fut.result(timeout=5)
            if fast is not None:
                send_message(chat_id, fast)
                return
        except Exception as e:
            log.debug("fast_path miss: %s", e)

        # 2. full pipeline
        collected: list[str] = []
        done = Event()

        def on_update(msg: str) -> None:
            if msg.startswith("CHUNK:"):
                collected.append(msg[6:])
            elif msg.startswith("DONE:") or msg.startswith("ERROR:"):
                done.set()

        try:
            self.friday.dispatch_background(text, on_update=on_update)
            done.wait(timeout=55)
        except Exception as e:
            send_message(chat_id, f"Error: {e}")
            return

        reply = "".join(collected).strip() or "Done."
        # Telegram has a 4096-char message limit — chunk if longer.
        for i in range(0, len(reply), 4096):
            send_message(chat_id, reply[i:i + 4096])


# Module-level holder so the CLI can stop/restart the bot on /telegram toggle
_BOT: Optional[TelegramBot] = None


def start_bot(friday, loop: asyncio.AbstractEventLoop) -> Optional[TelegramBot]:
    """Start the bot (noop if no token or already running)."""
    global _BOT
    if _BOT is not None and _BOT._running:
        return _BOT
    if not _token():
        return None
    _BOT = TelegramBot(friday, loop)
    _BOT.start()
    return _BOT


def stop_bot() -> None:
    global _BOT
    if _BOT:
        _BOT.stop()
        _BOT = None
