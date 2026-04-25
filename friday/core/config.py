"""FRIDAY configuration. Single source of truth for model, paths, settings."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent

# Load env from layered sources, first-write-wins:
#   1. Mac app bundled defaults — friday_defaults.env (Tavily etc, shipped)
#   2. ~/Friday/.env     ← primary user env (visible, editable alongside user.json)
#   3. ~/.friday/.env    ← legacy location, still read for backwards compat
#   4. <repo>/.env       ← dev environment
# The Mac app passes per-user secrets via subprocess environment (highest
# effective priority since env vars set before Python starts aren't overridden).
def _load_layered_env() -> None:
    # Inside the bundled .app, sys.executable is .../Friday.app/Contents/Resources/python/bin/python3
    # → walk up to Resources and look for friday_defaults.env.
    exe = Path(sys.executable).resolve()
    for ancestor in exe.parents:
        candidate = ancestor / "friday_defaults.env"
        if candidate.exists():
            load_dotenv(candidate, override=False)
            break
        if ancestor.name == "Contents":
            break  # don't escape the app bundle

    # Primary: ~/Friday/.env — visible, colocated with user.json
    primary_env = Path.home() / "Friday" / ".env"
    if primary_env.exists():
        load_dotenv(primary_env, override=False)

    # Legacy: ~/.friday/.env — kept for backwards compatibility
    legacy_env = Path.home() / ".friday" / ".env"
    if legacy_env.exists():
        load_dotenv(legacy_env, override=False)

    # Dev install from source: the repo's own .env file
    repo_env = PROJECT_ROOT / ".env"
    if repo_env.exists():
        load_dotenv(repo_env, override=False)


_load_layered_env()
DATA_DIR = PROJECT_ROOT / "data"
MEMORY_DIR = DATA_DIR / "memory"
SKILLS_DIR = PROJECT_ROOT / "friday" / "skills"

# Ollama (local)
OLLAMA_BASE_URL = "http://localhost:11434"
MODEL_NAME = "qwen3.5:9b"       # All tasks — reliable tool calling (8/8 accuracy), chat, formatting

# Cloud LLM — provider-agnostic (any OpenAI-compatible API).
#
# Provider priority for the INITIAL active provider (see llm.py for runtime
# fallback chain — if the active provider fails, it automatically cascades
# through the rest):
#
#   1. CLOUD_API_KEY (+ CLOUD_BASE_URL + CLOUD_MODEL) — explicit manual override
#   2. OPENROUTER_API_KEY — Gemma 4 via OpenRouter (preferred — multimodal + cheapest)
#   3. GOOGLE_API_KEY      — Gemma via Google AI Studio (OpenAI-compatible shim)
#   4. GROQ_API_KEY        — fastest inference, tool-calling specialist, fallback
#   5. (none of the above) — local Ollama
#
# CLOUD_FALLBACK_CHAIN (below) lists all providers runtime-fallback should try
# in order if the primary 429s / 5xxs. llm.py reads this.

_explicit_key   = os.getenv("CLOUD_API_KEY", "")
_openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
# Google AI Studio is intentionally NOT in the default chain. Gemma on AI
# Studio rejects system-role messages, and Gemini 2.5 Flash refuses
# dual-use OSINT work on "helpful and harmless" grounds — so it's useless
# as a fallback for FRIDAY's investigation path. Opt back in with
# FRIDAY_USE_GOOGLE_AI_STUDIO=true if you want it for non-OSINT agents.
_google_ai_key  = ""
if os.getenv("FRIDAY_USE_GOOGLE_AI_STUDIO", "").lower() == "true":
    _google_ai_key = os.getenv("GOOGLE_AI_STUDIO_KEY", "") or os.getenv("GEMINI_API_KEY", "")
_groq_key       = os.getenv("GROQ_API_KEY", "")

# Per-provider default models — Gemma where available, Qwen3 on Groq
_DEFAULTS = {
    "openrouter": ("https://openrouter.ai/api/v1",                                    "google/gemma-4-31b-it:free"),
    # Google AI Studio default: Gemini 2.5 Flash.
    # Why not Gemma? Gemma models on AI Studio (gemma-3-27b-it) reject `system`
    # role messages with "Developer instruction is not enabled" — they only
    # accept user/assistant turns. Gemini 2.5 Flash is Google's current
    # multi-modal free-tier model (text + image + audio + video in, supports
    # system messages, 1500 req/day free) — the closest equivalent to what
    # "Gemma 4 multimodal" maps to on Google's own API in 2026.
    "google":     ("https://generativelanguage.googleapis.com/v1beta/openai",         "gemini-2.5-flash"),
    "groq":       ("https://api.groq.com/openai/v1",                                  "qwen/qwen3-32b"),
}

# Primary-provider override. When set, that provider goes first regardless
# of normal key-priority order. Useful for: temporarily pinning to Groq
# while OpenRouter is daily-capped, or pinning to OpenRouter while testing
# Gemma quality. Other configured providers still appear in the fallback
# chain below.
#   FRIDAY_PRIMARY_PROVIDER=groq        → force Groq primary
#   FRIDAY_PRIMARY_PROVIDER=openrouter  → force OpenRouter primary
#   FRIDAY_PRIMARY_PROVIDER=auto / unset → key-priority order (default)
_pin = os.getenv("FRIDAY_PRIMARY_PROVIDER", "").strip().lower()
if _pin in ("auto", ""):
    _pin = ""

def _try_pin(name: str, key: str):
    """Return (key, base, model, provider_name) if this pin is usable."""
    if _pin == name and key:
        return key, _DEFAULTS[name][0], _DEFAULTS[name][1], name
    return None

_pinned = (
    _try_pin("groq",       _groq_key)
    or _try_pin("openrouter", _openrouter_key)
    or _try_pin("google",  _google_ai_key)
)

if _explicit_key:
    CLOUD_API_KEY = _explicit_key
    CLOUD_BASE_URL = os.getenv("CLOUD_BASE_URL", "")
    CLOUD_MODEL_NAME = os.getenv("CLOUD_MODEL", "")
    _PRIMARY_PROVIDER = "explicit"
elif _pinned:
    CLOUD_API_KEY, CLOUD_BASE_URL, CLOUD_MODEL_NAME, _PRIMARY_PROVIDER = _pinned
    # When pinning, intentionally IGNORE the env CLOUD_MODEL override —
    # it was usually set for a different provider (e.g.
    # CLOUD_MODEL=google/gemma-4-31b-it:free is OpenRouter-flavoured but
    # nonsense to Groq). Use the pinned provider's native default.
elif _openrouter_key:
    CLOUD_API_KEY = _openrouter_key
    CLOUD_BASE_URL = os.getenv("CLOUD_BASE_URL", _DEFAULTS["openrouter"][0])
    CLOUD_MODEL_NAME = os.getenv("CLOUD_MODEL", _DEFAULTS["openrouter"][1])
    _PRIMARY_PROVIDER = "openrouter"
elif _google_ai_key:
    CLOUD_API_KEY = _google_ai_key
    CLOUD_BASE_URL = os.getenv("CLOUD_BASE_URL", _DEFAULTS["google"][0])
    CLOUD_MODEL_NAME = os.getenv("CLOUD_MODEL", _DEFAULTS["google"][1])
    _PRIMARY_PROVIDER = "google"
elif _groq_key:
    CLOUD_API_KEY = _groq_key
    CLOUD_BASE_URL = os.getenv("CLOUD_BASE_URL", _DEFAULTS["groq"][0])
    CLOUD_MODEL_NAME = os.getenv("CLOUD_MODEL", _DEFAULTS["groq"][1])
    _PRIMARY_PROVIDER = "groq"
else:
    CLOUD_API_KEY = ""
    CLOUD_BASE_URL = ""
    CLOUD_MODEL_NAME = ""
    _PRIMARY_PROVIDER = "ollama"

USE_CLOUD = bool(CLOUD_API_KEY)

# Runtime fallback chain (read by llm.py) — when the primary fails
# (HTTP 429/404/5xx or network error), cascade through every configured
# alternative before dropping to local Ollama.
# Each entry: (name, api_key, base_url, model).
CLOUD_FALLBACK_CHAIN: list[tuple[str, str, str, str]] = []
for prov_name, prov_key in (
    ("openrouter", _openrouter_key),
    ("google",     _google_ai_key),
    ("groq",       _groq_key),
):
    if prov_key and prov_name != _PRIMARY_PROVIDER:
        CLOUD_FALLBACK_CHAIN.append((
            prov_name,
            prov_key,
            _DEFAULTS[prov_name][0],
            _DEFAULTS[prov_name][1],
        ))

# ElevenLabs TTS (cloud streaming voice)
# Set ELEVENLABS_API_KEY in .env to enable. Falls back to local Kokoro if unset.
# Two separate model configs because live streaming and one-shot voice notes
# have different latency/quality trade-offs:
#   - Live streaming voice pipeline → Flash v2.5 (~75ms TTFB, minimal emotion)
#   - Voice notes on Telegram / offline rendering → Eleven v3 (expressive,
#     supports inline audio tags like [laughs], [whispers], [excited])
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "lxYfHSkYm1EzQzGhdbfc").strip("/")
# Live-streaming model (used by friday/voice/pipeline.py for speaker playback).
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5")
# Expressive model for generated voice notes / audio files. Slower than flash
# but supports audio tags for emotion. Used by friday/tools/voice_tools.py.
ELEVENLABS_EXPRESSIVE_MODEL = os.getenv("ELEVENLABS_EXPRESSIVE_MODEL", "eleven_v3")
USE_CLOUD_TTS = bool(ELEVENLABS_API_KEY)

# Memory
SQLITE_DB_PATH = MEMORY_DIR / "friday.db"
CHROMA_PERSIST_DIR = str(MEMORY_DIR / "chroma")

# Ensure dirs exist
DATA_DIR.mkdir(exist_ok=True)
MEMORY_DIR.mkdir(exist_ok=True)
