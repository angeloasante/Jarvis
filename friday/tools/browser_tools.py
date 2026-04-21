"""Browser tools v2 — persistent daemon + accessibility-tree refs + snapshot diffing.

Inspired by gstack's architecture:
  1. Persistent Chromium — single browser stays alive across all calls (~100ms per call vs ~3s)
  2. Ref-based targeting — accessibility tree assigns @e1, @e2, etc. to every element.
     No CSS selectors needed. More stable across page changes.
  3. Snapshot diffing — compare page states to see what changed.

Uses YOUR Chrome profile (cookies, sessions, passwords) via Playwright persistent context.
Safari AppleScript kept as fallback for simple nav/text extraction.

Old browser_tools.py → browser_tools_old.py (commented out, kept for reference).
"""

import asyncio
import json
import re
import logging
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional

from friday.core.types import ToolResult, ToolError, ErrorCode, Severity

logger = logging.getLogger("friday.browser")

BROWSER_DATA_DIR = str(Path.home() / ".friday" / "browser_data")
SCREENSHOT_DIR = Path.home() / "Downloads" / "friday_screenshots"

# ═══════════════════════════════════════════════════════════════════════════
# PERSISTENT BROWSER DAEMON
# ═══════════════════════════════════════════════════════════════════════════
# Single Playwright instance stays alive across all tool calls.
# First call: ~3s (launch). Every call after: ~100-200ms.

_playwright = None
_context = None
_page = None
_last_snapshot: dict = None   # For diffing
_ref_map: dict = {}           # @e1 → {role, name, locator_strategy}
_idle_timer = None


async def _get_page():
    """Get the persistent browser page. Launches Chromium on first call."""
    global _playwright, _context, _page

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright not installed. Run: uv add playwright && uv run playwright install chromium"
        )

    if _page and not _page.is_closed():
        return _page

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
        logger.info("[Browser] Persistent Chromium launched")

    pages = _context.pages
    _page = pages[0] if pages else await _context.new_page()
    return _page


# ═══════════════════════════════════════════════════════════════════════════
# ACCESSIBILITY TREE → REF MAP
# ═══════════════════════════════════════════════════════════════════════════
# Parse the page's accessibility tree into a flat list of interactive elements.
# Each element gets a ref like @e1, @e2, etc.
# Agents say "click @e5" instead of hunting for CSS selectors.


# Roles that get refs and are clickable/fillable
_INTERACTIVE_ROLES = {
    "link", "button", "textbox", "checkbox", "radio",
    "combobox", "menuitem", "tab", "switch", "searchbox",
    "option", "slider", "spinbutton", "menuitemcheckbox",
    "menuitemradio", "treeitem",
}
# Context roles — assigned refs for navigation but not interactive
_CONTEXT_ROLES = {"heading", "img", "banner", "navigation", "main"}

# Regex to parse one line of aria_snapshot output
# Examples:  "- button \"Submit order\""  or  "- textbox \"Email\" [level=1]"
_ARIA_LINE_RE = re.compile(
    r'^(\s*)-\s+'            # indent + dash
    r'(\w+)'                 # role
    r'(?:\s+"([^"]*)")?'     # optional name in quotes
    r'(.*?)$'                # rest (attrs like [level=1], [checked])
)


async def _build_ref_map(page) -> dict:
    """Build ref map from Playwright's aria_snapshot().

    Parses the YAML-like accessibility tree into a flat dict of
    @e1, @e2, ... → {role, name, locator, interactive, ...}.
    """
    global _ref_map

    try:
        raw = await page.locator("body").aria_snapshot()
    except Exception:
        _ref_map = {}
        return _ref_map

    if not raw:
        _ref_map = {}
        return _ref_map

    refs = {}
    counter = 0

    for line in raw.splitlines():
        m = _ARIA_LINE_RE.match(line)
        if not m:
            continue

        indent, role, name, rest = m.groups()
        depth = len(indent) // 2
        name = name or ""

        if role not in _INTERACTIVE_ROLES and role not in _CONTEXT_ROLES:
            continue

        counter += 1
        ref = f"@e{counter}"

        # Parse optional attributes from rest: [level=1], [checked]
        checked = None
        if "[checked]" in rest or "checked=true" in rest.lower():
            checked = True
        elif "checked=false" in rest.lower():
            checked = False

        entry = {
            "ref": ref,
            "role": role,
            "name": name[:100],
            "value": "",
            "checked": checked,
            "disabled": "[disabled]" in rest,
            "depth": depth,
        }

        if role in _INTERACTIVE_ROLES:
            entry["interactive"] = True
            entry["locator"] = _build_locator(role, name)
        else:
            entry["interactive"] = False

        refs[ref] = entry

    _ref_map = refs
    return refs


