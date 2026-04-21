"""WhatsApp tools — send messages, read chats, search via Baileys bridge.

Talks to the Node.js Baileys HTTP bridge at localhost:3100.
The bridge handles WhatsApp Web multi-device auth + message send/receive.
Bridge auto-starts when any WhatsApp tool is called.
"""

import asyncio
import re
import subprocess
import logging
import httpx
from pathlib import Path
from typing import Optional

from friday.core.types import ToolResult, ToolError, ErrorCode, Severity

logger = logging.getLogger(__name__)

BRIDGE_URL = "http://localhost:3100"
_client = None
_bridge_process = None

# Look for server.js in repo first, then ~/.friday/whatsapp
_REPO_BRIDGE = Path(__file__).parent.parent / "whatsapp" / "server.js"
_HOME_BRIDGE = Path.home() / ".friday" / "whatsapp" / "server.js"
BRIDGE_DIR = _REPO_BRIDGE.parent if _REPO_BRIDGE.exists() else _HOME_BRIDGE.parent


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(base_url=BRIDGE_URL, timeout=15.0)
    return _client


def _kill_stale_bridge():
    """Kill any existing node server.js processes hogging port 3100."""
    import os
    my_pid = str(os.getpid())
    try:
        result = subprocess.run(
            ["lsof", "-ti", ":3100"],
            capture_output=True, text=True, timeout=5,
        )
        if result.stdout.strip():
            pids = result.stdout.strip().split("\n")
            for pid in pids:
                pid = pid.strip()
                if pid == my_pid:
                    continue  # Don't kill ourselves (httpx keep-alive socket)
                try:
                    subprocess.run(["kill", pid], timeout=5)
                    logger.info(f"[WhatsApp] Killed stale process on port 3100 (PID {pid})")
                except Exception:
                    pass
            import time
            time.sleep(1)
    except Exception:
        pass


