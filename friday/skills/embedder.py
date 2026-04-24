"""Skill description embedder — cheap first-pass filter for skill selection.

Embeds every skill's description field (1-2 sentences) once at startup,
caches the vectors on disk, and exposes a cosine-similarity shortlist for
a given user task.

The embedder intentionally uses a **local** model (Ollama's nomic-embed-text
by default) so:
  1. No network round-trip — selection adds <10ms, not 100ms+.
  2. No cloud quota consumed on pre-selection.
  3. Works offline.

Graceful fallback: if Ollama isn't running or the model isn't pulled,
``embed()`` returns None and ``selector.py`` drops to LLM-only selection.
Nothing breaks.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from pathlib import Path
from typing import Optional

log = logging.getLogger("friday.skills.embedder")

# Where we cache embeddings — beside SKILL.md files so it travels with the
# skill. One JSON per user.
_CACHE_PATH = Path.home() / ".friday" / "skill_embeddings.json"
_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

# Small, fast, local; 137 MB disk. Pull via `ollama pull nomic-embed-text`.
EMBED_MODEL = "nomic-embed-text"

_ollama_available: Optional[bool] = None  # lazy-checked once


def _ollama_ok() -> bool:
    """Check whether Ollama is running AND the embed model is pulled."""
    global _ollama_available
    if _ollama_available is not None:
        return _ollama_available
    try:
        import ollama
        # ollama.list() returns current models; cheap call
        models = {m.get("model", "").split(":")[0] for m in ollama.list().get("models", [])}
        _ollama_available = EMBED_MODEL in models or any(
            m.startswith(EMBED_MODEL) for m in models
        )
        if not _ollama_available:
            log.info(
                "Skill embedder disabled — Ollama model '%s' not pulled. "
                "Run: ollama pull %s", EMBED_MODEL, EMBED_MODEL,
            )
    except Exception as e:
        log.info("Skill embedder disabled — Ollama not reachable (%s)", e)
        _ollama_available = False
    return _ollama_available


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _load_cache() -> dict:
    if not _CACHE_PATH.exists():
        return {}
    try:
        return json.loads(_CACHE_PATH.read_text())
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    try:
        _CACHE_PATH.write_text(json.dumps(cache))
    except Exception as e:
        log.warning("Couldn't persist skill embedding cache: %s", e)


def embed(text: str) -> Optional[list[float]]:
    """Return a vector for `text`, or None if embedder is unavailable."""
    if not text or not _ollama_ok():
        return None
    try:
        import ollama
        resp = ollama.embeddings(model=EMBED_MODEL, prompt=text)
        vec = resp.get("embedding") or resp.get("embeddings")
        if isinstance(vec, list) and vec and isinstance(vec[0], list):
            vec = vec[0]  # batch wrapper
        return vec
    except Exception as e:
        log.debug("embed() failed: %s", e)
        return None


def embed_skills(skills: dict[str, dict]) -> dict[str, list[float]]:
    """Return {skill_name: vector} for every skill whose description we can
    embed. Cache hits avoid re-computing unchanged descriptions."""
    cache = _load_cache()
    vectors: dict[str, list[float]] = {}
    touched = False

    for name, skill in skills.items():
        desc = (skill.get("description") or "").strip()
        if not desc:
            continue
        h = _hash_text(desc)
        hit = cache.get(name)
        if hit and hit.get("hash") == h and hit.get("vector"):
            vectors[name] = hit["vector"]
            continue
        v = embed(desc)
        if v is None:
            continue
        vectors[name] = v
        cache[name] = {"hash": h, "vector": v}
        touched = True

    if touched:
        _save_cache(cache)
    return vectors


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def rank_skills_for_task(
    task: str, skills: dict[str, dict], top_k: int = 5,
    threshold: float = 0.3,
) -> list[tuple[str, float]]:
    """Return [(skill_name, similarity_score)] ordered by descending cosine.

    Only skills scoring above ``threshold`` are returned. Empty list if
    embeddings are unavailable — the caller should fall back to LLM-only.
    """
    task_vec = embed(task)
    if task_vec is None:
        return []
    skill_vecs = embed_skills(skills)
    if not skill_vecs:
        return []
    scored = [(n, cosine(task_vec, v)) for n, v in skill_vecs.items()]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [(n, s) for n, s in scored[:top_k] if s >= threshold]
