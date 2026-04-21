"""Browser automation tools — full browser control.

Navigate, screenshot, click, fill, type, check boxes, select dropdowns,
scroll, list elements, run JS, manage tabs — everything needed for
autonomous web interaction.

Default: Safari via AppleScript + JavaScript — uses YOUR actual Safari window
with all your existing cookies, sessions, saved passwords. No new windows,
no private mode, no login walls.

Fallback: Playwright Chromium (headless) — for when Safari isn't available.

Safari setup (one time):
  1. Safari → Settings → Advanced → Show features for web developers ✅
  2. Develop menu → Allow Remote Automation ✅
"""

import asyncio
import base64
import subprocess
from pathlib import Path
from typing import Optional

from friday.core.types import ToolResult, ToolError, ErrorCode, Severity

# Persistent Playwright profile (fallback only)
BROWSER_DATA_DIR = str(Path.home() / ".friday" / "browser_data")

# ── Safari via AppleScript (default) ────────────────────────────────────────
# Controls your ACTUAL Safari — no new windows, uses existing tabs + sessions.


async def _safari_applescript(script: str) -> str:
    """Run AppleScript and return stdout."""
    proc = await asyncio.create_subprocess_exec(
        "osascript", "-e", script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"AppleScript error: {err}")
    return stdout.decode("utf-8", errors="replace").strip()


async def _safari_js(script: str) -> str:
    """Execute JavaScript in Safari's current tab via AppleScript. Returns result as string."""
    # Escape for AppleScript string embedding
    escaped = script.replace("\\", "\\\\").replace('"', '\\"')
    applescript = f'tell application "Safari" to do JavaScript "{escaped}" in current tab of front window'
    return await _safari_applescript(applescript)


async def _safari_get_url() -> str:
    return await _safari_applescript('tell application "Safari" to get URL of current tab of front window')


async def _safari_get_title() -> str:
    return await _safari_applescript('tell application "Safari" to get name of current tab of front window')


def _safari_available() -> bool:
    """Check if Safari is running or can be launched."""
    try:
        result = subprocess.run(
            ["osascript", "-e", 'tell application "Safari" to get name of front window'],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


# ── Playwright fallback ─────────────────────────────────────────────────────

_playwright = None
_context = None
_page = None


async def _get_playwright_page():
    """Lazy-init Playwright Chromium with persistent context (fallback)."""
    global _playwright, _context, _page

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError(
            "Neither Safari nor Playwright available. "
            "Enable Safari: Safari → Settings → Advanced → Show features for web developers, "
            "then Develop → Allow Remote Automation. "
            "Or install Playwright: uv add playwright && uv run playwright install chromium"
        )

    if not _context:
        Path(BROWSER_DATA_DIR).mkdir(parents=True, exist_ok=True)
        _playwright = await async_playwright().start()
        _context = await _playwright.chromium.launch_persistent_context(
            user_data_dir=BROWSER_DATA_DIR,
            channel="chrome",
            headless=False,
            viewport={"width": 1280, "height": 800},
            locale="en-GB",
            timezone_id="Europe/London",
        )

    if not _page or _page.is_closed():
        pages = _context.pages
        _page = pages[0] if pages else await _context.new_page()

    return _page


# ── Detect which engine to use ──────────────────────────────────────────────

_engine = None  # "safari" or "playwright"


def _detect_engine() -> str:
    """Detect which browser engine to use. Safari (AppleScript) preferred."""
    global _engine
    if _engine:
        return _engine

    if _safari_available():
        _engine = "safari"
    else:
        _engine = "playwright"

    return _engine


# ── Common helpers ──────────────────────────────────────────────────────────

LOGIN_INDICATORS = [
    "sign in", "log in", "login", "signin",
    "username", "password", "email address",
    "forgot password", "create account", "sign up",
    "authentication", "sso", "single sign-on",
]

DANGEROUS_ACTIONS = [
    "submit", "pay", "confirm", "delete", "remove",
    "purchase", "buy", "checkout", "place order",
    "send", "transfer", "authorize",
]


async def _detect_login_safari() -> bool:
    """Check if current Safari page is a login page."""
    try:
        url_lower = (await _safari_get_url()).lower()
        login_url_parts = ["login", "signin", "sign-in", "auth", "sso", "accounts"]
        if any(part in url_lower for part in login_url_parts):
            return True
        body_text = await _safari_js("document.body.innerText.substring(0, 3000)")
        body_lower = (body_text or "").lower()
        matches = sum(1 for ind in LOGIN_INDICATORS if ind in body_lower)
        return matches >= 3
    except Exception:
        return False


async def _detect_login_playwright(page) -> bool:
    """Check if current Playwright page is a login page."""
    try:
        url_lower = page.url.lower()
        login_url_parts = ["login", "signin", "sign-in", "auth", "sso", "accounts"]
        if any(part in url_lower for part in login_url_parts):
            return True
        body_text = await page.inner_text("body")
        body_lower = body_text.lower()[:3000]
        matches = sum(1 for ind in LOGIN_INDICATORS if ind in body_lower)
        return matches >= 3
    except Exception:
        return False


# ── Tool implementations ────────────────────────────────────────────────────

async def browser_navigate(
    url: str,
    wait_for: str = "load",
    timeout: int = 30000,
) -> ToolResult:
    """Navigate to a URL. Uses Safari (your sessions) by default."""
    engine = _detect_engine()

    if engine == "safari":
        return await _safari_navigate(url, timeout)
    else:
        return await _playwright_navigate(url, wait_for, timeout)


async def _safari_navigate(url: str, timeout: int = 30000) -> ToolResult:
    try:
        # Navigate in the current tab of the front Safari window
        escaped_url = url.replace('"', '\\"')
        await _safari_applescript(f'tell application "Safari" to set URL of current tab of front window to "{escaped_url}"')
        await asyncio.sleep(2)  # Let page load

        current_url = await _safari_get_url()
        title = await _safari_get_title()

        # Check for login page
        url_lower = current_url.lower()
        login_url_parts = ["login", "signin", "sign-in", "auth", "sso", "accounts"]
        is_login = any(part in url_lower for part in login_url_parts)

        data = {
            "url": current_url,
            "title": title,
            "engine": "safari",
        }

        if is_login:
            data["login_required"] = True
            data["message"] = (
                "This page requires login. Safari has your saved sessions — "
                "log in manually and call browser_wait_for_login()."
            )

        return ToolResult(success=True, data=data)
    except Exception as e:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.NETWORK_ERROR,
                message=f"Safari navigation failed: {e}",
                severity=Severity.MEDIUM,
                recoverable=True,
            ),
        )


