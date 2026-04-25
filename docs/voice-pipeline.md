# FRIDAY Voice Pipeline

How always-on voice input becomes an LLM action and an audible reply, with full file references and the small decisions that actually matter.

For the *user-facing* setup (microphone permissions, wake word, picking ElevenLabs vs Kokoro), see [setup-voice.md](setup-voice.md). This doc is the **engineering view** — what each module does, how they connect, where the latency goes.

---

## 1. The 30-second mental model

```
                    ┌─────────────────────────────────────────────┐
                    │  daemon thread "friday-voice" — pipeline.py │
                    └─────────────────────────────────────────────┘
                                          │
   mic ──► sounddevice InputStream (16 kHz, mono, int16, 32 ms blocks)
                                          │
                                          ▼
   ┌──────────┐    32 ms frame      ┌──────────┐
   │ Silero   │  ────────────────►  │ rolling  │  ── on "end" ──►  Whisper transcribe
   │  VAD     │   speech / silence  │ buffer   │                    (mlx-whisper)
   └──────────┘                     └──────────┘                            │
                                                                            ▼
                                          ┌──────────────────────────────────┐
                                          │  rolling transcript (5 min)      │
                                          │  + check for trigger word        │
                                          │     "friday"                     │
                                          └──────────────────────────────────┘
                                                            │
                                              ┌─────────────┴─────────────┐
                                              ▼                           ▼
                                       no trigger                trigger / follow-up
                                       discard query             build ambient context
                                                                             │
                                                                             ▼
                                                  friday.fast_path(query) ── hit  ──► speak
                                                                  │
                                                                  miss
                                                                  ▼
                                                  friday.dispatch_background(query)
                                                          │ (chunks)
                                                          ▼
                                                  Speaker.speak per sentence
                                                  (ElevenLabs streaming PCM
                                                   OR Kokoro local fallback)
```

Always-on means **the mic stays open the whole session**. Every utterance is transcribed even when FRIDAY isn't being addressed — those go into a 5-minute rolling buffer. When the trigger word fires, that buffer becomes the **ambient context** so FRIDAY knows what you were just talking about.

---

## 2. The five layers

