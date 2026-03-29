"""iMessage & FaceTime tools — send texts, read conversations, initiate calls.

Uses AppleScript to control Messages.app and FaceTime URL schemes.
Reads message history from ~/Library/Messages/chat.db (requires Full Disk Access).
Contact resolution via Contacts.app (name → phone number/email).

Requirements:
  - macOS with Messages.app signed into iMessage
  - Contacts.app for name resolution
  - FaceTime.app for calls
  - Full Disk Access for reading message history
"""

import asyncio
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from friday.core.types import ToolResult, ToolError, ErrorCode, Severity

# iMessage database
CHAT_DB = Path.home() / "Library" / "Messages" / "chat.db"

# Apple's CoreData epoch (2001-01-01) in nanoseconds
IMESSAGE_EPOCH = 978307200


# ── Helper: run AppleScript ──────────────────────────────────────────────────

async def _run_applescript(script: str, timeout: int = 15) -> tuple[bool, str]:
    """Run AppleScript, return (success, output_or_error)."""
    proc = await asyncio.create_subprocess_exec(
        "osascript", "-",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(input=script.encode()),
        timeout=timeout,
    )
    if proc.returncode == 0:
        return True, stdout.decode(errors="replace").strip()
    return False, stderr.decode(errors="replace").strip()


# ── Read iMessage history ────────────────────────────────────────────────────

def _imsg_timestamp_to_str(ns_timestamp: int) -> str:
    """Convert iMessage nanosecond timestamp to readable datetime."""
    if not ns_timestamp:
        return "unknown"
    try:
        seconds = ns_timestamp / 1_000_000_000 + IMESSAGE_EPOCH
        dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError):
        return "unknown"


def _extract_text_from_attributed_body(blob: bytes) -> str | None:
    """Extract plain text from NSAttributedString binary blob.

    iMessage stores some messages (especially with emoji or rich text)
    only in attributedBody as a serialized NSAttributedString. The text
    follows the 'NSString' marker with a length prefix byte.
    """
    if not blob:
        return None
    try:
        idx = blob.find(b"NSString")
        if idx < 0:
            return None
        # After 'NSString' + some overhead bytes, find the length-prefixed text
        # Format: NSString [overhead] [length_byte] [utf8_text]
        search = blob[idx + 8 : idx + 300]
        for i in range(min(8, len(search))):
            length = search[i]
            if 0 < length < 250 and i + 1 + length <= len(search):
                candidate = search[i + 1 : i + 1 + length]
                try:
                    text = candidate.decode("utf-8")
                    # Verify it's real text (not binary garbage)
                    if any(c.isalnum() for c in text):
                        return text
                except UnicodeDecodeError:
                    continue
    except Exception:
        pass
    return None