def _build_locator(role: str, name: str) -> dict:
    """Build a Playwright locator strategy for an element."""
    if name:
        return {"method": "get_by_role", "role": role, "name": name}
    else:
        return {"method": "get_by_role", "role": role, "name": None}


async def _resolve_ref(page, ref: str):
    """Resolve a @ref to a Playwright Locator."""
    if ref not in _ref_map:
        return None

    entry = _ref_map[ref]
    loc = entry.get("locator")
    if not loc:
        return None

    role = loc["role"]
    name = loc["name"]

    if name:
        locator = page.get_by_role(role, name=name)
    else:
        locator = page.get_by_role(role)

    # If multiple matches, try to find the right one by checking count
    count = await locator.count()
    if count == 0:
        return None
    if count == 1:
        return locator

    # Multiple matches — find the one most likely matching our ref
    # Use the ref index to pick the nth occurrence
    ref_num = int(ref.replace("@e", ""))

    # Count how many refs with the same role+name exist before this one
    nth = 0
    for r, e in _ref_map.items():
        if r == ref:
            break
        if e.get("locator") and e["locator"]["role"] == role and e["locator"]["name"] == name:
            nth += 1

    if nth < count:
        return locator.nth(nth)
    return locator.first


# ═══════════════════════════════════════════════════════════════════════════
# SNAPSHOT + DIFFING
# ═══════════════════════════════════════════════════════════════════════════


def _snapshot_to_text(refs: dict) -> str:
    """Convert ref map to a readable text snapshot."""
    lines = []
    for ref, entry in refs.items():
        role = entry["role"]
        name = entry.get("name", "")
        value = entry.get("value", "")
        inter = "●" if entry.get("interactive") else "○"

        parts = [f"{inter} {ref} [{role}]"]
        if name:
            parts.append(f'"{name}"')
        if value:
            parts.append(f"value={value}")
        if entry.get("checked") is not None:
            parts.append(f"checked={entry['checked']}")
        if entry.get("disabled"):
            parts.append("(disabled)")

        lines.append(" ".join(parts))
    return "\n".join(lines)


def _diff_snapshots(old: dict, new: dict) -> dict:
    """Diff two ref maps. Returns added, removed, and changed elements."""
    old_keys = set(old.keys()) if old else set()
    new_keys = set(new.keys())

    # Build fingerprints for comparison (by role+name, not ref number)
    def _fingerprint(entry):
        return f"{entry['role']}|{entry.get('name', '')}|{entry.get('value', '')}"

    old_fps = {_fingerprint(v): k for k, v in old.items()} if old else {}
    new_fps = {_fingerprint(v): k for k, v in new.items()}

    added = []
    removed = []
    changed = []

    # Elements in new but not old
    for fp, ref in new_fps.items():
        if fp not in old_fps:
            entry = new[ref]
            added.append(f"+ {ref} [{entry['role']}] \"{entry.get('name', '')}\"")

    # Elements in old but not new
    for fp, ref in old_fps.items():
        if fp not in new_fps:
            entry = old[ref]
            removed.append(f"- {ref} [{entry['role']}] \"{entry.get('name', '')}\"")

    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "summary": f"+{len(added)} -{len(removed)} elements",
    }


# ═══════════════════════════════════════════════════════════════════════════
# SAFETY HELPERS
# ═══════════════════════════════════════════════════════════════════════════

LOGIN_INDICATORS = [
    "sign in", "log in", "login", "signin",
    "username", "password", "email address",
    "forgot password", "create account", "sign up",
]

DANGEROUS_ACTIONS = [
    "submit", "pay", "confirm", "delete", "remove",
    "purchase", "buy", "checkout", "place order",
    "send", "transfer", "authorize",
]


async def _detect_login(page) -> bool:
    try:
        url_lower = page.url.lower()
        if any(p in url_lower for p in ["login", "signin", "sign-in", "auth", "sso", "accounts"]):
            return True
        body = await page.inner_text("body")
        matches = sum(1 for ind in LOGIN_INDICATORS if ind in body.lower()[:3000])
        return matches >= 3
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════
# TOOL IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════════════════════════