async def _playwright_navigate(url: str, wait_for: str = "load", timeout: int = 30000) -> ToolResult:
    try:
        page = await _get_playwright_page()
        response = await page.goto(url, wait_until=wait_for, timeout=timeout)
        is_login = await _detect_login_playwright(page)

        data = {
            "url": page.url,
            "title": await page.title(),
            "status_code": response.status if response else None,
            "engine": "playwright",
        }

        if is_login:
            data["login_required"] = True
            data["message"] = (
                "This page requires login. Travis can log in manually in the browser window — "
                "the session will be saved for future use."
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
    """Take a screenshot of the current browser page."""
    engine = _detect_engine()

    save_dir = Path.home() / "Downloads" / "friday_screenshots"
    save_dir.mkdir(parents=True, exist_ok=True)
    if not save_path:
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = str(save_dir / f"browser_{ts}.png")

    if engine == "safari":
        return await _safari_screenshot(save_path)
    else:
        return await _playwright_screenshot(save_path, full_page, selector)


async def _safari_screenshot(save_path: str) -> ToolResult:
    try:
        # Use screencapture on Safari's front window
        proc = await asyncio.create_subprocess_exec(
            "screencapture", "-x", "-l",
            # Capture the front window by getting its ID
            str(save_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        # Simpler: just capture the full screen and crop later, or use Safari's bounds
        # Actually, use the _capture_window approach from screen_tools
        from friday.tools.screen_tools import _activate_app, _capture_window
        await _activate_app("Safari")
        success = await _capture_window(save_path)

        if not success:
            # Fallback to full screen
            proc = await asyncio.create_subprocess_exec(
                "screencapture", "-x", save_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

        url = await _safari_get_url()
        title = await _safari_get_title()

        return ToolResult(
            success=True,
            data={
                "saved_path": save_path,
                "current_url": url,
                "page_title": title,
                "engine": "safari",
            },
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=f"Safari screenshot failed: {e}",
                severity=Severity.MEDIUM,
                recoverable=True,
            ),
        )


async def _playwright_screenshot(save_path: str, full_page: bool, selector: str) -> ToolResult:
    try:
        page = await _get_playwright_page()

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
                "engine": "playwright",
            },
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
    """Click an element on the page. Dangerous buttons need confirm_dangerous=True."""
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

    engine = _detect_engine()

    if engine == "safari":
        return await _safari_click(selector)
    else:
        return await _playwright_click(selector, wait_for_navigation)


async def _safari_click(selector: str) -> ToolResult:
    try:
        # Handle Playwright-style :has-text() selectors — not supported by querySelector
        import re as _re
        has_text_match = _re.search(r':has-text\(["\'](.+?)["\']\)', selector)
        if has_text_match:
            search_text = has_text_match.group(1)
            base_tag = _re.sub(r':has-text\(.+?\)', '', selector).strip() or '*'
            js = f"""
            (function() {{
                var els = document.querySelectorAll('{base_tag}');
                for (var i = 0; i < els.length; i++) {{
                    if (els[i].textContent.trim().includes('{search_text}')) {{
                        els[i].click();
                        return 'clicked';
                    }}
                }}
                return 'not_found';
            }})()
            """
        else:
            escaped = selector.replace("'", "\\'")
            js = f"""
            (function() {{
                var el = document.querySelector('{escaped}');
                if (!el) return 'not_found';
                el.click();
                return 'clicked';
            }})()
            """

        result = await _safari_js(js)
        await asyncio.sleep(0.5)

        if result and 'not_found' in str(result):
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Element not found: '{selector}'",
                    severity=Severity.MEDIUM,
                    recoverable=True,
                ),
            )

        url = await _safari_get_url()
        return ToolResult(
            success=True,
            data={
                "selector": selector,
                "clicked": True,
                "current_url": url,
                "engine": "safari",
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


async def _playwright_click(selector: str, wait_for_navigation: bool) -> ToolResult:
    try:
        page = await _get_playwright_page()
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
                "engine": "playwright",
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
    engine = _detect_engine()

    if engine == "safari":
        return await _safari_fill(selector, value, clear_first)
    else:
        return await _playwright_fill(selector, value, clear_first)


async def _safari_fill(selector: str, value: str, clear_first: bool) -> ToolResult:
    try:
        escaped_sel = selector.replace("'", "\\'")
        escaped_val = value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
        if clear_first:
            await _safari_js(f"document.querySelector('{escaped_sel}').value = ''")
        await _safari_js(f"var el = document.querySelector('{escaped_sel}'); el.value = '{escaped_val}'; el.dispatchEvent(new Event('input', {{bubbles: true}})); el.dispatchEvent(new Event('change', {{bubbles: true}}))")
        return ToolResult(
            success=True,
            data={"selector": selector, "filled": True, "value_length": len(value), "engine": "safari"},
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


async def _playwright_fill(selector: str, value: str, clear_first: bool) -> ToolResult:
    try:
        page = await _get_playwright_page()
        await page.wait_for_selector(selector, timeout=5000)
        if clear_first:
            await page.fill(selector, "")
        await page.fill(selector, value)
        return ToolResult(
            success=True,
            data={"selector": selector, "filled": True, "value_length": len(value), "engine": "playwright"},
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
    """Extract text content from an element (default: entire page body)."""
    engine = _detect_engine()

    if engine == "safari":
        return await _safari_get_text(selector)
    else:
        return await _playwright_get_text(selector)


async def _safari_get_text(selector: str) -> ToolResult:
    try:
        escaped = selector.replace("'", "\\'")
        text = await _safari_js(f"document.querySelector('{escaped}').innerText")
        if len(text) > 5000:
            text = text[:5000] + "\n... (truncated)"
        url = await _safari_get_url()
        return ToolResult(
            success=True,
            data={"text": text, "selector": selector, "url": url, "engine": "safari"},
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.NOT_FOUND,
                message=f"Element not found: {selector}: {e}",
                severity=Severity.LOW,
                recoverable=False,
            ),
        )


async def _playwright_get_text(selector: str) -> ToolResult:
    try:
        page = await _get_playwright_page()
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
        if len(text) > 5000:
            text = text[:5000] + "\n... (truncated)"
        return ToolResult(
            success=True,
            data={"text": text, "selector": selector, "url": page.url, "engine": "playwright"},
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
    """Wait for Travis to log in manually. Watches for URL change."""
    engine = _detect_engine()

    if engine == "safari":
        return await _safari_wait_for_login(timeout)
    else:
        return await _playwright_wait_for_login(timeout)


async def _safari_wait_for_login(timeout: int) -> ToolResult:
    try:
        login_url = await _safari_get_url()
        elapsed = 0
        while elapsed < timeout:
            await asyncio.sleep(2)
            elapsed += 2
            current_url = await _safari_get_url()
            if current_url != login_url:
                url_lower = current_url.lower()
                login_parts = ["login", "signin", "sign-in", "auth", "sso"]
                if not any(part in url_lower for part in login_parts):
                    title = await _safari_get_title()
                    return ToolResult(
                        success=True,
                        data={
                            "logged_in": True,
                            "url": current_url,
                            "title": title,
                            "message": "Login successful. Safari keeps the session.",
                        },
                    )
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.TIMEOUT,
                message=f"Login wait timed out after {timeout}s.",
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


async def _playwright_wait_for_login(timeout: int) -> ToolResult:
    try:
        page = await _get_playwright_page()
        login_url = page.url
        elapsed = 0
        while elapsed < timeout:
            await asyncio.sleep(2)
            elapsed += 2
            current_url = page.url
            if current_url != login_url:
                is_still_login = await _detect_login_playwright(page)
                if not is_still_login:
                    return ToolResult(
                        success=True,
                        data={
                            "logged_in": True,
                            "url": current_url,
                            "title": await page.title(),
                            "message": "Login successful. Session saved.",
                        },
                    )
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.TIMEOUT,
                message=f"Login wait timed out after {timeout}s.",
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
    """Close the browser tab (Safari) or browser window (Playwright)."""
    global _playwright, _context, _page

    engine = _detect_engine()

    try:
        if engine == "safari":
            # Close the current tab, not the whole browser
            await _safari_applescript('tell application "Safari" to close current tab of front window')
            return ToolResult(success=True, data={"closed": True, "engine": "safari", "note": "Closed current tab"})
        elif _context:
            await _context.close()
            _context = None
            _page = None
            if _playwright:
                await _playwright.stop()
                _playwright = None
        return ToolResult(success=True, data={"closed": True, "engine": engine})
    except Exception as e:
        _context = None
        _page = None
        _playwright = None
        return ToolResult(success=True, data={"closed": True, "note": str(e)})


# ── New tools: type, checkbox, select, scroll, elements, JS, back, tabs ─────

async def browser_type(
    selector: str,
    text: str,
    delay: int = 50,
) -> ToolResult:
    """Type text character by character into an element.

    Use this instead of browser_fill for JS-heavy inputs (React, Vue, etc.)
    that need keystroke events to trigger validation or autocomplete.
    """
    engine = _detect_engine()

    if engine == "safari":
        try:
            # Focus the element, then use AppleScript keystroke for real key events
            escaped_sel = selector.replace("'", "\\'")
            await _safari_js(f"document.querySelector('{escaped_sel}').focus()")
            await asyncio.sleep(0.1)
            # Use AppleScript keystrokes for realistic typing
            for char in text:
                escaped_char = char.replace("\\", "\\\\").replace('"', '\\"')
                await _safari_applescript(f'tell application "System Events" to keystroke "{escaped_char}"')
                await asyncio.sleep(delay / 1000)
            return ToolResult(success=True, data={
                "selector": selector, "typed": True, "length": len(text), "engine": "safari",
            })
        except Exception as e:
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.NOT_FOUND, message=f"Could not type into '{selector}': {e}",
                severity=Severity.MEDIUM, recoverable=False,
            ))
    else:
        try:
            page = await _get_playwright_page()
            await page.click(selector)
            await page.type(selector, text, delay=delay)
            return ToolResult(success=True, data={
                "selector": selector, "typed": True, "length": len(text), "engine": "playwright",
            })
        except Exception as e:
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.NOT_FOUND, message=f"Could not type into '{selector}': {e}",
                severity=Severity.MEDIUM, recoverable=False,
            ))


