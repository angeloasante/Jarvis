"""Cloud STT — ElevenLabs Scribe v2 Realtime via WebSocket.

Streams mic audio over a persistent WebSocket connection. ElevenLabs handles
transcription server-side, returning partial and committed transcripts
in real-time (~30-80ms latency).

Client-side Silero VAD gates audio before sending — only speech reaches the
cloud. Background noise, music, and silence never leave the device.
"""

import asyncio
import base64
import collections
import json
import logging
from typing import Callable

import numpy as np
import sounddevice as sd
import websockets

from friday.voice.config import SAMPLE_RATE, CHANNELS, FRAME_SIZE

logger = logging.getLogger(__name__)

WS_URL = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"

# Batch ~5 chunks before sending (reduces WebSocket message overhead)
# 5 × 512 samples × 2 bytes = 5120 bytes (~160ms of audio)
SEND_THRESHOLD = FRAME_SIZE * 2 * 5

# Pre-roll: keep last N chunks so speech onset isn't clipped
PRE_ROLL_CHUNKS = 3  # ~96ms of audio before VAD triggers


class CloudListener:
    """Always-on cloud transcription with local VAD gating.

    Silero VAD runs locally to filter noise/music. Only confirmed speech
    is sent to ElevenLabs Scribe Realtime over WebSocket.
    """

    def __init__(
        self,
        on_partial: Callable[[str], None],
        on_committed: Callable[[str], None],
        language: str = "en",
    ):
        self.on_partial = on_partial
        self.on_committed = on_committed
        self.language = language
        self._running = False
        self._muted = False
        self._audio_queue: asyncio.Queue[bytes] = asyncio.Queue()

        # Local VAD gate — filters noise before it reaches the cloud
        from friday.voice.vad import VoiceActivityDetector
        self._vad = VoiceActivityDetector()

    def stop(self):
        self._running = False

    def mute(self):
        """Pause sending audio (during TTS playback to prevent feedback)."""
        self._muted = True

    def unmute(self):
        self._muted = False

    async def run(self):
        """Main loop — connect, stream speech-only audio, receive transcripts."""
        from friday.core.config import ELEVENLABS_API_KEY

        self._running = True

        params = {
            "model_id": "scribe_v2_realtime",
            "audio_format": f"pcm_{SAMPLE_RATE}",
            "commit_strategy": "vad",
            "language_code": self.language,
            # Stricter server-side VAD (second layer after local Silero)
            "vad_threshold": "0.6",
            "vad_silence_threshold_secs": "1.0",
            "min_speech_duration_ms": "400",
            "min_silence_duration_ms": "200",
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{WS_URL}?{query}"

        headers = {"xi-api-key": ELEVENLABS_API_KEY}

        while self._running:
            try:
                async with websockets.connect(
                    url,
                    additional_headers=headers,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    msg = await asyncio.wait_for(ws.recv(), timeout=10)
                    data = json.loads(msg)
                    if data.get("message_type") == "session_started":
                        logger.debug(f"Scribe session: {data.get('session_id')}")

                    await asyncio.gather(
                        self._send_audio(ws),
                        self._receive_transcripts(ws),
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._running:
                    logger.debug(f"Cloud STT error ({type(e).__name__}), reconnecting in 2s")
                    await asyncio.sleep(2)

    async def _send_audio(self, ws):
        """Read mic, gate through local VAD, batch and send speech to ElevenLabs."""
        loop = asyncio.get_running_loop()

        # Local VAD state
        is_speaking = False
        pre_roll = collections.deque(maxlen=PRE_ROLL_CHUNKS)
        send_buffer = bytearray()

        def _audio_callback(indata, frames, time_info, status):
            if self._muted or not self._running:
                return
            audio = indata[:, 0] if indata.ndim > 1 else indata.flatten()
            raw = audio.astype(np.int16).tobytes()
            # Also pass the numpy array for VAD check
            loop.call_soon_threadsafe(
                self._audio_queue.put_nowait, (raw, audio.copy())
            )

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=FRAME_SIZE,
            callback=_audio_callback,
        ):
            while self._running:
                try:
                    item = await asyncio.wait_for(
                        self._audio_queue.get(), timeout=5.0,
                    )
                except asyncio.TimeoutError:
                    continue

                raw_bytes, audio_np = item

                # Local VAD gate: only send speech, not noise/music
                speech = self._vad.is_speech(audio_np)

                if speech:
                    if not is_speaking:
                        # Speech just started — flush pre-roll buffer first
                        is_speaking = True
                        for pre_chunk in pre_roll:
                            send_buffer.extend(pre_chunk)
                        pre_roll.clear()

                    send_buffer.extend(raw_bytes)

                    # Batch: send when buffer reaches threshold (~160ms)
                    if len(send_buffer) >= SEND_THRESHOLD:
                        await self._send_chunk(ws, bytes(send_buffer))
                        send_buffer.clear()

                else:
                    if is_speaking:
                        # Speech just ended — flush remaining buffer
                        if send_buffer:
                            send_buffer.extend(raw_bytes)  # Include this trailing chunk
                            await self._send_chunk(ws, bytes(send_buffer))
                            send_buffer.clear()
                        is_speaking = False
                        self._vad.reset()
                    else:
                        # Silence/noise — just keep pre-roll rotating
                        pre_roll.append(raw_bytes)

    async def _send_chunk(self, ws, audio_bytes: bytes):
        """Send a batched audio chunk over WebSocket."""
        msg = json.dumps({
            "message_type": "input_audio_chunk",
            "audio_base_64": base64.b64encode(audio_bytes).decode(),
        })
        try:
            await ws.send(msg)
        except Exception:
            raise  # Let the outer loop handle reconnection

    async def _receive_transcripts(self, ws):
        """Receive and handle transcripts from ElevenLabs."""
        try:
            async for msg in ws:
                if not self._running:
                    break

                data = json.loads(msg)
                msg_type = data.get("message_type", "")

                if msg_type == "partial_transcript":
                    text = data.get("text", "").strip()
                    if text:
                        self.on_partial(text)

                elif msg_type in ("committed_transcript", "committed_transcript_with_timestamps"):
                    text = data.get("text", "").strip()
                    if text:
                        self.on_committed(text)

                elif "error" in msg_type:
                    logger.warning(f"Scribe error: {data}")

        except websockets.exceptions.ConnectionClosed:
            pass
