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
    """Fetch a web page and return its text content (stripped of HTML)."""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()

            text = re.sub(r"<script[^>]*>.*?</script>", "", resp.text, flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            text = text[:3000]

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
                "description": "Fetch a web page and return its text content (HTML stripped). Use when you need the full page, not just search snippets.",
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
}