async def browser_navigate(url: str, wait_for: str = "domcontentloaded", timeout: int = 15000) -> ToolResult:
    """Navigate to a URL. Returns page info + accessibility snapshot with @refs."""
    global _last_snapshot
    try:
        page = await _get_page()
        try:
            response = await page.goto(url, wait_until=wait_for, timeout=timeout)
        except Exception:
            # SPA or slow page — grab whatever loaded so far
            response = None
        await page.wait_for_load_state("domcontentloaded", timeout=5000)

        # Build ref map from accessibility tree
        refs = await _build_ref_map(page)
        _last_snapshot = refs

        is_login = await _detect_login(page)
        snapshot_text = _snapshot_to_text(refs)

        # Truncate snapshot for LLM context
        if len(snapshot_text) > 4000:
            snapshot_text = snapshot_text[:4000] + "\n... (truncated, use browser_snapshot for full)"

        data = {
            "url": page.url,
            "title": await page.title(),
            "status_code": response.status if response else None,
            "elements": len(refs),
            "interactive": sum(1 for r in refs.values() if r.get("interactive")),
            "snapshot": snapshot_text,
        }

        if is_login:
            data["login_required"] = True
            data["message"] = "Login page detected. the user can log in manually — session will persist."

        return ToolResult(success=True, data=data)
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.NETWORK_ERROR,
            message=f"Navigation failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


async def browser_snapshot(diff: bool = False) -> ToolResult:
    """Get the current page's accessibility snapshot with @refs.

    Args:
        diff: If True, show what changed since last snapshot.
    """
    global _last_snapshot
    try:
        page = await _get_page()
        old_snapshot = _last_snapshot

        refs = await _build_ref_map(page)
        snapshot_text = _snapshot_to_text(refs)

        data = {
            "url": page.url,
            "title": await page.title(),
            "elements": len(refs),
            "interactive": sum(1 for r in refs.values() if r.get("interactive")),
            "snapshot": snapshot_text,
        }

        if diff and old_snapshot:
            diff_result = _diff_snapshots(old_snapshot, refs)
            data["diff"] = diff_result

        _last_snapshot = refs
        return ToolResult(success=True, data=data)
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=f"Snapshot failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


async def browser_click(ref: str, confirm_dangerous: bool = False) -> ToolResult:
    """Click an element by @ref (e.g. @e5) or fallback CSS selector.

    Args:
        ref: Element ref like @e5, or CSS selector as fallback.
        confirm_dangerous: Required True for pay/delete/submit buttons.
    """
    global _last_snapshot
    try:
        page = await _get_page()

        if ref.startswith("@e"):
            # Ref-based click
            locator = await _resolve_ref(page, ref)
            if not locator:
                return ToolResult(success=False, error=ToolError(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Ref {ref} not found. Run browser_snapshot to refresh refs.",
                    severity=Severity.LOW, recoverable=True))

            # Safety check
            entry = _ref_map.get(ref, {})
            name_lower = (entry.get("name") or "").lower()
            if any(d in name_lower for d in DANGEROUS_ACTIONS) and not confirm_dangerous:
                return ToolResult(success=True, data={
                    "blocked": True,
                    "ref": ref,
                    "element": f"[{entry['role']}] \"{entry.get('name', '')}\"",
                    "reason": "Dangerous action detected. Set confirm_dangerous=True to proceed.",
                })

            await locator.click(timeout=10000)
        else:
            # CSS selector fallback
            await page.click(ref, timeout=10000)

        await asyncio.sleep(0.5)  # Let page settle

        # Rebuild refs after click (page may have changed)
        refs = await _build_ref_map(page)
        _last_snapshot = refs

        return ToolResult(success=True, data={
            "clicked": ref,
            "url": page.url,
            "title": await page.title(),
            "elements_after": len(refs),
        })
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=f"Click failed on {ref}: {e}",
            severity=Severity.MEDIUM, recoverable=True))


async def browser_fill(ref: str, value: str) -> ToolResult:
    """Fill a form field by @ref or CSS selector.

    Args:
        ref: Element ref like @e3, or CSS selector as fallback.
        value: Text to fill in.
    """
    try:
        page = await _get_page()

        if ref.startswith("@e"):
            locator = await _resolve_ref(page, ref)
            if not locator:
                return ToolResult(success=False, error=ToolError(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Ref {ref} not found. Run browser_snapshot to refresh.",
                    severity=Severity.LOW, recoverable=True))
            await locator.fill(value, timeout=10000)
        else:
            await page.fill(ref, value, timeout=10000)

        return ToolResult(success=True, data={"filled": ref, "value": value})
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=f"Fill failed on {ref}: {e}",
            severity=Severity.MEDIUM, recoverable=True))


