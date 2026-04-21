"""Gesture Listener — two hands, pinch drag, combos.

Daemon thread captures camera frames, MediaPipe classifies gestures,
hold threshold prevents accidental triggers, pinch drag gives continuous
control (volume slider in mid-air).

Same architecture as VoicePipeline — daemon thread + asyncio bridge.
"""

import asyncio
import os
import threading
import time

# Suppress MediaPipe C++ logs before any import
os.environ.setdefault("GLOG_minloglevel", "3")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

from rich.console import Console

from friday.vision import gesture_commands

console = Console()


class GestureListener:
    """Background gesture control — two hands, pinch, combos."""

    def __init__(self, friday, main_loop: asyncio.AbstractEventLoop):
        self.friday = friday
        self.main_loop = main_loop
        self._thread: threading.Thread | None = None
        self._running = False
        self._active = True

        # Config — loaded fresh from .env on each start()
        self._gesture_map: dict[str, str] = {}
        self._hold_threshold: float = 0.4
        self._cooldown: float = 1.5
        self._drag_threshold: float = 0.06

        # Gesture hold tracking
        self._current_gesture: str | None = None
        self._gesture_start: float = 0.0
        self._last_seen: float = 0.0
        self._last_fired: dict[str, float] = {}

        # Pinch drag tracking (per hand)
        self._pinch_start: dict[str, tuple[float, float]] = {}
        self._pinch_last_fire: dict[str, float] = {}

        # Two-hand buffer — if one hand is detected now and the other
        # was detected in a recent frame, merge them for combo detection
        self._hand_buffer: dict[str, tuple] = {}  # side -> (gesture, pinching, pinch_pos, timestamp)
        self._hand_buffer_window: float = 0.4  # seconds to keep a hand in buffer

    # ── Public controls ───────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        # Load config fresh from .env each time (picks up edits)
        self._gesture_map, self._hold_threshold, self._cooldown, self._drag_threshold = gesture_commands.load()
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="friday-gesture"
        )
        self._thread.start()

    def stop(self):
        self._running = False

    def set_active(self, on: bool):
        self._active = on

    # ── Main loop ─────────────────────────────────────────────────────

    def _run(self):
        try:
            cap = self._init_camera()
        except Exception as e:
            console.print(f"  [red]  Gesture init failed: {e}[/red]")
            self._running = False
            return

        from friday.vision.gesture_engine import GestureEngine
        engine = GestureEngine()

        try:
            while self._running:
                if not self._active:
                    time.sleep(0.1)
                    continue

                ret, frame = cap.read()
                if not ret:
                    continue

                result = engine.detect(frame)
                self._process_frame(result)

        finally:
            engine.close()
            cap.release()
            console.print("  [dim green]:: Camera released[/dim green]")

    @staticmethod
    def _init_camera():
        """Open the FaceTime camera with warmup."""
        import cv2

        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            raise RuntimeError(
                "Camera unavailable — check macOS privacy settings "
                "or close apps using the camera"
            )

        # AVFoundation warmup — drain black frames
        for _ in range(8):
            ret, frame = cap.read()
            if ret and frame.mean() > 10:
                break
            time.sleep(0.1)

        console.print(
            "  [bold green]:: Gesture control ACTIVE[/bold green]"
        )
        console.print("  [dim]   Hold gesture 0.4s to trigger. Two hands supported.[/dim]")
        console.print("  [dim]   Pinch + drag = continuous control (volume, brightness)[/dim]")
        console.print()
        return cap

    # ── Frame processing ──────────────────────────────────────────────

    def _process_frame(self, result):
        """Process a full frame result — buffer hands, handle combos + pinch drag."""
        from friday.vision.gesture_engine import FrameResult, HandState
        now = time.time()

        # Update hand buffer with what we see this frame
        for hand in result.hands:
            self._hand_buffer[hand.side] = (
                hand.gesture, hand.pinching, hand.pinch_pos, now
            )

        # Expire old buffer entries
        for side in list(self._hand_buffer):
            _, _, _, ts = self._hand_buffer[side]
            if (now - ts) > self._hand_buffer_window:
                del self._hand_buffer[side]

        # Build a merged FrameResult from current frame + recent buffer
        # This lets two-hand combos work even if hands flicker between frames
        merged = FrameResult()
        seen_sides = set()
        for hand in result.hands:
            merged.hands.append(hand)
            seen_sides.add(hand.side)

        # Add buffered hand if not in current frame
        for side, (gesture, pinching, pinch_pos, ts) in self._hand_buffer.items():
            if side not in seen_sides:
                merged.hands.append(HandState(
                    side=side,
                    gesture=gesture,
                    confidence=0.5,
                    pinching=pinching,
                    pinch_pos=pinch_pos,
                    landmarks=[],
                ))

        # Check for pinch drag FIRST (continuous, bypasses hold threshold)
        self._handle_pinch_drag(result)  # Use real frame, not merged (need real landmarks)

        # Then check for regular gestures (hold threshold applies)
        gesture_name = merged.compound_name()
        self._process_gesture(gesture_name)

    def _handle_pinch_drag(self, result):
        """Track pinch position over time for drag gestures."""
        now = time.time()

        for hand in result.hands:
            side = hand.side.lower()

            if hand.pinching and hand.pinch_pos:
                if side not in self._pinch_start:
                    # Pinch just started — record start position
                    self._pinch_start[side] = hand.pinch_pos
                    self._pinch_last_fire[side] = now
                else:
                    # Already pinching — check for drag
                    start = self._pinch_start[side]
                    cur = hand.pinch_pos
                    dy = start[1] - cur[1]  # positive = dragged up
                    dx = cur[0] - start[0]  # positive = dragged right

                    # Cooldown per drag fire (don't spam)
                    if (now - self._pinch_last_fire.get(side, 0)) < 0.3:
                        continue

                    if abs(dy) > self._drag_threshold:
                        direction = "up" if dy > 0 else "down"
                        drag_name = f"{side}_pinch_drag_{direction}"
                        command = self._gesture_map.get(drag_name)
                        if command:
                            console.print(
                                f"  [bold magenta]DRAG[/bold magenta] "
                                f"[magenta]{drag_name}[/magenta] -> "
                                f"[green]{command}[/green]"
                            )
                            self._fire_command(command)
                            # Reset start to current pos for next drag step
                            self._pinch_start[side] = cur
                            self._pinch_last_fire[side] = now

            else:
                # Not pinching — clear drag state for this hand
                self._pinch_start.pop(side, None)

    def _process_gesture(self, gesture: str | None):
        """Hold threshold + cooldown for regular (non-drag) gestures."""
        now = time.time()
        grace_window = 0.3

        # Skip pinch-only gestures here (handled by drag)
        if gesture and "pinch" in gesture and "drag" not in gesture:
            # Only fire pinch as a regular gesture if not dragging
            for side in ("right", "left"):
                if side in self._pinch_start:
                    return  # Dragging — don't fire pinch as tap

        if gesture is not None and gesture == self._current_gesture:
            self._last_seen = now
            held = now - self._gesture_start
            if held < self._hold_threshold:
                return

            last = self._last_fired.get(gesture, 0.0)
            if (now - last) < self._cooldown:
                return

            command = self._gesture_map.get(gesture)
            if not command:
                return

            console.print(
                f"\n  [bold cyan]GESTURE[/bold cyan] "
                f"[cyan]{gesture}[/cyan] -> [green]{command}[/green]"
            )
            self._fire_command(command)
            self._last_fired[gesture] = now
            self._current_gesture = None
            return

        if gesture is None and self._current_gesture is not None:
            if (now - self._last_seen) < grace_window:
                return
            self._current_gesture = None
            return

        if gesture is not None and gesture != self._current_gesture:
            self._current_gesture = gesture
            self._gesture_start = now
            self._last_seen = now

    # ── Command dispatch ──────────────────────────────────────────────

    def _fire_command(self, command: str):
        """Send command through FRIDAY — fast_path first, agent fallback."""
        try:
            fast_result = asyncio.run_coroutine_threadsafe(
                self.friday.fast_path(command), self.main_loop
            ).result(timeout=15)
        except Exception:
            fast_result = None

        if fast_result is not None:
            console.print(
                f"  [bold green]FRIDAY[/bold green] "
                f"[green]{fast_result}[/green]"
            )
            console.print()
            return

        def on_update(msg: str):
            if msg.startswith("CHUNK:"):
                console.print(f"[green]{msg[6:]}[/green]", end="")
            elif msg.startswith("DONE:"):
                console.print()
            elif msg.startswith("ACK:"):
                console.print(f"  [dim green]  {msg[4:]}[/dim green]")

        self.friday.dispatch_background(command, on_update=on_update)
