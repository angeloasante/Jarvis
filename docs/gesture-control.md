# Gesture Control (MediaPipe)

FRIDAY can see you. Raise your hand, hold a gesture, and FRIDAY reacts. No voice needed, no typing needed. Just your MacBook camera and your hands.

Tony Stark waved his hands and holograms moved. This is the same concept — minus the holograms, plus a real working system.

## How It Works

```
MacBook FaceTime Camera (built-in)
    |
    |  30fps video frames
    v
MediaPipe GestureRecognizer (Google, runs locally)
    |
    |  Detects hand + classifies gesture
    v
Gesture Listener (daemon thread)
    |
    |  Hold threshold (0.4s) + cooldown (1.5s)
    v
FridayCore.fast_path() or dispatch_background()
    |
    v
TV mutes. Volume changes. Briefing starts.
```

The entire pipeline runs locally. No cloud. No GPU. MediaPipe uses TFLite on CPU — optimized for Apple Silicon, runs at 30fps without breaking a sweat.

The gesture listener runs as a daemon thread, identical architecture to the voice pipeline. Camera captures frames, MediaPipe classifies the hand shape, and if you hold a gesture steady for 0.4 seconds, it fires the mapped command through the normal FRIDAY pipeline. Most commands (TV control) hit the fast_path and execute in under a second with zero LLM calls.

## Supported Gestures

29 gestures total — right hand, left hand, two-hand combos, pinch, and pinch drag. All customizable from `.env`.

### ✋ Right Hand

| | Gesture | What To Do | FRIDAY Command |
|---|---------|-----------|----------------|
| ✊ | **Closed Fist** | Close all fingers tight | mute |
| 🖐 | **Open Palm** | All five fingers spread | unmute |
| 👆 | **Pointing Up** | Index finger up, rest closed | turn it up |
| 👍 | **Thumb Up** | Thumb up, rest closed | play |
| 👎 | **Thumb Down** | Thumb down, rest closed | turn it down |
| ✌️ | **Victory** | Index + middle up (peace sign) | pause |
| 🤟 | **ILoveYou** | Thumb + index + pinky up | catch me up |
| 🤌 | **Pinch** | Thumb tip + index tip touching | what's on my screen |

### 🤚 Left Hand

| | Gesture | What To Do | FRIDAY Command |
|---|---------|-----------|----------------|
| ✊ | **Closed Fist** | Close all fingers tight | privacy mode |
| 🖐 | **Open Palm** | All five fingers spread | catch me up |
| 👆 | **Pointing Up** | Index finger up | brightness up |
| 👍 | **Thumb Up** | Thumb up | save to memory |
| 👎 | **Thumb Down** | Thumb down | forget that |
| ✌️ | **Victory** | Index + middle up | read this |
| 🤟 | **ILoveYou** | Thumb + index + pinky | evening briefing |
| 🤌 | **Pinch** | Thumb + index touching | screenshot |

### 🙌 Both Hands (same gesture)

| | Gesture | FRIDAY Command |
|---|---------|----------------|
| ✊✊ | Both Fists | silence everything |
| 🖐🖐 | Both Palms | full attention |
| 👍👍 | Both Thumbs Up | send it |
| 👎👎 | Both Thumbs Down | cancel everything |
| ✌️✌️ | Both Victory | screenshot and tweet |
| 🤟🤟 | Both ILoveYou | party mode |
| 🤌🤌 | Both Pinch | zoom |

### 🤝 Mixed Combos (different gesture each hand)

| | Gesture | FRIDAY Command |
|---|---------|----------------|
| ✊🖐 | Right Fist + Left Palm | i'm leaving |
| 🖐✊ | Right Palm + Left Fist | i'm back |

### 🤌 Pinch Drag (continuous — pinch then move hand)

| | Gesture | FRIDAY Command |
|---|---------|----------------|
| 🤌☝️ | Right pinch + drag up | turn it up (volume) |
| 🤌👇 | Right pinch + drag down | turn it down (volume) |
| 🤌☝️ | Left pinch + drag up | brightness up |
| 🤌👇 | Left pinch + drag down | brightness down |

Pinch drag fires continuously as you move — like dragging a holographic slider in mid-air. The Tony Stark moment.