async def browser_type(ref: str, text: str, delay: int = 50) -> ToolResult:
    """Type text character by character. Use for JS-heavy inputs (React, autocomplete).

    Args:
        ref: Element ref like @e3, or CSS selector.
        text: Text to type.
        delay: Milliseconds between keystrokes (default 50).
    """
    try:
        page = await _get_page()

        if ref.startswith("@e"):
            locator = await _resolve_ref(page, ref)
            if not locator:
                return ToolResult(success=False, error=ToolError(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Ref {ref} not found.",
                    severity=Severity.LOW, recoverable=True))
            await locator.press_sequentially(text, delay=delay, timeout=10000)
        else:
            await page.type(ref, text, delay=delay, timeout=10000)

        return ToolResult(success=True, data={"typed": ref, "text": text})
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=f"Type failed on {ref}: {e}",
            severity=Severity.MEDIUM, recoverable=True))


async def browser_screenshot(full_page: bool = False) -> ToolResult:
    """Take a screenshot of the current page."""
    try:
        page = await _get_page()

        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = str(SCREENSHOT_DIR / f"browser_{ts}.png")

        await page.screenshot(path=save_path, full_page=full_page)

        return ToolResult(success=True, data={
            "saved_path": save_path,
            "url": page.url,
            "title": await page.title(),
        })
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=f"Screenshot failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


async def browser_get_text(ref: str = None) -> ToolResult:
    """Extract text from the page or a specific element.

    Args:
        ref: Element ref or CSS selector. Default: entire page body.
    """
    try:
        page = await _get_page()

        if ref and ref.startswith("@e"):
            locator = await _resolve_ref(page, ref)
            if not locator:
                return ToolResult(success=False, error=ToolError(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Ref {ref} not found.",
                    severity=Severity.LOW, recoverable=True))
            text = await locator.inner_text(timeout=10000)
        elif ref:
            text = await page.inner_text(ref, timeout=10000)
        else:
            text = await page.inner_text("body", timeout=10000)

        # Truncate for LLM context
        if len(text) > 8000:
            text = text[:8000] + "\n... [truncated]"

        return ToolResult(success=True, data={
            "text": text,
            "url": page.url,
            "length": len(text),
        })
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=f"Text extraction failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


async def browser_check(ref: str, checked: bool = True) -> ToolResult:
    """Tick or untick a checkbox/radio by @ref or CSS selector."""
    try:
        page = await _get_page()

        if ref.startswith("@e"):
            locator = await _resolve_ref(page, ref)
            if not locator:
                return ToolResult(success=False, error=ToolError(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Ref {ref} not found.",
                    severity=Severity.LOW, recoverable=True))
            if checked:
                await locator.check(timeout=10000)
            else:
                await locator.uncheck(timeout=10000)
        else:
            if checked:
                await page.check(ref, timeout=10000)
            else:
                await page.uncheck(ref, timeout=10000)

        return ToolResult(success=True, data={"ref": ref, "checked": checked})
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=f"Check failed on {ref}: {e}",
            severity=Severity.MEDIUM, recoverable=True))


async def browser_select(ref: str, value: str) -> ToolResult:
    """Select an option from a dropdown by @ref or CSS selector."""
    try:
        page = await _get_page()

        if ref.startswith("@e"):
            locator = await _resolve_ref(page, ref)
            if not locator:
                return ToolResult(success=False, error=ToolError(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Ref {ref} not found.",
                    severity=Severity.LOW, recoverable=True))
            # Try by label first, then by value
            try:
                await locator.select_option(label=value, timeout=10000)
            except Exception:
                await locator.select_option(value=value, timeout=10000)
        else:
            try:
                await page.select_option(ref, label=value, timeout=10000)
            except Exception:
                await page.select_option(ref, value=value, timeout=10000)

        return ToolResult(success=True, data={"ref": ref, "selected": value})
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=f"Select failed on {ref}: {e}",
            severity=Severity.MEDIUM, recoverable=True))


