"""Text-to-Speech — ElevenLabs streaming (primary) + Kokoro ONNX (fallback).

Cloud TTS:  ElevenLabs Flash v2.5 (~75ms latency), streams PCM chunks in real-time.
Local TTS:  Kokoro-82M ONNX, fully offline, ~1-2s per sentence on M4.

Auto-switches: if ELEVENLABS_API_KEY is set → cloud. Otherwise → local Kokoro.
Falls back to Kokoro on any cloud error (network, rate limit, etc.).
"""

import io
import os
import logging
import threading
import tempfile
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
                logger.debug(f"ElevenLabs failed ({type(e).__name__}: {e}), falling back to Kokoro")

        self._speak_local(text)

    def stop(self):
        """Stop current playback immediately (barge-in)."""
        self._interrupted = True
        self._playing = False
        try:
            sd.stop()
        except Exception:
            pass

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
            timeout=10.0,
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
            "text": text[:1000],
            "model_id": ELEVENLABS_MODEL,
        }

        if self._last_request_id:
            body["previous_request_ids"] = [self._last_request_id]

        params = {
            "output_format": ELEVEN_OUTPUT_FORMAT,
            "optimize_streaming_latency": "3",  # 0-4, prioritize speed over quality
        }

        self._playing = True
        request_id = None

        try:
            with self._http_client.stream(
                "POST", url,
                json=body, params=params,
            ) as response:
                response.raise_for_status()

                request_id = response.headers.get("request-id")

                with sd.OutputStream(
                    samplerate=ELEVEN_SAMPLE_RATE,
                    channels=1,
                    dtype="int16",
                ) as out_stream:
                    for chunk in response.iter_bytes(chunk_size=4800):
                        if self._interrupted:
                            break
                        if chunk:
                            samples = np.frombuffer(chunk, dtype=np.int16)
                            out_stream.write(samples.reshape(-1, 1))

        finally:
            self._playing = False
            if request_id:
                self._last_request_id = request_id

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
