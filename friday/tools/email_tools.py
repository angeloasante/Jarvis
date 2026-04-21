"""Email tools — Gmail read, send, draft, search, label.

Requires Google OAuth2 setup. Run: uv run python -m friday.tools.google_auth
"""

import asyncio
import base64
from datetime import datetime
from email.mime.text import MIMEText
from typing import Optional

from friday.core.types import ToolResult, ToolError, ErrorCode, Severity
from friday.tools.google_auth import get_credentials

_gmail_service = None


def _get_gmail():
    """Lazy-init Gmail API service."""
    global _gmail_service
    if _gmail_service is None:
        creds = get_credentials()
        if creds is None:
            raise ValueError(
                "Google API not configured. Run: uv run python -m friday.tools.google_auth"
            )
        from googleapiclient.discovery import build
        _gmail_service = build("gmail", "v1", credentials=creds)
    return _gmail_service


# Priority senders — emails from these get flagged
PRIORITY_SENDERS = {
    "paystack": "critical",
    "stripe": "critical",
    "railway": "high",
    "modal": "high",
    "github": "high",
    "google": "normal",
}


def _get_priority(email: dict) -> str:
    sender = email.get("from", "").lower()
    for keyword, level in PRIORITY_SENDERS.items():
        if keyword in sender:
            return level
    if "IMPORTANT" in email.get("labels", []):
        return "high"
    return "normal"


def _parse_email(email_data: dict, include_body: bool = False) -> dict:
    headers = {
        h["name"].lower(): h["value"]
        for h in email_data.get("payload", {}).get("headers", [])
    }

    parsed = {
        "id": email_data["id"],
        "thread_id": email_data.get("threadId"),
        "subject": headers.get("subject", "(no subject)"),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "date": headers.get("date", ""),
        "snippet": email_data.get("snippet", ""),
        "labels": email_data.get("labelIds", []),
        "unread": "UNREAD" in email_data.get("labelIds", []),
    }

    parsed["priority"] = _get_priority(parsed)

    if include_body:
        body = _extract_body(email_data.get("payload", {}))
        # Strip HTML tags for cleaner LLM input
        if "<html" in body.lower() or "<div" in body.lower():
            import re as _re
            body = _re.sub(r"<style[^>]*>.*?</style>", "", body, flags=_re.DOTALL | _re.IGNORECASE)
            body = _re.sub(r"<[^>]+>", " ", body)
            body = _re.sub(r"\s+", " ", body).strip()
        # Truncate individual bodies to avoid overwhelming the LLM
        if len(body) > 1500:
            body = body[:1500] + "... (truncated)"
        parsed["body"] = body

    return parsed


def _extract_body(payload: dict) -> str:
    if payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(
            payload["body"]["data"]
        ).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain":
            if part.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(
                    part["body"]["data"]
                ).decode("utf-8", errors="replace")
    return ""


# ── Tools ────────────────────────────────────────────────────────────────────


async def read_emails(
    filter: str = "all",
    limit: int = 10,
    include_body: bool = False,
    label: str = "INBOX",
) -> ToolResult:
    """Read emails from Gmail. Filter: 'all' (default), 'unread', 'today', 'urgent', or any Gmail search query like 'from:devpost' or 'subject:payment'."""
    try:
        service = _get_gmail()

        query_map = {
            "all": "",
            "unread": "is:unread",
            "today": "after:" + datetime.now().strftime("%Y/%m/%d"),
            "urgent": "is:unread is:important",
        }
        query = query_map.get(filter, filter)
        if label != "INBOX":
            query = f"in:{label} {query}"

        result = await asyncio.to_thread(
            lambda: service.users().messages().list(
                userId="me", q=query, maxResults=limit
            ).execute()
        )

        messages = result.get("messages", [])
        emails = []

        for msg in messages:
            email_data = await asyncio.to_thread(
                lambda m=msg: service.users().messages().get(
                    userId="me",
                    id=m["id"],
                    format="full" if include_body else "metadata",
                ).execute()
            )
            emails.append(_parse_email(email_data, include_body))

        # Sort: critical first, then high, then normal
        priority_order = {"critical": 0, "high": 1, "normal": 2, "low": 3}
        emails.sort(key=lambda e: priority_order.get(e.get("priority", "normal"), 2))

        return ToolResult(
            success=True,
            data=emails,
            metadata={
                "filter": filter,
                "count": len(emails),
                "critical_count": sum(1 for e in emails if e.get("priority") == "critical"),
            },
        )
    except ValueError as e:
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
                code=ErrorCode.NETWORK_ERROR,
                message=str(e),
                severity=Severity.MEDIUM,
                recoverable=True,
            ),
        )


async def search_emails(query: str, limit: int = 10) -> ToolResult:
    """Search Gmail with a query. Uses Gmail search syntax (from:, subject:, has:attachment, etc.).
    Includes email bodies so you can answer questions about the content."""
    return await read_emails(filter=query, limit=limit, include_body=True)


