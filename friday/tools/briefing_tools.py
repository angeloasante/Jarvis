"""Briefing tools — pulls together monitor alerts, emails, calendar for delivery.

Two types:
  Morning briefing — proactive, comprehensive, fires on first interaction
  Quick briefing — reactive, one thing, two sentences
"""

import json
from datetime import datetime

from friday.core.types import ToolResult
from friday.memory.store import get_memory_store


def _get_db():
    return get_memory_store().db


async def get_briefing_queue(briefing_type: str = "morning") -> ToolResult:
    """Get all items queued for the next briefing."""
    db = _get_db()

    # Get undelivered briefing queue items, ordered by priority
    rows = db.execute(
        "SELECT id, source, content, priority, queued_at FROM briefing_queue WHERE delivered = 0 ORDER BY priority ASC, queued_at ASC"
    ).fetchall()

    items = []
    for r in rows:
        content = r[2]
        try:
            content = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            pass

        items.append({
            "id": r[0],
            "source": r[1],
            "content": content,
            "priority": r[3],
            "queued_at": r[4],
        })

    # For quick briefing, only return the highest priority item
    if briefing_type == "quick" and items:
        items = [items[0]]

    return ToolResult(
        success=True,
        data={
            "briefing_type": briefing_type,
            "items": items,
            "count": len(items),
        },
    )


async def get_monitor_alerts(importance: str = "all") -> ToolResult:
    """Get undelivered monitor alerts."""
    db = _get_db()

    if importance == "all":
        rows = db.execute(
            """SELECT me.id, me.monitor_id, me.change_summary, me.diff,
                      me.is_material, me.detected_at, m.topic, m.target, m.importance
               FROM monitor_events me
               JOIN monitors m ON me.monitor_id = m.id
               WHERE me.delivered = 0
               ORDER BY m.importance ASC, me.detected_at DESC"""
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT me.id, me.monitor_id, me.change_summary, me.diff,
                      me.is_material, me.detected_at, m.topic, m.target, m.importance
               FROM monitor_events me
               JOIN monitors m ON me.monitor_id = m.id
               WHERE me.delivered = 0 AND m.importance = ?
               ORDER BY me.detected_at DESC""",
            (importance,),
        ).fetchall()

    alerts = []
    for r in rows:
        alerts.append({
            "event_id": r[0],
            "monitor_id": r[1],
            "summary": r[2],
            "diff": r[3],
            "material": bool(r[4]),
            "detected_at": r[5],
            "topic": r[6],
            "target": r[7],
            "importance": r[8],
        })

    return ToolResult(
        success=True,
        data={"alerts": alerts, "count": len(alerts)},
    )


async def get_daily_digest(time_of_day: str = "morning") -> ToolResult:
    """Pull everything relevant for a full briefing.

    Combines: monitor alerts + briefing queue.
    The briefing agent also calls email/calendar tools separately for live data.
    """
    db = _get_db()

    # Monitor alerts (undelivered)
    alert_result = await get_monitor_alerts("all")
    alerts = alert_result.data.get("alerts", [])

    # Briefing queue items (undelivered)
    queue_result = await get_briefing_queue(time_of_day)
    queue_items = queue_result.data.get("items", [])

    # Active monitors summary
    monitors = db.execute(
        "SELECT id, topic, frequency, last_checked FROM monitors WHERE active = 1"
    ).fetchall()
    active_monitors = [
        {"id": r[0], "topic": r[1], "frequency": r[2], "last_checked": r[3]}
        for r in monitors
    ]

    return ToolResult(
        success=True,
        data={
            "time_of_day": time_of_day,
            "monitor_alerts": alerts,
            "alert_count": len(alerts),
            "queued_items": queue_items,
            "queued_count": len(queue_items),
            "active_monitors": active_monitors,
            "monitor_count": len(active_monitors),
        },
    )


async def mark_briefing_delivered(item_ids: list[int]) -> ToolResult:
    """Mark briefing items and monitor events as delivered so they don't repeat."""
    db = _get_db()

    # Mark briefing queue items
    if item_ids:
        placeholders = ",".join("?" * len(item_ids))
        db.execute(
            f"UPDATE briefing_queue SET delivered = 1 WHERE id IN ({placeholders})",
            item_ids,
        )
        # Also mark any monitor events referenced by these queue items
        db.execute(
            f"UPDATE monitor_events SET delivered = 1 WHERE id IN ({placeholders})",
            item_ids,
        )
        db.commit()

    return ToolResult(
        success=True,
        data={"marked_delivered": item_ids, "count": len(item_ids)},
    )


# ── Tool Schemas ────────────────────────────────────────────────────────────

TOOL_SCHEMAS = {
    "get_briefing_queue": {
        "fn": get_briefing_queue,
        "schema": {
            "type": "function",
            "function": {
                "name": "get_briefing_queue",
                "description": "Get all items queued for the next briefing. Includes monitor alerts, pending reminders.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "briefing_type": {
                            "type": "string",
                            "enum": ["morning", "evening", "quick"],
                            "description": "Type of briefing to build",
                        },
                    },
                    "required": [],
                },
            },
        },
    },
    "get_monitor_alerts": {
        "fn": get_monitor_alerts,
        "schema": {
            "type": "function",
            "function": {
                "name": "get_monitor_alerts",
                "description": "Get undelivered monitor alerts. Use in briefings to surface what changed.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "importance": {
                            "type": "string",
                            "enum": ["all", "critical", "high", "normal"],
                            "description": "Filter by importance level",
                        },
                    },
                    "required": [],
                },
            },
        },
    },
    "get_daily_digest": {
        "fn": get_daily_digest,
        "schema": {
            "type": "function",
            "function": {
                "name": "get_daily_digest",
                "description": "Pull everything relevant for a full briefing: monitor alerts, queued items, active monitor status.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "time_of_day": {
                            "type": "string",
                            "enum": ["morning", "evening"],
                            "description": "Morning or evening digest",
                        },
                    },
                    "required": [],
                },
            },
        },
    },
    "mark_briefing_delivered": {
        "fn": mark_briefing_delivered,
        "schema": {
            "type": "function",
            "function": {
                "name": "mark_briefing_delivered",
                "description": "Mark briefing items as delivered so they don't repeat.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "item_ids": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "IDs of items to mark delivered",
                        },
                    },
                    "required": ["item_ids"],
                },
            },
        },
    },
}