async def browser_check(
    selector: str,
    checked: bool = True,
) -> ToolResult:
    """Tick or untick a checkbox. Also works for radio buttons."""
    engine = _detect_engine()

    if engine == "safari":
        try:
            escaped = selector.replace("'", "\\'")
            is_checked = (await _safari_js(f"document.querySelector('{escaped}').checked")).lower() == "true"
            if is_checked != checked:
                await _safari_js(f"document.querySelector('{escaped}').click()")
            return ToolResult(success=True, data={
                "selector": selector, "checked": checked, "engine": "safari",
            })
        except Exception as e:
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.NOT_FOUND, message=f"Could not toggle '{selector}': {e}",
                severity=Severity.MEDIUM, recoverable=False,
            ))
    else:
        try:
            page = await _get_playwright_page()
            if checked:
                await page.check(selector)
            else:
                await page.uncheck(selector)
            return ToolResult(success=True, data={
                "selector": selector, "checked": checked, "engine": "playwright",
            })
        except Exception as e:
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.NOT_FOUND, message=f"Could not toggle '{selector}': {e}",
                severity=Severity.MEDIUM, recoverable=False,
            ))


async def browser_select(
    selector: str,
    value: str,
) -> ToolResult:
    """Select an option from a dropdown (<select> element).

    Tries matching by visible text first, then by value attribute.
    """
    engine = _detect_engine()

    if engine == "safari":
        try:
            escaped_sel = selector.replace("'", "\\'")
            escaped_val = value.replace("'", "\\'")
            # Try selecting by visible text, fall back to value
            js = f"""
            var sel = document.querySelector('{escaped_sel}');
            var found = false;
            for (var i = 0; i < sel.options.length; i++) {{
                if (sel.options[i].text === '{escaped_val}' || sel.options[i].value === '{escaped_val}') {{
                    sel.selectedIndex = i;
                    sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                    found = true;
                    break;
                }}
            }}
            found
            """
            result = await _safari_js(js)
            return ToolResult(success=True, data={
                "selector": selector, "selected": value, "engine": "safari",
            })
        except Exception as e:
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.NOT_FOUND, message=f"Could not select '{value}' in '{selector}': {e}",
                severity=Severity.MEDIUM, recoverable=False,
            ))
    else:
        try:
            page = await _get_playwright_page()
            await page.select_option(selector, label=value)
            return ToolResult(success=True, data={
                "selector": selector, "selected": value, "engine": "playwright",
            })
        except Exception:
            try:
                page = await _get_playwright_page()
                await page.select_option(selector, value=value)
                return ToolResult(success=True, data={
                    "selector": selector, "selected": value, "engine": "playwright",
                })
            except Exception as e:
                return ToolResult(success=False, error=ToolError(
                    code=ErrorCode.NOT_FOUND, message=f"Could not select '{value}' in '{selector}': {e}",
                    severity=Severity.MEDIUM, recoverable=False,
                ))