async def read_imessages(
    contact: str = None,
    limit: int = 20,
    search: str = None,
    direction: str = None,
) -> ToolResult:
    """Read recent iMessage conversations from the local database.

    Args:
        contact: Filter by contact name, phone number, or email. If None, shows recent messages across all chats.
        limit: Number of messages to return (default 20).
        search: Search for messages containing this text.
        direction: Filter by direction — "received" (from them) or "sent" (from me). None = both.

    Requires Full Disk Access for Terminal/Python.
    """
    # If contact is a name (not a phone number or email), resolve via Contacts.app
    # to get their actual phone/email identifiers for querying chat.db
    resolved_ids = []
    display_name = None
    if contact:
        is_phone = re.match(r'^[\+\d\s\-\(\)]+$', contact.strip()) and len(contact.strip()) >= 7
        is_email = "@" in contact
        if not is_phone and not is_email:
            result = await search_contacts(contact)
            if result.success and result.data:
                contacts_found = result.data.get("contacts", [])
                if contacts_found:
                    c = _best_contact_match(contacts_found, contact)
                    display_name = c.get("name", contact)
                    # Collect all phone numbers and emails for this contact
                    for entry in _parse_phone_entries(c.get("phones", "")):
                        resolved_ids.append(entry["number"])
                    for entry in _parse_email_entries(c.get("emails", "")):
                        resolved_ids.append(entry["email"])

    def _read():
        if not CHAT_DB.exists():
            return None, "iMessage database not found.", False

        try:
            conn = sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Build query — join message, handle, and chat tables
            conditions = []
            params = []

            if contact:
                if resolved_ids:
                    # Match against any of the contact's known phone numbers / emails
                    # Use both h.id (handle) and c.chat_identifier (chat) for robustness
                    all_clauses = []
                    for rid in resolved_ids:
                        rid = rid.strip()
                        if "@" in rid:
                            # Email — use as-is
                            clean = rid
                        else:
                            # Phone — strip everything except digits and leading +
                            clean = re.sub(r'[^\d+]', '', rid)
                        all_clauses.append("h.id LIKE ?")
                        params.append(f"%{clean}%")
                        all_clauses.append("c.chat_identifier LIKE ?")
                        params.append(f"%{clean}%")
                    conditions.append(f"({' OR '.join(all_clauses)})")
                else:
                    # Fallback: search raw identifier (phone number, email, or partial name)
                    conditions.append("(h.id LIKE ? OR c.chat_identifier LIKE ?)")
                    wildcard = f"%{contact}%"
                    params.extend([wildcard, wildcard])

            if search:
                conditions.append("m.text LIKE ?")
                params.append(f"%{search}%")

            if direction == "received":
                conditions.append("m.is_from_me = 0")
            elif direction == "sent":
                conditions.append("m.is_from_me = 1")

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            query = f"""
                SELECT
                    m.rowid,
                    m.text,
                    m.attributedBody,
                    m.date as msg_date,
                    m.is_from_me,
                    m.date_read,
                    m.cache_has_attachments,
                    h.id as sender_id,
                    c.chat_identifier,
                    c.display_name as chat_name
                FROM message m
                LEFT JOIN handle h ON m.handle_id = h.rowid
                LEFT JOIN chat_message_join cmj ON m.rowid = cmj.message_id
                LEFT JOIN chat c ON cmj.chat_id = c.rowid
                {where}
                ORDER BY m.date DESC
                LIMIT ?
            """
            params.append(limit)
            cursor.execute(query, params)
            rows = cursor.fetchall()

            # Look up attachment types for messages that have them
            attachment_types = {}
            msg_ids_with_attachments = [
                row["rowid"] for row in rows
                if row["cache_has_attachments"] and not row["text"]
            ]
            if msg_ids_with_attachments:
                placeholders = ",".join("?" * len(msg_ids_with_attachments))
                att_query = f"""
                    SELECT maj.message_id, a.mime_type, a.filename
                    FROM message_attachment_join maj
                    JOIN attachment a ON maj.attachment_id = a.rowid
                    WHERE maj.message_id IN ({placeholders})
                """
                att_rows = cursor.execute(att_query, msg_ids_with_attachments).fetchall()
                for ar in att_rows:
                    mid = ar["message_id"]
                    mime = ar["mime_type"] or ""
                    fname = ar["filename"] or ""
                    if "image" in mime:
                        attachment_types[mid] = "photo"
                    elif "video" in mime:
                        attachment_types[mid] = "video"
                    elif "audio" in mime:
                        attachment_types[mid] = "voice message"
                    elif "pdf" in mime or "document" in mime:
                        attachment_types[mid] = "document"
                    elif fname:
                        attachment_types[mid] = f"file ({fname.rsplit('/', 1)[-1]})"
                    else:
                        attachment_types[mid] = "attachment"

            conn.close()

            messages = []
            for row in rows:
                # Determine message text — try text column, then attributedBody, then attachment
                text = row["text"]
                if not text:
                    text = _extract_text_from_attributed_body(row["attributedBody"])
                if not text:
                    att_type = attachment_types.get(row["rowid"], "attachment")
                    text = f"[{att_type}]"

                # Use resolved display name instead of raw phone number
                sender = "me"
                if not row["is_from_me"]:
                    sender = display_name or row["sender_id"] or "unknown"
                chat_label = display_name or row["chat_name"] or row["chat_identifier"] or row["sender_id"] or "unknown"

                msg = {
                    "from": sender,
                    "direction": "sent" if row["is_from_me"] else "received",
                    "text": text,
                    "date": _imsg_timestamp_to_str(row["msg_date"]),
                    "chat": chat_label,
                }
                messages.append(msg)

            # Reverse so oldest is first (conversation order)
            messages.reverse()

            # Determine if the conversation has an unreplied message
            # (last message is from them, not from me)
            unreplied = False
            if messages:
                last_msg = messages[-1]
                if last_msg["from"] != "me":
                    unreplied = True

            return messages, None, unreplied

        except sqlite3.OperationalError as e:
            err = str(e)
            if "unable to open" in err or "not permitted" in err or "authorization denied" in err:
                return None, (
                    "Full Disk Access needed. Go to System Settings → Privacy & Security → "
                    "Full Disk Access → add Terminal (or your Python app)."
                ), False
            return None, f"Database error: {err}", False
        except Exception as e:
            return None, f"Failed to read messages: {e}", False

    messages, error, unreplied = await asyncio.to_thread(_read)

    if error:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=error,
            severity=Severity.MEDIUM, recoverable=True))

    if not messages:
        label = f" with {contact}" if contact else ""
        return ToolResult(success=True, data={
            "messages": [],
            "message": f"No messages found{label}.",
        })

    return ToolResult(success=True, data={
        "messages": messages,
        "count": len(messages),
        "contact_filter": contact,
        "unreplied": unreplied,
    })


