"""Text-to-Speech — ElevenLabs streaming (primary) + Kokoro ONNX (fallback).

Cloud TTS:  ElevenLabs Flash v2.5 (~75ms latency), streams PCM chunks in real-time.
Local TTS:  Kokoro-82M ONNX, fully offline, ~1-2s per sentence on M4.

Two cloud paths:
    HTTP /stream         — input is one-shot, output streams. Default.
    WebSocket /stream-input — text streams in AS the LLM emits it, audio
                              flows back continuously. Eliminates the
                              "wait for sentence boundary" cost. Enabled
                              with env var FRIDAY_TTS_INPUT_STREAMING=true.

Auto-switches: if ELEVENLABS_API_KEY is set → cloud. Otherwise → local Kokoro.
Falls back to Kokoro on any cloud error (network, rate limit, etc.).
"""

import asyncio
import base64
import io
import json
import os
import logging
import threading
import tempfile
from typing import Callable
import numpy as np
import sounddevice as sd

from friday.voice.config import KOKORO_VOICE, KOKORO_SPEED

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

KOKORO_SAMPLE_RATE = 24000
KOKORO_REPO = "onnx-community/Kokoro-82M-v1.0-ONNX"

ELEVEN_SAMPLE_RATE = 24000       # pcm_24000 = 24kHz 16-bit signed LE mono
ELEVEN_OUTPUT_FORMAT = "pcm_24000"
ELEVEN_API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
ELEVEN_WS_URL = "wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input"


# ── Kokoro loader (local fallback) ───────────────────────────────────────────

def _load_kokoro():
    """Download model and voice, return Kokoro instance."""
    from huggingface_hub import hf_hub_download
    from kokoro_onnx import Kokoro

    model_path = hf_hub_download(KOKORO_REPO, "onnx/model.onnx")
    voice_path = hf_hub_download(KOKORO_REPO, f"voices/{KOKORO_VOICE}.bin")

    voice_data = np.fromfile(voice_path, dtype=np.float32).reshape(-1, 256)
    voices_file = os.path.join(tempfile.gettempdir(), "friday_kokoro_voices.npz")
    np.savez(voices_file, **{KOKORO_VOICE: voice_data})

    kokoro = Kokoro(model_path, voices_file)

    # Monkey-patch _create_audio to fix rank mismatch (style needs [1, 256])
    def _patched_create(phonemes, voice, speed):
        from kokoro_onnx import MAX_PHONEME_LENGTH, SAMPLE_RATE as K_SR

        phonemes = phonemes[:MAX_PHONEME_LENGTH]
        tokens = np.array(kokoro.tokenizer.tokenize(phonemes), dtype=np.int64)
        style = voice[len(tokens)].reshape(1, -1)
        tokens = [[0, *tokens, 0]]
        inputs = {
            "input_ids": tokens,
            "style": np.array(style, dtype=np.float32),
            "speed": np.array([speed], dtype=np.float32),
        }
        audio = kokoro.sess.run(None, inputs)[0].squeeze()
        return audio, K_SR

    kokoro._create_audio = _patched_create
    return kokoro


# ── Speaker (unified interface) ──────────────────────────────────────────────

