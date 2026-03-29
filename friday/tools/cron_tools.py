"""Cron Tools — create, list, delete, toggle scheduled tasks.

Users say things like "every weekday at 8am run my briefing" and the LLM
translates that into a cron expression + task string. These tools handle the CRUD.
"""

from friday.core.types import ToolResult


async def create_cron(name: str, schedule: str, task: str, channel: str = "cli") -> ToolResult:
    """Create a new scheduled cron job."""
    from friday.background.cron_scheduler import get_cron_scheduler
    cron = get_cron_scheduler()
    return cron.create_job(name=name, schedule=schedule, task=task, channel=channel)


async def list_crons() -> ToolResult:
    """List all cron jobs."""
    from friday.background.cron_scheduler import get_cron_scheduler
    cron = get_cron_scheduler()
    return cron.list_jobs()


async def delete_cron(job_id: str) -> ToolResult:
    """Delete a cron job by ID."""
    from friday.background.cron_scheduler import get_cron_scheduler
    cron = get_cron_scheduler()
    return cron.delete_job(job_id=job_id)


async def toggle_cron(job_id: str, enabled: bool) -> ToolResult:
    """Enable or disable a cron job."""
    from friday.background.cron_scheduler import get_cron_scheduler
    cron = get_cron_scheduler()
    return cron.toggle_job(job_id=job_id, enabled=enabled)


TOOL_SCHEMAS = {
    "create_cron": {
        "fn": create_cron,
        "schema": {
            "name": "create_cron",
            "description": "Create a scheduled cron job. The LLM converts natural language schedules to cron expressions. Examples: '0 8 * * 1-5' = weekdays 8am, '0 18 * * 5' = Friday 6pm, '*/15 * * * *' = every 15 min.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Short name for this cron (e.g. 'morning_briefing', 'weekly_summary')",
                    },
                    "schedule": {
                        "type": "string",
                        "description": "Standard 5-field cron expression: minute hour day month weekday. Examples: '0 8 * * 1-5', '30 9 * * 1', '*/15 * * * *'",
                    },
                    "task": {
                        "type": "string",
                        "description": "The task to execute as natural language (e.g. 'Give me my morning briefing', 'Check my unread emails and summarize')",
                    },
                    "channel": {
                        "type": "string",
                        "enum": ["cli", "imessage", "telegram"],
                        "description": "Where to deliver the output. Default: cli",
                    },
                },
                "required": ["name", "schedule", "task"],
            },
        },
    },
    "list_crons": {
        "fn": list_crons,
        "schema": {
            "name": "list_crons",
            "description": "List all scheduled cron jobs with their status, schedule, and last run time.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "delete_cron": {
        "fn": delete_cron,
        "schema": {
            "name": "delete_cron",
            "description": "Delete a cron job by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "The ID of the cron job to delete.",
                    },
                },
                "required": ["job_id"],
            },
        },
    },
    "toggle_cron": {
        "fn": toggle_cron,
        "schema": {
            "name": "toggle_cron",
            "description": "Enable or disable a cron job without deleting it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "The ID of the cron job.",
                    },
                    "enabled": {
                        "type": "boolean",
                        "description": "True to enable, false to disable.",
                    },
                },
                "required": ["job_id", "enabled"],
            },
        },
    },
}