async def browser_scroll(
    direction: str = "down",
    pixels: int = 500,
) -> ToolResult:
    """Scroll the page. Direction: up, down, top, bottom."""
    engine = _detect_engine()

    js_map = {
        "down": f"window.scrollBy(0, {pixels})",
        "up": f"window.scrollBy(0, -{pixels})",
        "top": "window.scrollTo(0, 0)",
        "bottom": "window.scrollTo(0, document.body.scrollHeight)",
    }
    js_cmd = js_map.get(direction, js_map["down"])

    if engine == "safari":
        try:
            await _safari_js(js_cmd)
            scroll_y = await _safari_js("window.scrollY")
            page_h = await _safari_js("document.body.scrollHeight")
            return ToolResult(success=True, data={
                "direction": direction, "scroll_y": scroll_y, "page_height": page_h, "engine": "safari",
            })
        except Exception as e:
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.COMMAND_FAILED, message=f"Scroll failed: {e}",
                severity=Severity.LOW, recoverable=True,
            ))
    else:
        try:
            page = await _get_playwright_page()
            await page.evaluate(js_cmd)
            scroll_y = await page.evaluate("window.scrollY")
            page_h = await page.evaluate("document.body.scrollHeight")
            return ToolResult(success=True, data={
                "direction": direction, "scroll_y": scroll_y, "page_height": page_h, "engine": "playwright",
            })
        except Exception as e:
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.COMMAND_FAILED, message=f"Scroll failed: {e}",
                severity=Severity.LOW, recoverable=True,
            ))


async def browser_elements(
    selector: str = "body",
) -> ToolResult:
    """List all interactive elements on the page (buttons, links, inputs, selects, checkboxes).

    Returns their selector, tag, type, text/placeholder, and whether they're visible.
    This is how you figure out what to click, fill, or check on a page.
    """
    # Safari doesn't support arrow function args in execute_script — use inline JS
    safari_js = '''
    var root = arguments[0];
    var els = root.querySelectorAll('a, button, input, select, textarea, [role="button"], [role="link"], [role="checkbox"], [role="tab"], [onclick]');
    var results = [];
    for (var i = 0; i < els.length && i < 80; i++) {
        var el = els[i];
        var rect = el.getBoundingClientRect();
        if (rect.width === 0 && rect.height === 0) continue;
        var tag = el.tagName.toLowerCase();
        var type = el.type || el.getAttribute('role') || '';
        var text = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim().substring(0, 100);
        var name = el.name || '';
        var id = el.id || '';
        var sel = tag;
        if (id) sel = '#' + id;
        else if (name) sel = tag + '[name="' + name + '"]';
        else if (el.className && typeof el.className === 'string') {
            var cls = el.className.trim().split(/\\s+/).slice(0, 2).join('.');
            if (cls) sel = tag + '.' + cls;
        }
        var href = el.href ? el.href.substring(0, 80) : '';
        var checked = el.checked !== undefined ? el.checked : null;
        results.push({selector: sel, tag: tag, type: type, text: text, name: name, href: href, checked: checked});
    }
    return results;
    '''

    playwright_js = '''
    (root) => {
        const els = root.querySelectorAll('a, button, input, select, textarea, [role="button"], [role="link"], [role="checkbox"], [role="tab"], [onclick]');
        const results = [];
        for (const el of els) {
            const rect = el.getBoundingClientRect();
            if (rect.width === 0 && rect.height === 0) continue;
            const tag = el.tagName.toLowerCase();
            const type = el.type || el.getAttribute('role') || '';
            const text = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim().substring(0, 100);
            const name = el.name || '';
            const id = el.id || '';
            let sel = tag;
            if (id) sel = '#' + id;
            else if (name) sel = tag + '[name="' + name + '"]';
            else if (el.className && typeof el.className === 'string') {
                const cls = el.className.trim().split(/\\s+/).slice(0, 2).join('.');
                if (cls) sel = tag + '.' + cls;
            }
            const href = el.href ? el.href.substring(0, 80) : '';
            const checked = el.checked !== undefined ? el.checked : null;
            results.push({selector: sel, tag, type, text, name, href, checked});
            if (results.length >= 80) break;
        }
        return results;
    }
    '''

    engine = _detect_engine()

    if engine == "safari":
        try:
            # Run the element-finding JS via AppleScript — no Selenium needed
            # Wrap safari_js to scope to selector and return JSON
            wrapped_js = f'''
            (function() {{
                var root = document.querySelector('{selector}');
                if (!root) return JSON.stringify([]);
                var els = root.querySelectorAll('a, button, input, select, textarea, [role="button"], [role="link"], [role="checkbox"], [role="tab"], [onclick]');
                var results = [];
                for (var i = 0; i < els.length && i < 80; i++) {{
                    var el = els[i];
                    var rect = el.getBoundingClientRect();
                    if (rect.width === 0 && rect.height === 0) continue;
                    var tag = el.tagName.toLowerCase();
                    var type = el.type || el.getAttribute('role') || '';
                    var text = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim().substring(0, 100);
                    var name = el.name || '';
                    var id = el.id || '';
                    var sel = tag;
                    if (id) sel = '#' + id;
                    else if (name) sel = tag + '[name="' + name + '"]';
                    else if (el.className && typeof el.className === 'string') {{
                        var cls = el.className.trim().split(/\\s+/).slice(0, 2).join('.');
                        if (cls) sel = tag + '.' + cls;
                    }}
                    var href = el.href ? el.href.substring(0, 80) : '';
                    var checked = el.checked !== undefined ? el.checked : null;
                    results.push({{selector: sel, tag: tag, type: type, text: text, name: name, href: href, checked: checked}});
                }}
                return JSON.stringify(results);
            }})()
            '''
            import json
            raw = await _safari_js(wrapped_js)
            elements = json.loads(raw) if raw else []
            url = await _safari_get_url()
            return ToolResult(success=True, data={
                "elements": elements[:80], "count": len(elements),
                "url": url, "engine": "safari",
            })
        except Exception as e:
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.COMMAND_FAILED, message=f"Failed to list elements: {e}",
                severity=Severity.LOW, recoverable=True,
            ))
    else:
        try:
            page = await _get_playwright_page()
            root = await page.query_selector(selector)
            elements = await page.evaluate(playwright_js, root)
            return ToolResult(success=True, data={
                "elements": elements, "count": len(elements),
                "url": page.url, "engine": "playwright",
            })
        except Exception as e:
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.COMMAND_FAILED, message=f"Failed to list elements: {e}",
                severity=Severity.LOW, recoverable=True,
            ))