The 7 base gestures come from MediaPipe's GestureRecognizer model, trained on a large dataset — works across skin tones, lighting conditions, and hand sizes. Pinch is custom landmark-based detection on top.

## Timing

- **Hold threshold: 0.4 seconds** — You need to hold the gesture steady for 0.4s before it fires. This prevents accidental triggers from waving your hand around or scratching your head.
- **Cooldown: 1.5 seconds** — After a gesture fires, the same gesture won't fire again for 1.5s. Different gestures can still fire independently.
- **Grace window: 0.3 seconds** — MediaPipe sometimes drops detection for a frame or two. The system tolerates 300ms gaps without resetting the hold timer.

## Prerequisites

- **MacBook with FaceTime camera** (any Mac with a built-in camera works)
- **macOS camera permissions** for Terminal / your IDE
- **Python dependencies**: `mediapipe`, `opencv-python` (installed automatically with FRIDAY)
- **Model file**: `~/.friday/models/gesture_recognizer.task` (8MB, downloaded once)

## Setup

### 1. Install dependencies (if not already)

```bash
uv add mediapipe opencv-python
```

### 2. Download the gesture model

```bash
mkdir -p ~/.friday/models
curl -sL -o ~/.friday/models/gesture_recognizer.task \
  "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/latest/gesture_recognizer.task"
```

### 3. Enable gesture control

In your `.env` file:
```
FRIDAY_GESTURES=true
```

Or toggle at runtime:
```
/gestures
```

### 4. Grant camera permission

macOS will prompt for camera access the first time. If it doesn't work:
- System Settings > Privacy & Security > Camera
- Enable access for Terminal (or VS Code, iTerm, whatever you run FRIDAY from)

## Running

Start FRIDAY normally:
```bash
friday
```

If `FRIDAY_GESTURES=true` is set, you'll see:
```
  :: Gesture control ACTIVE
     Hold gesture 0.4s to trigger:
     ✊ Fist = mute  |  🖐 Palm = pause  |  👆 Point = vol up
     👍 Thumb up = YouTube  |  👎 Thumb down = vol down
     ✌️ Victory = TV off  |  🤟 ILoveYou = briefing
```

Hold a gesture to your camera. FRIDAY fires the command:
```
  GESTURE Closed_Fist -> mute
  FRIDAY Muted.

  GESTURE Open_Palm -> pause
  FRIDAY Paused.
```

Toggle on/off at runtime:
```
/gestures    → Gestures ON / Gestures OFF
```

## Customizing Gestures

Everything is in `.env` — no Python files to touch. Each gesture has an env var:

```bash
# Change right fist from mute to turning off the TV
GESTURE_RIGHT_CLOSED_FIST=turn off tv

# Make left thumbs up check your email
GESTURE_LEFT_THUMB_UP=check my email

# Make both palms trigger a web search
GESTURE_BOTH_OPEN_PALM=search for AI news

# Adjust timing
GESTURE_HOLD_SECONDS=0.6          # Slower trigger (default 0.4)
GESTURE_COOLDOWN_SECONDS=2.0      # Longer cooldown (default 1.5)
GESTURE_PINCH_DRAG_THRESHOLD=0.08 # Less sensitive drag (default 0.06)
```

The command strings are regular FRIDAY input — they go through the same routing as typing. If it works when you type it, it works as a gesture command.

