"""SMS tools — send/receive texts via Twilio.

FRIDAY can send SMS and receive inbound texts as commands.
The webhook server handles inbound; this module handles outbound + tools.
"""

import os
import logging
from friday.core.types import ToolResult, ToolError, ErrorCode, Severity

log = logging.getLogger("friday.sms")

_client = None


def _get_client():
    global _client
    if _client is None:
        from twilio.rest import Client
        sid = os.getenv("TWILIO_ACCOUNT_SID", "")
        token = os.getenv("TWILIO_AUTH_TOKEN", "")
        if not sid or not token or token == "your_auth_token_here":
            raise RuntimeError("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set in .env")
        _client = Client(sid, token)
    return _client


async def send_sms(to: str = "", message: str = "") -> ToolResult:
    """Send an SMS via Twilio.

    Args:
        to: Phone number to send to (e.g. +447555834656). Defaults to the user's own number (CONTACT_PHONE env var) if "me" or empty.
        message: Text message content
    """
    try:
        client = _get_client()

        # Default to the user's own number (CONTACT_PHONE env var) if "me" or similar
        if not to or to.lower() in ("me", "myself", "my phone"):
            to = os.getenv("CONTACT_PHONE", "")
        if not to or not to.startswith("+"):
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.DATA_VALIDATION,
                message=f"Invalid phone number: '{to}'. Use format +447555834656, or 'me' for the user's own number (CONTACT_PHONE env var).",
                severity=Severity.HIGH, recoverable=True))

        from_number = os.getenv("TWILIO_PHONE_NUMBER", "")
        if not from_number:
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.CONFIG_ERROR,
                message="TWILIO_PHONE_NUMBER not set in .env",
                severity=Severity.HIGH, recoverable=False))

        # Truncate long messages (SMS limit is 1600 chars for concatenated)
        if len(message) > 1500:
            message = message[:1500] + "..."

        import asyncio
        msg = await asyncio.to_thread(
            lambda: client.messages.create(
                body=message,
                from_=from_number,
                to=to,
            )
        )

        log.info(f"SMS sent to {to}: {msg.sid}")
        return ToolResult(success=True, data={
            "sid": msg.sid,
            "to": to,
            "status": msg.status,
            "length": len(message),
        })

    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=str(e),
            severity=Severity.HIGH, recoverable=True))


async def read_sms(limit: int = 10) -> ToolResult:
    """Read recent inbound SMS messages.

    Args:
        limit: Number of messages to return (default 10)
    """
    try:
        client = _get_client()
        from_number = os.getenv("TWILIO_PHONE_NUMBER", "")

        import asyncio
        messages = await asyncio.to_thread(
            lambda: list(client.messages.list(
                to=from_number,
                limit=limit,
            ))
        )

        sms_list = []
        for m in messages:
            sms_list.append({
                "from": m.from_,
                "body": m.body,
                "date": str(m.date_sent),
                "status": m.status,
                "sid": m.sid,
            })

        return ToolResult(success=True, data={
            "messages": sms_list,
            "count": len(sms_list),
        })

    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=str(e),
            severity=Severity.HIGH, recoverable=True))


TOOL_SCHEMAS = {
    "send_sms": {
        "fn": send_sms,
        "schema": {
            "type": "function",
            "function": {
                "name": "send_sms",
                "description": "Send an SMS text message via Twilio. Use when the user asks to text someone or send an SMS.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string", "description": "Phone number with country code (e.g. +447555834656), or 'me' to send to the user"},
                        "message": {"type": "string", "description": "Message text to send"},
                    },
                    "required": ["to", "message"],
                },
            },
        },
    },
    "read_sms": {
        "fn": read_sms,
        "schema": {
            "type": "function",
            "function": {
                "name": "read_sms",
                "description": "Read recent inbound SMS messages received on FRIDAY's Twilio number.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "Number of messages to return (default 10)"},
                    },
                },
            },
        },
    },
}