async def browser_execute_js(script: str) -> ToolResult:
    """Execute JavaScript on the current page. Returns the result.

    Use for edge cases — custom scrolling, extracting specific data,
    interacting with elements that don't have good CSS selectors, etc.
    """
    engine = _detect_engine()

    if engine == "safari":
        try:
            result = await _safari_js(script)
            return ToolResult(success=True, data={
                "result": result if result else None,
                "engine": "safari",
            })
        except Exception as e:
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.COMMAND_FAILED, message=f"JS execution failed: {e}",
                severity=Severity.MEDIUM, recoverable=True,
            ))
    else:
        try:
            page = await _get_playwright_page()
            result = await page.evaluate(script)
            return ToolResult(success=True, data={
                "result": str(result) if result is not None else None,
                "engine": "playwright",
            })
        except Exception as e:
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.COMMAND_FAILED, message=f"JS execution failed: {e}",
                severity=Severity.MEDIUM, recoverable=True,
            ))


async def browser_back() -> ToolResult:
    """Go back to the previous page."""
    engine = _detect_engine()

    if engine == "safari":
        try:
            await _safari_js("history.back()")
            await asyncio.sleep(1)
            url = await _safari_get_url()
            title = await _safari_get_title()
            return ToolResult(success=True, data={
                "url": url, "title": title, "engine": "safari",
            })
        except Exception as e:
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.COMMAND_FAILED, message=f"Back failed: {e}",
                severity=Severity.LOW, recoverable=True,
            ))
    else:
        try:
            page = await _get_playwright_page()
            await page.go_back()
            return ToolResult(success=True, data={
                "url": page.url, "title": await page.title(), "engine": "playwright",
            })
        except Exception as e:
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.COMMAND_FAILED, message=f"Back failed: {e}",
                severity=Severity.LOW, recoverable=True,
            ))


async def browser_upload(
    selector: str,
    file_path: str,
) -> ToolResult:
    """Upload a file to a file input element. For uploading CVs, cover letters, etc."""
    from pathlib import Path as P
    if not P(file_path).exists():
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.FILE_NOT_FOUND, message=f"File not found: {file_path}",
            severity=Severity.MEDIUM, recoverable=False,
        ))

    engine = _detect_engine()

    if engine == "safari":
        try:
            import base64 as _b64
            escaped_sel = selector.replace("'", "\\'")

            # Read file as base64
            with open(file_path, "rb") as f:
                b64_data = _b64.b64encode(f.read()).decode()

            filename = Path(file_path).name
            # Guess MIME type
            ext = Path(file_path).suffix.lower()
            mime_map = {".pdf": "application/pdf", ".doc": "application/msword",
                        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        ".txt": "text/plain", ".rtf": "application/rtf", ".png": "image/png", ".jpg": "image/jpeg"}
            mime = mime_map.get(ext, "application/octet-stream")

            # Use DataTransfer API to set file without Finder dialog
            result = await _safari_js(f"""
            (function() {{
                try {{
                    var b64 = "{b64_data}";
                    var byteChars = atob(b64);
                    var byteArray = new Uint8Array(byteChars.length);
                    for (var i = 0; i < byteChars.length; i++) byteArray[i] = byteChars.charCodeAt(i);
                    var file = new File([byteArray], "{filename}", {{type: "{mime}"}});
                    var dt = new DataTransfer();
                    dt.items.add(file);
                    var input = document.querySelector('{escaped_sel}');
                    if (!input) return 'not_found';
                    input.files = dt.files;
                    input.dispatchEvent(new Event('change', {{bubbles: true}}));
                    return 'ok:' + input.files.length;
                }} catch(e) {{
                    return 'error:' + e.message;
                }}
            }})()
            """)

            if result and result.startswith("ok:"):
                return ToolResult(success=True, data={
                    "selector": selector, "file": file_path,
                    "uploaded": True, "engine": "safari",
                })
            else:
                return ToolResult(success=False, error=ToolError(
                    code=ErrorCode.COMMAND_FAILED,
                    message=f"Upload failed: {result}",
                    severity=Severity.MEDIUM, recoverable=True,
                ))
        except Exception as e:
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.COMMAND_FAILED, message=f"Upload failed: {e}",
                severity=Severity.MEDIUM, recoverable=True,
            ))
    else:
        try:
            page = await _get_playwright_page()
            await page.set_input_files(selector, file_path)
            return ToolResult(success=True, data={
                "selector": selector, "file": file_path, "uploaded": True, "engine": "playwright",
            })
        except Exception as e:
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.COMMAND_FAILED, message=f"Upload failed: {e}",
                severity=Severity.MEDIUM, recoverable=True,
            ))


