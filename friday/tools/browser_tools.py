"""Browser automation tools — navigate, screenshot, click, fill forms.

Uses Playwright with a persistent browser profile so logins are remembered.
Install: uv add playwright && uv run playwright install chromium
"""

import asyncio
import base64
from pathlib import Path
from typing import Optional

from friday.core.types import ToolResult, ToolError, ErrorCode, Severity

# Persistent browser profile — cookies and sessions survive between runs
BROWSER_DATA_DIR = str(Path.home() / ".friday" / "browser_data")

# Global browser context and page — reused across calls
_playwright = None
_context = None
_page = None


async def _get_page():
    """Lazy-init browser with persistent context. Sessions/cookies are saved."""
    global _playwright, _context, _page

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright not installed. Run: uv add playwright && uv run playwright install chromium"
        )

    if not _context:
        Path(BROWSER_DATA_DIR).mkdir(parents=True, exist_ok=True)
        _playwright = await async_playwright().start()
        # Use system Chrome (not Playwright's Chromium) — looks and feels like real Chrome.
        # Persistent profile saves cookies/sessions between runs so logins stick.
        _context = await _playwright.chromium.launch_persistent_context(
            user_data_dir=BROWSER_DATA_DIR,
            channel="chrome",  # Use installed Google Chrome
            headless=False,
            viewport={"width": 1280, "height": 800},
            locale="en-GB",
            timezone_id="Europe/London",
        )

    if not _page or _page.is_closed():
        pages = _context.pages
        _page = pages[0] if pages else await _context.new_page()

    return _page


# Common login page indicators
LOGIN_INDICATORS = [
    "sign in", "log in", "login", "signin",
    "username", "password", "email address",
    "forgot password", "create account", "sign up",
    "authentication", "sso", "single sign-on",
]


async def _detect_login_page(page) -> bool:
    """Check if the current page is a login/authentication page."""
    try:
        # Check URL patterns
        url_lower = page.url.lower()
        login_url_parts = ["login", "signin", "sign-in", "auth", "sso", "accounts"]
        if any(part in url_lower for part in login_url_parts):
            return True

        # Check page content for login indicators
        body_text = await page.inner_text("body")
        body_lower = body_text.lower()[:3000]  # Only check first 3000 chars
        matches = sum(1 for indicator in LOGIN_INDICATORS if indicator in body_lower)
        # Need at least 3 matches to be confident it's a login page
        return matches >= 3
    except Exception:
        return False


# Selectors/text that trigger safety confirmation
DANGEROUS_ACTIONS = [
    "submit", "pay", "confirm", "delete", "remove",
    "purchase", "buy", "checkout", "place order",
    "send", "transfer", "authorize",
]


async def browser_navigate(
    url: str,
    wait_for: str = "load",
    timeout: int = 30000,
) -> ToolResult:
    """Navigate to a URL. Returns page title and final URL."""
    try:
        page = await _get_page()

        response = await page.goto(
            url,
            wait_until=wait_for,
            timeout=timeout,
        )

        is_login = await _detect_login_page(page)

        data = {
            "url": page.url,
            "title": await page.title(),
            "status_code": response.status if response else None,
        }

        if is_login:
            data["login_required"] = True
            data["message"] = (
                "This page requires login. Travis can log in manually in the browser window — "
                "the session will be saved for future use. Call browser_wait_for_login() to wait, "
                "or browser_screenshot() to capture the current state."
            )

        return ToolResult(success=True, data=data)
    except RuntimeError as e:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.CONFIG_MISSING,
                message=str(e),
                severity=Severity.HIGH,
                recoverable=False,
            ),
        )
    except Exception as e:
        err_str = str(e).lower()
        if "timeout" in err_str:
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.TIMEOUT,
                    message=f"Navigation timed out for {url}",
                    severity=Severity.MEDIUM,
                    recoverable=True,
                    retry_after=5,
                ),
            )
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.NETWORK_ERROR,
                message=f"Navigation failed: {e}",
                severity=Severity.MEDIUM,
                recoverable=True,
            ),
        )


