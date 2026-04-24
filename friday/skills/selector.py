"""Skill selector — picks the 1-3 skills relevant to a specific user task.

Two-stage pipeline:

  Stage 1 — embedding shortlist (optional, via ``embedder.py``):
    Embed the task + every agent-matching skill description. Cosine-sim
    filter to the top 5 candidates above similarity 0.3. Local, ~10ms.
    Skipped if Ollama / nomic-embed-text isn't available.

  Stage 2 — LLM precision pick:
    Show the shortlist (or all agent-matching skills, if stage 1 was
    skipped) to the LLM and ask it to pick the 1-3 that actually apply.
    Returns JSON.

Replaces the old ``build_skill_context(agent_name)`` call in
``BaseAgent.run()`` that blindly appended every agent-matching skill to
the system prompt — regardless of whether the user's task needed any of
them. For agents like ``job_agent`` that previously paid ~22 000 chars
(~5 500 tokens) of irrelevant skill text on every call, the saving is
substantial and compounding across a session.

Fallbacks (always safe):
  - Embedder unavailable → skip stage 1, hand all agent-matching skills to LLM.
  - LLM picker fails / times out → return all agent-matching skills (old behaviour).
  - Task is trivially short (greetings, acks) → return [] to skip skills entirely.

Public surface:
  - ``select_for_task(agent_name, task)`` → list[dict] of chosen skills
  - ``build_skill_context_for_task(agent_name, task)`` → str ready for prompt
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from friday.skills.loader import get_skills_for_agent

log = logging.getLogger("friday.skills.selector")

# Tasks shorter/simpler than this rarely benefit from a skill — skip the
# selector entirely for latency wins on greetings / acks.
_TRIVIAL_TASK_RE = re.compile(
    r"^\s*(hi|hello|hey|yo|ok|okay|thanks?|thank\s+you|cool|nice|yeah|"
    r"yep|nope|no|done|sure|got\s+it|understood|bye|goodbye|\?)\s*[!.?]*\s*$",
    re.IGNORECASE,
)


def _is_trivial(task: str) -> bool:
    if not task or len(task.strip()) < 4:
        return True
    return bool(_TRIVIAL_TASK_RE.match(task))


def _shortlist_via_embedding(
    task: str, skills: list[dict], top_k: int = 5,
) -> Optional[list[dict]]:
    """Return a subset of ``skills`` ranked by embedding similarity, or
    None if embeddings are unavailable (caller then uses full list)."""
    try:
        from friday.skills.embedder import rank_skills_for_task
    except Exception:
        return None

    index = {s["name"]: s for s in skills}
    ranked = rank_skills_for_task(task, index, top_k=top_k)
    if not ranked:
        return None
    return [index[n] for n, _ in ranked]


def _pick_via_llm(
    task: str, candidates: list[dict], max_picks: int = 3,
    preferred_provider: str = "",
) -> list[dict]:
    """Ask the LLM which of ``candidates`` apply to ``task``. Returns a
    (possibly empty) list of candidates. Falls back to returning all
    candidates on any failure so we never block the main call.

    When the caller has a provider preference (e.g. investigation_agent
    preferring Groq), we honour it on the selector call too — avoids a
    wasted 429 on the primary just to pre-select skills.
    """
    if not candidates:
        return []
    if len(candidates) == 1:
        # Only one option — save the LLM call
        return candidates

    try:
        from friday.core.llm import cloud_chat, extract_text
        from friday.core.config import USE_CLOUD
    except Exception:
        return candidates

    if not USE_CLOUD:
        # Local-only mode — we don't want to burn an Ollama call on
        # pre-selection. Use everything.
        return candidates

    listing = "\n".join(
        f"- {s['name']}: {s.get('description','').strip()[:200]}"
        for s in candidates
    )
    sys_prompt = (
        "You are a skill router. Given a user's task and a list of candidate "
        "skills (each with a one-line description), return the names of the "
        "skills actually useful for THIS task. If none are relevant, return "
        "an empty list. If multiple are relevant, rank by usefulness.\n\n"
        f"Return ONLY JSON: {{\"skills\": [\"name1\", \"name2\"]}}. "
        f"Choose at most {max_picks}."
    )
    user_prompt = f"User task:\n{task}\n\nCandidate skills:\n{listing}"

    try:
        resp = cloud_chat(
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=200,
            preferred_provider=preferred_provider,
        )
        raw = extract_text(resp).strip()
        # Strip common markdown wrappers
        if raw.startswith("```"):
            raw = re.sub(r"^```\w*\s*|\s*```$", "", raw, flags=re.DOTALL)
        data = json.loads(raw)
        picked_names = data.get("skills") or []
    except Exception as e:
        log.debug("LLM picker failed (%s) — using full shortlist", e)
        return candidates

    chosen: list[dict] = []
    index = {s["name"]: s for s in candidates}
    for n in picked_names:
        s = index.get(n)
        if s and s not in chosen:
            chosen.append(s)
        if len(chosen) >= max_picks:
            break
    return chosen


def select_for_task(
    agent_name: str, task: str, max_skills: int = 3,
    preferred_provider: str = "",
) -> list[dict]:
    """Return the skills actually relevant to this specific task.

    Args:
        agent_name: which agent is running (so we only consider skills
                    whose frontmatter allows that agent).
        task: the user's task / query text.
        max_skills: cap on how many skills are returned.
        preferred_provider: forwarded to the LLM picker call. When the
            calling agent has a provider preference (e.g. "groq"), pass
            it through so the selector doesn't hit a wasted primary 429.

    Returns:
        List of skill dicts (same shape as ``loader.discover()`` values).
        Empty list if the task is trivial or no skill applies.
    """
    if _is_trivial(task):
        log.debug("skill-select: trivial task, no skills injected")
        return []

    agent_skills = get_skills_for_agent(agent_name)
    if not agent_skills:
        return []

    # Stage 1 — embedding shortlist (~10ms local, optional)
    shortlist = _shortlist_via_embedding(task, agent_skills, top_k=5)
    if shortlist is None:
        shortlist = agent_skills  # embedder unavailable; LLM sees all

    # Stage 2 — LLM picks the 1-3 that apply
    chosen = _pick_via_llm(
        task, shortlist, max_picks=max_skills,
        preferred_provider=preferred_provider,
    )

    if chosen:
        log.info(
            "skill-select agent=%s picked=%s (from %d candidates)",
            agent_name, [s["name"] for s in chosen], len(shortlist),
        )
    return chosen


def build_skill_context_for_task(
    agent_name: str, task: str, preferred_provider: str = "",
) -> str:
    """Same output shape as ``loader.build_skill_context`` — a markdown
    block ready to append to a system prompt — but containing only the
    skills the selector picked."""
    chosen = select_for_task(agent_name, task, preferred_provider=preferred_provider)
    if not chosen:
        return ""
    parts = [f"## Skill: {s['name']}\n{s['body']}" for s in chosen]
    return "\n\n---\n\n".join(parts)
