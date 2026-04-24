# Voice pipeline setup

FRIDAY's voice stack is an always-on ambient listener. The microphone stays
open, speech segments are transcribed continuously, and when the word
"Friday" appears in a transcript the assistant answers with full awareness
of everything that was said in the preceding five minutes. You can be
mid-conversation with someone in the room and drop "Friday, what do you
think?" without repeating context.

This guide covers what the pipeline does, how it's wired, how to turn it
on, and how to troubleshoot it.

---

## 1. Overview

**Ambient-listen mode.** No push-to-talk, no wake-word button. Speak
normally; the mic picks up audio, Silero VAD chops it into speech
segments, MLX Whisper transcribes each one, the transcript is scanned for
the trigger word "Friday", and the pipeline either stays quiet (no
trigger) or activates FRIDAY (trigger found).

**Privacy model.**
- **STT is always local.** Audio never leaves the machine. Silero VAD and
  MLX Whisper both run on-device.
- **TTS is optional cloud.** If `ELEVENLABS_API_KEY` is set, FRIDAY
  streams synthesised speech back from ElevenLabs (~75 ms first byte). If
  the key is blank, the pipeline falls back to Kokoro-82M ONNX — fully
  offline, runs on the Neural Engine.
- **No raw audio is retained.** A rolling text transcript (5 min by
  default) sits in RAM for ambient-context building. Nothing is written
  to disk.

Source: `/Users/travismoore/Desktop/JARVIS/friday/voice/pipeline.py`

---

## 2. Architecture

```
┌───────┐   ┌───────────────┐   ┌──────────────┐   ┌────────┐   ┌────────┐
│  Mic  ├──▶│  Silero VAD   ├──▶│ MLX Whisper  ├──▶│ FRIDAY ├──▶│  TTS   │──▶ Speaker
│16kHz  │   │ speech/silence│   │  STT (en)    │   │  core  │   │ Eleven │
│  s16  │   │ 512-sample    │   │  ~200 MB     │   │ router │   │ / Koko │
└───────┘   └───────────────┘   └──────────────┘   └────────┘   └────────┘
                                        │
                                        ▼
                               Rolling transcript
                               (5 min, text only)
                                        │
                                        ▼
                               Trigger scan: /\bfriday\b/i
                                        │
                                        ▼
                               On hit: extract query +
                               ambient context → FRIDAY
```

The pipeline runs on a single daemon thread inside the CLI process. The
main `asyncio` loop is reused for dispatching queries to FRIDAY — the
voice thread hands work back via `run_coroutine_threadsafe`.

---

## 3. The four layers

### VAD — Silero

Silero VAD decides which frames contain speech. It's bundled with the
`silero_vad` Python package, so there is no download on first run.

```python
# friday/voice/vad.py
class VoiceActivityDetector:
    def __init__(self):
        self.model = silero_vad.load_silero_vad()

    def is_speech(self, chunk: np.ndarray) -> bool:
        tensor = torch.from_numpy(chunk.astype(np.float32) / 32768.0)
        prob = self.model(tensor, SAMPLE_RATE).item()
        return prob > VAD_THRESHOLD   # 0.7 — strict, filters music/TV
```

Silero requires exactly **512 samples at 16 kHz** per frame (32 ms). The
pipeline feeds it `FRAME_SIZE = 512` chunks and aggregates state over
~800 ms of trailing silence before declaring end-of-speech.

Tuning knobs live in `friday/voice/config.py`:

| Const                    | Default | What it does                                   |
| ------------------------ | ------- | ---------------------------------------------- |
| `VAD_THRESHOLD`          | 0.7     | Silero confidence. Higher = stricter.          |
| `VAD_SILENCE_MS`         | 800     | Trailing silence before end-of-speech.         |
| `VAD_MIN_SPEECH_MS`      | 400     | Minimum speech to accept (filters blips).      |

### STT — MLX Whisper

Transcription runs on Apple's MLX framework. The first invocation
downloads `mlx-community/whisper-small-mlx` (~200 MB) into the Hugging
Face cache; subsequent runs load from disk. Real-time factor on an M-
series chip is well under 1.0 for `small`.

```python
# friday/voice/stt.py
class Transcriber:
    def warmup(self):
        silence = np.zeros(16000, dtype=np.float32)
        mlx_whisper.transcribe(silence, path_or_hf_repo=WHISPER_MODEL,
                               language=WHISPER_LANGUAGE)
        self._warmed_up = True
```

`warmup()` is called during pipeline init so the first real utterance
doesn't eat the model-load cost.

### Wake word — fuzzy match on the transcript

FRIDAY does **not** use a dedicated wake-word NN in the ambient-listen
path. Instead, every transcribed segment is regex-scanned for any token
in `TRIGGER_WORDS` (default: `["friday"]`).

