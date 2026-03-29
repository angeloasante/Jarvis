"""FRIDAY Voice Pipeline — always-on ambient listening.

Mic is always open. Every speech segment gets transcribed and added to a
rolling context buffer. When "Friday" is detected in the transcript, FRIDAY
activates with full conversation context — you can be mid-conversation with
a friend and just say "Friday, what do you think?" and it has the full context.

Two modes (auto-selected):
  Cloud:  Mic → ElevenLabs WebSocket (Scribe Realtime, ~150ms) → transcripts
  Local:  Mic → Silero VAD → MLX Whisper → transcripts

Toggle: /listening-off to pause, /listening-on to resume.
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
    TRANSCRIPT_BUFFER_SECONDS,
    TRIGGER_WORDS,
    FOLLOWUP_WINDOW_S,
)
from friday.voice.tts import Speaker

console = Console()

_DONE = object()
SENTENCE_END_RE = re.compile(r"[.!?]\s")

# Build trigger regex — matches "friday" (or custom words) at word boundary
_TRIGGER_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in TRIGGER_WORDS) + r")\b",
    re.IGNORECASE,
)


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


# ── Transcript entry ─────────────────────────────────────────────────────────

class _Segment:
    __slots__ = ("text", "timestamp")

    def __init__(self, text: str, timestamp: float):
        self.text = text
        self.timestamp = timestamp


# ── Noise / hallucination filter ──────────────────────────────────────────────

_HALLUCINATIONS = {
    "thank you", "thanks for watching", "thank you for watching",
    "subscribe", "like and subscribe", "you", "bye",
    "the end", "thanks", "thank you very much",
    "", "...", "hmm", "um", "uh",
}

# Noise description words ElevenLabs Scribe produces for non-speech audio
_NOISE_WORDS = {
    "music", "applause", "laughter", "silence", "inaudible",
    "noise", "static", "beep", "ring", "buzz", "clicking",
    "crowd", "cheering", "screaming", "sighing", "coughing",
    "engine", "typing", "breathing", "whistling",
}


def _is_noise_or_hallucination(text: str) -> bool:
    """Filter out non-speech transcripts: hallucinations, sound descriptions, noise."""
    t = text.strip()
    tl = t.lower().rstrip(".")

    # Too short to be real speech
    if len(tl) < 4:
        return True

    # Exact hallucination match
    if tl in _HALLUCINATIONS:
        return True

    # Parenthetical sound descriptions: (engine revving), (screaming), (dramatic music)
    if re.match(r"^\(.*\)$", t):
        return True

    # Broken parentheticals: "Music)", "(crowd", "screaming)"
    if (t.endswith(")") and "(" not in t) or (t.startswith("(") and ")" not in t):
        return True

    # Single noise word with optional parens: "Music", "(applause)"
    cleaned = tl.strip("(). ")
    if cleaned in _NOISE_WORDS:
        return True

    # Two-word noise descriptions: "engine revving", "crowd cheering"
    words = cleaned.split()
    if len(words) == 2 and words[0] in _NOISE_WORDS:
        return True
    if len(words) == 2 and words[1] in _NOISE_WORDS:
        return True

    # Repetitive word pattern: "audio audio audio", "hello hello hello"
    if len(words) >= 3 and len(set(words)) == 1:
        return True

    # Mostly same word repeated: "Hello? F audio audio audio audio"
    if len(words) >= 4:
        from collections import Counter
        most_common_count = Counter(words).most_common(1)[0][1]
        if most_common_count >= len(words) * 0.6:
            return True

    return False


# ── Pipeline ─────────────────────────────────────────────────────────────────

class VoicePipeline:
    """Always-on ambient listener with trigger-word activation.

    The mic stays open. Speech segments are transcribed continuously.
    When "Friday" is detected, FRIDAY responds with full awareness
    of the ambient conversation.
    """

    def __init__(self, friday, main_loop: asyncio.AbstractEventLoop):
        self.friday = friday
        self.main_loop = main_loop
        self._thread = None
        self._running = False
        self._listening = True  # /listening-off toggles this

        self._tts: Speaker | None = None
        self._vad = None
        self._stt = None

        # Rolling transcript — pruned to last N seconds
        self._transcript: list[_Segment] = []
        self._transcript_lock = threading.Lock()

        # Pause transcription during TTS to prevent feedback
        self._muted = False

        # Follow-up window — after FRIDAY responds, treat next speech as directed
        # at FRIDAY for N seconds without needing trigger word again
        self._last_response_time: float = 0.0
        self._followup_window_s: float = FOLLOWUP_WINDOW_S

    # ── Public controls ──────────────────────────────────────────────────

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

    def set_listening(self, on: bool):
        """Toggle ambient listening on/off."""
        self._listening = on

    def get_transcript(self, last_seconds: float | None = None) -> str:
        """Get the rolling transcript as a single string."""
        with self._transcript_lock:
            if last_seconds is None:
                segments = list(self._transcript)
            else:
                cutoff = time.time() - last_seconds
                segments = [s for s in self._transcript if s.timestamp >= cutoff]
        return "\n".join(s.text for s in segments)

    # ── Init ─────────────────────────────────────────────────────────────

    def _init_components(self):
        console.print("  [dim green]:: Loading voice models...[/dim green]")

        self._tts = Speaker()
        from friday.core.config import USE_CLOUD_TTS
        tts_label = "ElevenLabs" if USE_CLOUD_TTS else "Kokoro (local)"
        console.print(f"  [dim green]   ✓ TTS: {tts_label}[/dim green]")

        # Always use local STT — fast, reliable, no cloud dependency
        from friday.voice.vad import VoiceActivityDetector
        from friday.voice.stt import Transcriber
        self._vad = VoiceActivityDetector()
        console.print("  [dim green]   ✓ VAD ready (Silero)[/dim green]")
        self._stt = Transcriber()
        self._stt.warmup()
        console.print("  [dim green]   ✓ STT ready (MLX Whisper)[/dim green]")

        console.print(f"  [bold green]:: Voice pipeline ACTIVE — always listening[/bold green]")
        console.print(f"  [dim]   Say \"Friday\" at any time to activate[/dim]")
        console.print()

    # ── Main loop ────────────────────────────────────────────────────────

    def _run(self):
        try:
            self._init_components()
        except Exception as e:
            console.print(f"  [red]✗ Voice init failed: {e}[/red]")
            self._running = False
            return

        while self._running:
            try:
                self._ambient_loop_local()
            except Exception as e:
                if self._running:
                    console.print(f"  [red]✗ Voice error: {e}[/red]")
                    time.sleep(1)

    def _handle_committed_text(self, text: str):
        """Process a finalized transcript (from cloud or local)."""
        if not text or len(text.strip()) < 2:
            return

        text = text.strip()
        if _is_noise_or_hallucination(text):
            return

        now = time.time()

        # Add to rolling transcript
        with self._transcript_lock:
            self._transcript.append(_Segment(text=text, timestamp=now))
            cutoff = now - TRANSCRIPT_BUFFER_SECONDS
            self._transcript = [s for s in self._transcript if s.timestamp >= cutoff]

        # Show committed transcript
        console.print(f"\r  [dim]  ◦ {text}[/dim]    ")

        # Check for trigger word OR follow-up window
        trigger_match = _TRIGGER_RE.search(text)
        if trigger_match:
            self._on_triggered(text, trigger_match)
        elif (self._last_response_time
              and (now - self._last_response_time) < self._followup_window_s):
            # Within follow-up window — treat as directed at FRIDAY
            self._on_followup(text)

    # ══════════════════════════════════════════════════════════════════════
    #  LOCAL MODE — Silero VAD + MLX Whisper (fallback)
    # ══════════════════════════════════════════════════════════════════════

    def _ambient_loop_local(self):
        """Local mode: VAD detects speech, Whisper transcribes."""
        self._vad.reset()
        audio_buffer = []
        has_speech = False

        with sd.InputStream(
            samplerate=SAMPLE_RATE, channels=CHANNELS,
            dtype="int16", blocksize=FRAME_SIZE,
        ) as stream:
            while self._running:
                if not self._listening or self._muted:
                    time.sleep(0.1)
                    continue

                chunk, _ = stream.read(FRAME_SIZE)
                audio = chunk[:, 0] if chunk.ndim > 1 else chunk

                state = self._vad.feed(audio)

                if state == "speech":
                    audio_buffer.append(audio.copy())
                    has_speech = True
                elif state == "silence" and has_speech:
                    audio_buffer.append(audio.copy())
                elif state == "end" and has_speech:
                    self._transcribe_local_segment(audio_buffer)
                    audio_buffer = []
                    has_speech = False
                    self._vad.reset()

    def _transcribe_local_segment(self, audio_buffer: list[np.ndarray]):
        """Transcribe a local audio segment with MLX Whisper."""
        if not audio_buffer:
            return

        full_audio = np.concatenate(audio_buffer)
        duration_s = len(full_audio) / SAMPLE_RATE
        if duration_s < 0.5:
            return

        t0 = time.time()
        text = self._stt.transcribe(full_audio)
        stt_ms = (time.time() - t0) * 1000
        console.print(f"  [dim]  ⏱ STT: {stt_ms:.0f}ms ({duration_s:.1f}s audio)[/dim]")
        self._handle_committed_text(text)

    # ══════════════════════════════════════════════════════════════════════
    #  TRIGGER — "Friday" detected in transcript
    # ══════════════════════════════════════════════════════════════════════

    def _on_triggered(self, trigger_text: str, match: re.Match):
        """FRIDAY was addressed — extract query, build context, respond."""
        after_trigger = trigger_text[match.end():].strip()
        before_trigger = trigger_text[:match.start()].strip()

        # Strip trailing filler: "friday, you dig?" → "you dig?"
        query = after_trigger if after_trigger else before_trigger

        if not query or len(query) < 2:
            _play_chime()
            console.print(f"\n  [bold cyan]🎤 Travis:[/bold cyan] [cyan]{trigger_text}[/cyan]")
            self._tts.speak("Yeah?")
            self._last_response_time = time.time()
            return

        # Build ambient context from rolling transcript
        ambient_context = self._build_ambient_context()

        console.print(f"\n  [bold cyan]🎤 Travis:[/bold cyan] [cyan]{trigger_text}[/cyan]")
        _play_chime()

        self._respond(query, ambient_context)

    def _on_followup(self, text: str):
        """Speech within follow-up window — treat as directed at FRIDAY."""
        ambient_context = self._build_ambient_context()
        console.print(f"\n  [bold cyan]🎤 Travis:[/bold cyan] [cyan]{text}[/cyan]")
        _play_chime()
        self._respond(text, ambient_context)

    def _respond(self, query: str, ambient_context: str = ""):
        """Send query to FRIDAY and speak the response."""
        t_start = time.time()
        # Mute mic during response
        self._muted = True
        try:
            contextualized_query = query
            if ambient_context:
                contextualized_query = (
                    f"[Ambient conversation context — Travis was talking and then addressed you:\n"
                    f"{ambient_context}\n"
                    f"---\n"
                    f"Travis said to you: {query}]"
                )

            # Try fast path first
            try:
                fast_result = asyncio.run_coroutine_threadsafe(
                    self.friday.fast_path(query), self.main_loop
                ).result(timeout=15)
            except Exception as e:
                console.print(f"  [dim red]  ⏱ Fast path error: {e}[/dim red]")
                fast_result = None

            if fast_result is not None:
                fast_ms = (time.time() - t_start) * 1000
                console.print(f"  [dim]  ⏱ Fast path: {fast_ms:.0f}ms[/dim]")
                console.print(f"  [bold green]FRIDAY[/bold green] [green]{fast_result}[/green]")
                console.print()
                t_tts = time.time()
                self._tts.speak(fast_result)
                tts_ms = (time.time() - t_tts) * 1000
                console.print(f"  [dim]  ⏱ TTS: {tts_ms:.0f}ms[/dim]")
            else:
                self._process_and_speak(contextualized_query, t_start)
        except Exception as e:
            console.print(f"  [red]✗ Voice response error: {e}[/red]")
        finally:
            total_ms = (time.time() - t_start) * 1000
            console.print(f"  [dim]  ⏱ Total: {total_ms:.0f}ms[/dim]")
            self._muted = False
            self._last_response_time = time.time()

    def _build_ambient_context(self) -> str:
        """Build recent conversation context (last 2 min, max 10 segments)."""
        with self._transcript_lock:
            cutoff = time.time() - 120
            recent = [s for s in self._transcript if s.timestamp >= cutoff]

        if not recent or len(recent) <= 1:
            return ""

        # Exclude the triggering segment (last one)
        context_segments = recent[:-1]
        if not context_segments:
            return ""

        return "\n".join(s.text for s in context_segments[-10:])

    # ══════════════════════════════════════════════════════════════════════
    #  STREAMING TTS RESPONSE
    # ══════════════════════════════════════════════════════════════════════

    def _process_and_speak(self, text: str, t_start: float = None):
        """Stream LLM → TTS with minimal gaps.

        Speaks each sentence as soon as it completes from the LLM stream.
        While TTS plays a sentence, LLM chunks keep accumulating. When TTS
        finishes, all accumulated complete sentences are batched into the
        next TTS call. No dead air between sentences.
        """
        if t_start is None:
            t_start = time.time()

        chunk_queue: queue.Queue = queue.Queue()
        t_first_chunk = [None]

        def _on_update(msg: str):
            if msg.startswith("ACK:"):
                console.print(f"  [dim green]◈ thinking...[/dim green]")
            elif msg.startswith("STATUS:"):
                console.print(f"  [dim green]  ◈ {msg[7:]}[/dim green]")
            elif msg.startswith("CHUNK:"):
                if t_first_chunk[0] is None:
                    t_first_chunk[0] = time.time()
                    llm_ms = (t_first_chunk[0] - t_start) * 1000
                    console.print(f"  [dim]  ⏱ LLM first chunk: {llm_ms:.0f}ms[/dim]")
                chunk_queue.put(msg[6:])
            elif msg.startswith("DONE:"):
                chunk_queue.put(_DONE)
            elif msg.startswith("ERROR:"):
                chunk_queue.put(Exception(msg[6:]))
                chunk_queue.put(_DONE)

        self.friday.dispatch_background(text, on_update=_on_update)

        sentence_buffer = ""
        full_chunks: list[str] = []
        header_printed = False
        llm_done = False
        tts_count = 0

        def _drain_available():
            """Read all immediately available chunks from queue (non-blocking)."""
            nonlocal sentence_buffer, llm_done
            while True:
                try:
                    item = chunk_queue.get_nowait()
                    if item is _DONE:
                        llm_done = True
                        return
                    if isinstance(item, Exception):
                        console.print(f"  [red]✗ LLM error: {item}[/red]")
                        llm_done = True
                        return
                    full_chunks.append(item)
                    sentence_buffer += item
                except queue.Empty:
                    return

        def _extract_sentences() -> list[str]:
            """Pull all complete sentences from buffer."""
            nonlocal sentence_buffer
            sentences = []
            while SENTENCE_END_RE.search(sentence_buffer):
                m = SENTENCE_END_RE.search(sentence_buffer)
                raw = sentence_buffer[:m.end()].strip()
                sentence_buffer = sentence_buffer[m.end():]
                clean = _strip_for_voice(raw)
                if clean and len(clean) >= 3 and not raw.strip().startswith("```"):
                    sentences.append(clean)
            return sentences

        def _speak_batch(sentences: list[str]):
            """Speak a batch of sentences as one TTS call."""
            nonlocal header_printed, tts_count
            if not sentences or self._tts._interrupted:
                return
            batch = " ".join(sentences)
            if not batch.strip():
                return
            if not header_printed:
                console.print(f"  [bold green]FRIDAY[/bold green] ", end="")
                header_printed = True

            t_tts = time.time()
            if tts_count == 0:
                voice_delay_ms = (t_tts - t_start) * 1000
                console.print(f"  [dim]  ⏱ Voice delay: {voice_delay_ms:.0f}ms[/dim]")

            self._tts.speak(batch)
            tts_ms = (time.time() - t_tts) * 1000
            tts_count += 1
            console.print(f"  [dim]  ⏱ TTS #{tts_count} ({len(batch)} chars): {tts_ms:.0f}ms[/dim]")

        # ── Main loop: read chunks → extract sentences → speak → repeat ──
        while not llm_done:
            # Check if buffer already has complete sentences (from previous drain)
            sentences = _extract_sentences()
            if sentences:
                _speak_batch(sentences)
                if self._tts._interrupted:
                    self._drain_queue(chunk_queue, full_chunks)
                    break
                # While TTS was playing, more chunks arrived — drain them
                _drain_available()
                continue

            # No sentences ready — wait for next chunk (blocking)
            try:
                item = chunk_queue.get(timeout=120)
            except queue.Empty:
                console.print("  [red]✗ Voice timeout — no response[/red]")
                break
            if item is _DONE:
                llm_done = True
                break
            if isinstance(item, Exception):
                console.print(f"  [red]✗ Error: {item}[/red]")
                break
            full_chunks.append(item)
            sentence_buffer += item

        # ── Final: speak any leftover text ──
        full_text = "".join(full_chunks)
        llm_ms = (time.time() - t_start) * 1000
        console.print(f"  [dim]  ⏱ LLM done: {llm_ms:.0f}ms | {len(full_text)} chars[/dim]")

        remaining = _strip_for_voice(sentence_buffer)
        if remaining and len(remaining) >= 3 and not self._tts._interrupted:
            _speak_batch([remaining])

        # If nothing was spoken at all (no sentence boundaries found)
        if tts_count == 0 and not self._tts._interrupted:
            clean = _strip_for_voice(full_text)
            if clean and len(clean) >= 3:
                _speak_batch([clean])

        # Print full text to CLI
        if full_text.strip():
            if not header_printed:
                console.print(f"  [bold green]FRIDAY[/bold green] ", end="")
            console.print(f"[green]{full_text}[/green]")
            console.print()
        elif not full_text.strip():
            console.print(f"  [red]✗ LLM returned empty response[/red]")

    @staticmethod
    def _drain_queue(q: queue.Queue, collect: list[str]):
        while True:
            try:
                item = q.get(timeout=30)
                if item is _DONE or isinstance(item, Exception):
                    break
                if isinstance(item, str):
                    collect.append(item)
            except queue.Empty:
                break
