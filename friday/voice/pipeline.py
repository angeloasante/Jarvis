"""FRIDAY Voice Pipeline — always-on, fully local.

Wake word → VAD → STT → FridayCore → streaming TTS
Runs in a dedicated thread alongside the CLI.
"""

import asyncio
import queue
import re
import threading
import time
import numpy as np
import sounddevice as sd

from rich.console import Console

from friday.voice.config import (
    SAMPLE_RATE,
    CHANNELS,
    FRAME_SIZE,
    CHIME_FREQ,
    CHIME_DURATION,
    CHIME_VOLUME,
    MAX_VOICE_SENTENCES,
)
from friday.voice.wake_word import WakeWordDetector
from friday.voice.vad import VoiceActivityDetector
from friday.voice.stt import Transcriber
from friday.voice.tts import Speaker

console = Console()

# Sentinel to signal end of stream
_DONE = object()

# Regex to detect sentence boundaries
SENTENCE_END_RE = re.compile(r"[.!?]\s")


def _play_chime():
    """Play a short activation chime."""
    t = np.linspace(0, CHIME_DURATION, int(SAMPLE_RATE * CHIME_DURATION), False)
    chime = (CHIME_VOLUME * np.sin(2 * np.pi * CHIME_FREQ * t)).astype(np.float32)
    fade = np.linspace(1, 0, len(chime))
    chime *= fade
    sd.play(chime, samplerate=SAMPLE_RATE)
    sd.wait()