async def _ensure_bridge() -> bool:
    """Auto-start the bridge if it's not running. Returns True if bridge is up."""
    global _bridge_process

    # Check if already running (any response = bridge is alive)
    try:
        r = await _get_client().get("/status")
        data = r.json()
        if data.get("status") in ("connected", "qr_pending", "disconnected"):
            return True
    except Exception:
        pass

    # Not responding at all — kill any stale processes on the port before starting fresh
    _kill_stale_bridge()

    # Not running — try to start it
    server_js = BRIDGE_DIR / "server.js"
    node_modules = BRIDGE_DIR / "node_modules"

    if not server_js.exists():
        return False

    if not node_modules.exists():
        # Install deps first
        logger.info("[WhatsApp] Installing bridge dependencies...")
        proc = subprocess.run(
            ["npm", "install"],
            cwd=str(BRIDGE_DIR),
            capture_output=True, timeout=60,
        )
        if proc.returncode != 0:
            logger.error(f"[WhatsApp] npm install failed: {proc.stderr.decode()[:200]}")
            return False

    # Start bridge in background
    logger.info("[WhatsApp] Starting bridge...")
    _bridge_process = subprocess.Popen(
        ["node", "server.js"],
        cwd=str(BRIDGE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait up to 10s for it to come up (needs time to connect to WhatsApp)
    for _ in range(20):
        await asyncio.sleep(0.5)
        try:
            r = await _get_client().get("/status")
            data = r.json()
            if data.get("status") in ("connected", "qr_pending"):
                logger.info(f"[WhatsApp] Bridge started (status: {data['status']})")
                return True
        except Exception:
            continue

    logger.warning("[WhatsApp] Bridge started but not responding")
    return False


async def _bridge_ok() -> bool:
    """Check if the WhatsApp bridge is running and connected."""
    try:
        r = await _get_client().get("/status")
        data = r.json()
        return data.get("status") == "connected"
    except Exception:
        return False


async def _bridge_status() -> dict:
    """Get full bridge status, auto-starting if needed."""
    # Try to auto-start
    await _ensure_bridge()

    try:
        r = await _get_client().get("/status")
        return r.json()
    except httpx.ConnectError:
        return {"status": "bridge_offline", "error": "WhatsApp bridge not running and auto-start failed. Run manually: cd friday/whatsapp && node server.js"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Contact resolution via macOS Contacts ──────────────────────────────────

async def _resolve_to_phone(name: str) -> str | None:
    """Resolve a contact name to a phone number via macOS Contacts.

    WhatsApp history sync doesn't include contact names from the phone,
    so we use the same Contacts.app lookup as iMessage to find the number.
    """
    # Already a phone number
    if re.match(r'^[\+\d\s\-\(\)]+$', name.strip()) and len(name.strip()) >= 7:
        return name.strip()

    try:
        from friday.tools.imessage_tools import search_contacts, _best_contact_match, _parse_phone_entries
        result = await search_contacts(name)
        if result.success and result.data:
            contacts = result.data.get("contacts", [])
            if contacts:
                c = _best_contact_match(contacts, name)
                phones = _parse_phone_entries(c.get("phones", ""))
                if phones:
                    # Prefer mobile
                    for preferred in ("mobile", "iphone", "cell"):
                        for p in phones:
                            if preferred in p["label"]:
                                return p["number"]
                    return phones[0]["number"]
    except Exception as e:
        logger.debug(f"[WhatsApp] Contact resolution failed: {e}")

    return None


# ── Send WhatsApp message ──────────────────────────────────────────────────

async def send_whatsapp(
    recipient: str,
    message: str,
    confirm: bool = False,
) -> ToolResult:
    """Send a WhatsApp message via the Baileys bridge.

    Args:
        recipient: Phone number (with country code, e.g. +44...), contact name, or WhatsApp JID.
        message: The message text to send.
        confirm: Must be True to actually send. If False, shows preview only.
    """
    if not message.strip():
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.VALIDATION_ERROR,
            message="Message cannot be empty",
            severity=Severity.LOW, recoverable=True))

    status = await _bridge_status()
    if status.get("status") not in ("connected", "disconnected"):
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=status.get("error", "WhatsApp bridge not running"),
            severity=Severity.HIGH, recoverable=True))

    if not confirm:
        return ToolResult(success=True, data={
            "preview": True,
            "recipient": recipient,
            "message": message,
            "note": "Set confirm=True to send. Call send_whatsapp again with confirm=True.",
        })

    try:
        # Resolve name to phone via Contacts if needed
        resolved = recipient
        if not re.match(r'^[\+\d\s\-\(\)]+$', recipient.strip()) and "@" not in recipient:
            phone = await _resolve_to_phone(recipient)
            if phone:
                resolved = phone

        r = await _get_client().post("/send", json={"to": resolved, "message": message})
        data = r.json()
        if r.status_code == 200 and data.get("success"):
            return ToolResult(success=True, data={
                "sent": True,
                "recipient": recipient,
                "to_jid": data.get("to"),
                "message": message,
                "message_id": data.get("id"),
            })
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=data.get("error", "Failed to send WhatsApp message"),
            severity=Severity.HIGH, recoverable=True))
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=str(e),
            severity=Severity.HIGH, recoverable=False))


# ── Read WhatsApp messages ─────────────────────────────────────────────────

async def read_whatsapp(
    contact: str = None,
    limit: int = 20,
) -> ToolResult:
    """Read recent WhatsApp messages from a contact or across all chats.

    Args:
        contact: Contact name or phone number. If None, returns recent chats list.
        limit: Number of messages to return (default 20).
    """
    status = await _bridge_status()
    if status.get("status") not in ("connected", "disconnected"):
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=status.get("error", "WhatsApp bridge not running"),
            severity=Severity.HIGH, recoverable=True))

    try:
        if not contact:
            # No contact specified — return recent chats
            r = await _get_client().get("/chats", params={"limit": limit})
            data = r.json()
            return ToolResult(success=True, data={
                "chats": data.get("chats", []),
                "count": data.get("count", 0),
            })

        # Read messages from a specific contact
        # First try name match in bridge
        r = await _get_client().get("/messages", params={"contact": contact, "limit": limit})
        if r.status_code == 404:
            # Try as phone number
            r = await _get_client().get("/messages", params={"phone": contact, "limit": limit})
        if r.status_code == 404:
            # Resolve via macOS Contacts → phone number → bridge
            phone = await _resolve_to_phone(contact)
            if phone:
                r = await _get_client().get("/messages", params={"phone": phone, "limit": limit})

        data = r.json()
        if r.status_code != 200:
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.NOT_FOUND,
                message=data.get("error", f"No messages found for {contact}"),
                severity=Severity.LOW, recoverable=True,
                context={"hint": data.get("hint")}))

        messages = data.get("messages", [])
        # Add direction labels like iMessage tools
        for msg in messages:
            msg["direction"] = "sent" if msg.get("from_me") else "received"
            msg["from"] = "me" if msg.get("from_me") else (msg.get("push_name") or data.get("name") or contact)

        # Check if unreplied
        unreplied = bool(messages and not messages[-1].get("from_me"))

        return ToolResult(success=True, data={
            "messages": messages,
            "count": len(messages),
            "contact": data.get("name") or contact,
            "jid": data.get("jid"),
            "unreplied": unreplied,
        })
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=str(e),
            severity=Severity.HIGH, recoverable=False))


