"""Gesture-to-command mapping — all config from .env.

Supports: single hand (right/left), two-hand combos (both/mixed),
pinch, and pinch drag. Any FRIDAY command works as a value.

Config is loaded fresh each time `load()` is called — so editing
.env and toggling /gestures picks up changes without restarting FRIDAY.
"""

import os
from dotenv import load_dotenv
from pathlib import Path

_ENV_PATH = Path(__file__).parent.parent.parent / ".env"

# ── Defaults (used when env var is not set) ────────────────────────────
_DEFAULTS: dict[str, str] = {
    # Right hand
    "right_closed_fist":    "mute",
    "right_open_palm":      "unmute",
    "right_pointing_up":    "turn it up",
    "right_thumb_up":       "play",
    "right_thumb_down":     "turn it down",
    "right_victory":        "pause",
    "right_iloveyou":       "catch me up",
    "right_pinch":          "what's on my screen",

    # Left hand
    "left_closed_fist":     "privacy mode",
    "left_open_palm":       "catch me up",
    "left_pointing_up":     "brightness up",
    "left_thumb_up":        "save to memory",
    "left_thumb_down":      "forget that",
    "left_victory":         "read this",
    "left_iloveyou":        "evening briefing",
    "left_pinch":           "screenshot",

    # Both hands — same gesture
    "both_closed_fist":     "silence everything",
    "both_open_palm":       "full attention",
    "both_thumb_up":        "send it",
    "both_thumb_down":      "cancel everything",
    "both_victory":         "screenshot and tweet",
    "both_iloveyou":        "party mode",
    "both_pinch":           "zoom",

    # Mixed combos
    "right_closed_fist_left_open_palm":  "i'm leaving",
    "right_open_palm_left_closed_fist":  "i'm back",

    # Pinch drag
    "right_pinch_drag_up":      "turn it up",
    "right_pinch_drag_down":    "turn it down",
    "left_pinch_drag_up":       "brightness up",
    "left_pinch_drag_down":     "brightness down",
}


def load() -> tuple[dict[str, str], float, float, float]:
    """Load gesture config fresh from .env. Returns (gesture_map, hold, cooldown, drag_threshold)."""
    # Re-read .env from disk (picks up edits without restart)
    load_dotenv(_ENV_PATH, override=True)

    hold = float(os.getenv("GESTURE_HOLD_SECONDS", "0.4"))
    cooldown = float(os.getenv("GESTURE_COOLDOWN_SECONDS", "1.5"))
    drag_threshold = float(os.getenv("GESTURE_PINCH_DRAG_THRESHOLD", "0.06"))

    gesture_map = {}
    for name, default_cmd in _DEFAULTS.items():
        env_key = f"GESTURE_{name.upper()}"
        gesture_map[name] = os.getenv(env_key, default_cmd)

    return gesture_map, hold, cooldown, drag_threshold


# Initial load for backward compat (import-time access still works)
GESTURE_MAP, HOLD_THRESHOLD_SECONDS, COOLDOWN_SECONDS, PINCH_DRAG_THRESHOLD = load()
