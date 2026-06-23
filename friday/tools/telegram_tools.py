"""Telegram send tools — outbound messaging + media from the LLM.

The inbound side lives in ``friday.telegram.bot`` (long-polling listener).
This module is the outbound half: send text, photos, audio, voice notes,
documents to the user's Telegram chat. The LLM calls these via
``TOOL_SCHEMAS``.

Rich-media is the reason Telegram is here — Twilio UK/EU numbers can't
carry MMS, so the LLM routes images and audio through this module
instead. 50 MB per file (voice notes capped at 20 MB, ideal <1 MB).
"""

from __future__ import annotations

import logging
import mimetypes
import os
import urllib.parse
import urllib.request
from pathlib import Path

import httpx

from friday.core.types import ToolResult, ToolError, ErrorCode, Severity

log = logging.getLogger("friday.telegram.tools")

_API = "https://api.telegram.org"


def _token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def _default_chat_id() -> str:
    """First ID from TELEGRAM_ALLOWED_CHAT_IDS, or TELEGRAM_CHAT_ID."""
    raw = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
    if raw:
        return raw.split(",")[0].strip()
    return os.getenv("TELEGRAM_CHAT_ID", "").strip()


def _find_artifact_fuzzy(requested_name: str) -> Path | None:
    """LLM-friendly fallback: when the agent passes a hallucinated filename
    that doesn't exist, search recently-modified files in known FRIDAY output
    directories whose name contains the same tokens (case-insensitive).

    Example: agent asks for `Mark_Smith_Background_Check.docx` but the real
    file is `mark_smith_20260601_173452.docx`. Tokens 'mark', 'smith' both
    appear in the real filename → return that.
    """
    import re as _re
    import time as _time

    # Pull alpha tokens of length >= 3 from the requested name (ignore
    # 'background', 'check', 'report' generic words; keep distinctive ones)
    raw = Path(requested_name).stem.lower()
    tokens = [t for t in _re.findall(r"[a-z]{3,}", raw)
              if t not in {"background", "check", "report", "investigation", "dossier", "file", "doc", "the", "and"}]
    if not tokens:
        return None

    # Extension match if specified
    want_ext = Path(requested_name).suffix.lower()

    candidates: list[tuple[float, Path]] = []
    search_dirs = [
        Path.home() / "Friday" / "investigations",
        Path.home() / "Friday" / "reports",
        Path.home() / "Desktop" / "JARVIS" / "data" / "cv_output",
        Path.home() / "Desktop" / "JARVIS" / "data" / "research",
        Path.home() / "Downloads",
        Path.home() / "Desktop",
        Path("/tmp"),
    ]
    now = _time.time()
    for d in search_dirs:
        if not d.exists() or not d.is_dir():
            continue
        try:
            for f in d.iterdir():
                if not f.is_file():
                    continue
                if want_ext and f.suffix.lower() != want_ext:
                    continue
                name_lower = f.name.lower()
                # Require at least 1 distinctive token to match
                matches = sum(1 for t in tokens if t in name_lower)
                if matches == 0:
                    continue
                # Score: more matching tokens > more recent file > extension match
                age_hours = (now - f.stat().st_mtime) / 3600.0
                if age_hours > 168:  # skip files older than a week
                    continue
                score = matches * 100 - age_hours
                candidates.append((score, f))
        except OSError:
            continue

    if not candidates:
        return None
    candidates.sort(reverse=True)
    log.info("telegram fuzzy match: requested=%r → resolved=%r (score=%.1f)",
             requested_name, str(candidates[0][1]), candidates[0][0])
    return candidates[0][1]


def _err(code: ErrorCode, msg: str) -> ToolResult:
    return ToolResult(
        success=False,
        error=ToolError(code=code, message=msg, severity=Severity.MEDIUM, recoverable=True),
    )


def _resolve_target(chat_id: str) -> str | None:
    cid = (chat_id or "").strip() or _default_chat_id()
    return cid or None