| Layer | File | Role |
|---|---|---|
| **Audio capture** | [`friday/voice/pipeline.py:296-325`](../friday/voice/pipeline.py#L296-L325) | `sounddevice.InputStream` — 16 kHz, mono, 32 ms / 512-sample frames (Silero requirement) |
| **VAD** | [`friday/voice/vad.py`](../friday/voice/vad.py) | Silero VAD — per-frame speech probability; emits `speech` / `silence` / `end` |
| **STT** | [`friday/voice/stt.py`](../friday/voice/stt.py) | MLX Whisper (Apple-Silicon optimised, `whisper-small-mlx` by default) |
| **Trigger + dispatch** | [`friday/voice/pipeline.py:263-377`](../friday/voice/pipeline.py#L263-L377) | Trigger-word regex, follow-up window, ambient-context builder, fast_path/dispatch routing |
| **TTS** | [`friday/voice/tts.py`](../friday/voice/tts.py) | ElevenLabs Flash v2.5 (cloud, streaming PCM) primary; Kokoro-82M ONNX fallback |

All five live under `friday/voice/`. The pipeline thread calls them in order; nothing else in FRIDAY needs to know the audio path exists.

### Audio capture

Silero v5 needs **exactly 512 samples at 16 kHz** per call (32 ms). That's the source of every other constant in [`friday/voice/config.py`](../friday/voice/config.py):

```python
SAMPLE_RATE = 16000
FRAME_SIZE_MS = 32                  # 32 ms chunks
FRAME_SIZE = 512                    # Silero requires exactly 512 @ 16 kHz
VAD_SILENCE_MS = 800                # silence to trigger end-of-speech
VAD_SILENCE_FRAMES = 25             # 800 / 32
VAD_MIN_SPEECH_MS = 400             # rejects music/TV bursts
VAD_MIN_SPEECH_FRAMES = 12          # 400 / 32
VAD_THRESHOLD = 0.7                 # Silero confidence; higher = stricter
```

The audio buffer is `int16` because Silero's PyTorch model expects it; STT converts to float32 itself. We never resample — everything in the pipeline is fixed at 16 kHz.

### VAD — Silero v5

[`friday/voice/vad.py`](../friday/voice/vad.py) is ~60 lines. Three states are emitted:

- `speech` — current frame is speech AND we've seen ≥ 12 consecutive speech frames (latched into `_is_speaking`)
- `silence` — silence frame, but we haven't yet hit the silence-frame threshold
- `end` — we'd been speaking, and silence has now lasted ≥ 25 frames (~800 ms). The pipeline takes this as "user finished a thought", flushes the audio buffer to STT, and resets.

Why latched min-speech: filters out short bursts from background music or TV chatter that briefly trip a single frame above 0.7 confidence.

### STT — MLX Whisper

`mlx-whisper` is Whisper running on Apple's MLX framework — same model weights as openai-whisper but Apple-Silicon GPU-accelerated. On an M-series Mac, `whisper-small-mlx` runs ~3× real-time, which means a 5-second utterance transcribes in about 1.5 s.

Warmup is important: the first call downloads the model and JITs the kernels (~5 s). [`Transcriber.warmup()`](../friday/voice/stt.py) is called during `_init_components` so the user never sees that latency on their first real utterance.

### Trigger + ambient context

[`friday/voice/pipeline.py:284-291`](../friday/voice/pipeline.py#L284-L291) — every committed transcript runs through a regex:

```python
_TRIGGER_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in TRIGGER_WORDS) + r")\b",
    re.IGNORECASE,
)
```

`TRIGGER_WORDS = ["friday"]` by default. When the regex matches, three things happen:

1. **Query extraction** — text after the trigger is the query; if nothing follows, FRIDAY plays a chime and says `"Yeah?"`.
2. **Ambient context** — the last 10 segments from the past 2 minutes (excluding the triggering segment itself) are concatenated as context. So "Friday, what do you think?" gets sent with everything you and the other person were discussing.
3. **Follow-up window** — after FRIDAY finishes responding, a `FOLLOWUP_WINDOW_S = 8` window opens. Within that window, the **next** committed transcript is treated as directed at FRIDAY *without* needing the trigger word again. Resets every response.

Hallucination filter at [`friday/voice/pipeline.py:114-160`](../friday/voice/pipeline.py#L114-L160) drops common Whisper noise outputs (`"thanks for watching"`, lone punctuation, etc.) before they reach the trigger check.

### TTS — dual-model

| Path | Model | Why | Where |
|---|---|---|---|
| **Live speaker playback** | `eleven_flash_v2_5` | ~75 ms time-to-first-byte, streaming PCM straight to `sounddevice.OutputStream`. Latency-critical. | [`friday/voice/tts.py`](../friday/voice/tts.py) |
| **Voice notes rendered to file** | `eleven_v3` | Supports inline audio tags `[laughs] [whispers] [excited] [sighs]`. Slower but offline. | [`friday/tools/voice_tools.py`](../friday/tools/voice_tools.py) |

If `ELEVENLABS_API_KEY` is unset, both paths fall back to local **Kokoro-82M ONNX** ([`friday/voice/tts.py:34-65`](../friday/voice/tts.py#L34-L65)). Kokoro is ~500 ms TTFB, ships as ONNX weights via Hugging Face, runs purely on CPU. Voice quality is good but not expressive.

The cloud path uses a **persistent `httpx` client** so TCP+TLS handshake cost is paid once and reused across every sentence in a session. PCM chunks (`pcm_24000` = 24 kHz signed 16-bit LE mono) stream directly into `sounddevice` — audio starts playing before synthesis finishes.

---

## 3. The streaming response loop — minimising dead air

This is the most performance-sensitive part of the pipeline. The naive flow is:

```
user speaks → STT → LLM (full reply) → TTS (full audio) → playback
```

The total latency there is `STT + LLM_full + TTS_full + playback_first_byte` — easily 4–6 s before audio starts.

The real flow at [`friday/voice/pipeline.py:443-575`](../friday/voice/pipeline.py#L443-L575) is sentence-batched and overlapped:

```python
def _process_and_speak(text, t_start):
    # while LLM streams chunks, accumulate into a sentence buffer
    # the moment we've got a complete sentence, fire it through TTS
    # while TTS plays sentence N, LLM keeps streaming chunks for N+1, N+2…
    # when TTS returns, drain everything that arrived during playback
    # send that batch through TTS as one call (saves handshake)
```

Effect: time-to-first-audio drops to roughly `STT + LLM_first_sentence + TTS_TTFB` — about **1.5 s** in practice on a Mac with a warmed STT model. Subsequent sentences play with no perceptible gap because TTS for sentence N+1 is queued before sentence N's audio finishes.

`_strip_for_voice` at [`friday/voice/pipeline.py:72-83`](../friday/voice/pipeline.py#L72-L83) cleans each sentence before TTS — removes code blocks, URLs, file paths, markdown — so the spoken version doesn't include unspeakable garbage.

### 3.1 Even tighter — input-streaming over WebSocket (opt-in)

The HTTP `/stream` endpoint described above is one-shot in the **input** direction: we POST a complete sentence, then receive PCM bytes back. So even with sentence-batching, every reply pays one **"wait for the LLM to finish a sentence"** cost before TTS can fire.

ElevenLabs has a separate WebSocket endpoint that lifts that constraint:

```
wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input
```

We push text fragments **as the LLM emits them**. ElevenLabs synthesises continuously and audio frames flow back without waiting for sentence boundaries.

**Wired but gated** — see [`friday/voice/tts.py`'s `Speaker.speak_streaming()`](../friday/voice/tts.py) and [`friday/voice/pipeline.py`'s `_process_and_speak_streaming()`](../friday/voice/pipeline.py).

```bash
# Enable
export FRIDAY_TTS_INPUT_STREAMING=true
# In ~/Friday/.env:
FRIDAY_TTS_INPUT_STREAMING=true
```

Architecture:

```python
# pipeline.py — token bridge from the orchestrator's CHUNK callback
chunk_queue = queue.Queue()

def _on_update(msg):
    if msg.startswith("CHUNK:"):
        chunk_queue.put(_strip_for_voice(msg[6:]) + " ")
    elif msg.startswith("DONE:"):
        chunk_queue.put(None)

# tts.py — Speaker.speak_streaming runs two concurrent asyncio tasks:
#   _send_loop:  pulls chunks from the queue → ws.send({"text": chunk})
#   _recv_loop:  reads {"audio": base64-pcm} frames → OutputStream.write
```

When it pays off:

| Configuration | First-audio latency |
|---|---|
| HTTP path, slow LLM (full sentence ~800 ms) | LLM_full_sentence + 75 ms = **~875 ms** |
| WebSocket path, slow LLM (first word ~300 ms) | LLM_first_word + ~150 ms = **~450 ms** |
| HTTP path, fast LLM (Groq Qwen3, full sentence ~250 ms) | 250 + 75 = **~325 ms** |
| WebSocket path, fast LLM (first word ~80 ms) | 80 + ~150 = **~230 ms** |

The WebSocket path **adds ~75 ms of TTFB cost** vs the HTTP path's ~75 ms, because connection setup + initial config message + chunk-length-schedule make the first audio frame arrive a bit later. So it only wins when LLM-to-first-word is *much* faster than LLM-to-full-sentence — i.e. with a fast LLM and longer outputs.

When it loses:

- **Slow LLM** (rate-limited primary cascading to fallback): you wait for the slow LLM regardless. The WebSocket can't synthesise faster than text arrives.
- **Short replies** ("OK", "Done"): full sentence arrives so fast that the WebSocket's setup overhead dominates. The HTTP path wins by ~75 ms here.

If `FRIDAY_TTS_INPUT_STREAMING=true` is set and the WebSocket fails to connect, the pipeline falls back to the HTTP path automatically — you'll see `⏱ WS streaming failed — falling back to HTTP` in the log. Local Kokoro stays as the offline fallback under both paths.

**Generation tuning lives at [`friday/voice/tts.py`](../friday/voice/tts.py) in the `_runner` config message:**

```python
"generation_config": {
    # When ElevenLabs decides it has enough text to start synthesising.
    # Lower = more aggressive partial generation, lower TTFB.
    # Higher = smoother prosody between fragments.
    # [50, 90, 160, 210] is fairly snappy; bump if speech sounds chopped.
    "chunk_length_schedule": [50, 90, 160, 210],
}
```

---

## 4. Anti-feedback: muting during TTS

If FRIDAY's own voice goes through your microphone, it'll get transcribed and the trigger word "friday" inside its own response could activate it again. Two safeguards:

1. `_muted = True` set in [`pipeline.py:383`](../friday/voice/pipeline.py#L383) before TTS; the audio capture loop at [`pipeline.py:307-309`](../friday/voice/pipeline.py#L307-L309) skips frames while `_muted` is True. Reset to False in `finally`.
2. The hallucination filter ignores transcripts ≤ 2 chars and well-known Whisper noise outputs.

This is sufficient for typical laptop-speaker volumes. It's not bulletproof — if you push speakers loud enough to bleed during the gap between sentences, you can still echo. Use headphones for high-volume scenarios.

---

## 5. Integration with the rest of FRIDAY

The pipeline only knows two things about FRIDAY's brain:

```python
self.friday.fast_path(query)               # sub-second deterministic path
self.friday.dispatch_background(query, on_update=...)  # full agent pipeline
```

Both are public methods on `FridayCore` ([`friday/core/orchestrator.py`](../friday/core/orchestrator.py)). Voice is bolted on, not woven in — you could replace `pipeline.py` with anything that calls those two methods and the rest of FRIDAY wouldn't notice.

```python
# friday/voice/pipeline.py:395-414
fast_result = asyncio.run_coroutine_threadsafe(
    self.friday.fast_path(query), self.main_loop
).result(timeout=15)
if fast_result is not None:
    self._tts.speak(fast_result)         # quick win — TV controls, greetings
else:
    self._process_and_speak(query, t0)    # full pipeline with streaming TTS
```

`run_coroutine_threadsafe` is required because the voice thread is **not** the asyncio event loop — `FridayCore` lives on the main loop, voice lives on `friday-voice` daemon thread.

### Started where

```python
# friday/cli.py:145-153
if "--voice" in sys.argv:
    from friday.voice.pipeline import VoicePipeline
    loop = asyncio.get_event_loop()
    voice_pipeline = VoicePipeline(friday, loop)
    voice_pipeline.start()
```

`/voice` toggles it at runtime; `/listening-off` and `/listening-on` flip `set_listening(bool)` without tearing down the audio device. `/quit` calls `voice_pipeline.stop()` which sets `_running = False` and the daemon thread exits cleanly.

---

## 6. Performance budget

Measured on M3 Pro, ElevenLabs cloud TTS, headphones:

| Stage | Cold | Warm | Notes |
|---|---|---|---|
| Whisper model load | ~5 s | 0 | Done during `_init_components` warmup |
| Per-utterance VAD | — | <1 ms / frame | 32 ms frames, way faster than real-time |
| Whisper transcribe | — | ~0.3× real-time | 3 s of audio → ~1 s transcribe |
| Trigger regex | — | <1 ms | Single regex search per committed transcript |
| Fast path (TV / greeting) | — | 100–400 ms | Sub-second hits skip the LLM |
| LLM first sentence | — | 300–800 ms | OpenRouter Gemma 4 / Groq Qwen |
| TTS first byte (cloud) | ~150 ms (handshake) | ~75 ms | Persistent httpx client reuses connection |
| TTS first byte (Kokoro) | ~500 ms (model load) | ~500 ms | Synth blocks until done |

End-to-end perceived latency from end-of-speech to first audible reply: **typically 1.2–2.0 s** with a warm cache and a fast path miss; **0.4–0.6 s** on a fast path hit (TV controls, greetings).

---

## 7. Configuration surface

Most knobs live in [`friday/voice/config.py`](../friday/voice/config.py). The ones worth knowing:

| Constant | Default | When to change |
|---|---|---|
| `VAD_THRESHOLD` | 0.7 | Lower (0.5) for soft speakers; higher (0.85) if music keeps tripping it |
| `VAD_SILENCE_MS` | 800 | Lower for snappier turn-taking; higher if short pauses keep cutting you off |
| `TRIGGER_WORDS` | `["friday"]` | Add aliases — `["friday", "yo friday", "f"]` |
| `FOLLOWUP_WINDOW_S` | 8 | Increase for slower conversations |
| `TRANSCRIPT_BUFFER_SECONDS` | 300 | The ambient-context window — 5 min by default |
| `WHISPER_MODEL` | `whisper-small-mlx` | Bump to `medium-mlx` for accuracy if you have RAM headroom |

Cloud-side knobs live in [`friday/core/config.py`](../friday/core/config.py):

| Variable | Purpose |
|---|---|
| `ELEVENLABS_API_KEY` | Cloud TTS auth — unset to force Kokoro |
| `ELEVENLABS_VOICE_ID` | Voice for both live + voice notes |
| `ELEVENLABS_MODEL` | Live-streaming model (Flash v2.5) |
| `ELEVENLABS_EXPRESSIVE_MODEL` | Voice-note model (Eleven v3) — see [telegram.md](telegram.md#voice-notes-via-elevenlabs-v3) |
| `FRIDAY_TTS_INPUT_STREAMING` | `true` enables WebSocket input streaming (§3.1). Default off. |
| `FRIDAY_PRIMARY_PROVIDER` | Pin which LLM the pipeline calls — `groq`, `openrouter`, or `auto`. See [agents.md §4.9](agents.md). |

---

## 8. Diagnostics

```bash
# Is the pipeline actually running?
#   In FRIDAY CLI:
/voice
# → "Voice ON" + ":: Loading voice models…" + "✓ TTS:/✓ VAD/✓ STT" lines
# → "Voice pipeline ACTIVE — always listening"

# Does the mic open?
python -c "import sounddevice as sd; print(sd.query_devices(kind='input'))"

# Is Silero installed and runnable?
python -c "import silero_vad, torch; \
           m = silero_vad.load_silero_vad(); \
           print('Silero loaded; torch', torch.__version__)"

# Is Whisper warm + transcribing?
python -c "
import numpy as np
from friday.voice.stt import Transcriber
t = Transcriber(); t.warmup()
# 1s of silence — should return empty string fast
print(repr(t.transcribe(np.zeros(16000, dtype=np.int16))))
"

# Does ElevenLabs auth work?
curl -sH "xi-api-key: $ELEVENLABS_API_KEY" \
     https://api.elevenlabs.io/v1/user | jq .subscription.tier
```

If `_run` prints `✗ Voice init failed: …` the most common causes are:

| Error | Cause | Fix |
|---|---|---|
| `No module named 'silero_vad'` | Dep missing | `pip install silero-vad torch` (already declared in pyproject.toml as of commit `26c7ace`) |
| `OSError: [Errno -9999] Unanticipated host error` | macOS mic permission denied for the terminal app | System Settings → Privacy & Security → Microphone → enable for Terminal/iTerm/Warp |
| `RuntimeError: HTTPError 429` from ElevenLabs | Quota exceeded | Pipeline auto-falls back to Kokoro on next sentence; check your ElevenLabs dashboard |
| `Could not load mlx-whisper model` | First-run download interrupted | Re-run; the model caches under `~/.cache/huggingface/hub/` |

---

## 9. What this design deliberately doesn't do

- **No always-on cloud STT.** `cloud_stt.py` exists for a hypothetical ElevenLabs Scribe Realtime mode but the active pipeline runs local Whisper. Cloud STT would mean every word you say leaves your machine — that's the wrong default for a personal AI OS, even with the wake-word approach.
- **No barge-in.** You can't interrupt FRIDAY mid-sentence by speaking — the mic is muted during TTS. Adding barge-in means VAD running parallel to TTS playback with echo cancellation, which is doable but complicated. Future work.
- **No multi-speaker diarization.** Whisper produces one stream of text. If two people are talking, both end up in the rolling transcript without speaker labels. Good enough for personal assistant use.
- **No custom wake-word model.** Currently uses literal-word matching against the transcript (`"friday"` regex). [`wake_word.py`](../friday/voice/wake_word.py) has scaffolding for an OpenWakeWord-based pretrained model (`hey_jarvis` is the closest open weight) but it's not the active path. Trigger-from-transcript works well enough that we haven't switched.

---

## 10. File map

```
friday/voice/
├── __init__.py
├── config.py            # 42 lines — every magic number lives here
├── vad.py               # 59 lines — Silero wrapper, three-state machine
├── stt.py               # 47 lines — MLX Whisper wrapper + warmup
├── tts.py               # ~410 lines — Speaker class:
│                        #   ├ speak()           — HTTP /stream (one-shot input, streamed output)
│                        #   └ speak_streaming() — WebSocket /stream-input (token-by-token in, audio out)
├── pipeline.py          # ~680 lines — the daemon thread, ambient loop, trigger, dispatch:
│                        #   ├ _process_and_speak()           — sentence-batched HTTP TTS
│                        #   └ _process_and_speak_streaming() — chunk-streamed WS TTS (FRIDAY_TTS_INPUT_STREAMING=true)
├── response_filter.py   # 67 lines — strip code/markdown for spoken output
├── wake_word.py         # 47 lines — OpenWakeWord scaffolding (currently unused)
└── cloud_stt.py         # 220 lines — ElevenLabs Scribe Realtime client (currently unused)
```

Files that *aren't* under `friday/voice/` but are still part of the voice story:

- [`friday/tools/voice_tools.py`](../friday/tools/voice_tools.py) — TTS-to-file for Telegram voice notes (separate path, see [telegram.md](telegram.md))
- [`friday/cli.py:145-153`](../friday/cli.py#L145-L153) — boot wiring
- [`friday/core/orchestrator.py`](../friday/core/orchestrator.py) — `fast_path` and `dispatch_background` are what the pipeline calls

---

## See also

- [setup-voice.md](setup-voice.md) — user setup, mic permissions, voice picker, ElevenLabs config wizard
- [telegram.md](telegram.md#voice-notes-via-elevenlabs-v3) — voice notes (offline render path)
- [llm-providers.md](llm-providers.md) — what the LLM stage of `_process_and_speak` is calling under the hood