class Speaker:
    """Synthesizes and plays speech.

    Primary:  ElevenLabs streaming (cloud, ~75ms first byte).
    Fallback: Kokoro-82M local ONNX.

    All playback is streaming — audio starts playing before full synthesis.
    """

    def __init__(self):
        self._kokoro = None          # Lazy load
        self._lock = threading.Lock()
        self._playing = False
        self._interrupted = False
        self._last_request_id: str | None = None  # ElevenLabs continuity

        # Check cloud availability once
        from friday.core.config import USE_CLOUD_TTS
        self._use_cloud = USE_CLOUD_TTS

        # Persistent HTTP client for ElevenLabs TTS (avoids per-sentence handshake)
        self._http_client = None
        if self._use_cloud:
            self._init_http_client()

        # Persistent audio output stream — saves ~30-80ms macOS CoreAudio
        # device-open latency on every sentence after the first. Lazy-opened
        # on first speak() and reused across the session.
        self._out_stream = None

    # ── Public API ───────────────────────────────────────────────────────

    def speak(self, text: str) -> None:
        """Speak text aloud. Streams from cloud or falls back to local."""
        self._interrupted = False
        if not text.strip():
            return

        if self._use_cloud:
            try:
                self._speak_cloud(text)
                return
            except Exception as e:
                logger.warning(f"ElevenLabs failed ({type(e).__name__}: {e}), falling back to Kokoro")
                # Recreate HTTP client — connection may be stale
                try:
                    self._init_http_client()
                except Exception:
                    pass

        self._speak_local(text)

    def stop(self):
        """Stop current playback immediately (barge-in)."""
        self._interrupted = True
        self._playing = False
        try:
            sd.stop()
        except Exception:
            pass
        # Tear down the persistent output stream so the next speak() reopens
        # cleanly — avoids leaving a half-flushed buffer between sessions.
        if self._out_stream is not None:
            try:
                self._out_stream.stop()
                self._out_stream.close()
            except Exception:
                pass
            self._out_stream = None

    def is_speaking(self) -> bool:
        return self._playing

    # ── ElevenLabs streaming (primary) ───────────────────────────────────

    def _init_http_client(self):
        """Create persistent httpx client for ElevenLabs TTS.

        Reuses TCP connections across sentences — saves ~100-200ms per call
        vs creating a new connection each time.
        """
        import httpx
        from friday.core.config import ELEVENLABS_API_KEY

        self._http_client = httpx.Client(
            headers={
                "xi-api-key": ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
        )

    def _speak_cloud(self, text: str) -> None:
        """Stream PCM audio from ElevenLabs and play chunks in real-time.

        Uses persistent httpx client with streaming for low-latency playback.
        Audio starts playing within ~75ms of first byte arriving.
        """
        from friday.core.config import ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL

        if not self._http_client:
            self._init_http_client()

        url = ELEVEN_API_URL.format(voice_id=ELEVENLABS_VOICE_ID)

        body = {
            "text": text,
            "model_id": ELEVENLABS_MODEL,
        }

        if self._last_request_id:
            body["previous_request_ids"] = [self._last_request_id]

        params = {
            "output_format": ELEVEN_OUTPUT_FORMAT,
            # 0-4 — bigger = lower latency at slight quality cost.
            # 3 is the most aggressive without disabling text normalisation.
            "optimize_streaming_latency": "3",
        }

        self._playing = True
        request_id = None

        # Lazy-open the persistent output stream on first speak. Reuses the
        # CoreAudio device handle across every sentence, saving ~30-80ms of
        # device-open latency per call. `latency='low'` requests CoreAudio's
        # smallest practical output buffer (~10-20ms vs ~80ms default).
        if self._out_stream is None:
            self._out_stream = sd.OutputStream(
                samplerate=ELEVEN_SAMPLE_RATE,
                channels=1,
                dtype="int16",
                latency="low",
            )
            self._out_stream.start()

        try:
            with self._http_client.stream(
                "POST", url,
                json=body, params=params,
            ) as response:
                response.raise_for_status()

                request_id = response.headers.get("request-id")

                # 50ms chunks (vs the old 200ms) — first audible word plays
                # 4× sooner. ElevenLabs streams faster than we can play, so
                # the smaller chunk size doesn't reduce throughput, only
                # the size of the first-byte buffer.
                for chunk in response.iter_bytes(chunk_size=2400):
                    if self._interrupted:
                        break
                    if chunk:
                        samples = np.frombuffer(chunk, dtype=np.int16)
                        self._out_stream.write(samples.reshape(-1, 1))

        finally:
            self._playing = False
            if request_id:
                self._last_request_id = request_id

    # ── ElevenLabs INPUT-STREAMING via WebSocket ─────────────────────────
    #
    # Eliminates the "wait for full sentence before firing TTS" lag by
    # pushing text fragments AS the LLM emits them. ElevenLabs synthesises
    # continuously and PCM bytes flow back without per-sentence handshake
    # cost. End-to-end first-audible-word drops from ~400-800ms to ~100-150ms.
    #
    # Protocol summary (https://elevenlabs.io/docs/api-reference/websockets):
    #   1. Open WS to /v1/text-to-speech/{voice_id}/stream-input
    #   2. Send config message (voice_settings + xi_api_key)
    #   3. Send {"text": "fragment "} repeatedly as the LLM streams
    #   4. Send {"text": ""} to flush + signal end of stream
    #   5. Receive {"audio": "base64-pcm", "isFinal": false/true}

    def speak_streaming(
        self,
        get_chunk: Callable[[], str | None],
        log: Callable[[str], None] | None = None,
    ) -> bool:
        """Stream LLM text into ElevenLabs WebSocket TTS.

        Args:
            get_chunk: Blocking callable that returns the next text chunk
                       to speak, or None when the LLM is finished. Called
                       from a worker thread.
            log:       Optional callable for status messages (latency, etc).

        Returns:
            True on success. False on connection failure — caller should
            fall back to the HTTP path or the local Kokoro path.
        """
        if not self._use_cloud or not self._http_client:
            return False
        if not log:
            log = lambda _msg: None

        from friday.core.config import (
            ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL,
        )

        url = ELEVEN_WS_URL.format(voice_id=ELEVENLABS_VOICE_ID)
        # ElevenLabs accepts query params for some settings on stream-input
        url += (
            f"?model_id={ELEVENLABS_MODEL}"
            f"&output_format={ELEVEN_OUTPUT_FORMAT}"
            f"&optimize_streaming_latency=3"
            f"&inactivity_timeout=20"
        )

        # Make sure we have an output stream open with low-latency hint
        if self._out_stream is None:
            self._out_stream = sd.OutputStream(
                samplerate=ELEVEN_SAMPLE_RATE,
                channels=1,
                dtype="int16",
                latency="low",
            )
            self._out_stream.start()

        async def _runner() -> bool:
            try:
                import websockets
            except ImportError:
                logger.warning("websockets not installed — falling back")
                return False

            try:
                async with websockets.connect(
                    url,
                    additional_headers={"xi-api-key": ELEVENLABS_API_KEY},
                    open_timeout=5,
                    ping_interval=10,
                    ping_timeout=5,
                ) as ws:
                    # Initial config message
                    await ws.send(json.dumps({
                        "text": " ",
                        "voice_settings": {
                            "stability": 0.5,
                            "similarity_boost": 0.8,
                            "use_speaker_boost": True,
                        },
                        "generation_config": {
                            # When to fire generation: lower numbers = more
                            # aggressive partial generation, higher latency
                            # smoothness. [50,90,160,210] is fairly snappy.
                            "chunk_length_schedule": [50, 90, 160, 210],
                        },
                        "xi_api_key": ELEVENLABS_API_KEY,
                    }))

                    sender = asyncio.create_task(_send_loop(ws))
                    receiver = asyncio.create_task(_recv_loop(ws))

                    done, pending = await asyncio.wait(
                        [sender, receiver],
                        return_when=asyncio.FIRST_EXCEPTION,
                    )
                    for task in pending:
                        task.cancel()
                    for task in done:
                        exc = task.exception()
                        if exc:
                            raise exc
                return True
            except Exception as e:
                logger.warning("WebSocket TTS failed: %s", e)
                return False

        async def _send_loop(ws):
            """Pull text chunks from get_chunk() and push to ws."""
            loop = asyncio.get_event_loop()
            sent_chars = [0]
            while True:
                if self._interrupted:
                    break
                # Run the (blocking) get_chunk in a thread executor so we
                # don't block the event loop.
                chunk = await loop.run_in_executor(None, get_chunk)
                if chunk is None:
                    # End-of-stream — empty text flushes ElevenLabs.
                    await ws.send(json.dumps({"text": ""}))
                    break
                if not chunk.strip():
                    continue
                # Trigger generation as soon as we have something to say.
                await ws.send(json.dumps({
                    "text": chunk,
                    "try_trigger_generation": sent_chars[0] == 0,
                }))
                sent_chars[0] += len(chunk)

        first_audio_logged = [False]
        t_start = [None]

        async def _recv_loop(ws):
            """Read audio frames from ws and write to output stream."""
            t_start[0] = asyncio.get_event_loop().time()
            async for raw in ws:
                if self._interrupted:
                    break
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                audio_b64 = msg.get("audio")
                if audio_b64:
                    if not first_audio_logged[0]:
                        first_audio_logged[0] = True
                        elapsed_ms = (asyncio.get_event_loop().time() - t_start[0]) * 1000
                        log(f"  ⏱ TTS first byte (WS): {elapsed_ms:.0f}ms")
                    audio = base64.b64decode(audio_b64)
                    samples = np.frombuffer(audio, dtype=np.int16)
                    if samples.size:
                        # OutputStream.write is thread-safe; called from coroutine.
                        self._out_stream.write(samples.reshape(-1, 1))
                if msg.get("isFinal"):
                    break

        self._playing = True
        try:
            return asyncio.run(_runner())
        finally:
            self._playing = False

    # ── Kokoro local (fallback) ──────────────────────────────────────────

    def _speak_local(self, text: str) -> None:
        """Synthesize with Kokoro and play. Blocking."""
        self._ensure_kokoro()
        try:
            samples, sr = self._kokoro.create(
                text, voice=KOKORO_VOICE, speed=KOKORO_SPEED
            )
            if self._interrupted:
                return
            self._playing = True
            sd.play(samples, samplerate=sr)
            sd.wait()
        except Exception:
            pass
        finally:
            self._playing = False

    def _ensure_kokoro(self):
        if self._kokoro is None:
            with self._lock:
                if self._kokoro is None:
                    self._kokoro = _load_kokoro()

    # ── Legacy API (kept for compatibility) ──────────────────────────────

    def synthesize(self, text: str) -> tuple[np.ndarray, int] | None:
        """Synthesize text to audio without playing. Returns (samples, sample_rate) or None.
        Only uses local Kokoro (can't return streaming cloud audio as array).
        """
        if not text.strip():
            return None
        self._ensure_kokoro()
        try:
            samples, sr = self._kokoro.create(
                text, voice=KOKORO_VOICE, speed=KOKORO_SPEED
            )
            return samples, sr
        except Exception:
            return None

    def play(self, samples: np.ndarray, sample_rate: int) -> None:
        """Play pre-synthesized audio. Blocking. Respects interruption."""
        if self._interrupted:
            return
        self._playing = True
        try:
            sd.play(samples, samplerate=sample_rate)
            sd.wait()
        except Exception:
            pass
        finally:
            self._playing = False
