"""Autonomous skill creation — distil successful multi-step workflows into
reusable SKILL.md files so the next time a similar task comes in, the
selector picks the distilled workflow and the agent runs it in fewer
LLM calls.

Trigger policy (heuristic, inspired by Hermes Agent):
  - Task completed successfully AND
  - Used 5+ distinct tool calls (non-trivial workflow) AND
  - No existing skill's description is semantically similar (cosine > 0.85)
  - Task itself isn't trivial ("hi", "ok", etc.)

Flow:
  1. Build a compact trace digest from (task, tools, args summaries, final result).
  2. Ask the LLM to output SKILL.md frontmatter + markdown body as one string.
  3. Validate the output has required frontmatter keys.
  4. Write to ``~/.friday/skills/auto_<slug>/SKILL.md``.
  5. Call ``loader.reload()`` so the selector sees it on the next call.

Everything runs fire-and-forget in a background thread — creation never
blocks the user-visible response.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("friday.skills.creator")

_USER_SKILLS_DIR = Path.home() / ".friday" / "skills"
_USER_SKILLS_DIR.mkdir(parents=True, exist_ok=True)

# Audit log of every creation — makes it easy for the user to see what
# FRIDAY has been drafting in the background.
_AUDIT_LOG = _USER_SKILLS_DIR / "auto_creation_log.jsonl"

MIN_TOOL_CALLS = 5           # under this, it's not a reusable workflow
DEDUP_THRESHOLD = 0.85       # skip creation if cosine similarity ≥ this


# ── Heuristics ──────────────────────────────────────────────────────────────

def _slugify(text: str, limit: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:limit] or "untitled"


def _is_already_covered(description: str, existing_skills: dict[str, dict]) -> bool:
    """True if any existing skill's description is semantically close."""
    try:
        from friday.skills.embedder import embed, cosine, _ollama_ok
        if not _ollama_ok():
            return False  # can't dedup without embeddings; accept and move on
        new_vec = embed(description)
        if not new_vec:
            return False
        for s in existing_skills.values():
            existing_desc = (s.get("description") or "").strip()
            if not existing_desc:
                continue
            existing_vec = embed(existing_desc)
            if not existing_vec:
                continue
            if cosine(new_vec, existing_vec) >= DEDUP_THRESHOLD:
                log.info("Autoskill dedup: similar to existing '%s'", s.get("name"))
                return True
    except Exception as e:
        log.debug("dedup check failed, allowing creation (%s)", e)
    return False


def _trace_digest(
    task: str, tools_called: list[str], tool_args: list[dict] | None,
    final_result: str,
) -> str:
    """Build a compact, LLM-friendly summary of what happened."""
    pieces = [f"USER TASK: {task.strip()[:400]}"]
    pieces.append(f"\nTOOLS USED (in order): {', '.join(tools_called) or '(none)'}")
    if tool_args:
        pieces.append("\nTOOL CALL ARGUMENTS (summarised):")
        for i, a in enumerate(tool_args[:12]):  # cap noise
            try:
                compact = json.dumps(a, default=str)[:180]
            except Exception:
                compact = str(a)[:180]
            pieces.append(f"  {i+1}. {compact}")
    pieces.append(f"\nFINAL RESPONSE (truncated):\n{(final_result or '').strip()[:600]}")
    return "\n".join(pieces)


# ── LLM draft + validation ──────────────────────────────────────────────────