# ── Contact resolution ───────────────────────────────────────────────────────

def _contacts_applescript(search_name: str) -> str:
    """Build AppleScript to search Contacts by name."""
    safe = search_name.replace('\\', '\\\\').replace('"', '\\"')
    return f'''
tell application "Contacts"
    set matchResults to {{}}
    set searchName to "{safe}"
    set matchingPeople to every person whose name contains searchName

    repeat with p in matchingPeople
        set personName to name of p
        set personPhones to {{}}
        set personEmails to {{}}

        repeat with ph in (every phone of p)
            set end of personPhones to (label of ph) & ": " & (value of ph)
        end repeat

        repeat with em in (every email of p)
            set end of personEmails to (label of em) & ": " & (value of em)
        end repeat

        set phoneStr to ""
        repeat with i from 1 to count of personPhones
            if i > 1 then set phoneStr to phoneStr & " | "
            set phoneStr to phoneStr & (item i of personPhones)
        end repeat

        set emailStr to ""
        repeat with i from 1 to count of personEmails
            if i > 1 then set emailStr to emailStr & " | "
            set emailStr to emailStr & (item i of personEmails)
        end repeat

        set end of matchResults to personName & " ;; " & phoneStr & " ;; " & emailStr
    end repeat

    set output to ""
    repeat with i from 1 to count of matchResults
        if i > 1 then set output to output & linefeed
        set output to output & (item i of matchResults)
    end repeat
    return output
end tell
'''


def _parse_contacts_output(output: str) -> list[dict]:
    """Parse AppleScript contacts output into list of dicts."""
    contacts = []
    for line in output.strip().split("\n"):
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(";;")]
        contact = {
            "name": parts[0] if len(parts) > 0 else "Unknown",
            "phones": parts[1] if len(parts) > 1 and parts[1] else None,
            "emails": parts[2] if len(parts) > 2 and parts[2] else None,
        }
        contacts.append(contact)
    return contacts


async def search_contacts(name: str) -> ToolResult:
    """Search macOS Contacts for a person by name. Returns matching contacts with phone numbers and emails.

    Args:
        name: Name to search for (first, last, or full name).
    """
    try:
        # Ensure Contacts.app is running (AppleScript fails with -600 if it's not)
        proc = await asyncio.create_subprocess_exec(
            "open", "-a", "Contacts", "-g",  # -g = don't bring to foreground
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        await asyncio.sleep(0.5)

        # Try exact phrase first
        ok, output = await _run_applescript(_contacts_applescript(name))
        if not ok:
            # Retry once — Contacts might need more time to initialize
            await asyncio.sleep(1)
            ok, output = await _run_applescript(_contacts_applescript(name))
        if not ok:
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=f"Contacts search failed: {output}",
                severity=Severity.MEDIUM, recoverable=True))

        contacts = _parse_contacts_output(output)

        # If no results, try individual words (longest first) as fallback
        # e.g. "father in law" → try "father", "law" — catches "Father-in-Law"
        # e.g. "Ellen's pap" → try "Ellen", "pap"
        if not contacts:
            words = re.findall(r"[a-zA-Z]+", name)
            # Skip common filler words, search by meaningful ones (longest first)
            skip = {"my", "the", "a", "an", "in", "on", "to", "of", "and", "or", "s"}
            words = sorted([w for w in words if w.lower() not in skip], key=len, reverse=True)
            for word in words:
                if len(word) < 2:
                    continue
                ok2, output2 = await _run_applescript(_contacts_applescript(word))
                if ok2:
                    contacts = _parse_contacts_output(output2)
                    if contacts:
                        break

        if not contacts:
            return ToolResult(success=True, data={
                "contacts": [],
                "message": f"No contacts found matching '{name}'",
            })

        return ToolResult(success=True, data={
            "contacts": contacts,
            "count": len(contacts),
        })

    except asyncio.TimeoutError:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.PROCESS_TIMEOUT,
            message="Contacts search timed out",
            severity=Severity.MEDIUM, recoverable=True))
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=str(e),
            severity=Severity.MEDIUM, recoverable=False))