```python
# friday/voice/pipeline.py
_TRIGGER_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in TRIGGER_WORDS) + r")\b",
    re.IGNORECASE,
)

def _handle_committed_text(self, text: str):
    ...
    trigger_match = _TRIGGER_RE.search(text)
    if trigger_match:
        self._on_triggered(text, trigger_match)
```

Why no neural wake word? Whisper is already running on every segment and
its transcripts are strong — a literal regex against the text is faster,
has zero extra latency, and is trivially user-configurable (add your own
trigger words to `TRIGGER_WORDS`). An older OpenWakeWord path exists in
`friday/voice/wake_word.py` for push-to-talk use cases but is not wired
into the ambient loop.

### TTS — cloud or local

Two backends, one interface. The `Speaker` class auto-selects based on
whether `ELEVENLABS_API_KEY` is set.

```python
# friday/voice/tts.py
class Speaker:
    def speak(self, text: str) -> None:
        if self._use_cloud:
            try:
                self._speak_cloud(text)   # ElevenLabs streaming PCM
                return
            except Exception:
                logger.warning("ElevenLabs failed, falling back to Kokoro")
        self._speak_local(text)           # Kokoro-82M ONNX
```

Cloud playback uses a **persistent httpx client** so TCP + TLS handshake
cost is paid once, not per sentence. Chunks arrive as 24 kHz signed
16-bit PCM and are piped directly into a `sounddevice.OutputStream` —
audio starts coming out of the speakers before synthesis finishes.

---

## 4. TTS options

| Feature            | ElevenLabs Flash v2.5              | Kokoro-82M ONNX                |
| ------------------ | ---------------------------------- | ------------------------------ |
| Runs on            | Cloud (HTTPS stream)               | Local (ONNX Runtime / CPU)     |
| First-byte latency | ~75 ms                             | ~500 ms                        |
| Per-sentence cost  | ~1–2 s wall, streamed              | ~1–2 s wall, blocking          |
| Quality            | Studio-grade, expressive           | Good, slightly robotic         |
| Price              | $ per 1K chars (free tier exists)  | Free                           |
| Privacy            | Text leaves machine                | Fully offline                  |
| Setup              | Paste API key                      | Auto-downloads on first use    |
| Default voice      | `ELEVENLABS_VOICE_ID`              | `af_heart`                     |

Kokoro is the default. Pick ElevenLabs if you care about latency and
voice quality and are okay sending text out.

### Two ElevenLabs models, different jobs

FRIDAY runs ElevenLabs in **two modes** with different trade-offs. Both
are configured via the same API key — the model selection happens
per-callsite.

| Path | Model | Controlled by | Reason |
|---|---|---|---|
| Live speaker playback (`friday/voice/pipeline.py`) | `eleven_flash_v2_5` | `ELEVENLABS_MODEL` | Lowest TTFB (~75 ms) — required for interactive feel |
| Voice notes rendered to file (`friday/tools/voice_tools.py`) | `eleven_v3` | `ELEVENLABS_EXPRESSIVE_MODEL` | Supports inline audio tags (`[laughs] [whispers] [excited] [sighs] [sarcastic]`) for expressive delivery. Slower than flash but latency doesn't matter when rendering offline. |

The LLM can embed audio tags directly in the `text` parameter of
`tts_to_file` — see the tool schema. Example: `"Alright Travis [sighs]
OpenRouter is still down [laughs] Groq's carrying."` The tags are voice-
dependent — some voices carry laughter well, others don't. Test short
samples before scripting anything long.

