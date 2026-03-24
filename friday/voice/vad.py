"""Voice Activity Detection — Silero VAD wrapper."""

import numpy as np
import torch
import silero_vad

from friday.voice.config import (
    SAMPLE_RATE,
    VAD_THRESHOLD,
    VAD_SILENCE_FRAMES,
    VAD_MIN_SPEECH_FRAMES,
)


class VoiceActivityDetector:
    """Detects speech start/end using Silero VAD."""

    def __init__(self):
        self.model = silero_vad.load_silero_vad()
        self._silence_count = 0
        self._speech_count = 0
        self._is_speaking = False

    def is_speech(self, chunk: np.ndarray) -> bool:
        """Check if a single audio chunk contains speech.

        Args:
            chunk: int16 numpy array, 512 samples at 16kHz.
        """
        tensor = torch.from_numpy(chunk.astype(np.float32) / 32768.0)
        prob = self.model(tensor, SAMPLE_RATE).item()
        return prob > VAD_THRESHOLD

    def feed(self, chunk: np.ndarray) -> str:
        """Feed a chunk and return state: 'speech', 'silence', or 'end'.

        Returns 'end' when speech was detected and then silence lasted
        longer than VAD_SILENCE_FRAMES.
        """
        speech = self.is_speech(chunk)

        if speech:
            self._speech_count += 1
            self._silence_count = 0
            if not self._is_speaking and self._speech_count >= VAD_MIN_SPEECH_FRAMES:
                self._is_speaking = True
            return "speech"
        else:
            self._silence_count += 1
            if self._is_speaking and self._silence_count >= VAD_SILENCE_FRAMES:
                return "end"
            return "silence"

    def reset(self):
        """Reset state for next utterance."""
        self._silence_count = 0
        self._speech_count = 0
        self._is_speaking = False
        self.model.reset_states()