async def read_email_thread(thread_id: str) -> ToolResult:
    """Read a full email thread by thread ID. Returns all messages in the thread with bodies."""
    try:
        service = _get_gmail()

        thread = await asyncio.to_thread(
            lambda: service.users().threads().get(
                userId="me", id=thread_id, format="full"
            ).execute()
        )

        messages = [
            _parse_email(msg, include_body=True)
            for msg in thread.get("messages", [])
        ]

        return ToolResult(
            success=True,
            data=messages,
            metadata={"thread_id": thread_id, "message_count": len(messages)},
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


async def send_email(
    to: str,
    subject: str,
    body: str,
    reply_to_thread_id: Optional[str] = None,
    confirm: bool = False,
) -> ToolResult:
    """Send an email via Gmail. REQUIRES confirm=True — always draft first."""
    if not confirm:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.VALIDATION_ERROR,
                message=(
                    f"Email NOT sent. Review first:\n"
                    f"  To: {to}\n  Subject: {subject}\n  Body: {body[:200]}...\n\n"
                    f"Call send_email again with confirm=True to send."
                ),
                severity=Severity.LOW,
                recoverable=True,
                context={"to": to, "subject": subject},
            ),
        )

    try:
        service = _get_gmail()

        message = MIMEText(body, "plain")
        message["to"] = to
        message["subject"] = subject

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        send_data = {"raw": raw}
        if reply_to_thread_id:
            send_data["threadId"] = reply_to_thread_id

        result = await asyncio.to_thread(
            lambda: service.users().messages().send(
                userId="me", body=send_data
            ).execute()
        )

        return ToolResult(
            success=True,
            data={
                "message_id": result.get("id"),
                "thread_id": result.get("threadId"),
                "to": to,
                "subject": subject,
                "sent": True,
            },
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.NETWORK_ERROR,
                message=str(e),
                severity=Severity.HIGH,
                recoverable=True,
            ),
        )


async def draft_email(
    to: str,
    subject: str,
    body: str,
) -> ToolResult:
    """Create a Gmail draft. Does NOT send. Returns draft for the user to review."""
    try:
        service = _get_gmail()

        message = MIMEText(body, "plain")
        message["to"] = to
        message["subject"] = subject

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        draft = await asyncio.to_thread(
            lambda: service.users().drafts().create(
                userId="me", body={"message": {"raw": raw}}
            ).execute()
        )

        return ToolResult(
            success=True,
            data={
                "draft_id": draft.get("id"),
                "to": to,
                "subject": subject,
                "body_preview": body[:300],
                "ready_to_send": False,
                "note": "Draft created in Gmail. Review in Gmail or call send_email with confirm=True.",
            },
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


async def send_draft(
    draft_id: str,
    confirm: bool = False,
) -> ToolResult:
    """Send an existing Gmail draft by its draft ID. REQUIRES confirm=True."""
    if not confirm:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.VALIDATION_ERROR,
                message=f"Draft NOT sent. Call send_draft(draft_id='{draft_id}', confirm=True) to send.",
                severity=Severity.LOW,
                recoverable=True,
                context={"draft_id": draft_id},
            ),
        )

    try:
        service = _get_gmail()

        result = await asyncio.to_thread(
            lambda: service.users().drafts().send(
                userId="me", body={"id": draft_id}
            ).execute()
        )

        return ToolResult(
            success=True,
            data={
                "message_id": result.get("id"),
                "thread_id": result.get("threadId"),
                "sent": True,
                "draft_id": draft_id,
            },
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.NETWORK_ERROR,
                message=str(e),
                severity=Severity.HIGH,
                recoverable=True,
            ),
        )


