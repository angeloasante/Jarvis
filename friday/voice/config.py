"""Voice pipeline constants."""

# Audio
SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"
FRAME_SIZE_MS = 32          # 32ms chunks → 512 samples at 16kHz (Silero VAD requirement)
FRAME_SIZE = 512            # Silero VAD requires exactly 512 samples at 16kHz

# VAD
VAD_THRESHOLD = 0.5         # Silero confidence threshold
VAD_SILENCE_MS = 800        # Silence duration to trigger end-of-speech
VAD_SILENCE_FRAMES = int(VAD_SILENCE_MS / FRAME_SIZE_MS)
VAD_MIN_SPEECH_MS = 300     # Minimum speech to accept (filters noise)
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

# TTS (Kokoro)
KOKORO_VOICE = "af_heart"   # Default female voice
KOKORO_SPEED = 1.0

# Response filter
MAX_VOICE_SENTENCES = 3     # Max sentences to speak aloud

# Chime
CHIME_FREQ = 880            # Hz — A5 note
CHIME_DURATION = 0.15       # seconds
CHIME_VOLUME = 0.3
