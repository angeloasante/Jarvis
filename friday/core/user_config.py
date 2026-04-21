"""User config loader for FRIDAY.

One file, one source of truth: ``~/Friday/user.json``.

It lives at the top level of the home directory (visible in Finder,
not a dotfile) because users need to actually see and edit it. Everything
FRIDAY knows about the user is here — identity, tone, slang, contact
aliases, CV, briefing watchlist — so the full picture loads with the model
on every call.

Usage:

    from friday.core.user_config import USER

    prompt = f"You are {USER.assistant_name}. {USER.possessive} AI."
    if USER.is_configured:
        prompt += f" {USER.name}: {USER.bio}."
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# Visible location — at the top level of the home directory, no dot prefix,
# so it shows up in Finder and `ls ~`.
FRIDAY_DIR = Path.home() / "Friday"
CONFIG_PATH = FRIDAY_DIR / "user.json"

# Legacy location (pre-0.4). Still read as a fallback so existing setups
# keep working; `friday init` and Settings UI writes always go to the new one.
_LEGACY_DIR = Path.home() / ".friday"
_LEGACY_CONFIG = _LEGACY_DIR / "user.json"
_LEGACY_CV = _LEGACY_DIR / "cv.json"


@dataclass
class UserConfig:
    """Loaded user profile + CV. All fields have safe empty defaults."""

    # Identity
    name: str = ""
    bio: str = ""
    location: str = ""
    country_code: str = "US"
    email: str = ""
    phone: str = ""
    github: str = ""
    website: str = ""

    # Voice / personality
    tone: str = ""
    slang: dict[str, str] = field(default_factory=dict)

    # Relationships + watchlists
    contact_aliases: dict[str, str] = field(default_factory=dict)
    briefing_watchlist: list[dict] = field(default_factory=list)

    # Full CV lives here too — used by job applications, CV PDF generation,
    # and injected into the LLM system prompt so every response is grounded
    # in who the user actually is.
    cv: dict = field(default_factory=dict)

    # Fixed — not user-editable. The assistant is always called FRIDAY.
    assistant_name: str = "FRIDAY"

    @property
    def is_configured(self) -> bool:
        """True once the user has set at least their name."""
        return bool(self.name.strip())

    @property
    def display_name(self) -> str:
        """Name to use in prompts. Falls back to 'the user' if unconfigured."""
        return self.name.strip() or "the user"

    @property
    def possessive(self) -> str:
        """Uniform `'s` — matches Chicago/AP style."""
        return f"{self.display_name}'s"

    def bio_line(self) -> str:
        """One-line bio for prompts. Empty string if unconfigured."""
        parts = [p for p in [self.bio, self.location] if p]
        return " — ".join(parts) if parts else ""


# ── Loading ──────────────────────────────────────────────────────────────────

_KNOWN_FIELDS = {f for f in UserConfig.__dataclass_fields__ if f != "assistant_name"}


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        log.warning("%s is malformed (%s) — ignoring", path, e)
        return {}
    except OSError:
        return {}


def _load_from_legacy() -> dict:
    """Read pre-0.4 ``~/.friday/user.json`` + ``~/.friday/cv.json`` as one dict."""
    merged: dict = {}
    if _LEGACY_CONFIG.exists():
        merged.update(_read_json(_LEGACY_CONFIG))
    if _LEGACY_CV.exists() and "cv" not in merged:
        merged["cv"] = _read_json(_LEGACY_CV)
    return merged


def _load() -> UserConfig:
    """Load from disk. Never raises — missing / malformed files yield defaults.

    Lookup order:
        1. ``~/Friday/user.json``   (new, visible)
        2. ``~/.friday/user.json`` + ``~/.friday/cv.json``  (legacy fallback)
    """
    if CONFIG_PATH.exists():
        raw = _read_json(CONFIG_PATH)
    else:
        raw = _load_from_legacy()
        if raw:
            log.debug("Loaded legacy ~/.friday config; run `friday init` to migrate.")

    if not raw:
        return UserConfig()

    return UserConfig(**{k: v for k, v in raw.items() if k in _KNOWN_FIELDS})


def reload() -> UserConfig:
    """Re-read the config from disk. Call after Settings UI writes."""
    global USER
    USER = _load()
    try:
        from friday.data import cv as cv_module
        cv_module.reload()
    except Exception:
        pass
    return USER


# Singleton — import this.
USER = _load()


# ── Writing ──────────────────────────────────────────────────────────────────

def _to_dict(cfg: UserConfig) -> dict:
    return {
        "name": cfg.name,
        "bio": cfg.bio,
        "location": cfg.location,
        "country_code": cfg.country_code,
        "email": cfg.email,
        "phone": cfg.phone,
        "github": cfg.github,
        "website": cfg.website,
        "tone": cfg.tone,
        "slang": cfg.slang,
        "contact_aliases": cfg.contact_aliases,
        "briefing_watchlist": cfg.briefing_watchlist,
        "cv": cfg.cv,
    }


def write(cfg: UserConfig) -> None:
    """Persist the full config to ``~/Friday/user.json``. Creates the dir if needed."""
    FRIDAY_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(_to_dict(cfg), indent=2))
    # chmod 600 — phone / email live in here.
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass
    reload()


def migrate_from_legacy() -> bool:
    """Copy legacy ``~/.friday/user.json`` + ``cv.json`` into the new single file.

    Returns True if a migration was performed, False if there was nothing to migrate
    or the new file already exists.
    """
    if CONFIG_PATH.exists():
        return False
    merged = _load_from_legacy()
    if not merged:
        return False
    FRIDAY_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(merged, indent=2))
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass
    reload()
    return True