# ── Resolve contact name to phone number ─────────────────────────────────────

def _best_contact_match(contacts: list[dict], query: str) -> dict:
    """Pick the contact whose name best matches the query.

    Scores by how many query words appear in the contact name.
    On tie, prefers shorter names (closer match to what user typed).
    Falls back to first result if no words match.
    """
    if len(contacts) == 1:
        return contacts[0]

    # Keep all words including "my" — it's meaningful in contact names like "My Bby"
    query_words = set(re.findall(r"[a-zA-Z]+", query.lower()))
    query_words -= {"the", "a", "an", "in", "on", "to", "of", "and", "or"}
    # Also remove standalone "s" from possessives like "Ellen's"
    query_words.discard("s")

    scored = []
    for c in contacts:
        name_lower = c.get("name", "").lower()
        name_alpha = re.findall(r"[a-zA-Z]+", name_lower)
        # Count how many query words appear in the contact name
        word_score = sum(1 for w in query_words if w in name_lower)
        # Tiebreaker: prefer names closer in length to the query (more exact match)
        length_diff = abs(len(name_alpha) - len(query_words))
        scored.append((word_score, -length_diff, c))

    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return scored[0][2]


def _parse_phone_entries(phones_str: str) -> list[dict]:
    """Parse 'mobile: +123 | home: +456' into [{"label": "mobile", "number": "+123"}, ...]."""
    entries = []
    if not phones_str:
        return entries
    for entry in phones_str.split("|"):
        entry = entry.strip()
        if ":" in entry:
            label, number = entry.split(":", 1)
            number = number.strip()
            if number:
                entries.append({"label": label.strip().lower(), "number": number})
    return entries


def _parse_email_entries(emails_str: str) -> list[dict]:
    """Parse 'home: x@y.com | work: a@b.com' into [{"label": "home", "email": "x@y.com"}, ...]."""
    entries = []
    if not emails_str:
        return entries
    for entry in emails_str.split("|"):
        entry = entry.strip()
        if ":" in entry:
            label, email = entry.split(":", 1)
            email = email.strip()
            if email:
                entries.append({"label": label.strip().lower(), "email": email})
    return entries


async def _resolve_recipient(recipient: str) -> tuple[str, str | None]:
    """Resolve a name or number to a phone number/email.

    Returns (resolved_address, display_name) or (original, None) if not found.
    Picks the first available phone number (prefers mobile).
    """
    # Already a phone number or email — use as-is
    if re.match(r'^[\+\d\s\-\(\)]+$', recipient.strip()) and len(recipient.strip()) >= 7:
        return recipient.strip(), None
    if "@" in recipient:
        return recipient.strip(), None

    # Try to resolve via Contacts
    result = await search_contacts(recipient)
    if result.success and result.data:
        contacts = result.data.get("contacts", [])
        if contacts:
            contact = _best_contact_match(contacts, recipient)
            name = contact.get("name", recipient)
            phones = _parse_phone_entries(contact.get("phones", ""))

            # Prefer mobile, then iPhone, then first available
            if phones:
                for preferred in ("mobile", "iphone", "cell"):
                    for p in phones:
                        if preferred in p["label"]:
                            return p["number"], name
                return phones[0]["number"], name

            # Fall back to email
            emails = _parse_email_entries(contact.get("emails", ""))
            if emails:
                return emails[0]["email"], name

    return recipient, None