# ── Batch tools (minimize round trips) ───────────────────────────────────────


async def browser_fill_form(fields: dict, click_first: str = None) -> ToolResult:
    """Fill multiple form fields in a SINGLE browser call. Way faster than calling browser_fill N times.

    fields: dict of {css_selector: value} — fills each input/textarea.
    click_first: optional CSS selector to click before filling (e.g. the Apply button).
    """
    import json as _json

    engine = _detect_engine()
    if engine != "safari":
        # Playwright fallback — sequential fills
        try:
            page = await _get_playwright_page()
            if click_first:
                await page.click(click_first)
                await asyncio.sleep(1)
            results = {}
            for sel, val in fields.items():
                try:
                    await page.fill(sel, val)
                    results[sel] = "filled"
                except Exception as e:
                    results[sel] = f"error: {e}"
            return ToolResult(success=True, data={"filled": results, "engine": "playwright"})
        except Exception as e:
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.COMMAND_FAILED, message=str(e),
                severity=Severity.MEDIUM, recoverable=True,
            ))

    # Safari — single JS call fills everything (with React-Select detection)
    try:
        # Build JS that fills all fields + triggers React change events
        # React-Select inputs are detected and marked for a second pass
        fill_lines = []
        for sel, val in fields.items():
            escaped_sel = sel.replace("'", "\\'")
            escaped_val = val.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
            fill_lines.append(f"""
                (function() {{
                    var el = document.querySelector('{escaped_sel}');
                    if (!el) return '{escaped_sel}:not_found';
                    // Detect React-Select: input itself or parent has class containing "css-"
                    var isReactSelect = false;
                    if (el.className && typeof el.className === 'string' && el.className.match(/css-/)) {{
                        isReactSelect = true;
                    }}
                    var parent = el.parentElement;
                    for (var i = 0; i < 5 && parent; i++) {{
                        if (parent.className && typeof parent.className === 'string' && parent.className.match(/css-/)) {{
                            isReactSelect = true;
                            break;
                        }}
                        parent = parent.parentElement;
                    }}
                    if (isReactSelect) {{
                        return '{escaped_sel}:react_select';
                    }}
                    // Checkbox / radio — click to toggle
                    if (el.type === 'checkbox' || el.type === 'radio') {{
                        var want = '{escaped_val}'.toLowerCase();
                        var shouldCheck = (want === 'true' || want === 'yes' || want === '1' || want === 'on');
                        if (el.checked !== shouldCheck) {{
                            el.click();
                        }}
                        el.dispatchEvent(new Event('change', {{bubbles: true}}));
                        return '{escaped_sel}:filled';
                    }}
                    // Select dropdown — set by value or visible text
                    if (el.tagName === 'SELECT') {{
                        var found = false;
                        for (var j = 0; j < el.options.length; j++) {{
                            if (el.options[j].value === '{escaped_val}' || el.options[j].text.trim() === '{escaped_val}') {{
                                el.selectedIndex = j;
                                found = true;
                                break;
                            }}
                        }}
                        if (!found) {{
                            // Fuzzy match — case-insensitive contains
                            var lv = '{escaped_val}'.toLowerCase();
                            for (var j = 0; j < el.options.length; j++) {{
                                if (el.options[j].text.toLowerCase().indexOf(lv) >= 0) {{
                                    el.selectedIndex = j;
                                    found = true;
                                    break;
                                }}
                            }}
                        }}
                        el.dispatchEvent(new Event('change', {{bubbles: true}}));
                        return '{escaped_sel}:' + (found ? 'filled' : 'option_not_found');
                    }}
                    var proto = el.tagName === 'TEXTAREA'
                        ? window.HTMLTextAreaElement.prototype
                        : window.HTMLInputElement.prototype;
                    var setter = Object.getOwnPropertyDescriptor(proto, 'value');
                    if (setter && setter.set) {{
                        setter.set.call(el, '{escaped_val}');
                    }} else {{
                        el.value = '{escaped_val}';
                    }}
                    el.dispatchEvent(new Event('input', {{bubbles: true}}));
                    el.dispatchEvent(new Event('change', {{bubbles: true}}));
                    return '{escaped_sel}:filled';
                }})()""")

        click_js = ""
        if click_first:
            escaped_click = click_first.replace("'", "\\'")
            click_js = f"var btn = document.querySelector('{escaped_click}'); if (btn) btn.click();\n"

        batch_js = f"""
        (function() {{
            {click_js}
            var results = [];
            {';'.join(f'results.push({line})' for line in fill_lines)};
            return JSON.stringify(results);
        }})()
        """

        raw = await _safari_js(batch_js)
        results = _json.loads(raw) if raw else []

        filled = {}
        react_select_fields = {}  # sel -> value, for second pass
        for r in results:
            if ':' in str(r):
                sel, status = str(r).rsplit(':', 1)
                filled[sel] = status
                if status == "react_select":
                    # Find original value for this selector
                    for orig_sel, orig_val in fields.items():
                        if orig_sel.replace("'", "\\'") == sel or orig_sel == sel:
                            react_select_fields[orig_sel] = orig_val
                            break
            else:
                filled[str(r)] = "unknown"

        # Second pass: handle React-Select fields one at a time
        for sel, val in react_select_fields.items():
            try:
                escaped_sel = sel.replace("'", "\\'")
                escaped_val = val.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")

                # Step 1: Click/focus the React-Select input to open it
                await _safari_js(f"""
                (function() {{
                    var el = document.querySelector('{escaped_sel}');
                    if (!el) return 'not_found';
                    el.focus();
                    el.click();
                    return 'focused';
                }})()
                """)

                # Step 2: Type the value by setting it and dispatching an InputEvent
                await _safari_js(f"""
                (function() {{
                    var el = document.querySelector('{escaped_sel}');
                    if (!el) return 'not_found';
                    var nativeSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    );
                    if (nativeSetter && nativeSetter.set) {{
                        nativeSetter.set.call(el, '{escaped_val}');
                    }} else {{
                        el.value = '{escaped_val}';
                    }}
                    el.dispatchEvent(new InputEvent('input', {{
                        bubbles: true,
                        inputType: 'insertText',
                        data: '{escaped_val}'
                    }}));
                    return 'typed';
                }})()
                """)

                # Step 3: Wait for dropdown options to render
                await asyncio.sleep(0.3)

                # Step 4: Click the first matching option in the dropdown
                option_result = await _safari_js(f"""
                (function() {{
                    // Try React-Select specific option classes first, then generic
                    var option = document.querySelector('[class*="option"]:not([class*="optionDisabled"])');
                    if (!option) option = document.querySelector('[id*="option-"]');
                    if (!option) option = document.querySelector('[class*="menu"] [class*="option"]');
                    if (option) {{
                        option.click();
                        return 'selected';
                    }}
                    return 'no_option_found';
                }})()
                """)

                filled[sel] = option_result.strip() if option_result else "react_select_failed"
            except Exception as e:
                filled[sel] = f"react_select_error: {e}"

        failed = {k: v for k, v in filled.items() if v not in ("filled", "selected")}
        return ToolResult(success=True, data={
            "filled": filled,
            "total": len(fields),
            "success_count": sum(1 for v in filled.values() if v in ("filled", "selected")),
            "failed_count": len(failed),
            "failed_fields": failed if failed else None,
            "react_select_count": len(react_select_fields),
            "engine": "safari",
        })
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Batch fill failed: {e}",
            severity=Severity.MEDIUM, recoverable=True,
        ))


