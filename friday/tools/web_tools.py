"""Web tools — Tavily for search, httpx for raw page fetching."""

import os
import re
import httpx
from tavily import TavilyClient
from friday.core.types import ToolResult, ToolError, ErrorCode, Severity
import friday.core.config  # noqa: F401 — ensures .env is loaded before we read keys

# Load from env
_tavily: TavilyClient | None = None


def _get_tavily() -> TavilyClient:
    global _tavily
    if _tavily is None:
        key = os.environ.get("TAVILY_API_KEY", "")
        if not key:
            raise ValueError("TAVILY_API_KEY not set")
        _tavily = TavilyClient(api_key=key)
    return _tavily


async def search_web(query: str, num_results: int = 5) -> ToolResult:
    """Search the web using Tavily. Returns structured results with content."""
    try:
        client = _get_tavily()
        response = client.search(
            query=query,
            max_results=min(num_results, 3),
            search_depth="advanced",
            include_answer=True,
            include_raw_content=False,
        )

        results = []
        for r in response.get("results", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", ""),
                "score": r.get("score", 0),
            })

        return ToolResult(
            success=True,
            data={
                "answer": response.get("answer", ""),
                "results": results,
            },
            metadata={"query": query, "count": len(results)},
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


async def fetch_page(url: str) -> ToolResult:
    """Fetch a web page. Auto-falls back to browser rendering for JS-heavy sites."""
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
                metadata={"url": url, "length": len(text)},
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
