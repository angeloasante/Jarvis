"""Web tools — three-tier search cascade and content fetching.

Search:  Tavily → Firecrawl → DuckDuckGo
Fetch:   Firecrawl → raw httpx → Playwright (for JS-heavy pages)

The cascade auto-promotes the first provider that succeeds. When a
provider 429s, plan-limits, or returns nothing, the next one in line
is tried. DDGS is always reachable (no key required) so search_web is
*never* fully unavailable when there's an internet connection.
"""

import logging
import os
import re
import httpx
from tavily import TavilyClient
from friday.core.types import ToolResult, ToolError, ErrorCode, Severity
import friday.core.config  # noqa: F401 — ensures .env is loaded before we read keys

# Load from env
_tavily: TavilyClient | None = None


def _get_tavily() -> TavilyClient | None:
    """Return a Tavily client, or None if no key is configured."""
    global _tavily
    if _tavily is None:
        key = os.environ.get("TAVILY_API_KEY", "")
        if not key:
            return None
        _tavily = TavilyClient(api_key=key)
    return _tavily


async def search_web(query: str, num_results: int = 5) -> ToolResult:
    """Search the web with a three-tier provider cascade.

    Order:
        1. **Tavily** (primary) — paid, AI-tuned, includes a synthesised
           ``answer`` field. Skipped silently if key not set.
        2. **Firecrawl** (middle) — paid (cheap), good Google-style
           results. Triggered when Tavily errors or returns nothing.
           500 free credits one-off.
        3. **DuckDuckGo** (final) — free, no key, always available as a
           safety net via the ``ddgs`` library.

    Each provider returns the same shape so callers don't branch:
        {"answer": str, "results": [{"title", "url", "content", "score"}]}
    """
    log = logging.getLogger("friday.tools.web")
    last_error: Exception | None = None

    # ── 1. Tavily ────────────────────────────────────────────────────────
    client = _get_tavily()
    if client is not None:
        try:
            response = client.search(
                query=query,
                max_results=min(num_results, 3),
                search_depth="advanced",
                include_answer=True,
                include_raw_content=False,
            )
            results = [{
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", ""),
                "score": r.get("score", 0),
            } for r in response.get("results", [])]
            if results:
                return ToolResult(
                    success=True,
                    data={
                        "answer": response.get("answer", ""),
                        "results": results,
                    },
                    metadata={"query": query, "count": len(results),
                              "provider": "tavily"},
                )
            # Empty results — try the next provider
            log.info("search_web: Tavily returned 0 results — trying Firecrawl")
        except Exception as e:
            last_error = e
            msg = str(e).lower()
            if "plan" in msg or "usage limit" in msg or "forbidden" in msg:
                log.warning(":: Tavily plan limit reached — routing to Firecrawl")
            else:
                log.warning(":: Tavily failed (%s) — routing to Firecrawl",
                            type(e).__name__)

    # ── 2. Firecrawl ─────────────────────────────────────────────────────
    try:
        from friday.tools.firecrawl_client import is_configured as _fc_ok, search as _fc_search
        if _fc_ok():
            payload = await _fc_search(query, limit=min(num_results, 5))
            results = payload.get("results", [])
            if results:
                return ToolResult(
                    success=True,
                    data={"answer": "", "results": results},
                    metadata={"query": query, "count": len(results),
                              "provider": "firecrawl"},
                )
            log.info("search_web: Firecrawl returned 0 results — trying DDGS")
    except Exception as e:
        last_error = e
        log.warning(":: Firecrawl failed (%s) — routing to DDGS",
                    type(e).__name__)

    # ── 3. DuckDuckGo (always available — no key) ────────────────────────
    try:
        from ddgs import DDGS
        results = []
        with DDGS() as d:
            for r in d.text(query, max_results=min(num_results, 5)):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href") or r.get("url", ""),
                    "content": r.get("body") or "",
                    "score": None,
                })
        if results:
            return ToolResult(
                success=True,
                data={"answer": "", "results": results},
                metadata={"query": query, "count": len(results),
                          "provider": "duckduckgo"},
            )
    except Exception as e:
        last_error = e

    # All three failed
    return ToolResult(
        success=False,
        error=ToolError(
            code=ErrorCode.NETWORK_ERROR,
            message=(f"All web search providers failed: "
                     f"{type(last_error).__name__ if last_error else 'unknown'}"),
            severity=Severity.MEDIUM,
            recoverable=True,
        ),
    )


