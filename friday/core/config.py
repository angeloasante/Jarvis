"""FRIDAY configuration. Single source of truth for model, paths, settings."""

import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")
DATA_DIR = PROJECT_ROOT / "data"
MEMORY_DIR = DATA_DIR / "memory"
SKILLS_DIR = PROJECT_ROOT / "friday" / "skills"

# Ollama (local)
OLLAMA_BASE_URL = "http://localhost:11434"
MODEL_NAME = "qwen3.5:9b"       # All tasks — reliable tool calling (8/8 accuracy), chat, formatting

# Cloud LLM — provider-agnostic (any OpenAI-compatible API)
# Set CLOUD_API_KEY + CLOUD_BASE_URL + CLOUD_MODEL in .env, or use provider shortcuts:
#   OPENROUTER_API_KEY → auto-sets base URL + model (Gemma 4 31B)
#   GROQ_API_KEY       → auto-sets base URL + model (Qwen3-32B)
# Priority: explicit CLOUD_* > OPENROUTER > GROQ. Falls back to local Ollama if none set.
_explicit_key = os.getenv("CLOUD_API_KEY", "")
_openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
_groq_key = os.getenv("GROQ_API_KEY", "")

if _explicit_key:
    # Fully manual config
    CLOUD_API_KEY = _explicit_key
    CLOUD_BASE_URL = os.getenv("CLOUD_BASE_URL", "")
    CLOUD_MODEL_NAME = os.getenv("CLOUD_MODEL", "")
elif _groq_key:
    CLOUD_API_KEY = _groq_key
    CLOUD_BASE_URL = os.getenv("CLOUD_BASE_URL", "https://api.groq.com/openai/v1")
    CLOUD_MODEL_NAME = os.getenv("CLOUD_MODEL", "qwen/qwen3-32b")
elif _openrouter_key:
    CLOUD_API_KEY = _openrouter_key
    CLOUD_BASE_URL = os.getenv("CLOUD_BASE_URL", "https://openrouter.ai/api/v1")
    CLOUD_MODEL_NAME = os.getenv("CLOUD_MODEL", "google/gemma-4-31b-it")
else:
    CLOUD_API_KEY = ""
    CLOUD_BASE_URL = ""
    CLOUD_MODEL_NAME = ""

USE_CLOUD = bool(CLOUD_API_KEY)

# ElevenLabs TTS (cloud streaming voice)
# Set ELEVENLABS_API_KEY in .env to enable. Falls back to local Kokoro if unset.
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb").strip("/")  # "George" — warm male
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5")  # ~75ms latency, best for real-time
USE_CLOUD_TTS = bool(ELEVENLABS_API_KEY)

# Memory
SQLITE_DB_PATH = MEMORY_DIR / "friday.db"
CHROMA_PERSIST_DIR = str(MEMORY_DIR / "chroma")

# Ensure dirs exist
DATA_DIR.mkdir(exist_ok=True)
MEMORY_DIR.mkdir(exist_ok=True)
