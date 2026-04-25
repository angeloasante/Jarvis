"""Thin async wrapper around the Firecrawl REST API.

Two endpoints we care about:
  POST /v2/search  — search + optional inline scrape (saves a fetch_page call)
  POST /v2/scrape  — clean markdown extraction of a single URL

Cost model (2 credits = 1 search request, +1 per result if scraping inline):
  - 500 free credits one-off (no card) → ~250 plain searches OR ~70
    searches-with-scrape OR ~500 plain page-scrapes.
  - Paid: $83 per 100k credits (~$0.83 per 1k searches without scrape).

We hit Firecrawl directly via httpx — no extra dep — so the rest of the
codebase stays portable without adding `firecrawl-py` as a dependency.
"""

from __future__ import annotations

import os
import logging
from typing import Any

import httpx

# Triggers config.py's _load_layered_env so FIRECRAWL_API_KEY in
# ~/Friday/.env is visible even when this module is imported standalone.
from friday.core import config  # noqa: F401

log = logging.getLogger("friday.tools.firecrawl")

_BASE = "https://api.firecrawl.dev"
SEARCH_PATH = "/v2/search"
SCRAPE_PATH = "/v2/scrape"


def _api_key() -> str:
    return os.getenv("FIRECRAWL_API_KEY", "").strip()


def is_configured() -> bool:
    return bool(_api_key())


async def search(
    query: str,
    limit: int = 5,
    with_content: bool = False,
    *,
    timeout: float = 25.0,
) -> dict[str, Any]:
    """Run a Firecrawl search.

    Args:
        query:        what to search for.
        limit:        number of results to return (1-20 typical).
        with_content: if True, ask Firecrawl to scrape each result page
                      and return the markdown inline. Costs more credits
                      (+1 per result) but eliminates a separate
                      ``fetch_page`` call later.

    Returns:
        Normalised dict shaped like ``{"results": [{title, url, content,
        score}], "answer": ""}`` — same surface as Tavily so callers
        don't need to branch.

    Raises:
        Httpx / network errors propagate. Caller decides whether to retry
        or fall through to the next provider in the chain.
    """
    if not _api_key():
        raise RuntimeError("FIRECRAWL_API_KEY not set")

    body: dict[str, Any] = {
        "query": query,
        "limit": min(max(limit, 1), 20),
    }
    if with_content:
        body["scrapeOptions"] = {"formats": ["markdown"]}

    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(
            _BASE + SEARCH_PATH,
            json=body,
            headers={
                "Authorization": f"Bearer {_api_key()}",
                "Content-Type": "application/json",
            },
        )
        r.raise_for_status()
        payload = r.json()

    if not payload.get("success"):
        raise RuntimeError(f"Firecrawl search returned success=false: {payload}")

    raw = payload.get("data") or []
    # Some payloads bucket by source: {"web": [...], "news": [...]}
    if isinstance(raw, dict):
        flat: list[dict] = []
        for bucket in ("web", "news", "images"):
            flat.extend(raw.get(bucket) or [])
        raw = flat

    results = []
    for item in raw:
        # Firecrawl's `description` is the snippet; `markdown` is the
        # full page body when scrapeOptions was set. Fold the markdown
        # into ``content`` if present so callers get the richer data
        # transparently — the schema stays Tavily-compatible.
        content = item.get("markdown") or item.get("description") or ""
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "content": content,
            "score": None,
        })

    return {"answer": "", "results": results}


async def scrape(
    url: str,
    *,
    formats: list[str] | None = None,
    timeout: float = 25.0,
) -> dict[str, Any]:
    """Scrape a single URL into clean markdown via Firecrawl.

    Returns:
        Dict with ``markdown``, ``html`` (if requested), ``title``,
        ``description``, ``status_code``. Falsy ``markdown`` means the
        page was empty / blocked / Firecrawl couldn't extract.
    """
    if not _api_key():
        raise RuntimeError("FIRECRAWL_API_KEY not set")

    body = {
        "url": url,
        "formats": formats or ["markdown"],
    }

    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(
            _BASE + SCRAPE_PATH,
            json=body,
            headers={
                "Authorization": f"Bearer {_api_key()}",
                "Content-Type": "application/json",
            },
        )
        r.raise_for_status()
        payload = r.json()

    if not payload.get("success"):
        raise RuntimeError(f"Firecrawl scrape returned success=false: {payload}")

    data = payload.get("data") or {}
    metadata = data.get("metadata") or {}
    return {
        "markdown": data.get("markdown") or "",
        "html": data.get("html") or "",
        "links": data.get("links") or [],
        "title": metadata.get("title") or "",
        "description": metadata.get("description") or "",
        "status_code": metadata.get("statusCode"),
    }