async def edit_draft(
    draft_id: str,
    to: str = None,
    subject: str = None,
    body: str = None,
) -> ToolResult:
    """Edit an existing Gmail draft. Only updates the fields you provide."""
    try:
        service = _get_gmail()

        # Get the existing draft first
        existing = await asyncio.to_thread(
            lambda: service.users().drafts().get(
                userId="me", id=draft_id, format="full"
            ).execute()
        )

        # Parse existing message to get current values
        existing_msg = existing.get("message", {})
        existing_parsed = _parse_email(existing_msg, include_body=True)

        # Use existing values for anything not provided
        final_to = to or existing_parsed.get("to", "")
        final_subject = subject or existing_parsed.get("subject", "")
        final_body = body or existing_parsed.get("body", "")

        message = MIMEText(final_body, "plain")
        message["to"] = final_to
        message["subject"] = final_subject

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        updated = await asyncio.to_thread(
            lambda: service.users().drafts().update(
                userId="me", id=draft_id,
                body={"message": {"raw": raw}}
            ).execute()
        )

        return ToolResult(
            success=True,
            data={
                "draft_id": updated.get("id"),
                "to": final_to,
                "subject": final_subject,
                "body_preview": final_body[:300],
                "updated": True,
            },
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


async def label_email(email_id: str, add_labels: list[str] = None, remove_labels: list[str] = None) -> ToolResult:
    """Add or remove labels from an email. Common labels: STARRED, IMPORTANT, TRASH, SPAM."""
    try:
        service = _get_gmail()

        body = {}
        if add_labels:
            body["addLabelIds"] = add_labels
        if remove_labels:
            body["removeLabelIds"] = remove_labels

        await asyncio.to_thread(
            lambda: service.users().messages().modify(
                userId="me", id=email_id, body=body
            ).execute()
        )

        return ToolResult(
            success=True,
            data={
                "email_id": email_id,
                "added": add_labels or [],
                "removed": remove_labels or [],
            },
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


# ── Tool Schemas ─────────────────────────────────────────────────────────────

TOOL_SCHEMAS = {
    "read_emails": {
        "fn": read_emails,
        "schema": {
            "type": "function",
            "function": {
                "name": "read_emails",
                "description": "Read emails from Gmail. Returns structured email data sorted by priority. When the user asks about a SPECIFIC email (e.g. 'check the devpost mail'), use filter='from:devpost' to search ALL emails — do NOT default to unread.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filter": {
                            "type": "string",
                            "description": "Default 'all'. Use 'unread' only for 'check my emails' / 'any new emails'. For specific emails use Gmail query: 'from:devpost', 'subject:payment', 'from:stripe'. NEVER use 'unread' when the user asks about a specific sender or subject.",
                        },
                        "limit": {"type": "integer", "description": "Max emails to return (default 10)"},
                        "include_body": {"type": "boolean", "description": "Include full email body (default false)"},
                        "label": {"type": "string", "description": "Gmail label (default INBOX)"},
                    },
                    "required": [],
                },
            },
        },
    },
    "search_emails": {
        "fn": search_emails,
        "schema": {
            "type": "function",
            "function": {
                "name": "search_emails",
                "description": "Search Gmail with a query. Uses Gmail search syntax: from:, subject:, has:attachment, before:, after:, etc.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Gmail search query"},
                        "limit": {"type": "integer", "description": "Max results (default 10)"},
                    },
                    "required": ["query"],
                },
            },
        },
    },
    "read_email_thread": {
        "fn": read_email_thread,
        "schema": {
            "type": "function",
            "function": {
                "name": "read_email_thread",
                "description": "Read a full email conversation thread. Returns all messages with bodies.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "thread_id": {"type": "string", "description": "Gmail thread ID"},
                    },
                    "required": ["thread_id"],
                },
            },
        },
    },
    "send_email": {
        "fn": send_email,
        "schema": {
            "type": "function",
            "function": {
                "name": "send_email",
                "description": "Send an email via Gmail. IMPORTANT: Set confirm=True only after the user has reviewed the content. Always draft first unless told otherwise.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string", "description": "Recipient email address"},
                        "subject": {"type": "string", "description": "Email subject"},
                        "body": {"type": "string", "description": "Email body text"},
                        "reply_to_thread_id": {"type": "string", "description": "Thread ID if replying to an existing conversation"},
                        "confirm": {"type": "boolean", "description": "Must be true to actually send. False = preview only."},
                    },
                    "required": ["to", "subject", "body"],
                },
            },
        },
    },
    "draft_email": {
        "fn": draft_email,
        "schema": {
            "type": "function",
            "function": {
                "name": "draft_email",
                "description": "Create a Gmail draft. Does NOT send. Draft appears in Gmail for review.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string", "description": "Recipient email address"},
                        "subject": {"type": "string", "description": "Email subject"},
                        "body": {"type": "string", "description": "Email body text"},
                    },
                    "required": ["to", "subject", "body"],
                },
            },
        },
    },
    "send_draft": {
        "fn": send_draft,
        "schema": {
            "type": "function",
            "function": {
                "name": "send_draft",
                "description": "Send an existing Gmail draft by its draft ID. REQUIRES confirm=True. Use this when the user says 'send the draft' or 'send draft ID: X'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "draft_id": {"type": "string", "description": "Gmail draft ID (e.g. 'r-8289868670985246699')"},
                        "confirm": {"type": "boolean", "description": "Must be true to actually send. False = preview only."},
                    },
                    "required": ["draft_id"],
                },
            },
        },
    },
    "edit_draft": {
        "fn": edit_draft,
        "schema": {
            "type": "function",
            "function": {
                "name": "edit_draft",
                "description": "Edit an existing Gmail draft. Only updates the fields you provide — others stay the same.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "draft_id": {"type": "string", "description": "Gmail draft ID to edit"},
                        "to": {"type": "string", "description": "New recipient (optional)"},
                        "subject": {"type": "string", "description": "New subject (optional)"},
                        "body": {"type": "string", "description": "New body text (optional)"},
                    },
                    "required": ["draft_id"],
                },
            },
        },
    },
    "label_email": {
        "fn": label_email,
        "schema": {
            "type": "function",
            "function": {
                "name": "label_email",
                "description": "Add or remove Gmail labels from an email. Labels: STARRED, IMPORTANT, TRASH, SPAM, UNREAD, or custom labels.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "email_id": {"type": "string", "description": "Gmail message ID"},
                        "add_labels": {"type": "array", "items": {"type": "string"}, "description": "Labels to add"},
                        "remove_labels": {"type": "array", "items": {"type": "string"}, "description": "Labels to remove"},
                    },
                    "required": ["email_id"],
                },
            },
        },
    },
}
