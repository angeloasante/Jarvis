"""Wake word detection — OpenWakeWord wrapper."""

import numpy as np
import openwakeword
from openwakeword.model import Model

from friday.voice.config import WAKE_WORD_MODEL, WAKE_WORD_THRESHOLD, FRAME_SIZE


class WakeWordDetector:
    """Listens for 'Hey FRIDAY' (using 'hey_jarvis' model until custom trained)."""

    def __init__(self):
        # Download default models on first run
        openwakeword.utils.download_models()
        self.model = Model(
            wakeword_models=[WAKE_WORD_MODEL],
            inference_framework="onnx",
        )
        self._enabled = True

    def detect(self, chunk: np.ndarray) -> bool:
        """Feed audio chunk, return True if wake word detected.

        Args:
            chunk: int16 numpy array, 80ms at 16kHz (1280 samples).
        """
        if not self._enabled:
            return False

        prediction = self.model.predict(chunk)
        score = prediction.get(WAKE_WORD_MODEL, 0.0)
        if score > WAKE_WORD_THRESHOLD:
            self.reset()
            return True
        return False

    def reset(self):
        """Reset internal buffers."""
        self.model.reset()

    def enable(self):
        self._enabled = True

    def disable(self):
        """Disable during TTS playback to prevent feedback."""
        self._enabled = False