async def browser_scroll(direction: str = "down", pixels: int = 500) -> ToolResult:
    """Scroll the page."""
    try:
        page = await _get_page()

        if direction == "top":
            await page.evaluate("window.scrollTo(0, 0)")
        elif direction == "bottom":
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        elif direction == "up":
            await page.evaluate(f"window.scrollBy(0, -{pixels})")
        else:
            await page.evaluate(f"window.scrollBy(0, {pixels})")

        return ToolResult(success=True, data={"scrolled": direction, "pixels": pixels})
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=f"Scroll failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


async def browser_execute_js(script: str) -> ToolResult:
    """Execute JavaScript on the current page."""
    try:
        page = await _get_page()
        result = await page.evaluate(script)
        return ToolResult(success=True, data={"result": result})
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=f"JS execution failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


async def browser_back() -> ToolResult:
    """Go back to the previous page."""
    global _last_snapshot
    try:
        page = await _get_page()
        await page.go_back(timeout=15000)

        refs = await _build_ref_map(page)
        _last_snapshot = refs

        return ToolResult(success=True, data={
            "url": page.url,
            "title": await page.title(),
            "elements": len(refs),
        })
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=f"Back navigation failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


async def browser_upload(ref: str, file_path: str) -> ToolResult:
    """Upload a file to a file input by @ref or CSS selector."""
    try:
        page = await _get_page()

        if not Path(file_path).exists():
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.NOT_FOUND,
                message=f"File not found: {file_path}",
                severity=Severity.LOW, recoverable=False))

        if ref.startswith("@e"):
            locator = await _resolve_ref(page, ref)
            if not locator:
                return ToolResult(success=False, error=ToolError(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Ref {ref} not found.",
                    severity=Severity.LOW, recoverable=True))
            await locator.set_input_files(file_path, timeout=10000)
        else:
            await page.set_input_files(ref, file_path, timeout=10000)

        return ToolResult(success=True, data={"uploaded": file_path, "to": ref})
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=f"Upload failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


async def browser_fill_form(fields: dict) -> ToolResult:
    """Fill multiple form fields in one call. Keys are @refs or CSS selectors.

    Args:
        fields: Dict of ref/selector → value. E.g. {"@e3": "John", "@e5": "john@example.com"}
    """
    try:
        page = await _get_page()
        filled = []
        errors = []

        for ref, value in fields.items():
            try:
                if ref.startswith("@e"):
                    locator = await _resolve_ref(page, ref)
                    if locator:
                        await locator.fill(str(value), timeout=10000)
                        filled.append(ref)
                    else:
                        errors.append(f"{ref}: not found")
                else:
                    await page.fill(ref, str(value), timeout=10000)
                    filled.append(ref)
            except Exception as e:
                errors.append(f"{ref}: {e}")

        return ToolResult(success=len(filled) > 0, data={
            "filled": filled,
            "errors": errors if errors else None,
            "count": len(filled),
        })
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=f"Form fill failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


async def browser_wait_for_login(timeout: int = 120) -> ToolResult:
    """Wait for the user to log in manually. Watches for URL change."""
    try:
        page = await _get_page()
        start_url = page.url

        for _ in range(timeout * 2):
            await asyncio.sleep(0.5)
            if page.url != start_url:
                is_still_login = await _detect_login(page)
                if not is_still_login:
                    refs = await _build_ref_map(page)
                    return ToolResult(success=True, data={
                        "logged_in": True,
                        "url": page.url,
                        "title": await page.title(),
                        "elements": len(refs),
                    })

        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.TIMEOUT,
            message=f"Login timeout after {timeout}s",
            severity=Severity.MEDIUM, recoverable=True))
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=f"Login wait failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


async def browser_close() -> ToolResult:
    """Close the browser and free resources."""
    global _playwright, _context, _page, _last_snapshot, _ref_map
    try:
        if _context:
            await _context.close()
        if _playwright:
            await _playwright.stop()
        _playwright = None
        _context = None
        _page = None
        _last_snapshot = None
        _ref_map = {}
        return ToolResult(success=True, data={"message": "Browser closed."})
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=f"Close failed: {e}",
            severity=Severity.LOW, recoverable=False))


# ═══════════════════════════════════════════════════════════════════════════
# TOOL SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════

