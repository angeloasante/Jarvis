"""Browser-extension tools — act in the user's *real* Chrome.

Complementary to ``friday/tools/browser_tools.py`` (Playwright). The LLM
should pick:

  - ``browser_ext_*``  — the user is already on the page, needs the
    user's logged-in session, the site fingerprints headless Chrome, or
    the user wants to *see* the AI work.
  - ``browser_*``      — headless / parallel / no-auth work.

If the extension isn't connected, every tool returns a graceful
ToolResult(success=False, ErrorCode.CONFIG_MISSING) with a message
telling the user to install the extension and run ``friday setup
browser-ext``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from friday.core.types import ToolResult, ToolError, ErrorCode, Severity
from friday.browser_ext.bridge import bridge

log = logging.getLogger("friday.tools.browser_ext")


def _not_connected_error() -> ToolResult:
    return ToolResult(success=False, error=ToolError(
        code=ErrorCode.CONFIG_MISSING,
        message=(
            "FRIDAY browser extension isn't connected. "
            "Install it (chrome://extensions → Load unpacked → "
            "extension/browser-bridge/) and paste your "
            "FRIDAY_BROWSER_EXT_TOKEN into the popup."
        ),
        severity=Severity.LOW,
        recoverable=True,
    ))


async def _send(action: str, metadata: dict | None = None,
                timeout: float = 15.0) -> ToolResult:
    if not bridge.is_connected():
        return _not_connected_error()
    try:
        result = await bridge.send_action(action, metadata or {}, timeout=timeout)
    except ConnectionError as e:
        return _not_connected_error()
    except asyncio.TimeoutError:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.NETWORK_ERROR,
            message=f"browser extension timed out on {action}",
            severity=Severity.MEDIUM, recoverable=True,
        ))
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.NETWORK_ERROR,
            message=f"{type(e).__name__}: {e}",
            severity=Severity.MEDIUM, recoverable=True,
        ))

    if not result.get("ok"):
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=result.get("error") or f"{action} failed",
            severity=Severity.LOW, recoverable=True,
        ))
    return ToolResult(success=True, data=result.get("data") or {})


# ── Tools ────────────────────────────────────────────────────────────────

async def browser_ext_navigate(url: str, tab_id: int = 0) -> ToolResult:
    """Open ``url`` in the user's active Chrome tab (or a specific tab_id)."""
    md: dict[str, Any] = {"url": url}
    if tab_id:
        md["tab_id"] = tab_id
    return await _send("navigate", md)


async def browser_ext_get_active_tab(include_text: bool = True) -> ToolResult:
    """Return the URL, title, and (optionally) the readable text of the
    user's currently focused tab. Use this when the user says
    *'fill the form on my screen'* or *'summarise what I'm reading'*."""
    return await _send("get_active_tab", {"include_text": include_text})


async def browser_ext_list_tabs() -> ToolResult:
    """List every tab open in the user's Chrome — id, url, title, active flag."""
    return await _send("list_tabs", {})


async def browser_ext_click(selector: str = "", text: str = "",
                              tab_id: int = 0) -> ToolResult:
    """Click an element. Pass either ``selector`` (CSS) or ``text``
    (visible link/button text). The element gets a brief highlight ring
    before the click so the user can see what FRIDAY is doing."""
    if not selector and not text:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.VALIDATION_ERROR,
            message="browser_ext_click needs selector or text",
            severity=Severity.LOW, recoverable=True,
        ))
    md = {"selector": selector, "text": text}
    if tab_id: md["tab_id"] = tab_id
    return await _send("click", md)


async def browser_ext_fill(selector: str, value: str,
                              tab_id: int = 0) -> ToolResult:
    """Type ``value`` into the input matched by ``selector``. Dispatches
    React/Vue-friendly input + change events so framework-driven inputs
    update correctly."""
    md = {"selector": selector, "value": value}
    if tab_id: md["tab_id"] = tab_id
    return await _send("fill", md)


async def browser_ext_get_text(selector: str = "", tab_id: int = 0) -> ToolResult:
    """Read the visible text of the page (or a specific element if
    ``selector`` is set). Strips scripts/styles/nav. Used by research
    agents on logged-in pages where Playwright can't reach."""
    md: dict[str, Any] = {"selector": selector}
    if tab_id: md["tab_id"] = tab_id
    return await _send("get_text", md)


async def browser_ext_scroll(x: int = 0, y: int = 0, by: bool = False,
                               tab_id: int = 0) -> ToolResult:
    """Scroll. ``by=False`` scrolls TO an absolute position; ``by=True``
    scrolls BY that much from the current position."""
    md: dict[str, Any] = {"x": x, "y": y, "by": by}
    if tab_id: md["tab_id"] = tab_id
    return await _send("scroll", md)


async def browser_ext_scan(label: str = "FRIDAY analysing page…",
                             duration_ms: int = 4000,
                             tab_id: int = 0) -> ToolResult:
    """Show the page-wide 'AI is reading' overlay — gradient frame +
    moving beam + small label pill. Auto-fades after ``duration_ms``.
    Cosmetic; no functional effect on the page."""
    md = {"label": label, "duration_ms": duration_ms}
    if tab_id: md["tab_id"] = tab_id
    return await _send("scanning_start", md)


async def browser_ext_highlight(selector: str = "", text: str = "",
                                  duration_ms: int = 1500,
                                  tab_id: int = 0) -> ToolResult:
    """Spotlight a specific element with a spinning gradient ring. Used
    automatically before clicks; can be called manually to draw the
    user's attention to something."""
    md = {"selector": selector, "text": text, "duration_ms": duration_ms}
    if tab_id: md["tab_id"] = tab_id
    return await _send("highlight", md)