Full list of env var names:
```
GESTURE_RIGHT_CLOSED_FIST      # ✊ Right fist
GESTURE_RIGHT_OPEN_PALM        # 🖐 Right palm
GESTURE_RIGHT_POINTING_UP      # 👆 Right point up
GESTURE_RIGHT_THUMB_UP         # 👍 Right thumbs up
GESTURE_RIGHT_THUMB_DOWN       # 👎 Right thumbs down
GESTURE_RIGHT_VICTORY          # ✌️ Right peace
GESTURE_RIGHT_ILOVEYOU         # 🤟 Right ILoveYou
GESTURE_RIGHT_PINCH            # 🤌 Right pinch

GESTURE_LEFT_CLOSED_FIST       # ✊ Left fist
GESTURE_LEFT_OPEN_PALM         # 🖐 Left palm
GESTURE_LEFT_POINTING_UP       # 👆 Left point up
GESTURE_LEFT_THUMB_UP          # 👍 Left thumbs up
GESTURE_LEFT_THUMB_DOWN        # 👎 Left thumbs down
GESTURE_LEFT_VICTORY           # ✌️ Left peace
GESTURE_LEFT_ILOVEYOU          # 🤟 Left ILoveYou
GESTURE_LEFT_PINCH             # 🤌 Left pinch

GESTURE_BOTH_CLOSED_FIST       # ✊✊ Both fists
GESTURE_BOTH_OPEN_PALM         # 🖐🖐 Both palms
GESTURE_BOTH_THUMB_UP          # 👍👍 Both thumbs up
GESTURE_BOTH_THUMB_DOWN        # 👎👎 Both thumbs down
GESTURE_BOTH_VICTORY           # ✌️✌️ Both peace
GESTURE_BOTH_ILOVEYOU          # 🤟🤟 Both ILoveYou
GESTURE_BOTH_PINCH             # 🤌🤌 Both pinch

GESTURE_RIGHT_CLOSED_FIST_LEFT_OPEN_PALM   # ✊🖐 Mixed combo
GESTURE_RIGHT_OPEN_PALM_LEFT_CLOSED_FIST   # 🖐✊ Mixed combo

GESTURE_RIGHT_PINCH_DRAG_UP    # 🤌☝️ Right drag up
GESTURE_RIGHT_PINCH_DRAG_DOWN  # 🤌👇 Right drag down
GESTURE_LEFT_PINCH_DRAG_UP     # 🤌☝️ Left drag up
GESTURE_LEFT_PINCH_DRAG_DOWN   # 🤌👇 Left drag down
```

## Architecture

```
friday/vision/
    __init__.py              # Package init, suppresses MediaPipe logs
    gesture_engine.py        # MediaPipe GestureRecognizer wrapper
    gesture_commands.py      # Gesture -> command mapping + timing constants
    gesture_listener.py      # Daemon thread (same pattern as VoicePipeline)
```

The gesture system follows the exact same daemon thread pattern as the voice pipeline (`friday/voice/pipeline.py`):

1. `GestureListener.__init__(friday, main_loop)` — stores FridayCore + event loop references
2. `start()` — spawns a daemon thread
3. `_run()` — opens camera, enters frame loop, detects gestures
4. `_fire_command()` — bridges to FridayCore via `asyncio.run_coroutine_threadsafe()`
5. `stop()` — sets flag, thread exits, camera releases

Voice and gesture can run simultaneously. They're independent threads dispatching through the same FridayCore instance. Thread-safe by design.

## Troubleshooting

**Camera not detected:**
```
Gesture init failed: Camera unavailable
```
- Check macOS camera permissions (System Settings > Privacy > Camera)
- Close other apps using the camera (Zoom, FaceTime, Photo Booth)
- Try `GESTURE_CAMERA_ID=1` if you have an external camera

**No gestures detected:**
- Make sure your hand is clearly visible to the camera
- Good lighting helps — MediaPipe works in low light but detection improves with better lighting
- Hold your hand 1-3 feet from the camera
- Try an open palm first — it's the easiest to detect

**Gesture fires too easily / not easily enough:**
Edit `friday/vision/gesture_commands.py`:
```python
HOLD_THRESHOLD_SECONDS = 0.4   # Increase to 0.6-0.8 if too sensitive
COOLDOWN_SECONDS = 1.5          # Increase if same gesture fires too often
```

**MediaPipe model not found:**
```bash
curl -sL -o ~/.friday/models/gesture_recognizer.task \
  "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/latest/gesture_recognizer.task"
```

## The Tech

- **MediaPipe** (Google) — Apache 2.0, hand tracking + gesture classification
- **GestureRecognizer model** — float16, 8MB, 7 built-in gestures
- **OpenCV** — camera capture via AVFoundation on macOS
- **TFLite + XNNPACK** — inference backend, optimized for ARM/Apple Silicon
- **No GPU required** — runs entirely on CPU at 30fps

## What's Next

MediaPipe also supports:
- **Face mesh** (468 landmarks) — raise eyebrows, wink, nod, shake head
- **Pose detection** (33 body landmarks) — full body gestures
- **Custom gesture training** — train your own gestures on top of the hand landmarks

Same camera. Same library. Just different models.
