"""FRIDAY configuration. Single source of truth for model, paths, settings."""

from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")
DATA_DIR = PROJECT_ROOT / "data"
MEMORY_DIR = DATA_DIR / "memory"
SKILLS_DIR = PROJECT_ROOT / "friday" / "skills"

# Ollama
OLLAMA_BASE_URL = "http://localhost:11434"
MODEL_NAME = "qwen3.5:9b"       # All tasks — reliable tool calling (8/8 accuracy), chat, formatting

# Memory
SQLITE_DB_PATH = MEMORY_DIR / "friday.db"
CHROMA_PERSIST_DIR = str(MEMORY_DIR / "chroma")

# Ensure dirs exist
DATA_DIR.mkdir(exist_ok=True)
MEMORY_DIR.mkdir(exist_ok=True)