async def _resolve_all_numbers(recipient: str) -> tuple[list[dict], str | None]:
    """Resolve a contact name to ALL their phone numbers.

    Returns (list_of_numbers, display_name).
    Each number is {"label": "mobile", "number": "+123456"}.
    """
    # Already a phone number — return as single option
    if re.match(r'^[\+\d\s\-\(\)]+$', recipient.strip()) and len(recipient.strip()) >= 7:
        return [{"label": "direct", "number": recipient.strip()}], None
    if "@" in recipient:
        return [{"label": "email", "number": recipient.strip()}], None

    result = await search_contacts(recipient)
    if result.success and result.data:
        contacts = result.data.get("contacts", [])
        if contacts:
            contact = _best_contact_match(contacts, recipient)
            name = contact.get("name", recipient)
            phones = _parse_phone_entries(contact.get("phones", ""))
            if phones:
                return phones, name

    return [], None


# ── Send iMessage ────────────────────────────────────────────────────────────

async def send_imessage(
    recipient: str,
    message: str,
    confirm: bool = False,
) -> ToolResult:
    """Send an iMessage via Messages.app.

    Args:
        recipient: Phone number, email, or contact name (will be resolved via Contacts).
        message: The message text to send.
        confirm: Must be True to actually send. If False, shows preview only.
    """
    if not message.strip():
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.VALIDATION_ERROR,
            message="Message cannot be empty",
            severity=Severity.LOW, recoverable=True))

    # Resolve contact name to address
    address, display_name = await _resolve_recipient(recipient)

    if not confirm:
        return ToolResult(success=True, data={
            "preview": True,
            "recipient": display_name or address,
            "address": address,
            "message": message,
            "note": "Set confirm=True to send. Call send_imessage again with confirm=True.",
        })

    # Escape for AppleScript
    safe_message = message.replace('\\', '\\\\').replace('"', '\\"')
    safe_address = address.replace('\\', '\\\\').replace('"', '\\"')

    script = f'''
tell application "Messages"
    set targetService to 1st account whose service type = iMessage
    set targetBuddy to participant "{safe_address}" of targetService
    send "{safe_message}" to targetBuddy
end tell
'''
    try:
        ok, output = await _run_applescript(script)
        if ok:
            return ToolResult(success=True, data={
                "sent": True,
                "recipient": display_name or address,
                "address": address,
                "message": message,
            })

        # If participant-based approach fails, try buddy-based
        script_alt = f'''
tell application "Messages"
    set targetService to 1st service whose service type = iMessage
    set targetBuddy to buddy "{safe_address}" of targetService
    send "{safe_message}" to targetBuddy
end tell
'''
        ok2, output2 = await _run_applescript(script_alt)
        if ok2:
            return ToolResult(success=True, data={
                "sent": True,
                "recipient": display_name or address,
                "address": address,
                "message": message,
            })

        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=f"Failed to send iMessage: {output2 or output}",
            severity=Severity.HIGH, recoverable=True,
            context={"recipient": address}))

    except asyncio.TimeoutError:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.PROCESS_TIMEOUT,
            message="iMessage send timed out",
            severity=Severity.MEDIUM, recoverable=True))
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=str(e),
            severity=Severity.HIGH, recoverable=False))


# ── FaceTime call ────────────────────────────────────────────────────────────

