"""FRIDAY Vision — gesture control via MediaPipe hand tracking."""

import os

# Suppress MediaPipe / TFLite C++ logs — must be set before any mediapipe import
os.environ.setdefault("GLOG_minloglevel", "3")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

# OpenCV's AVFoundation backend on macOS tries to pop up the camera
# permission dialog when first accessed. That dialog can only be shown
# from the main run loop — and our gesture listener runs in a daemon
# thread, which triggers: "can not spin main run loop from other thread".
#
# Setting this env var tells OpenCV to skip its own auth request and rely
# on whatever permission the host process already has. The user still
# needs to grant camera access to their terminal (or to Friday.app for the
# bundled Mac build) via System Settings → Privacy & Security → Camera,
# but at least the failure is clean instead of a thread-crash.
os.environ.setdefault("OPENCV_AVFOUNDATION_SKIP_AUTH", "1")

try:
    import absl.logging
    absl.logging.set_verbosity(absl.logging.ERROR)
except ImportError:
    pass
