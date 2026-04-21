"""MediaPipe gesture recognition — two hands, pinch, combos.

Uses GestureRecognizer (7 built-in gestures per hand) plus custom
landmark-based detection (pinch, pinch drag) for anything the
built-in model doesn't cover.

All local, pure CPU, ~30fps on M-series MacBooks.
"""

import logging
import os
import math
import numpy as np
from dataclasses import dataclass, field
from pathlib import Path

# Suppress MediaPipe C++ logs before any import
os.environ.setdefault("GLOG_minloglevel", "3")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
logging.getLogger("mediapipe").setLevel(logging.ERROR)

try:
    import absl.logging
    absl.logging.set_verbosity(absl.logging.ERROR)
except ImportError:
    pass

try:
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python.vision import (
        GestureRecognizer,
        GestureRecognizerOptions,
        RunningMode,
    )
    _HAS_MEDIAPIPE = True
except ImportError:
    _HAS_MEDIAPIPE = False

_MODEL_PATH = Path.home() / ".friday" / "models" / "gesture_recognizer.task"

# Pinch detection threshold (normalized landmark distance)
PINCH_THRESHOLD = 0.06


@dataclass
class HandState:
    """State of a single detected hand."""
    side: str                   # "Right" or "Left"
    gesture: str | None         # Built-in gesture name or None
    confidence: float
    pinching: bool = False
    pinch_pos: tuple[float, float] | None = None  # (x, y) of pinch point
    landmarks: list = field(default_factory=list)


@dataclass
class FrameResult:
    """Full gesture state for one frame — up to 2 hands."""
    hands: list[HandState] = field(default_factory=list)

    @property
    def right(self) -> HandState | None:
        return next((h for h in self.hands if h.side == "Right"), None)

    @property
    def left(self) -> HandState | None:
        return next((h for h in self.hands if h.side == "Left"), None)

    def compound_name(self) -> str | None:
        """Build a compound gesture name for command lookup.

        Priority: two-hand combos > pinch > single hand.
        Returns names like: both_fists, right_closed_fist, left_pinch,
        right_pinch_drag_up, etc.
        """
        r, l = self.right, self.left

        # Two hands detected — check combos first
        if r and l:
            rg = r.gesture
            lg = l.gesture

            # Both same gesture
            if rg and lg and rg == lg:
                return f"both_{rg.lower()}"

            # Both pinching
            if r.pinching and l.pinching:
                return "both_pinch"

            # Mixed combos (right_X_left_Y)
            if rg and lg:
                return f"right_{rg.lower()}_left_{lg.lower()}"

            # One hand gesture + other pinching
            if rg and l.pinching:
                return f"right_{rg.lower()}_left_pinch"
            if lg and r.pinching:
                return f"right_pinch_left_{lg.lower()}"

        # Single hand
        hand = r or l
        if not hand:
            return None

        prefix = hand.side.lower()

        # Pinch takes priority over "None" gesture
        if hand.pinching:
            return f"{prefix}_pinch"

        if hand.gesture:
            return f"{prefix}_{hand.gesture.lower()}"

        return None


class GestureEngine:
    """Detect gestures from camera frames — two hands, pinch, combos."""

    def __init__(self):
        if not _HAS_MEDIAPIPE:
            raise RuntimeError(
                "MediaPipe not installed. Run: uv add mediapipe opencv-python"
            )
        if not _MODEL_PATH.exists():
            raise RuntimeError(
                f"Gesture model not found at {_MODEL_PATH}. "
                "Download: curl -sL -o ~/.friday/models/gesture_recognizer.task "
                '"https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/latest/gesture_recognizer.task"'
            )

        options = GestureRecognizerOptions(
            base_options=BaseOptions(model_asset_path=str(_MODEL_PATH)),
            running_mode=RunningMode.IMAGE,
            num_hands=2,
            min_hand_detection_confidence=0.4,
            min_hand_presence_confidence=0.4,
            min_tracking_confidence=0.4,
        )

        # Suppress C++ noise during model load
        import sys
        _stderr_fd = os.dup(2)
        _devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(_devnull, 2)
        os.close(_devnull)
        try:
            self._recognizer = GestureRecognizer.create_from_options(options)
        finally:
            os.dup2(_stderr_fd, 2)
            os.close(_stderr_fd)

    def detect(self, frame: np.ndarray) -> FrameResult:
        """Detect gestures from a BGR frame. Returns up to 2 hands.

        Uses wrist x-position to determine left/right hand instead of
        MediaPipe's built-in classifier (which is unreliable with mirrored cameras).
        Camera is mirrored: hand on LEFT side of frame = user's RIGHT hand.
        """
        import cv2

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self._recognizer.recognize(image)

        frame_result = FrameResult()

        if not result.gestures:
            return frame_result

        for i in range(len(result.gestures)):
            gesture_info = result.gestures[i][0]
            gesture_name = gesture_info.category_name
            confidence = gesture_info.score
            landmarks = result.hand_landmarks[i]

            # Determine left/right from wrist position (much more reliable
            # than MediaPipe's handedness classifier on mirrored cameras)
            wrist_x = landmarks[0].x
            side = "Right" if wrist_x < 0.5 else "Left"

            # If two hands detected, ensure they don't both get the same side
            if len(result.gestures) == 2 and i == 1 and frame_result.hands:
                other_side = frame_result.hands[0].side
                if side == other_side:
                    side = "Left" if other_side == "Right" else "Right"

            # Built-in gesture (ignore "None")
            name = gesture_name if gesture_name != "None" else None

            # Custom: pinch detection from landmarks
            pinching, pinch_pos = self._check_pinch(landmarks)

            hand = HandState(
                side=side,
                gesture=name,
                confidence=confidence,
                pinching=pinching,
                pinch_pos=pinch_pos,
                landmarks=landmarks,
            )
            frame_result.hands.append(hand)

        return frame_result

    @staticmethod
    def _check_pinch(landmarks) -> tuple[bool, tuple[float, float] | None]:
        """Check if thumb tip and index tip are close (pinch gesture)."""
        thumb = landmarks[4]
        index = landmarks[8]

        dist = math.hypot(thumb.x - index.x, thumb.y - index.y)

        if dist < PINCH_THRESHOLD:
            # Pinch point = midpoint between thumb and index
            px = (thumb.x + index.x) / 2
            py = (thumb.y + index.y) / 2
            return True, (px, py)

        return False, None

    def close(self):
        """Release MediaPipe resources."""
        self._recognizer.close()