async def fetch_page(url: str) -> ToolResult:
    """Fetch a web page → clean text. Three-tier fallback.

    1. **Firecrawl** (primary if configured) — handles JS-heavy pages
       server-side, returns clean markdown without us spinning up
       Playwright. Costs 1 credit per page.
    2. **httpx + regex** (free fallback) — fast, works for static pages.
       The naive HTML stripper here misses semantic structure but is
       fine for plain articles.
    3. **Playwright** (browser render) — kicked in when (1) is unavailable
       AND the (2) fallback returns a JS-only shell.
    """
    log = logging.getLogger("friday.tools.web")

    # ── 1. Firecrawl primary ────────────────────────────────────────────
    try:
        from friday.tools.firecrawl_client import is_configured as _fc_ok, scrape as _fc_scrape
        if _fc_ok():
            data = await _fc_scrape(url)
            md = data.get("markdown", "")
            if md and len(md) > 100:
                truncated = md[:8000]
                return ToolResult(
                    success=True,
                    data=truncated,
                    metadata={"url": url, "length": len(truncated),
                              "provider": "firecrawl",
                              "title": data.get("title", "")},
                )
            log.debug("Firecrawl scrape thin/empty for %s — falling back", url)
    except Exception as e:
        log.warning(":: Firecrawl scrape failed (%s) — falling back to httpx",
                    type(e).__name__)

    # ── 2. httpx + regex fallback ───────────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()

            text = re.sub(r"<script[^>]*>.*?</script>", "", resp.text, flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            text = text[:5000]

            # Detect JS-only pages (React/SPA shells with no real content)
            js_shells = ["you need to enable javascript", "enable javascript to run this app",
                         "noscript", "__next_data__", "window.__remixContext"]
            if len(text) < 200 or any(s in text.lower() for s in js_shells):
                return await _fetch_with_browser(url)

            return ToolResult(
                success=True,
                data=text,
                metadata={"url": url, "length": len(text), "provider": "httpx"},
            )
    except Exception as e:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.NETWORK_ERROR,
                message=str(e),
                severity=Severity.MEDIUM,
                recoverable=True,
            ),
        )


async def _fetch_with_browser(url: str) -> ToolResult:
    """Render a JS-heavy page with Playwright and extract text."""
    try:
        from friday.tools.browser_tools import browser_navigate, browser_get_text

        nav = await browser_navigate(url=url, timeout=15000)
        if not nav.success:
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.NETWORK_ERROR,
                message=f"Browser render failed: {nav.error}",
                severity=Severity.MEDIUM, recoverable=True))

        text_result = await browser_get_text()
        if text_result.success:
            text = text_result.data.get("text", "") if isinstance(text_result.data, dict) else str(text_result.data)
            text = text[:5000]
            return ToolResult(
                success=True,
                data=text,
                metadata={"url": url, "length": len(text), "rendered_with_browser": True},
            )

        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message="Browser rendered but couldn't extract text",
            severity=Severity.MEDIUM, recoverable=True))
    except ImportError:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message="Page requires JavaScript but browser tools not available",
            severity=Severity.MEDIUM, recoverable=True))


