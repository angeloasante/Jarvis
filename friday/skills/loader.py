"""Skill Loader — discovers and loads SKILL.md files for agents.

Skills are markdown instruction files that tell agents HOW to think.
Two directories scanned:
  1. friday/skills/     — shipped with repo (generic)
  2. ~/.friday/skills/  — personal (gitignored, user-specific)

Each skill is a folder with a SKILL.md file:
  friday/skills/web_research/SKILL.md
  ~/.friday/skills/my_custom/SKILL.md

SKILL.md format (same as OpenClaw/ClawHub):
  ---
  name: skill-name
  description: What this skill does (used for matching)
  agents: [research_agent, job_agent]   # which agents load this
  ---
  # Instructions
  Markdown body with instructions for the agent.
"""

import re
import logging
from pathlib import Path

log = logging.getLogger("friday.skills")

# Skill directories
_REPO_SKILLS = Path(__file__).parent  # friday/skills/
_USER_SKILLS = Path.home() / ".friday" / "skills"

# Cache
_skills: dict[str, dict] | None = None


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from a SKILL.md file. Returns (metadata, body)."""
    if not text.startswith("---"):
        return {}, text

    end = text.find("---", 3)
    if end == -1:
        return {}, text

    frontmatter = text[3:end].strip()
    body = text[end + 3:].strip()

    # Simple YAML parsing (no dependency needed for our format)
    meta = {}
    for line in frontmatter.splitlines():
        line = line.strip()
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            # Parse lists: [a, b, c]
            if value.startswith("[") and value.endswith("]"):
                value = [v.strip().strip('"').strip("'") for v in value[1:-1].split(",")]
            meta[key] = value

    return meta, body


def discover() -> dict[str, dict]:
    """Discover all skills from both directories. Returns {name: {meta, body, path}}."""
    global _skills
    if _skills is not None:
        return _skills

    skills = {}

    for skills_dir in [_REPO_SKILLS, _USER_SKILLS]:
        if not skills_dir.exists():
            continue

        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue

            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue

            try:
                text = skill_file.read_text()
                meta, body = _parse_frontmatter(text)
                name = meta.get("name", skill_dir.name)

                skills[name] = {
                    "meta": meta,
                    "body": body,
                    "path": str(skill_file),
                    "name": name,
                    "description": meta.get("description", ""),
                    "agents": meta.get("agents", []),
                }

                # User skills override repo skills with same name
                log.debug(f"Skill loaded: {name} from {skill_file}")

            except Exception as e:
                log.warning(f"Failed to load skill {skill_dir}: {e}")

    _skills = skills
    log.info(f"Loaded {len(skills)} skills")
    return skills


def get_skills_for_agent(agent_name: str) -> list[dict]:
    """Get all skills that apply to a specific agent."""
    all_skills = discover()
    matched = []

    for name, skill in all_skills.items():
        agents = skill.get("agents", [])
        if not agents or agent_name in agents or "all" in agents:
            matched.append(skill)

    return matched


def build_skill_context(agent_name: str) -> str:
    """Build a combined skill instruction block for an agent's system prompt."""
    skills = get_skills_for_agent(agent_name)
    if not skills:
        return ""

    parts = []
    for skill in skills:
        parts.append(f"## Skill: {skill['name']}\n{skill['body']}")

    return "\n\n---\n\n".join(parts)


def reload():
    """Force reload all skills (call after adding/editing skills at runtime)."""
    global _skills
    _skills = None
    return discover()