TOOL_SCHEMAS = {
    "browser_navigate": {
        "fn": browser_navigate,
        "schema": {
            "type": "function",
            "function": {
                "name": "browser_navigate",
                "description": (
                    "Navigate browser to a URL. Returns page title, URL, and an accessibility "
                    "snapshot with @ref labels for every interactive element. Use @refs with "
                    "browser_click, browser_fill, etc. instead of CSS selectors."
                ),
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
    "browser_snapshot": {
        "fn": browser_snapshot,
        "schema": {
            "type": "function",
            "function": {
                "name": "browser_snapshot",
                "description": (
                    "Get current page's accessibility snapshot with @ref labels. "
                    "Shows all interactive elements (buttons, links, inputs, etc.) with their refs. "
                    "Use diff=True to see what changed since last snapshot."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "diff": {
                            "type": "boolean",
                            "description": "Show what changed since last snapshot (default: false)",
                        },
                    },
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
                "description": (
                    "Click an element by @ref (e.g. @e5) from the snapshot. "
                    "Falls back to CSS selector if not a @ref. "
                    "Dangerous buttons (pay, delete, submit) need confirm_dangerous=True."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "string", "description": "Element @ref (e.g. @e5) or CSS selector"},
                        "confirm_dangerous": {"type": "boolean", "description": "Required for pay/delete/submit buttons"},
                    },
                    "required": ["ref"],
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
                "description": "Fill a form field by @ref or CSS selector.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "string", "description": "Element @ref (e.g. @e3) or CSS selector"},
                        "value": {"type": "string", "description": "Text to fill in"},
                    },
                    "required": ["ref", "value"],
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
                "description": "Type text character by character. Use for JS-heavy inputs (React, autocomplete, search bars).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "string", "description": "Element @ref or CSS selector"},
                        "text": {"type": "string", "description": "Text to type"},
                        "delay": {"type": "integer", "description": "Delay between keystrokes in ms (default 50)"},
                    },
                    "required": ["ref", "text"],
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
                "description": "Screenshot the current browser page.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "full_page": {"type": "boolean", "description": "Capture full scrollable page (default false)"},
                    },
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
                "description": "Extract text from the page or a specific element by @ref.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "string", "description": "Element @ref or CSS selector (default: entire page)"},
                    },
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
                "description": "Tick or untick a checkbox/radio by @ref.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "string", "description": "Element @ref or CSS selector"},
                        "checked": {"type": "boolean", "description": "True to tick, False to untick (default True)"},
                    },
                    "required": ["ref"],
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
                "description": "Select an option from a dropdown by @ref.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "string", "description": "Element @ref or CSS selector"},
                        "value": {"type": "string", "description": "Option text or value to select"},
                    },
                    "required": ["ref", "value"],
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
                "description": "Scroll the page. Use 'bottom' for footer, 'top' to go back up.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "direction": {
                            "type": "string",
                            "enum": ["up", "down", "top", "bottom"],
                            "description": "Scroll direction (default: down)",
                        },
                        "pixels": {"type": "integer", "description": "Pixels to scroll (default 500)"},
                    },
                },
            },
        },
    },
    "browser_elements": {
        "fn": browser_snapshot,  # browser_elements is now browser_snapshot
        "schema": {
            "type": "function",
            "function": {
                "name": "browser_elements",
                "description": "List all interactive elements on the page with @ref labels. Alias for browser_snapshot.",
                "parameters": {
                    "type": "object",
                    "properties": {},
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
                "description": "Execute JavaScript on the current page.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "script": {"type": "string", "description": "JavaScript code to execute"},
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
                "description": "Go back to the previous page.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    },
    "browser_upload": {
        "fn": browser_upload,
        "schema": {
            "type": "function",
            "function": {
                "name": "browser_upload",
                "description": "Upload a file to a file input by @ref.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "string", "description": "Element @ref or CSS selector of file input"},
                        "file_path": {"type": "string", "description": "Absolute path to the file"},
                    },
                    "required": ["ref", "file_path"],
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
                "description": "Fill multiple form fields in one call. Keys are @refs or CSS selectors.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "fields": {
                            "type": "object",
                            "description": "Dict of @ref/selector → value. E.g. {\"@e3\": \"John\", \"@e5\": \"john@example.com\"}",
                        },
                    },
                    "required": ["fields"],
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
                "description": "Wait for the user to log in manually. Watches for URL change.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "timeout": {"type": "integer", "description": "Max seconds to wait (default 120)"},
                    },
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
                "parameters": {"type": "object", "properties": {}},
            },
        },
    },
    # Kept for backwards compat — browser_discover_form is now browser_snapshot
    "browser_discover_form": {
        "fn": browser_snapshot,
        "schema": {
            "type": "function",
            "function": {
                "name": "browser_discover_form",
                "description": "Discover all form fields on the page. Now returns full accessibility snapshot with @refs.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    },
}
