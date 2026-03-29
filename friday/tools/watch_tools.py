"""Watch Tools — create, list, cancel standing orders.

Standing orders are dynamic watch tasks Travis gives conversationally:
"watch Ellen's messages for the next hour, reply as FRIDAY if she texts"
"monitor my emails for the next 2 hours, ping me if anything from Stripe comes in"
"""

from friday.core.types import ToolResult


async def create_watch(instruction: str, interval_seconds: int = 60, duration_minutes: int = 0) -> ToolResult:
    """Create a standing order / watch task."""
    from friday.background.heartbeat import get_heartbeat_runner
    hb = get_heartbeat_runner()
    result = hb.create_watch(
        instruction=instruction,
        interval_seconds=interval_seconds,
        duration_minutes=duration_minutes,
    )
    dur_msg = f"for {duration_minutes} minutes" if duration_minutes > 0 else "until cancelled"
    return ToolResult(success=True, data={
        **result,
        "message": f"Watch active. Checking every {interval_seconds}s {dur_msg}.",
    })


async def list_watches() -> ToolResult:
    """List all active watch tasks."""
    from friday.background.heartbeat import get_heartbeat_runner
    hb = get_heartbeat_runner()
    watches = hb.list_watches()
    return ToolResult(success=True, data=watches)


async def cancel_watch(task_id: str) -> ToolResult:
    """Cancel a watch task."""
    from friday.background.heartbeat import get_heartbeat_runner
    hb = get_heartbeat_runner()
    hb.cancel_watch(task_id)
    return ToolResult(success=True, data={"message": f"Watch '{task_id}' cancelled."})


TOOL_SCHEMAS = {
    "create_watch": {
        "fn": create_watch,
        "schema": {
            "name": "create_watch",
            "description": "Create a RECURRING standing order — a background task that runs on a loop for a set duration. ONLY use this when Travis says 'watch', 'monitor', 'keep an eye on', 'for the next X hours/minutes'. Do NOT use for one-time reads like 'check messages' or 'read messages' — use read_imessages/read_whatsapp for those instead. Supports: iMessage (watch someone's messages, reply), WhatsApp (watch WhatsApp messages, reply), email (watch for emails from a sender, notify), missed calls (notify on new missed calls), browser/LinkedIn (check notifications). The instruction should contain the FULL context of what to check and what to do. For WhatsApp watches, include 'whatsapp' in the instruction.",
            "parameters": {
                "type": "object",
                "properties": {
                    "instruction": {
                        "type": "string",
                        "description": "The full standing order in natural language. Examples: 'Check messages from Ellen, reply like me' (iMessage). 'Watch WhatsApp messages from Abby, reply like me' (WhatsApp). 'Watch my emails for anything from Stripe, notify me' (email). 'Check for missed calls, notify me' (calls). 'Open LinkedIn and check for new notifications' (browser).",
                    },
                    "interval_seconds": {
                        "type": "integer",
                        "description": "How often to check, in seconds. Default 60 (every minute). Min 30.",
                    },
                    "duration_minutes": {
                        "type": "integer",
                        "description": "How long to keep watching, in minutes. 0 = persistent/indefinite (default). Use 0 for open-ended watches like 'watch for shipping email'. Use a value like 60 or 120 for short-lived watches like 'watch messages for the next hour'.",
                    },
                },
                "required": ["instruction"],
            },
        },
    },
    "list_watches": {
        "fn": list_watches,
        "schema": {
            "name": "list_watches",
            "description": "List all active standing orders / watch tasks.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "cancel_watch": {
        "fn": cancel_watch,
        "schema": {
            "name": "cancel_watch",
            "description": "Cancel an active watch task by ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "The ID of the watch task to cancel.",
                    },
                },
                "required": ["task_id"],
            },
        },
    },
}