async def start_facetime(
    recipient: str,
    audio_only: bool = False,
    number: str = None,
) -> ToolResult:
    """Initiate a FaceTime call.

    Args:
        recipient: Phone number, email, or contact name (will be resolved via Contacts).
        audio_only: If True, start audio-only call instead of video.
        number: Specific phone number to call (use when contact has multiple numbers
                and you've already asked which one). Skips contact resolution.
    """
    # If a specific number was provided, use it directly
    if number:
        address = number
        display_name = recipient
    else:
        # Resolve contact — check for multiple numbers
        numbers, display_name = await _resolve_all_numbers(recipient)

        if not numbers:
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.NOT_FOUND,
                message=f"No phone number found for '{recipient}'. Check the name or provide a number directly.",
                severity=Severity.MEDIUM, recoverable=True))

        if len(numbers) > 1:
            # Multiple numbers — return them as choices, don't auto-call
            return ToolResult(success=True, data={
                "needs_choice": True,
                "recipient": display_name or recipient,
                "numbers": numbers,
                "message": f"{display_name or recipient} has {len(numbers)} numbers. Ask Travis which one to call, then call start_facetime again with the chosen number= parameter.",
            })

        # Single number — proceed
        address = numbers[0]["number"]

    # Use URL scheme — most reliable across macOS versions
    scheme = "facetime-audio" if audio_only else "facetime"
    url = f"{scheme}://{address}"

    try:
        proc = await asyncio.create_subprocess_exec(
            "open", url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)

        if proc.returncode == 0:
            call_type = "FaceTime Audio" if audio_only else "FaceTime"
            return ToolResult(success=True, data={
                "calling": True,
                "recipient": display_name or address,
                "address": address,
                "type": call_type,
            })
        else:
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=f"FaceTime failed: {stderr.decode(errors='replace')}",
                severity=Severity.MEDIUM, recoverable=True))

    except asyncio.TimeoutError:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.PROCESS_TIMEOUT,
            message="FaceTime launch timed out",
            severity=Severity.MEDIUM, recoverable=True))
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=str(e),
            severity=Severity.MEDIUM, recoverable=False))


# ═════════════════════════════════════════════════════════════════════════════
# TOOL SCHEMAS
# ═════════════════════════════════════════════════════════════════════════════

TOOL_SCHEMAS = {
    "read_imessages": {
        "fn": read_imessages,
        "schema": {"type": "function", "function": {
            "name": "read_imessages",
            "description": (
                "Read recent iMessage/SMS conversations. Can filter by contact name, "
                "phone number, or email. Can also search message text. Use this to "
                "read a conversation before replying, or to check what someone said. "
                "Requires Full Disk Access."
            ),
            "parameters": {"type": "object", "properties": {
                "contact": {
                    "type": "string",
                    "description": "Filter by contact name, phone number, or email (optional — omit for all recent messages). Pass EXACTLY what the user said — e.g. 'Ellen's pap', 'my bby', 'father in law'.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of messages to return (default 20)",
                },
                "search": {
                    "type": "string",
                    "description": "Search for messages containing this text (optional)",
                },
                "direction": {
                    "type": "string",
                    "enum": ["received", "sent"],
                    "description": "Filter by direction: 'received' = messages FROM them TO Travis, 'sent' = messages FROM Travis TO them. Omit for both directions.",
                },
            }, "required": []},
        }},
    },
    "send_imessage": {
        "fn": send_imessage,
        "schema": {"type": "function", "function": {
            "name": "send_imessage",
            "description": (
                "Send an iMessage to someone. Can use phone number, email, or contact name "
                "(auto-resolved via Contacts). Set confirm=True to actually send — "
                "without it, returns a preview only."
            ),
            "parameters": {"type": "object", "properties": {
                "recipient": {
                    "type": "string",
                    "description": "Phone number, email address, or contact name (e.g. 'Mom', '+44123456789', 'john@example.com')",
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
    "start_facetime": {
        "fn": start_facetime,
        "schema": {"type": "function", "function": {
            "name": "start_facetime",
            "description": (
                "Start a FaceTime call (video or audio-only). Can use phone number, "
                "email, or contact name (auto-resolved via Contacts). If the contact "
                "has multiple numbers, returns the list — ask Travis which one, then "
                "call again with the chosen number= parameter."
            ),
            "parameters": {"type": "object", "properties": {
                "recipient": {
                    "type": "string",
                    "description": "Phone number, email address, or contact name to call",
                },
                "audio_only": {
                    "type": "boolean",
                    "description": "If true, start audio-only call instead of video (default: false)",
                },
                "number": {
                    "type": "string",
                    "description": "Specific phone number to call — use when contact has multiple numbers and Travis has picked one. Skips contact resolution.",
                },
            }, "required": ["recipient"]},
        }},
    },
    "search_contacts": {
        "fn": search_contacts,
        "schema": {"type": "function", "function": {
            "name": "search_contacts",
            "description": (
                "Search macOS Contacts for a person by name. Returns matching contacts "
                "with their phone numbers and email addresses."
            ),
            "parameters": {"type": "object", "properties": {
                "name": {
                    "type": "string",
                    "description": "Name to search for (first, last, or full name)",
                },
            }, "required": ["name"]},
        }},
    },
}
