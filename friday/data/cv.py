"""CV data loader.

As of 0.4 the CV lives **inside** ``~/Friday/user.json`` under the ``cv`` key,
so everything FRIDAY knows about the user is in one file. This module keeps
exporting ``CV`` as a plain dict for backwards compatibility with older
imports (``from friday.data.cv import CV``).

If ``user.json`` has no CV yet, we assemble a minimal scaffold from the
identity fields so callers that expect the shape don't crash.
"""

from __future__ import annotations

import logging

from friday.core.user_config import USER

log = logging.getLogger(__name__)


def _scaffold_from_user() -> dict:
    """Empty-but-valid CV assembled from identity fields."""
    first, _, last = (USER.name.partition(" ")) if USER.name else ("", "", "")
    return {
        "name": USER.name or "",
        "first_name": first or USER.name,
        "last_name": last,
        "title": "",
        "contact": {
            "email": USER.email,
            "phone": USER.phone,
            "location": USER.location,
            "github": f"github.com/{USER.github}" if USER.github else "",
            "linkedin": "",
            "portfolio": USER.website,
        },
        "status": {},
        "summary": USER.bio or "",
        "experience": [],
        "education": [],
        "skills": [],
        "projects": [],
    }


def _load() -> dict:
    return USER.cv if USER.cv else _scaffold_from_user()


CV: dict = _load()


def reload() -> dict:
    """Re-read from the current USER config. Called by user_config.reload()."""
    global CV
    CV = _load()
    return CV
