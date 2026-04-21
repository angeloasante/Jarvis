"""Watch Tools — create, list, cancel standing orders.

Standing orders are dynamic watch tasks the user gives conversationally:
"watch my partner's messages for the next hour, reply as FRIDAY if she texts"
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
            "description": "Create a RECURRING standing order — a background task that runs on a loop. ONLY use this when the user says 'watch', 'monitor', 'keep an eye on', 'track'. Do NOT use for one-time reads like 'check messages' or 'read messages'. Supports ALL watch types: iMessage (watch messages, reply), WhatsApp (watch messages, reply), email (watch for emails, notify), missed calls (notify), URL (watch a webpage for changes, diff and notify), search (recurring web search for news/updates), topic (broad topic awareness like 'AI news' or 'startup updates'), browser/LinkedIn (check notifications). The instruction should contain the FULL context of what to check and what to do. For URLs, include the full URL. For searches, describe what to search for.",
            "parameters": {
                "type": "object",
                "properties": {
                    "instruction": {
                        "type": "string",
                        "description": "The full standing order in natural language. Examples: 'Check messages from <contact>, reply like me' (iMessage). 'Watch WhatsApp messages from <contact>, reply like me' (WhatsApp). 'Watch my emails for anything from Stripe, notify me' (email). 'Check for missed calls, notify me' (calls). 'Watch https://news.ycombinator.com for new AI posts' (URL). 'Search for AI startup news daily' (search). 'Track the AI space for major announcements' (topic). 'Open LinkedIn and check for new notifications' (browser).",
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