async def youtube_transcript(url: str) -> ToolResult:
    """Fetch YouTube video transcript + metadata via yt-dlp."""
    import asyncio, json, subprocess

    try:
        # Get video info + subtitle URLs
        proc = await asyncio.to_thread(
            lambda: subprocess.run(
                ["yt-dlp", "--write-auto-sub", "--sub-lang", "en",
                 "--skip-download", "--print-json", url],
                capture_output=True, text=True, timeout=30,
            )
        )

        if proc.returncode != 0:
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=f"yt-dlp failed: {proc.stderr[:200]}",
                severity=Severity.MEDIUM, recoverable=True))

        data = json.loads(proc.stdout)
        title = data.get("title", "")
        channel = data.get("uploader", "")
        duration = data.get("duration_string", "")
        views = data.get("view_count", 0)

        # Get subtitle text
        # Try manual subs first, then auto-generated
        subs = data.get("subtitles", {}).get("en") or data.get("automatic_captions", {}).get("en", [])

        transcript = ""
        if subs:
            # Find json3 format (easiest to parse)
            sub_url = None
            for s in subs:
                if s.get("ext") == "json3":
                    sub_url = s["url"]
                    break
            if not sub_url:
                sub_url = subs[0].get("url")

            if sub_url:
                import httpx
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(sub_url)
                    if resp.status_code == 200:
                        sub_data = resp.json()
                        # Extract text from json3 subtitle format
                        segments = sub_data.get("events", [])
                        lines = []
                        for seg in segments:
                            for s in seg.get("segs", []):
                                text = s.get("utf8", "").strip()
                                if text and text != "\n":
                                    lines.append(text)
                        transcript = " ".join(lines)

        if not transcript:
            # Fallback: try downloading .vtt directly
            proc2 = await asyncio.to_thread(
                lambda: subprocess.run(
                    ["yt-dlp", "--write-auto-sub", "--sub-lang", "en",
                     "--skip-download", "-o", "/tmp/yt_sub", url],
                    capture_output=True, text=True, timeout=30,
                )
            )
            import pathlib
            vtt = pathlib.Path("/tmp/yt_sub.en.vtt")
            if vtt.exists():
                lines = [l.strip() for l in vtt.read_text().splitlines()
                         if l.strip() and not l.startswith("WEBVTT") and not l.startswith("Kind:")
                         and not l.startswith("Language:") and not re.match(r"^\d{2}:", l)
                         and not re.match(r"^$", l)]
                transcript = " ".join(lines)
                vtt.unlink(missing_ok=True)

        # Truncate for LLM context
        if len(transcript) > 6000:
            transcript = transcript[:6000] + "... [truncated]"

        return ToolResult(
            success=True,
            data={
                "title": title,
                "channel": channel,
                "duration": duration,
                "views": views,
                "transcript": transcript or "No subtitles available for this video.",
                "has_transcript": bool(transcript),
            },
            metadata={"url": url},
        )

    except json.JSONDecodeError:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message="Failed to parse yt-dlp output",
            severity=Severity.MEDIUM, recoverable=True))
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=str(e),
            severity=Severity.MEDIUM, recoverable=True))


TOOL_SCHEMAS = {
    "search_web": {
        "fn": search_web,
        "schema": {
            "type": "function",
            "function": {
                "name": "search_web",
                "description": "Search the web using Tavily. Returns an AI-generated answer plus source results with titles, URLs, and content.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "num_results": {"type": "integer", "description": "Number of results (default 5)"},
                    },
                    "required": ["query"],
                },
            },
        },
    },
    "fetch_page": {
        "fn": fetch_page,
        "schema": {
            "type": "function",
            "function": {
                "name": "fetch_page",
                "description": "Fetch a web page and return its text content (HTML stripped). Auto-falls back to browser for JS-heavy sites. Use when you need the full page, not just search snippets.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to fetch"},
                    },
                    "required": ["url"],
                },
            },
        },
    },
    "youtube_transcript": {
        "fn": youtube_transcript,
        "schema": {
            "type": "function",
            "function": {
                "name": "youtube_transcript",
                "description": "Get the transcript/subtitles of a YouTube video. Use when asked to summarize, analyze, or answer questions about a YouTube video. Returns video title, channel, duration, and full transcript text.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "YouTube video URL"},
                    },
                    "required": ["url"],
                },
            },
        },
    },
}
