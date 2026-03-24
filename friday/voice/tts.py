"""Text-to-Speech — Kokoro ONNX wrapper."""

import os
import threading
import tempfile
import numpy as np
import sounddevice as sd

from friday.voice.config import KOKORO_VOICE, KOKORO_SPEED

# Kokoro's native sample rate
KOKORO_SAMPLE_RATE = 24000
KOKORO_REPO = "onnx-community/Kokoro-82M-v1.0-ONNX"


def _load_kokoro():
    """Download model and voice, return Kokoro instance."""
    from huggingface_hub import hf_hub_download
    from kokoro_onnx import Kokoro

    model_path = hf_hub_download(KOKORO_REPO, "onnx/model.onnx")
    voice_path = hf_hub_download(KOKORO_REPO, f"voices/{KOKORO_VOICE}.bin")

    # Voice .bin is raw float32, reshape to (N, 256) for style lookup
    voice_data = np.fromfile(voice_path, dtype=np.float32).reshape(-1, 256)

    # kokoro_onnx expects an .npz file with voice name → (N, 256) array
    voices_file = os.path.join(
        tempfile.gettempdir(), "friday_kokoro_voices.npz"
    )
    np.savez(voices_file, **{KOKORO_VOICE: voice_data})

    kokoro = Kokoro(model_path, voices_file)

    # Monkey-patch _create_audio to fix rank mismatch (style needs [1, 256])
    def _patched_create(phonemes, voice, speed):
        from kokoro_onnx import MAX_PHONEME_LENGTH, SAMPLE_RATE as K_SR

        phonemes = phonemes[:MAX_PHONEME_LENGTH]
        tokens = np.array(kokoro.tokenizer.tokenize(phonemes), dtype=np.int64)

        style = voice[len(tokens)]  # (256,)
        style = style.reshape(1, -1)  # (1, 256) — fix rank

        tokens = [[0, *tokens, 0]]
        inputs = {
            "input_ids": tokens,
            "style": np.array(style, dtype=np.float32),
            "speed": np.array([speed], dtype=np.float32),
        }
        audio = kokoro.sess.run(None, inputs)[0]
        audio = audio.squeeze()  # (1, N) → (N,)
        return audio, K_SR

    kokoro._create_audio = _patched_create
    return kokoro


class Speaker:
    """Synthesizes and plays speech using Kokoro-82M.

    Supports both full-text and sentence-by-sentence streaming.
    """

    def __init__(self):
        self._kokoro = None  # Lazy load
        self._lock = threading.Lock()
        self._playing = False
        self._interrupted = False

    def _ensure_loaded(self):
        if self._kokoro is None:
            self._kokoro = _load_kokoro()

    def synthesize(self, text: str) -> tuple[np.ndarray, int] | None:
        """Synthesize text to audio without playing. Returns (samples, sample_rate) or None."""
        if not text.strip():
            return None

        self._ensure_loaded()
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

    def speak(self, text: str) -> None:
        """Synthesize text and play through speakers. Blocking."""
        self._interrupted = False
        result = self.synthesize(text)
        if result and not self._interrupted:
            self.play(*result)

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