# ── Search WhatsApp messages ───────────────────────────────────────────────

async def search_whatsapp(
    query: str,
    limit: int = 20,
) -> ToolResult:
    """Search WhatsApp messages across all chats.

    Args:
        query: Text to search for in messages.
        limit: Max results (default 20).
    """
    status = await _bridge_status()
    if status.get("status") not in ("connected", "disconnected"):
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=status.get("error", "WhatsApp bridge not running"),
            severity=Severity.HIGH, recoverable=True))

    try:
        r = await _get_client().get("/search", params={"query": query, "limit": limit})
        data = r.json()
        if r.status_code != 200:
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=data.get("error", "Search failed"),
                severity=Severity.MEDIUM, recoverable=True))

        results = data.get("results", [])
        for msg in results:
            msg["direction"] = "sent" if msg.get("from_me") else "received"
            msg["from"] = "me" if msg.get("from_me") else (msg.get("push_name") or msg.get("chat_name") or "unknown")

        return ToolResult(success=True, data={
            "results": results,
            "count": len(results),
            "query": query,
        })
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=str(e),
            severity=Severity.HIGH, recoverable=False))


# ── WhatsApp connection status ─────────────────────────────────────────────

async def whatsapp_status() -> ToolResult:
    """Check WhatsApp connection status. Shows if connected, QR pending, or offline."""
    data = await _bridge_status()
    return ToolResult(success=True, data=data)


# ═══════════════════════════════════════════════════════════════════════════
# TOOL SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════

TOOL_SCHEMAS = {
    "send_whatsapp": {
        "fn": send_whatsapp,
        "schema": {"type": "function", "function": {
            "name": "send_whatsapp",
            "description": (
                "Send a WhatsApp message to someone. Can use phone number (with country code), "
                "contact name, or WhatsApp JID. Set confirm=True to actually send — "
                "without it, returns a preview only."
            ),
            "parameters": {"type": "object", "properties": {
                "recipient": {
                    "type": "string",
                    "description": "Phone number with country code (e.g. '+447555834656'), contact name, or WhatsApp JID",
                },
                "message": {
                    "type": "string",
                    "description": "The message text to send",
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Must be True to actually send. False = preview only (default: false)",
                },
            }, "required": ["recipient", "message"]},
        }},
    },
    "read_whatsapp": {
        "fn": read_whatsapp,
        "schema": {"type": "function", "function": {
            "name": "read_whatsapp",
            "description": (
                "Read recent WhatsApp messages. With a contact name or phone number, "
                "returns messages from that chat. Without a contact, returns a list of "
                "recent chats. Use this to check WhatsApp conversations."
            ),
            "parameters": {"type": "object", "properties": {
                "contact": {
                    "type": "string",
                    "description": "Contact name or phone number (optional — omit for recent chats list)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of messages to return (default 20)",
                },
            }, "required": []},
        }},
    },
    "search_whatsapp": {
        "fn": search_whatsapp,
        "schema": {"type": "function", "function": {
            "name": "search_whatsapp",
            "description": (
                "Search WhatsApp messages across all chats for specific text. "
                "Returns matching messages with chat context."
            ),
            "parameters": {"type": "object", "properties": {
                "query": {
                    "type": "string",
                    "description": "Text to search for in WhatsApp messages",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default 20)",
                },
            }, "required": ["query"]},
        }},
    },
    "whatsapp_status": {
        "fn": whatsapp_status,
        "schema": {"type": "function", "function": {
            "name": "whatsapp_status",
            "description": (
                "Check WhatsApp connection status. Shows if connected, QR code pending "
                "(need to scan), or bridge offline."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
    },
}