async def browser_screenshot(
    full_page: bool = False,
    selector: str = None,
    save_path: str = None,
) -> ToolResult:
    """Take a screenshot of the current browser page.

    Use before clicking to see what's on screen.
    Optionally target a specific element with a CSS selector.
    """
    try:
        page = await _get_page()

        from pathlib import Path
        save_dir = Path.home() / "Downloads" / "friday_screenshots"
        save_dir.mkdir(parents=True, exist_ok=True)

        if not save_path:
            from datetime import datetime
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = str(save_dir / f"browser_{ts}.png")

        if selector:
            element = await page.query_selector(selector)
            if not element:
                return ToolResult(
                    success=False,
                    error=ToolError(
                        code=ErrorCode.NOT_FOUND,
                        message=f"Element not found: {selector}",
                        severity=Severity.LOW,
                        recoverable=False,
                    ),
                )
            await element.screenshot(path=save_path)
        else:
            await page.screenshot(path=save_path, full_page=full_page)

        return ToolResult(
            success=True,
            data={
                "saved_path": save_path,
                "current_url": page.url,
                "page_title": await page.title(),
            },
        )
    except RuntimeError as e:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.CONFIG_MISSING,
                message=str(e),
                severity=Severity.HIGH,
                recoverable=False,
            ),
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=f"Screenshot failed: {e}",
                severity=Severity.MEDIUM,
                recoverable=True,
            ),
        )


async def browser_click(
    selector: str,
    confirm_dangerous: bool = False,
    wait_for_navigation: bool = False,
) -> ToolResult:
    """Click an element on the page.

    Safety: buttons with text like 'pay', 'delete', 'submit' need confirm_dangerous=True.
    """
    selector_lower = selector.lower()
    is_dangerous = any(d in selector_lower for d in DANGEROUS_ACTIONS)

    if is_dangerous and not confirm_dangerous:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.VALIDATION_ERROR,
                message=f"Dangerous click: '{selector}'. Set confirm_dangerous=True after Travis confirms.",
                severity=Severity.HIGH,
                recoverable=True,
                context={"selector": selector},
            ),
        )

    try:
        page = await _get_page()

        if wait_for_navigation:
            async with page.expect_navigation():
                await page.click(selector)
        else:
            await page.click(selector)

        return ToolResult(
            success=True,
            data={
                "selector": selector,
                "clicked": True,
                "current_url": page.url,
            },
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.NOT_FOUND,
                message=f"Could not click '{selector}': {e}",
                severity=Severity.MEDIUM,
                recoverable=False,
            ),
        )


async def browser_fill(
    selector: str,
    value: str,
    clear_first: bool = True,
) -> ToolResult:
    """Fill a form field in the browser."""
    try:
        page = await _get_page()

        await page.wait_for_selector(selector, timeout=5000)

        if clear_first:
            await page.fill(selector, "")

        await page.fill(selector, value)

        return ToolResult(
            success=True,
            data={
                "selector": selector,
                "filled": True,
                "value_length": len(value),
            },
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.NOT_FOUND,
                message=f"Could not fill '{selector}': {e}",
                severity=Severity.MEDIUM,
                recoverable=False,
            ),
        )


async def browser_get_text(selector: str = "body") -> ToolResult:
    """Extract text content from an element (default: entire page body).

    Useful for reading page content without a full screenshot.
    """
    try:
        page = await _get_page()

        element = await page.query_selector(selector)
        if not element:
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Element not found: {selector}",
                    severity=Severity.LOW,
                    recoverable=False,
                ),
            )

        text = await element.inner_text()
        # Truncate for the 9B model
        if len(text) > 5000:
            text = text[:5000] + "\n... (truncated)"

        return ToolResult(
            success=True,
            data={
                "text": text,
                "selector": selector,
                "url": page.url,
            },
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=f"Failed to get text: {e}",
                severity=Severity.LOW,
                recoverable=True,
            ),
        )