async def send_telegram_message(message: str, chat_id: str = "") -> ToolResult:
    """Send a plain text Telegram message.

    Args:
        message: text body (max 4096 chars; longer messages are chunked).
        chat_id: destination chat. Defaults to the first ID in
                 ``TELEGRAM_ALLOWED_CHAT_IDS`` / ``TELEGRAM_CHAT_ID``.
    """
    if not _token():
        return _err(ErrorCode.VALIDATION_ERROR, "TELEGRAM_BOT_TOKEN not set")
    target = _resolve_target(chat_id)
    if not target:
        return _err(ErrorCode.VALIDATION_ERROR,
                    "No Telegram chat_id — run `friday setup telegram` first")
    if not message:
        return _err(ErrorCode.VALIDATION_ERROR, "message is empty")

    sent = 0
    async with httpx.AsyncClient(timeout=20) as c:
        for i in range(0, len(message), 4096):
            r = await c.post(
                f"{_API}/bot{_token()}/sendMessage",
                data={"chat_id": target, "text": message[i:i + 4096]},
            )
            if r.status_code != 200 or not r.json().get("ok"):
                return _err(ErrorCode.NETWORK_ERROR,
                            f"Telegram sendMessage failed: {r.text[:200]}")
            sent += 1
    return ToolResult(success=True, data={"chat_id": target, "chunks_sent": sent})


async def _send_file(method: str, field: str, path_or_url: str, chat_id: str,
                      caption: str = "", extra: dict | None = None) -> ToolResult:
    """Shared uploader for photo / audio / voice / document / video."""
    if not _token():
        return _err(ErrorCode.VALIDATION_ERROR, "TELEGRAM_BOT_TOKEN not set")
    target = _resolve_target(chat_id)
    if not target:
        return _err(ErrorCode.VALIDATION_ERROR, "No Telegram chat_id set")

    url = f"{_API}/bot{_token()}/{method}"
    data = {"chat_id": target}
    if caption:
        data["caption"] = caption[:1024]
    if extra:
        data.update(extra)

    # Accept either a remote URL (Telegram fetches) or a local path (we upload).
    path_or_url = (path_or_url or "").strip()
    if path_or_url.startswith(("http://", "https://")):
        data[field] = path_or_url
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(url, data=data)
    else:
        p = Path(path_or_url).expanduser()
        if not p.exists():
            # Fallback: the LLM often hallucinates a "reasonable looking"
            # filename when the real artifact has a timestamped name. Token-
            # match the requested basename against recently-created files in
            # known output directories.
            fuzzy = _find_artifact_fuzzy(p.name)
            if fuzzy:
                p = fuzzy
            else:
                return _err(ErrorCode.NOT_FOUND, f"file not found: {p}")
        if p.stat().st_size > 50 * 1024 * 1024:
            return _err(ErrorCode.VALIDATION_ERROR,
                        f"file too big ({p.stat().st_size/1e6:.1f} MB) — Telegram max is 50 MB")
        mime, _ = mimetypes.guess_type(str(p))
        async with httpx.AsyncClient(timeout=120) as c:
            with p.open("rb") as fh:
                r = await c.post(
                    url, data=data,
                    files={field: (p.name, fh, mime or "application/octet-stream")},
                )

    if r.status_code != 200 or not r.json().get("ok"):
        return _err(ErrorCode.NETWORK_ERROR,
                    f"Telegram {method} failed: {r.text[:200]}")
    return ToolResult(success=True, data={
        "chat_id": target,
        "message_id": r.json().get("result", {}).get("message_id"),
    })


async def send_telegram_photo(path_or_url: str, caption: str = "",
                                chat_id: str = "") -> ToolResult:
    """Send an image. JPG/PNG/WEBP, up to 10 MB as photo (larger = use document)."""
    return await _send_file("sendPhoto", "photo", path_or_url, chat_id, caption)


async def send_telegram_audio(path_or_url: str, caption: str = "",
                                chat_id: str = "") -> ToolResult:
    """Send a music / audio file. MP3/M4A/etc, shown in Telegram's audio player."""
    return await _send_file("sendAudio", "audio", path_or_url, chat_id, caption)


