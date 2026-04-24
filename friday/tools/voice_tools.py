"""Voice tools — generate audio files from text for outbound delivery.

The existing ``friday/voice/tts.py`` streams PCM chunks to speakers for
live conversation. That's the wrong shape when you want a file you can
send via Telegram or email — you need a complete, single-file artefact
on disk. This module fills that gap.

Primary use case: "send me a voice note saying X on telegram". The LLM
calls ``tts_to_file`` to get a path, then ``send_telegram_voice`` /
``send_telegram_audio`` with that path.

Format choice:
  - ``ogg`` — Telegram renders as a voice-note bubble (waveform UI).
    Requires ffmpeg to convert ElevenLabs' MP3 to OGG/Opus. Target.
  - ``mp3`` — Telegram renders as an audio-player row. No conversion
    needed. Use for longer music-player-style clips.

ElevenLabs settings come from ``friday.core.config``:
  - ``ELEVENLABS_API_KEY`` — auth
  - ``ELEVENLABS_VOICE_ID`` — default voice (George by default)
  - ``ELEVENLABS_MODEL``    — eleven_flash_v2_5 (~75ms latency, best cost)
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import httpx

# Import triggers friday.core.config's _load_layered_env so ~/Friday/.env
# and the repo .env get loaded even when this module is imported outside
# the usual CLI boot path.
from friday.core import config  # noqa: F401
from friday.core.types import ToolResult, ToolError, ErrorCode, Severity

log = logging.getLogger("friday.voice.tools")

VOICE_OUTBOX = Path.home() / "Friday" / "voice_outbox"
VOICE_OUTBOX.mkdir(parents=True, exist_ok=True)


def _eleven_url(voice_id: str) -> str:
    return f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"


async def tts_to_file(
    text: str,
    format: str = "ogg",
    voice_id: str = "",
    filename: str = "",
    model_id: str = "",
) -> ToolResult:
    """Render text to an audio file on disk. Returns the path.

    Args:
        text: The text to speak. Keep under ~500 chars for voice notes.
              You can embed **audio tags** to control emotion when using
              the Eleven v3 model (the default here):
                  [laughs] [laughs harder] [starts laughing] [wheezing]
                  [whispers] [excited] [sad] [curious] [sighs] [sarcastic]
              Example: "Oh no [sighs] not again [laughs] that's ridiculous"
        format: "ogg" (Telegram voice-note bubble, needs ffmpeg) or "mp3"
              (audio-player row, no conversion).
        voice_id: Override the ElevenLabs voice ID. Empty → config default.
        filename: Optional explicit filename (no extension). Empty → UUID.
        model_id: Override ElevenLabs model. Empty → ``eleven_v3``
              (expressive, audio-tag aware). Pass ``eleven_flash_v2_5``
              for fastest / cheapest / no-emotion.

    Returns:
        ToolResult with ``.data = {"path": ..., "format": ..., "bytes": ...}``.
    """
    if not text or not text.strip():
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.VALIDATION_ERROR, message="text is empty",
            severity=Severity.LOW, recoverable=True,
        ))
    if format not in ("ogg", "mp3"):
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"format must be 'ogg' or 'mp3', got {format!r}",
            severity=Severity.LOW, recoverable=True,
        ))

    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.VALIDATION_ERROR,
            message="ELEVENLABS_API_KEY not set. Run `friday setup elevenlabs`.",
            severity=Severity.MEDIUM, recoverable=True,
        ))

    voice_id = voice_id.strip() or os.getenv(
        "ELEVENLABS_VOICE_ID", "lxYfHSkYm1EzQzGhdbfc",
    ).strip("/")
    # Voice notes want expressiveness, not low latency — Eleven v3 supports
    # inline audio tags like [laughs] [whispers] [excited] [sighs] that the
    # LLM can embed in `text` to shape delivery. Flash v2.5 ignores them.
    model_id = model_id.strip() or os.getenv(
        "ELEVENLABS_EXPRESSIVE_MODEL", "eleven_v3",
    )

    base = filename.strip() or str(uuid.uuid4())
    mp3_path = VOICE_OUTBOX / f"{base}.mp3"

    # ── 1. ElevenLabs MP3 (one-shot, no streaming) ─────────────────────
    try:
        async with httpx.AsyncClient(timeout=30.0) as c:
            resp = await c.post(
                _eleven_url(voice_id),
                headers={
                    "xi-api-key": api_key,
                    "Accept": "audio/mpeg",
                    "Content-Type": "application/json",
                },
                json={
                    "text": text,
                    "model_id": model_id,
                    # Settings tuned for v3 expressive delivery:
                    #   stability 0.35 — lets tone swing with audio tags
                    #     (too high = flat; too low = unstable pacing)
                    #   style 0.65     — surfaces emotional inflection
                    #   similarity_boost 0.75 — track the cloned voice well
                    "voice_settings": {
                        "stability": 0.35,
                        "similarity_boost": 0.75,
                        "style": 0.65,
                        "use_speaker_boost": True,
                    },
                },
            )
        if resp.status_code != 200:
            # ElevenLabs returns JSON on errors
            try:
                err = resp.json().get("detail", resp.text[:200])
            except Exception:
                err = resp.text[:200]
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.NETWORK_ERROR,
                message=f"ElevenLabs HTTP {resp.status_code}: {err}",
                severity=Severity.MEDIUM, recoverable=True,
            ))
        mp3_path.write_bytes(resp.content)
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.NETWORK_ERROR,
            message=f"ElevenLabs call failed: {type(e).__name__}: {e}",
            severity=Severity.MEDIUM, recoverable=True,
        ))

    if format == "mp3":
        return ToolResult(success=True, data={
            "path": str(mp3_path),
            "format": "mp3",
            "bytes": mp3_path.stat().st_size,
            "voice_id": voice_id,
        })

    # ── 2. Convert MP3 → OGG/Opus for voice-note bubble ────────────────
    if not shutil.which("ffmpeg"):
        # Graceful downgrade — ship the MP3 rather than fail
        log.warning("ffmpeg not installed — returning MP3 instead of OGG. "
                    "Install via `brew install ffmpeg` to get voice-note UX.")
        return ToolResult(success=True, data={
            "path": str(mp3_path),
            "format": "mp3",
            "bytes": mp3_path.stat().st_size,
            "voice_id": voice_id,
            "note": "Requested OGG but ffmpeg unavailable — delivered MP3.",
        })

    ogg_path = VOICE_OUTBOX / f"{base}.ogg"
    # Telegram voice notes require OGG container with Opus codec.
    # -vn = no video stream, -c:a libopus = Opus codec,
    # -b:a 48k = bitrate suitable for speech (not music).
    cmd = [
        "ffmpeg", "-y", "-i", str(mp3_path),
        "-vn", "-c:a", "libopus", "-b:a", "48k",
        str(ogg_path),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.NETWORK_ERROR,
            message="ffmpeg conversion timed out",
            severity=Severity.LOW, recoverable=True,
        ))
    if res.returncode != 0:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"ffmpeg failed: {res.stderr[-200:]}",
            severity=Severity.LOW, recoverable=True,
        ))
    # Clean up the MP3 intermediate — keep the outbox tidy.
    try:
        mp3_path.unlink(missing_ok=True)
    except Exception:
        pass

    return ToolResult(success=True, data={
        "path": str(ogg_path),
        "format": "ogg",
        "bytes": ogg_path.stat().st_size,
        "voice_id": voice_id,
    })


# ── Tool registry ─────────────────────────────────────────────────────────────

TOOL_SCHEMAS = {
    "tts_to_file": {
        "fn": tts_to_file,
        "schema": {"type": "function", "function": {
            "name": "tts_to_file",
            "description": (
                "Generate a voice audio file from text using ElevenLabs and "
                "save it to ~/Friday/voice_outbox/. Returns the path. Use "
                "BEFORE send_telegram_voice (for a voice-note bubble — pick "
                "format='ogg') or send_telegram_audio (for an audio-player "
                "row — pick format='mp3'). Typical flow: user asks 'send me "
                "a voice note saying X on telegram' → tts_to_file(text=X, "
                "format='ogg') → send_telegram_voice(path_or_url=<path>). "
                "\n\nEMOTION: default model is Eleven v3 which supports "
                "inline audio tags that shape delivery. Embed them directly "
                "in the text string: [laughs] [laughs harder] [whispers] "
                "[excited] [sighs] [curious] [sad] [sarcastic] [wheezing]. "
                "Example: 'Alright [sighs] fine I'll do it [laughs]'. "
                "Use tags sparingly — 1–2 per note sounds natural, 5+ feels "
                "theatrical."
            ),
            "parameters": {"type": "object", "properties": {
                "text": {"type": "string",
                         "description": "What FRIDAY should say. Keep under 500 chars "
                                        "for voice notes. May include v3 audio tags inline, "
                                        "e.g. '[whispers] don't tell anyone [laughs]'."},
                "format": {"type": "string", "enum": ["ogg", "mp3"],
                           "description": "ogg = Telegram voice-note bubble (preferred). "
                                          "mp3 = audio-player row (longer clips)."},
                "voice_id": {"type": "string",
                             "description": "Optional ElevenLabs voice ID override. "
                                            "Empty → use configured default."},
                "filename": {"type": "string",
                             "description": "Optional explicit filename without extension. "
                                            "Empty → UUID."},
                "model_id": {"type": "string",
                             "description": "Optional ElevenLabs model override. "
                                            "Empty → 'eleven_v3' (expressive). "
                                            "Use 'eleven_flash_v2_5' for fastest / cheapest."},
            }, "required": ["text"]},
        }},
    },
}