Voice-note rendering path is documented in
[`docs/telegram.md`](telegram.md#voice-notes-via-elevenlabs-v3).

---

## 5. Setup flow

Run the wizard:

```bash
friday setup voice
```

What it does (`friday/core/setup_wizard.py::setup_voice()`):

1. Prompts `Enable voice pipeline (FRIDAY_VOICE=true)?` — toggles the env
   flag so `--voice` on later runs Just Works.
2. Asks for TTS backend — `1` for ElevenLabs, `2` for Kokoro (default).
3. If ElevenLabs: prompts for `ELEVENLABS_API_KEY` (hidden input) and
   optional `ELEVENLABS_VOICE_ID`. Blank voice ID falls back to George.
4. Writes updates to `~/.friday/.env`.

Example session:

```
$ friday setup voice

  FRIDAY's voice mode:
    · Ambient listen → say 'Friday' any time
    · STT runs fully local (Silero VAD + MLX Whisper) — nothing leaves your mac
    · TTS: ElevenLabs (cloud, ~75ms) or Kokoro (local, ~500ms)

  Enable voice pipeline (FRIDAY_VOICE=true)? [Y/n] y

  TTS choice:
    1. ElevenLabs (cloud, fastest) — needs API key
    2. Kokoro (local, private) — auto-downloads model on first use
  Pick 1 or 2 [2]: 1
  ELEVENLABS_API_KEY: ****
  ELEVENLABS_VOICE_ID (blank = 'George' default):

  ✓ Saved → /Users/you/.friday/.env
  Launch with: friday --voice · or toggle at runtime: /voice
```

Rerun the wizard any time to swap backends or change keys.

---

## 6. Runtime commands

The pipeline is wired into the CLI at
`/Users/travismoore/Desktop/JARVIS/friday/cli.py`.

| Command             | What it does                                         |
| ------------------- | ---------------------------------------------------- |
| `friday --voice`    | Start FRIDAY with voice enabled from boot.           |
| `/voice`            | Toggle pipeline on/off inside a running REPL.        |
| `/listening-on`     | Resume ambient mic after a pause.                    |
| `/listening-off`    | Pause ambient mic without killing the pipeline.      |

`/voice` tears the pipeline down entirely (STT + TTS + VAD unload).
`/listening-off` just sets a boolean — the pipeline is still alive and
the models stay resident, so resuming is instant. Use `/listening-off`
for meetings, `/voice off` to free memory.

Relevant CLI wiring:

```python
# friday/cli.py
if user_input == "/listening-off":
    voice_pipeline.set_listening(False)
    console.print("  [dim]:: Ambient mic paused[/dim]\n")
    continue

if user_input == "/listening-on":
    voice_pipeline.set_listening(True)
```

---

## 7. Follow-up window

After FRIDAY finishes speaking, the pipeline opens an **8-second grace
window** during which any speech is treated as directed at FRIDAY — no
trigger word required. Useful for natural back-and-forth:

```
You:    Friday, what's the weather?
FRIDAY: 62 and sunny in San Francisco.
You:    (within 8s) And tomorrow?         ← no "Friday" needed
FRIDAY: Rain expected by afternoon.
```

Controlled by `FOLLOWUP_WINDOW_S` in `friday/voice/config.py`. Set to 0
to disable.

---

## 8. Speaker label

Console transcripts show the user's name rather than a generic "You":

```python
# friday/voice/pipeline.py
def _voice_speaker_label() -> str:
    try:
        from friday.core.user_config import USER
        return USER.name.strip() or "You"
    except Exception:
        return "You"
```

`USER.name` comes from `~/.friday/user.json` (populated via
`friday setup user`). If the file is missing or the name is blank, the
label falls back to "You".

---

## 9. Permissions

### macOS — Terminal / iTerm / Warp / Ghostty

FRIDAY inherits microphone permissions from the terminal app you launch
it from. Grant access once per terminal:

1. Open **System Settings → Privacy & Security → Microphone**.
2. Toggle on **Terminal** (or iTerm2 / Warp / Ghostty / whichever you
   use).
3. Quit and relaunch the terminal so the permission picks up.

If the pipeline starts and you see zero transcripts appearing, this is
almost always the reason.

### Friday.app (Mac menu-bar build)

When running the native Mac app, grant **Friday.app** itself microphone
access in the same System Settings panel. The app can't auto-prompt
because the audio callback runs on a background thread.

---

## 10. Hardware notes

Tested on M1 / M2 / M3 / M4 MacBooks. Intel Macs will technically work
(MLX falls back) but real-time STT is not guaranteed — use Whisper `tiny`
if you go that route.

- **Moderate background noise is fine.** Silero VAD is tuned at
  threshold 0.7 to filter out ambient HVAC, traffic, keyboard clacks.
- **Loud music or multiple overlapping conversations degrade accuracy.**
  VAD will try to chunk the mix as one long speech segment and Whisper
  will return a garbled transcript. This is a fundamental VAD
  limitation — no mainstream open-source VAD handles cocktail-party
  audio well.
- **Built-in mic is fine** for desk use. AirPods and USB mics also work;
  the pipeline uses whatever is selected as default input in macOS
  Sound settings.

---

## 11. Troubleshooting

**"No audio device found" on startup.**
Check **System Settings → Sound → Input** and make sure an input device
is selected and not muted. Try running `python -c "import sounddevice;
print(sounddevice.query_devices())"` — you should see your mic listed.

**"Whisper model download failed."**
First-run fetches `mlx-community/whisper-small-mlx` from Hugging Face.
Check your connection, then rerun `friday --voice`. The download resumes
from wherever it stopped. Cached location:
`~/.cache/huggingface/hub/`.

**Pipeline keeps triggering on other people saying "Friday."**
The trigger is a literal regex match on the transcript, so anyone
saying the word will activate FRIDAY. Options:
- Change `TRIGGER_WORDS` in `friday/voice/config.py` to something
  less common (`["jarvis"]`, `["computer"]`, a nickname).
- Use `/listening-off` during group conversations.
- Future: tighten with a speaker-diarisation pass before trigger scan.

**Kokoro download fails.**
Kokoro pulls `onnx-community/Kokoro-82M-v1.0-ONNX` on first `.speak()`
call. If it errors, check your Hugging Face connection and disk space
(~100 MB needed). The file lives in the HF cache.

**ElevenLabs 401 / 429.**
401 = bad API key, re-run `friday setup voice`. 429 = rate limit; the
pipeline auto-falls-back to Kokoro for the rest of the session.

**Audio feedback loop (FRIDAY hears itself).**
The pipeline mutes the mic during TTS playback (`self._muted = True`),
so this shouldn't happen. If it does, you're likely using a separate
speaker + mic with no echo cancellation. Use headphones or a headset.

**High CPU while idle.**
Silero VAD + a short Whisper warmup loop are the baseline. Expect
~5–10% on one performance core on an M-series. Higher sustained usage
usually means Whisper is being re-triggered constantly by noisy input —
raise `VAD_THRESHOLD` to 0.8.

---

## 12. Environment variables

All config lives in `~/.friday/.env`.

| Var                    | Default                       | Notes                                       |
| ---------------------- | ----------------------------- | ------------------------------------------- |
| `FRIDAY_VOICE`         | `false`                       | Gate for `--voice` flag in CLI.             |
| `ELEVENLABS_API_KEY`   | *(unset)*                     | If set, cloud TTS is used.                  |
| `ELEVENLABS_VOICE_ID`  | `JBFqnCBsd6RMkjVDRZzb`        | "George" — warm male default.               |
| `ELEVENLABS_MODEL`     | `eleven_flash_v2_5`           | Lowest-latency tier, good enough quality.   |

Voice-pipeline internals (edit `friday/voice/config.py` for these):

| Const                      | Default | Purpose                             |
| -------------------------- | ------- | ----------------------------------- |
| `SAMPLE_RATE`              | 16000   | Mic + Whisper input rate.           |
| `VAD_THRESHOLD`            | 0.7     | Silero speech confidence.           |
| `TRIGGER_WORDS`            | `["friday"]` | Wake tokens (regex-matched).   |
| `TRANSCRIPT_BUFFER_SECONDS`| 300     | Rolling context horizon.            |
| `FOLLOWUP_WINDOW_S`        | 8       | Grace period after a response.      |
| `KOKORO_VOICE`             | `af_heart` | Kokoro voice bank selector.      |
| `KOKORO_SPEED`             | 1.0     | Kokoro playback speed multiplier.   |
| `WHISPER_MODEL`            | `mlx-community/whisper-small-mlx` | STT model repo.    |

---

## 13. Future work

- **Noise suppression preprocessing.** Run RNNoise or similar before VAD
  to handle loud environments and improve trigger-word reliability.
- **Streaming TTS first-token.** ElevenLabs Flash streams chunks already;
  the next step is starting playback on the LLM's first sentence fragment
  instead of waiting for a full sentence boundary. Kokoro would need a
  chunked-synthesis path that doesn't exist upstream yet.
- **Porcupine / OpenWakeWord upgrade path.** Swap the regex-on-transcript
  trigger for a dedicated wake-word NN to cut activation latency and
  cross-talk false-positives. Groundwork is already in
  `friday/voice/wake_word.py`.
- **Speaker diarisation.** So FRIDAY only activates when *you* say
  "Friday", not when someone else in the room does.
- **Push-to-talk fallback.** A hotkey mode for noisy environments where
  ambient listening is counterproductive.

---

## File reference

- `/Users/travismoore/Desktop/JARVIS/friday/voice/pipeline.py` — main loop, trigger logic, ambient context, follow-up window.
- `/Users/travismoore/Desktop/JARVIS/friday/voice/vad.py` — Silero VAD wrapper.
- `/Users/travismoore/Desktop/JARVIS/friday/voice/stt.py` — MLX Whisper wrapper.
- `/Users/travismoore/Desktop/JARVIS/friday/voice/tts.py` — ElevenLabs + Kokoro `Speaker`.
- `/Users/travismoore/Desktop/JARVIS/friday/voice/wake_word.py` — OpenWakeWord (unused in ambient path).
- `/Users/travismoore/Desktop/JARVIS/friday/voice/config.py` — all tunable constants.
- `/Users/travismoore/Desktop/JARVIS/friday/core/setup_wizard.py` — `setup_voice()` entry point.
- `/Users/travismoore/Desktop/JARVIS/friday/cli.py` — `--voice`, `/voice`, `/listening-on/off`.