async def browser_wait_for_login(timeout: int = 120) -> ToolResult:
    """Wait for Travis to log in manually in the browser window.

    Watches the page URL — when it changes away from the login page, login is complete.
    The persistent browser profile saves the session for future use.
    """
    try:
        page = await _get_page()
        login_url = page.url

        # Poll every 2 seconds until the URL changes or timeout
        elapsed = 0
        while elapsed < timeout:
            await asyncio.sleep(2)
            elapsed += 2
            current_url = page.url
            if current_url != login_url:
                # URL changed — login likely succeeded
                is_still_login = await _detect_login_page(page)
                if not is_still_login:
                    return ToolResult(
                        success=True,
                        data={
                            "logged_in": True,
                            "url": current_url,
                            "title": await page.title(),
                            "message": "Login successful. Session saved — won't need to log in again.",
                        },
                    )

        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.TIMEOUT,
                message=f"Login wait timed out after {timeout}s. Travis may not have logged in yet.",
                severity=Severity.LOW,
                recoverable=True,
            ),
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=str(e),
                severity=Severity.MEDIUM,
                recoverable=True,
            ),
        )


async def browser_close() -> ToolResult:
    """Close the browser. Sessions are saved in the persistent profile."""
    global _playwright, _context, _page

    try:
        if _context:
            await _context.close()
            _context = None
            _page = None
        if _playwright:
            await _playwright.stop()
            _playwright = None
        return ToolResult(success=True, data={"closed": True, "session_saved": True})
    except Exception as e:
        _context = None
        _page = None
        _playwright = None
        return ToolResult(success=True, data={"closed": True, "note": str(e)})


# ── Tool Schemas ─────────────────────────────────────────────────────────────

TOOL_SCHEMAS = {
    "browser_navigate": {
        "fn": browser_navigate,
        "schema": {
            "type": "function",
            "function": {
                "name": "browser_navigate",
                "description": "Navigate browser to a URL. Returns page title and status code.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to navigate to"},
                        "wait_for": {
                            "type": "string",
                            "enum": ["load", "networkidle", "domcontentloaded"],
                            "description": "Wait condition (default: load)",
                        },
                    },
                    "required": ["url"],
                },
            },
        },
    },
    "browser_screenshot": {
        "fn": browser_screenshot,
        "schema": {
            "type": "function",
            "function": {
                "name": "browser_screenshot",
                "description": "Screenshot the current browser page. Always do this before clicking.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "full_page": {"type": "boolean", "description": "Capture full scrollable page (default false)"},
                        "selector": {"type": "string", "description": "CSS selector to screenshot a specific element"},
                    },
                    "required": [],
                },
            },
        },
    },
    "browser_click": {
        "fn": browser_click,
        "schema": {
            "type": "function",
            "function": {
                "name": "browser_click",
                "description": "Click an element on the page. Dangerous buttons (pay, delete, submit) need confirm_dangerous=True.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string", "description": "CSS selector or text to click"},
                        "confirm_dangerous": {"type": "boolean", "description": "Required for pay/delete/submit buttons"},
                        "wait_for_navigation": {"type": "boolean", "description": "Wait for page navigation after click"},
                    },
                    "required": ["selector"],
                },
            },
        },
    },
    "browser_fill": {
        "fn": browser_fill,
        "schema": {
            "type": "function",
            "function": {
                "name": "browser_fill",
                "description": "Fill a form field in the browser.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string", "description": "CSS selector of the input field"},
                        "value": {"type": "string", "description": "Text to fill in"},
                    },
                    "required": ["selector", "value"],
                },
            },
        },
    },
    "browser_get_text": {
        "fn": browser_get_text,
        "schema": {
            "type": "function",
            "function": {
                "name": "browser_get_text",
                "description": "Extract text content from a page element. Default: entire page body.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string", "description": "CSS selector (default: body)"},
                    },
                    "required": [],
                },
            },
        },
    },
    "browser_wait_for_login": {
        "fn": browser_wait_for_login,
        "schema": {
            "type": "function",
            "function": {
                "name": "browser_wait_for_login",
                "description": "Wait for Travis to log in manually in the browser. Watches for URL change. Session is saved permanently.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "timeout": {"type": "integer", "description": "Max seconds to wait (default 120)"},
                    },
                    "required": [],
                },
            },
        },
    },
    "browser_close": {
        "fn": browser_close,
        "schema": {
            "type": "function",
            "function": {
                "name": "browser_close",
                "description": "Close the browser to free resources.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
    },
}