_SKILL_WRITER_SYS = """You are a skills distillation author for FRIDAY, a \
personal AI OS. You'll see a successful multi-step task — the user query, \
the tools FRIDAY used, and the final response. Your job is to write a \
reusable SKILL.md that captures the REPEATABLE workflow — NOT the one-off \
details of this specific request.

Output MUST be a single SKILL.md file starting with YAML frontmatter, \
then the markdown body. Nothing else — no commentary, no code fences.

Required frontmatter fields:
  name: kebab-case-name (no spaces, descriptive of the capability)
  description: ONE sentence describing when to use this skill (used for \
routing, so be specific about the trigger)
  agents: [one or more of: research_agent, comms_agent, code_agent, \
system_agent, household_agent, job_agent, memory_agent, social_agent, \
briefing_agent, monitor_agent, deep_research_agent, investigation_agent]

Body structure (markdown):
  # <Title Case of the capability>

  ## When to Use
  A few lines on the user phrasings / patterns that mean this skill \
applies. Think like a router: what exact cues trigger this.

  ## Procedure
  Numbered steps. Describe the TOOL PATTERN, not the specific data from \
this one trace. E.g. 'fetch the page, extract key fields, cross-reference \
memory' rather than 'fetch https://example.com/jobs/42'.

  ## Pitfalls
  Known failure modes or 'don't do this' notes, if any are obvious from \
the trace. Skip the section if you have nothing useful.

Rules:
- Never invent capabilities FRIDAY doesn't have — only mention tools you \
see in the trace.
- The skill should generalise: strip personal details, specific URLs, \
names from the body.
- Keep under 400 words total.
- No emoji, no marketing tone, no filler.
"""


async def _draft_skill(agent_name: str, digest: str) -> str | None:
    """Ask the LLM to draft a SKILL.md. Returns the raw markdown or None."""
    try:
        from friday.core.llm import cloud_chat, extract_text
        from friday.core.config import USE_CLOUD
    except Exception:
        return None
    if not USE_CLOUD:
        return None

    user = f"Agent that ran this task: {agent_name}\n\nTrace:\n{digest}"
    try:
        resp = cloud_chat(
            messages=[
                {"role": "system", "content": _SKILL_WRITER_SYS},
                {"role": "user", "content": user},
            ],
            max_tokens=900,
        )
        raw = extract_text(resp).strip()
    except Exception as e:
        log.debug("skill drafter LLM call failed: %s", e)
        return None

    # Strip accidental code fences
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\s*|\s*```$", "", raw, flags=re.DOTALL).strip()
    return raw or None


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
# LLMs often omit the opening --- fence — accept "name: …\nbody" too.
_BARE_FRONTMATTER_RE = re.compile(
    r"^\s*(name:.*?(?=\n\s*(?:#\s|```|$)))(.*)$", re.DOTALL | re.IGNORECASE,
)


def _parse_and_validate(raw: str) -> tuple[dict, str] | None:
    """Ensure the LLM-produced SKILL.md has the required frontmatter fields.

    Handles three formats the LLM produces in practice:
      1. Proper ``---\\n...\\n---\\n`` fenced frontmatter (ideal).
      2. Bare ``name: ...\\nagents: [...]\\n\\n# Title`` (missing fences).
      3. Same with a stray closing ``` between frontmatter and body.
    """
    text = raw.strip()

    # Strip any stray code fences anywhere in the text — LLMs sometimes
    # close a fence they never opened.
    text = re.sub(r"^```\w*\s*$", "", text, flags=re.MULTILINE).strip()

    m = _FRONTMATTER_RE.match(text)
    if m:
        fm_text, body = m.group(1), m.group(2).strip()
    else:
        # Fall back to bare-frontmatter mode
        bm = _BARE_FRONTMATTER_RE.match(text)
        if not bm:
            return None
        fm_text = bm.group(1).strip()
        body = bm.group(2).strip()

    meta: dict[str, Any] = {}
    for line in fm_text.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if v.startswith("[") and v.endswith("]"):
            v = [x.strip().strip('"').strip("'") for x in v[1:-1].split(",") if x.strip()]
        meta[k] = v

    required = ("name", "description", "agents")
    if not all(k in meta and meta[k] for k in required):
        return None
    if not body:
        return None
    # Kebab-case enforcement on name
    meta["name"] = _slugify(str(meta["name"]))
    return meta, body


# ── Entry point ─────────────────────────────────────────────────────────────