async def browser_ext_status() -> ToolResult:
    """Diagnostic — connection state, extension version, open tab count."""
    return ToolResult(success=True, data=bridge.status())


# ── Tool registry ────────────────────────────────────────────────────────

TOOL_SCHEMAS = {
    "browser_ext_navigate": {
        "fn": browser_ext_navigate,
        "schema": {"type": "function", "function": {
            "name": "browser_ext_navigate",
            "description": (
                "Open a URL in the USER'S real Chrome tab (preserves logged-in "
                "sessions, cookies, MFA, password manager). Use when the user "
                "says 'open X for me' or job_agent needs to apply on a "
                "session-locked site like LinkedIn. NOT for headless research "
                "— that's browser_navigate."
            ),
            "parameters": {"type": "object", "properties": {
                "url": {"type": "string"},
                "tab_id": {"type": "integer",
                           "description": "Optional — use a specific tab; "
                                          "defaults to the active tab"},
            }, "required": ["url"]},
        }},
    },
    "browser_ext_get_active_tab": {
        "fn": browser_ext_get_active_tab,
        "schema": {"type": "function", "function": {
            "name": "browser_ext_get_active_tab",
            "description": (
                "Return the URL, title, and readable text of the tab the user "
                "is CURRENTLY LOOKING AT. Use this when the user says 'fill "
                "the form on my screen', 'summarise what I'm reading', "
                "'apply for this job' (referring to a tab they have open)."
            ),
            "parameters": {"type": "object", "properties": {
                "include_text": {"type": "boolean",
                                  "description": "Include the page's "
                                                  "readable text. Default true."},
            }, "required": []},
        }},
    },
    "browser_ext_list_tabs": {
        "fn": browser_ext_list_tabs,
        "schema": {"type": "function", "function": {
            "name": "browser_ext_list_tabs",
            "description": "List every tab open in the user's Chrome.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
    },
    "browser_ext_click": {
        "fn": browser_ext_click,
        "schema": {"type": "function", "function": {
            "name": "browser_ext_click",
            "description": (
                "Click an element in the user's real Chrome tab. Pass "
                "EITHER a CSS selector OR visible button/link text. "
                "Element gets a brief highlight ring before the click."
            ),
            "parameters": {"type": "object", "properties": {
                "selector": {"type": "string", "description": "CSS selector"},
                "text": {"type": "string", "description": "Visible link/button text"},
                "tab_id": {"type": "integer"},
            }, "required": []},
        }},
    },
    "browser_ext_fill": {
        "fn": browser_ext_fill,
        "schema": {"type": "function", "function": {
            "name": "browser_ext_fill",
            "description": (
                "Type a value into an input/textarea matched by a CSS "
                "selector. Works correctly with React/Vue/Angular inputs."
            ),
            "parameters": {"type": "object", "properties": {
                "selector": {"type": "string"},
                "value": {"type": "string"},
                "tab_id": {"type": "integer"},
            }, "required": ["selector", "value"]},
        }},
    },
    "browser_ext_get_text": {
        "fn": browser_ext_get_text,
        "schema": {"type": "function", "function": {
            "name": "browser_ext_get_text",
            "description": (
                "Read the readable text of the user's current tab (or a "
                "specific element). Use for logged-in pages where "
                "fetch_page can't reach (e.g. private dashboards, "
                "subscription content the user has open)."
            ),
            "parameters": {"type": "object", "properties": {
                "selector": {"type": "string", "description": "Optional CSS selector"},
                "tab_id": {"type": "integer"},
            }, "required": []},
        }},
    },
    "browser_ext_scroll": {
        "fn": browser_ext_scroll,
        "schema": {"type": "function", "function": {
            "name": "browser_ext_scroll",
            "description": "Scroll the page. by=true is relative, by=false is absolute.",
            "parameters": {"type": "object", "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "by": {"type": "boolean"},
                "tab_id": {"type": "integer"},
            }, "required": []},
        }},
    },
    "browser_ext_scan": {
        "fn": browser_ext_scan,
        "schema": {"type": "function", "function": {
            "name": "browser_ext_scan",
            "description": (
                "Show a page-wide 'AI is analysing' visual overlay on the "
                "user's tab — gradient frame, moving beam, label pill. "
                "Cosmetic — call before a long page-read to give the user "
                "feedback that FRIDAY is working."
            ),
            "parameters": {"type": "object", "properties": {
                "label": {"type": "string"},
                "duration_ms": {"type": "integer"},
                "tab_id": {"type": "integer"},
            }, "required": []},
        }},
    },
    "browser_ext_highlight": {
        "fn": browser_ext_highlight,
        "schema": {"type": "function", "function": {
            "name": "browser_ext_highlight",
            "description": (
                "Spotlight a specific element with a spinning gradient "
                "ring. Use to draw the user's attention before performing "
                "an action they should see."
            ),
            "parameters": {"type": "object", "properties": {
                "selector": {"type": "string"},
                "text": {"type": "string"},
                "duration_ms": {"type": "integer"},
                "tab_id": {"type": "integer"},
            }, "required": []},
        }},
    },
    "browser_ext_status": {
        "fn": browser_ext_status,
        "schema": {"type": "function", "function": {
            "name": "browser_ext_status",
            "description": "Show whether the FRIDAY browser extension is connected.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
    },
}