async def send_telegram_voice(path_or_url: str, caption: str = "",
                                chat_id: str = "") -> ToolResult:
    """Send a voice note — must be OGG/Opus, 1 MB ideal, 20 MB hard max."""
    return await _send_file("sendVoice", "voice", path_or_url, chat_id, caption)


async def send_telegram_document(path_or_url: str, caption: str = "",
                                   chat_id: str = "") -> ToolResult:
    """Send any file as a document (PDF, DOCX, ZIP, etc.)."""
    return await _send_file("sendDocument", "document", path_or_url, chat_id, caption)


async def send_telegram_video(path_or_url: str, caption: str = "",
                                chat_id: str = "") -> ToolResult:
    """Send an MP4 video."""
    return await _send_file("sendVideo", "video", path_or_url, chat_id, caption)


# ── Tool registry ─────────────────────────────────────────────────────────────

TOOL_SCHEMAS = {
    "send_telegram_message": {
        "fn": send_telegram_message,
        "schema": {"type": "function", "function": {
            "name": "send_telegram_message",
            "description": "Send a plain text message to the user's Telegram chat. Use this for any reply longer than an SMS (1600 chars) or when the user is on Telegram. Default destination is the configured chat; override by passing chat_id.",
            "parameters": {"type": "object", "properties": {
                "message": {"type": "string", "description": "Text body (chunked at 4096 chars)"},
                "chat_id": {"type": "string", "description": "Optional chat_id override"},
            }, "required": ["message"]},
        }},
    },
    "send_telegram_photo": {
        "fn": send_telegram_photo,
        "schema": {"type": "function", "function": {
            "name": "send_telegram_photo",
            "description": "Send a photo (JPG/PNG/WEBP up to 10 MB as a photo, larger files go via send_telegram_document). Accepts a local file path or a public URL.",
            "parameters": {"type": "object", "properties": {
                "path_or_url": {"type": "string", "description": "Local file path or https:// URL"},
                "caption": {"type": "string", "description": "Optional caption, up to 1024 chars"},
                "chat_id": {"type": "string"},
            }, "required": ["path_or_url"]},
        }},
    },
    "send_telegram_audio": {
        "fn": send_telegram_audio,
        "schema": {"type": "function", "function": {
            "name": "send_telegram_audio",
            "description": "Send an audio file (MP3/M4A) to be shown in Telegram's audio player. Use send_telegram_voice for voice notes (OGG/Opus, bubble UI).",
            "parameters": {"type": "object", "properties": {
                "path_or_url": {"type": "string"},
                "caption": {"type": "string"},
                "chat_id": {"type": "string"},
            }, "required": ["path_or_url"]},
        }},
    },
    "send_telegram_voice": {
        "fn": send_telegram_voice,
        "schema": {"type": "function", "function": {
            "name": "send_telegram_voice",
            "description": "Send a voice note — OGG/Opus audio shown as a voice bubble. Keep under 1 MB; 20 MB hard ceiling.",
            "parameters": {"type": "object", "properties": {
                "path_or_url": {"type": "string"},
                "caption": {"type": "string"},
                "chat_id": {"type": "string"},
            }, "required": ["path_or_url"]},
        }},
    },
    "send_telegram_document": {
        "fn": send_telegram_document,
        "schema": {"type": "function", "function": {
            "name": "send_telegram_document",
            "description": "Send any file as a document attachment (PDF, DOCX, ZIP, big photos, etc.) up to 50 MB.",
            "parameters": {"type": "object", "properties": {
                "path_or_url": {"type": "string"},
                "caption": {"type": "string"},
                "chat_id": {"type": "string"},
            }, "required": ["path_or_url"]},
        }},
    },
    "send_telegram_video": {
        "fn": send_telegram_video,
        "schema": {"type": "function", "function": {
            "name": "send_telegram_video",
            "description": "Send an MP4 video up to 50 MB.",
            "parameters": {"type": "object", "properties": {
                "path_or_url": {"type": "string"},
                "caption": {"type": "string"},
                "chat_id": {"type": "string"},
            }, "required": ["path_or_url"]},
        }},
    },
}