def _strip_for_voice(text: str) -> str:
    """Quick clean for a single sentence before TTS."""
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`[^`]+`", "", text)
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-•→]\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"(?:/[\w.-]+){2,}", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class VoicePipeline:
    """Manages the full voice loop in a background thread."""

    def __init__(self, friday, main_loop: asyncio.AbstractEventLoop):
        self.friday = friday
        self.main_loop = main_loop
        self._thread = None
        self._running = False

        self._wake: WakeWordDetector | None = None
        self._vad: VoiceActivityDetector | None = None
        self._stt: Transcriber | None = None
        self._tts: Speaker | None = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="friday-voice")
        self._thread.start()

    def stop(self):
        self._running = False
        if self._tts:
            self._tts.stop()

    def _init_components(self):
        console.print("  [dim green]:: Loading voice models...[/dim green]")

        self._wake = WakeWordDetector()
        console.print("  [dim green]   ✓ Wake word ready[/dim green]")

        self._vad = VoiceActivityDetector()
        console.print("  [dim green]   ✓ VAD ready[/dim green]")

        self._stt = Transcriber()
        self._stt.warmup()
        console.print("  [dim green]   ✓ STT ready[/dim green]")

        self._tts = Speaker()
        console.print("  [dim green]   ✓ TTS ready[/dim green]")

        from friday.voice.config import WAKE_WORD_DISPLAY
        console.print(f"  [bold green]:: Voice pipeline ACTIVE — say '{WAKE_WORD_DISPLAY}'[/bold green]")
        console.print()

    def _run(self):
        try:
            self._init_components()
        except Exception as e:
            console.print(f"  [red]✗ Voice init failed: {e}[/red]")
            self._running = False
            return

        while self._running:
            try:
                self._listen_loop()
            except Exception as e:
                if self._running:
                    console.print(f"  [red]✗ Voice error: {e}[/red]")
                    time.sleep(1)

    def _listen_loop(self):
        """Listen for wake word, record speech, process with streaming TTS."""
        # Phase 1: Listen for wake word
        with sd.InputStream(
            samplerate=SAMPLE_RATE, channels=CHANNELS,
            dtype="int16", blocksize=FRAME_SIZE,
        ) as stream:
            while self._running:
                chunk, _ = stream.read(FRAME_SIZE)
                audio = chunk[:, 0] if chunk.ndim > 1 else chunk
                if self._wake.detect(audio):
                    break
            else:
                return

        # Phase 2: Activation chime
        _play_chime()

        # Phase 3: Record speech until silence
        self._vad.reset()
        audio_buffer = []

        with sd.InputStream(
            samplerate=SAMPLE_RATE, channels=CHANNELS,
            dtype="int16", blocksize=FRAME_SIZE,
        ) as stream:
            while self._running:
                chunk, _ = stream.read(FRAME_SIZE)
                audio = chunk[:, 0] if chunk.ndim > 1 else chunk
                audio_buffer.append(audio.copy())
                if self._vad.feed(audio) == "end":
                    break

        if not audio_buffer:
            return

        # Phase 4: Transcribe
        full_audio = np.concatenate(audio_buffer)
        text = self._stt.transcribe(full_audio)

        if not text or len(text.strip()) < 2:
            return

        console.print(f"\n  [bold cyan]🎤 Travis:[/bold cyan] [cyan]{text}[/cyan]")

        # Phase 5+6: Fast path or streamed response → TTS
        self._wake.disable()
        try:
            # Try fast path first (TV commands, etc.) — zero LLM, sub-second
            fast_result = asyncio.run_coroutine_threadsafe(
                self.friday.fast_path(text), self.main_loop
            ).result(timeout=15)

            if fast_result is not None:
                console.print(f"  [bold green]FRIDAY[/bold green] [green]{fast_result}[/green]")
                console.print()
                self._tts.speak(fast_result)
            else:
                self._process_and_speak(text)
        finally:
            self._wake.enable()

    # ── Streaming TTS: speak sentence-by-sentence as LLM generates ──

    def _process_and_speak(self, text: str):
        """All queries go through dispatch_background for consistent routing.

        Chunks flow through a thread-safe queue to the voice thread
        which speaks them sentence-by-sentence.
        """
        chunk_queue: queue.Queue = queue.Queue()

        def _on_update(msg: str):
            if msg.startswith("ACK:"):
                console.print(f"  [dim green]◈ working on it...[/dim green]")
            elif msg.startswith("STATUS:"):
                status_text = msg[7:]
                console.print(f"  [dim green]  ◈ {status_text}[/dim green]")
            elif msg.startswith("CHUNK:"):
                chunk_queue.put(msg[6:])
            elif msg.startswith("DONE:"):
                chunk_queue.put(_DONE)
            elif msg.startswith("ERROR:"):
                chunk_queue.put(Exception(msg[6:]))
                chunk_queue.put(_DONE)

        self.friday.dispatch_background(text, on_update=_on_update)

        # Consumer: voice thread pulls chunks, buffers sentences, speaks
        sentence_buffer = ""
        sentences_spoken = 0
        full_chunks: list[str] = []
        header_printed = False

        while True:
            try:
                item = chunk_queue.get(timeout=120)
            except queue.Empty:
                console.print("  [red]✗ Voice timeout — no response[/red]")
                break

            if item is _DONE:
                break
            if isinstance(item, Exception):
                console.print(f"  [red]✗ Error: {item}[/red]")
                break

            full_chunks.append(item)
            sentence_buffer += item

            # Check for sentence boundaries
            while SENTENCE_END_RE.search(sentence_buffer):
                match = SENTENCE_END_RE.search(sentence_buffer)
                sentence = sentence_buffer[:match.end()].strip()
                sentence_buffer = sentence_buffer[match.end():]

                if sentences_spoken >= MAX_VOICE_SENTENCES:
                    continue

                clean = _strip_for_voice(sentence)
                if not clean or len(clean) < 3:
                    continue

                if sentence.strip().startswith("```"):
                    continue

                if not header_printed:
                    console.print(f"  [bold green]FRIDAY[/bold green] ", end="")
                    header_printed = True

                # Speak this sentence immediately
                self._tts.speak(clean)
                sentences_spoken += 1

                if self._tts._interrupted:
                    # Drain remaining
                    self._drain_queue(chunk_queue, full_chunks)
                    break

            if self._tts._interrupted:
                break

        # Speak any remaining buffered text
        if (sentence_buffer.strip()
            and sentences_spoken < MAX_VOICE_SENTENCES
            and not self._tts._interrupted):
            clean = _strip_for_voice(sentence_buffer)
            if clean and len(clean) >= 3 and not sentence_buffer.strip().startswith("```"):
                if not header_printed:
                    console.print(f"  [bold green]FRIDAY[/bold green] ", end="")
                    header_printed = True
                self._tts.speak(clean)

        # Display full response on screen
        full_text = "".join(full_chunks)
        if full_text:
            if not header_printed:
                console.print(f"  [bold green]FRIDAY[/bold green] ", end="")
            console.print(f"[green]{full_text}[/green]")
            console.print()

    @staticmethod
    def _drain_queue(q: queue.Queue, collect: list[str]):
        """Drain remaining items from queue without speaking."""
        while True:
            try:
                item = q.get(timeout=30)
                if item is _DONE or isinstance(item, Exception):
                    break
                if isinstance(item, str):
                    collect.append(item)
            except queue.Empty:
                break
