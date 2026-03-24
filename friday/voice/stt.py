"""Speech-to-Text — MLX Whisper wrapper for Apple Silicon."""

import numpy as np
import mlx_whisper

from friday.voice.config import WHISPER_MODEL, WHISPER_LANGUAGE


class Transcriber:
    """Transcribes audio to text using MLX Whisper."""

    def __init__(self):
        self.model_path = WHISPER_MODEL
        # Warm up — first call downloads + loads the model
        self._warmed_up = False

    def warmup(self):
        """Pre-load model so first real transcription is fast."""
        if not self._warmed_up:
            silence = np.zeros(16000, dtype=np.float32)  # 1s silence
            mlx_whisper.transcribe(
                silence,
                path_or_hf_repo=self.model_path,
                language=WHISPER_LANGUAGE,
            )
            self._warmed_up = True

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe audio buffer to text.

        Args:
            audio: int16 or float32 numpy array at 16kHz mono.

        Returns:
            Transcribed text string (stripped).
        """
        # Convert int16 to float32 if needed
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0

        result = mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=self.model_path,
            language=WHISPER_LANGUAGE,
        )
        text = result.get("text", "").strip()
        return text
