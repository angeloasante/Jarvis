"""Voice pipeline constants."""

# Audio
SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"
FRAME_SIZE_MS = 32          # 32ms chunks → 512 samples at 16kHz (Silero VAD requirement)
FRAME_SIZE = 512            # Silero VAD requires exactly 512 samples at 16kHz

# VAD
VAD_THRESHOLD = 0.7         # Silero confidence — higher = stricter (filters music/TV better)
VAD_SILENCE_MS = 800        # Silence duration to trigger end-of-speech
VAD_SILENCE_FRAMES = int(VAD_SILENCE_MS / FRAME_SIZE_MS)
VAD_MIN_SPEECH_MS = 400     # Minimum speech to accept (filters music bursts)
VAD_MIN_SPEECH_FRAMES = int(VAD_MIN_SPEECH_MS / FRAME_SIZE_MS)

# Wake word
# No pretrained "hey friday" exists — using "hey_jarvis" as closest match.
# Say "Hey Jarvis" to activate. Train custom model later with ~5 recordings.
WAKE_WORD_MODEL = "hey_jarvis"
WAKE_WORD_THRESHOLD = 0.7        # Detection confidence
WAKE_WORD_DISPLAY = "Hey Jarvis"  # What to show in UI (matches actual model)

# STT (MLX Whisper)
WHISPER_MODEL = "mlx-community/whisper-small-mlx"  # Good balance of speed/accuracy
WHISPER_LANGUAGE = "en"

# TTS — Cloud: ElevenLabs Flash v2.5 (~75ms latency, streaming PCM)
#       Local:  Kokoro-82M ONNX (fallback when no API key or cloud fails)
KOKORO_VOICE = "af_heart"   # Default female voice (local fallback)
KOKORO_SPEED = 1.0

# Ambient listening
TRIGGER_WORDS = ["friday"]              # Words that activate FRIDAY in ambient mode
TRANSCRIPT_BUFFER_SECONDS = 300         # 5 minutes of rolling context
FOLLOWUP_WINDOW_S = 8                   # Seconds after response to accept follow-ups without trigger word


# Chime
CHIME_FREQ = 880            # Hz — A5 note
CHIME_DURATION = 0.15       # seconds
CHIME_VOLUME = 0.3