def _append_audit(entry: dict) -> None:
    try:
        with _AUDIT_LOG.open("a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        pass


async def maybe_create_skill(
    agent_name: str,
    task: str,
    tools_called: list[str],
    tool_args: list[dict] | None = None,
    final_result: str = "",
    success: bool = True,
) -> str | None:
    """Try to write a new SKILL.md if the trace warrants it.

    Returns the path of the created skill, or None if nothing was created
    (dedup, too few tool calls, LLM unavailable, validation failed, etc).
    """
    # Import locally — these are hot paths, don't pay import cost every call
    from friday.skills.loader import discover, reload as reload_skills

    if not success:
        return None
    if not tools_called or len(tools_called) < MIN_TOOL_CALLS:
        return None
    if not task or len(task.strip()) < 8:
        return None

    digest = _trace_digest(task, tools_called, tool_args or [], final_result)
    raw = await _draft_skill(agent_name, digest)
    if not raw:
        return None
    parsed = _parse_and_validate(raw)
    if not parsed:
        log.info("Autoskill: draft failed validation, discarded")
        return None
    meta, body = parsed

    # Dedup check: does an existing skill already cover this?
    existing = discover()
    if _is_already_covered(str(meta.get("description", "")), existing):
        _append_audit({
            "ts": datetime.utcnow().isoformat() + "Z",
            "outcome": "skipped_duplicate",
            "name": meta.get("name"),
            "description": meta.get("description"),
        })
        return None

    # Namespace autogenerated skills under auto_ so Travis can find / prune them.
    base_name = _slugify(str(meta.get("name") or "auto"))
    skill_dir_name = f"auto_{base_name}"
    target_dir = _USER_SKILLS_DIR / skill_dir_name
    # If name collision, add short hash
    if target_dir.exists():
        h = hashlib.sha1(digest.encode()).hexdigest()[:6]
        target_dir = _USER_SKILLS_DIR / f"{skill_dir_name}_{h}"
    target_dir.mkdir(parents=True, exist_ok=True)

    # Build the final SKILL.md. Normalise frontmatter we trust, then append body.
    agents_field = meta.get("agents")
    if isinstance(agents_field, list):
        agents_str = "[" + ", ".join(agents_field) + "]"
    else:
        agents_str = str(agents_field)

    skill_md = (
        "---\n"
        f"name: {meta['name']}\n"
        f"description: {str(meta['description']).strip()}\n"
        f"agents: {agents_str}\n"
        f"created: {datetime.utcnow().isoformat()}Z\n"
        f"source: autogenerated\n"
        f"source_agent: {agent_name}\n"
        "---\n\n"
        f"{body}\n"
    )
    skill_path = target_dir / "SKILL.md"
    try:
        skill_path.write_text(skill_md)
    except Exception as e:
        log.warning("Autoskill write failed: %s", e)
        return None

    # Refresh the loader cache so the selector sees it immediately.
    try:
        reload_skills()
    except Exception:
        pass

    log.info("Autoskill CREATED: %s — %s", meta["name"], skill_path)
    _append_audit({
        "ts": datetime.utcnow().isoformat() + "Z",
        "outcome": "created",
        "name": meta["name"],
        "description": meta["description"],
        "agent": agent_name,
        "path": str(skill_path),
        "tool_count": len(tools_called),
    })
    return str(skill_path)


def schedule(
    agent_name: str, task: str, tools_called: list[str],
    tool_args: list[dict] | None = None, final_result: str = "",
    success: bool = True,
) -> None:
    """Fire-and-forget wrapper. Safe to call from any event loop context."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(maybe_create_skill(
            agent_name, task, tools_called, tool_args,
            final_result, success,
        ))
    except RuntimeError:
        # No running loop (e.g. called from a sync thread) — spin one up.
        import threading
        def _runner():
            asyncio.run(maybe_create_skill(
                agent_name, task, tools_called, tool_args,
                final_result, success,
            ))
        threading.Thread(target=_runner, daemon=True,
                         name="friday-skill-creator").start()