async def browser_discover_form() -> ToolResult:
    """Discover ALL form fields on the current page in one call.

    Scrolls the full page first to load lazy elements, then finds every
    input, select, textarea, checkbox, radio, file input — with selector,
    type, label, current value, required status. Also returns a summary
    of unfilled required fields so the agent knows what still needs filling.
    """
    import json as _json

    engine = _detect_engine()

    # JS that scrolls full page, then discovers all fields
    discover_js = """
    (function() {
        // Scroll full page to trigger lazy-loaded elements
        var scrollHeight = document.documentElement.scrollHeight;
        var step = window.innerHeight;
        for (var pos = 0; pos < scrollHeight; pos += step) {
            window.scrollTo(0, pos);
        }
        // Scroll back to top
        window.scrollTo(0, 0);

        var fields = [];
        // Skip hidden/zero-size check — include ALL fields in the DOM regardless of viewport
        var els = document.querySelectorAll('input, select, textarea, [role="combobox"], [role="listbox"]');
        for (var i = 0; i < els.length && i < 80; i++) {
            var el = els[i];
            // Skip truly hidden (display:none) but NOT offscreen/below-fold
            var style = window.getComputedStyle(el);
            if (style.display === 'none' && !el.id && !el.name) continue;
            var tag = el.tagName.toLowerCase();
            var type = el.type || el.getAttribute('role') || '';
            // Skip hidden inputs (csrf tokens, etc)
            if (type === 'hidden') continue;
            var id = el.id || '';
            var name = el.name || '';
            var sel = tag;
            if (id) sel = '#' + id;
            else if (name) sel = tag + '[name="' + name + '"]';
            else if (el.className && typeof el.className === 'string') {
                var cls = el.className.trim().split(/\\s+/).slice(0, 2).join('.');
                if (cls) sel = tag + '.' + cls;
            }
            // Find label
            var label = '';
            if (id) {
                var lbl = document.querySelector('label[for="' + id + '"]');
                if (lbl) label = lbl.textContent.trim().substring(0, 80);
            }
            if (!label) {
                var parent = el.closest('label, .field, .form-group, [class*="field"]');
                if (parent) {
                    var lbl = parent.querySelector('label, .label, legend');
                    if (lbl) label = lbl.textContent.trim().substring(0, 80);
                }
            }
            if (!label) label = el.placeholder || el.getAttribute('aria-label') || '';
            var value = el.value || '';
            var required = el.required || el.getAttribute('aria-required') === 'true';
            var checked = (type === 'checkbox' || type === 'radio') ? el.checked : undefined;
            var options = [];
            if (tag === 'select') {
                for (var j = 0; j < el.options.length && j < 10; j++) {
                    options.push(el.options[j].text);
                }
            }
            // For checkboxes/radios, "filled" = checked. For selects, "filled" = not on first placeholder option.
            var isFilled = value.length > 0;
            if (type === 'checkbox' || type === 'radio') isFilled = el.checked;
            if (tag === 'select') isFilled = el.selectedIndex > 0 || (el.selectedIndex === 0 && el.options[0] && el.options[0].value !== '');
            fields.push({
                selector: sel, tag: tag, type: type, label: label.substring(0, 80),
                value: value.substring(0, 50), required: required, filled: isFilled,
                checked: checked,
                options: options.length > 0 ? options : undefined
            });
        }
        // Buttons
        var btns = document.querySelectorAll('button, input[type="submit"]');
        var buttons = [];
        for (var i = 0; i < btns.length && i < 10; i++) {
            var b = btns[i];
            var style = window.getComputedStyle(b);
            if (style.display === 'none') continue;
            var bsel = b.id ? '#' + b.id : (b.className ? 'button.' + b.className.trim().split(/\\s+/).slice(0,2).join('.') : 'button');
            buttons.push({selector: bsel, text: (b.textContent || b.value || '').trim().substring(0, 50)});
        }
        // Summary
        var unfilled_required = fields.filter(function(f) { return f.required && !f.filled && f.type !== 'file'; });
        var unfilled_optional = fields.filter(function(f) { return !f.required && !f.filled && f.type !== 'hidden' && f.type !== 'file'; });
        var unfilled_file = fields.filter(function(f) { return f.type === 'file' && !f.filled; });
        var unchecked_checkboxes = fields.filter(function(f) { return (f.type === 'checkbox' || f.type === 'radio') && !f.checked; });
        var default_selects = fields.filter(function(f) { return f.tag === 'select' && !f.filled; });
        return JSON.stringify({
            fields: fields, buttons: buttons,
            url: location.href, title: document.title,
            total_fields: fields.length,
            unfilled_required: unfilled_required.map(function(f) { return {selector: f.selector, label: f.label, type: f.type}; }),
            unfilled_required_count: unfilled_required.length,
            unfilled_optional_count: unfilled_optional.length,
            unchecked_checkboxes: unchecked_checkboxes.map(function(f) { return {selector: f.selector, label: f.label}; }),
            default_selects: default_selects.map(function(f) { return {selector: f.selector, label: f.label, options: f.options}; }),
            all_required_filled: unfilled_required.length === 0,
            all_fields_filled: unfilled_required.length === 0 && unfilled_optional.length === 0 && unchecked_checkboxes.length === 0 && default_selects.length === 0,
            has_file_upload: unfilled_file.length > 0
        });
    })()
    """

    try:
        if engine == "safari":
            raw = await _safari_js(discover_js)
        else:
            page = await _get_playwright_page()
            raw = await page.evaluate(discover_js)

        data = _json.loads(raw) if raw else {"fields": [], "buttons": []}
        return ToolResult(success=True, data=data)
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Form discovery failed: {e}",
            severity=Severity.MEDIUM, recoverable=True,
        ))


