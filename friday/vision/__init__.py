"""FRIDAY Vision — gesture control via MediaPipe hand tracking."""

import os

# Suppress MediaPipe / TFLite C++ logs — must be set before any mediapipe import
os.environ.setdefault("GLOG_minloglevel", "3")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

try:
    import absl.logging
    absl.logging.set_verbosity(absl.logging.ERROR)
except ImportError:
    pass