# ── Tool Schemas ─────────────────────────────────────────────────────────────

TOOL_SCHEMAS = {
    "browser_navigate": {
        "fn": browser_navigate,
        "schema": {
            "type": "function",
            "function": {
                "name": "browser_navigate",
                "description": "Navigate browser to a URL. Uses Safari (with all your logged-in sessions) by default. Returns page title and URL.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to navigate to"},
                        "wait_for": {
                            "type": "string",
                            "enum": ["load", "networkidle", "domcontentloaded"],
                            "description": "Wait condition (default: load). Only used with Playwright fallback.",
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
                "description": "Wait for Travis to log in manually in the browser. Watches for URL change.",
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
    "browser_type": {
        "fn": browser_type,
        "schema": {
            "type": "function",
            "function": {
                "name": "browser_type",
                "description": "Type text character by character into an input. Use instead of browser_fill for JS-heavy inputs (React, autocomplete, search bars) that need keystroke events.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string", "description": "CSS selector of the input element"},
                        "text": {"type": "string", "description": "Text to type"},
                        "delay": {"type": "integer", "description": "Delay between keystrokes in ms (default 50)"},
                    },
                    "required": ["selector", "text"],
                },
            },
        },
    },
    "browser_check": {
        "fn": browser_check,
        "schema": {
            "type": "function",
            "function": {
                "name": "browser_check",
                "description": "Tick or untick a checkbox or radio button.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string", "description": "CSS selector of the checkbox/radio"},
                        "checked": {"type": "boolean", "description": "True to tick, False to untick (default True)"},
                    },
                    "required": ["selector"],
                },
            },
        },
    },
    "browser_select": {
        "fn": browser_select,
        "schema": {
            "type": "function",
            "function": {
                "name": "browser_select",
                "description": "Select an option from a dropdown (<select> element). Matches by visible text first, then by value.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string", "description": "CSS selector of the <select> element"},
                        "value": {"type": "string", "description": "Option text or value to select"},
                    },
                    "required": ["selector", "value"],
                },
            },
        },
    },
    "browser_scroll": {
        "fn": browser_scroll,
        "schema": {
            "type": "function",
            "function": {
                "name": "browser_scroll",
                "description": "Scroll the browser page. Use 'bottom' to jump to footer, 'top' to go back up.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "direction": {
                            "type": "string",
                            "enum": ["up", "down", "top", "bottom"],
                            "description": "Scroll direction (default: down)",
                        },
                        "pixels": {"type": "integer", "description": "Pixels to scroll (default 500). Ignored for top/bottom."},
                    },
                },
            },
        },
    },
    "browser_elements": {
        "fn": browser_elements,
        "schema": {
            "type": "function",
            "function": {
                "name": "browser_elements",
                "description": "List all interactive elements on the page — buttons, links, inputs, checkboxes, dropdowns. Returns their CSS selector, type, and text. Call this to figure out what you can click/fill/check on a page.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string", "description": "Root element to search within (default: body)"},
                    },
                },
            },
        },
    },
    "browser_execute_js": {
        "fn": browser_execute_js,
        "schema": {
            "type": "function",
            "function": {
                "name": "browser_execute_js",
                "description": "Execute JavaScript on the current page. For edge cases — custom interactions, extracting data, or elements without good CSS selectors.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "script": {"type": "string", "description": "JavaScript code to execute. Use 'return X' to get a value back."},
                    },
                    "required": ["script"],
                },
            },
        },
    },
    "browser_back": {
        "fn": browser_back,
        "schema": {
            "type": "function",
            "function": {
                "name": "browser_back",
                "description": "Go back to the previous page (browser back button).",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        },
    },
    "browser_upload": {
        "fn": browser_upload,
        "schema": {
            "type": "function",
            "function": {
                "name": "browser_upload",
                "description": "Upload a file to a file input element. For uploading CVs, cover letters, documents, etc.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string", "description": "CSS selector of the file input (<input type='file'>)"},
                        "file_path": {"type": "string", "description": "Absolute path to the file to upload"},
                    },
                    "required": ["selector", "file_path"],
                },
            },
        },
    },
    "browser_fill_form": {
        "fn": browser_fill_form,
        "schema": {
            "type": "function",
            "function": {
                "name": "browser_fill_form",
                "description": "Fill MULTIPLE form fields in one call. Much faster than calling browser_fill many times. Pass a dict of {selector: value} pairs.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "fields": {
                            "type": "object",
                            "description": "Dict of CSS selector -> value to fill. Example: {\"#first_name\": \"John\", \"#email\": \"john@example.com\"}",
                        },
                        "click_first": {
                            "type": ["string", "null"],
                            "description": "Optional: CSS selector of a button to click before filling (e.g. Apply button)",
                        },
                    },
                    "required": ["fields"],
                },
            },
        },
    },
    "browser_discover_form": {
        "fn": browser_discover_form,
        "schema": {
            "type": "function",
            "function": {
                "name": "browser_discover_form",
                "description": "Discover ALL form fields on the page — inputs, selects, textareas, checkboxes, file uploads. Returns each field's selector, type, label, current value, and whether it's required. Also returns buttons. Use this before browser_fill_form to see what needs filling.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        },
    },
}
