"""Monitor tools — persistent watchers for URLs, searches, and topics.

FRIDAY watches things so Travis doesn't have to.
Creates monitors that check on schedules, detect material changes,
and route alerts based on importance.
"""

import hashlib
import json
from datetime import datetime
from difflib import unified_diff
from typing import Optional

from friday.core.types import ToolResult, ToolError, ErrorCode, Severity
from friday.memory.store import get_memory_store


def _get_db():
    """Get the SQLite connection from memory store."""
    return get_memory_store().db


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


async def _fetch_target(monitor_type: str, target: str) -> str:
    """Fetch current content for a monitor target."""
    from friday.tools.web_tools import fetch_page, search_web

    if monitor_type == "url":
        result = await fetch_page(target)
        return result.data if result.success else ""

    elif monitor_type == "search":
        result = await search_web(target, num_results=5)
        if result.success:
            return json.dumps(result.data, default=str)
        return ""

    elif monitor_type == "topic":
        result = await search_web(f"{target} news update", num_results=5)
        if result.success:
            return json.dumps(result.data, default=str)
        return ""

    return ""


def _extract_diff(old_content: str, new_content: str) -> str:
    """Extract a readable diff between old and new content."""
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()

    diff = list(unified_diff(
        old_lines, new_lines,
        fromfile="previous", tofile="current",
        lineterm=""
    ))

    if not diff:
        return ""

    # Only keep added/removed lines, skip context
    changes = []
    for line in diff:
        if line.startswith("+") and not line.startswith("+++"):
            changes.append(f"ADDED: {line[1:].strip()}")
        elif line.startswith("-") and not line.startswith("---"):
            changes.append(f"REMOVED: {line[1:].strip()}")

    return "\n".join(changes[:50])  # Cap at 50 lines


def _is_material_change(diff: str, keywords: list[str]) -> bool:
    """Determine if a change is material based on keywords."""
    if not diff:
        return False

    if not keywords:
        # No keywords — any substantial diff is material
        return len(diff) > 200

    diff_lower = diff.lower()
    return any(kw.lower() in diff_lower for kw in keywords)


def _summarise_diff(diff: str) -> str:
    """Create a brief summary of what changed."""
    if not diff:
        return "No visible changes."

    lines = diff.strip().split("\n")
    added = [l for l in lines if l.startswith("ADDED:")]
    removed = [l for l in lines if l.startswith("REMOVED:")]

    parts = []
    if added:
        parts.append(f"{len(added)} additions")
    if removed:
        parts.append(f"{len(removed)} removals")

    summary = f"{', '.join(parts)}."
    # Include first few meaningful changes
    previews = [l for l in lines[:3] if len(l) > 15]
    if previews:
        summary += " " + " | ".join(previews)

    return summary[:500]


# ── Tool Functions ──────────────────────────────────────────────────────────


async def create_monitor(
    topic: str,
    monitor_type: str,
    target: str,
    frequency: str = "daily",
    importance: str = "normal",
    keywords: list[str] | None = None,
) -> ToolResult:
    """Create a persistent monitor that watches for changes."""
    db = _get_db()

    # Take initial snapshot
    initial_content = await _fetch_target(monitor_type, target)
    if not initial_content:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.NETWORK_ERROR,
                message=f"Could not fetch initial content from '{target}'. Check the URL/query.",
                severity=Severity.MEDIUM,
                recoverable=True,
            ),
        )

    content_hash = _hash(initial_content)
    monitor_id = f"mon_{int(datetime.now().timestamp())}"
    now = datetime.now().isoformat()

    db.execute(
        """INSERT INTO monitors (
            id, topic, monitor_type, target, frequency,
            importance, keywords, content_hash,
            last_content, last_checked, active, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
        (
            monitor_id, topic, monitor_type, target,
            frequency, importance,
            json.dumps(keywords or []),
            content_hash,
            initial_content[:5000],
            now, now,
        ),
    )
    db.commit()

    return ToolResult(
        success=True,
        data={
            "monitor_id": monitor_id,
            "topic": topic,
            "type": monitor_type,
            "target": target,
            "frequency": frequency,
            "importance": importance,
            "keywords": keywords or [],
            "message": (
                f"Now monitoring '{topic}'. "
                f"Checking {frequency}. "
                f"Will alert you when something material changes."
            ),
        },
    )


async def list_monitors() -> ToolResult:
    """List all active monitors."""
    db = _get_db()
    rows = db.execute(
        "SELECT id, topic, monitor_type, target, frequency, importance, last_checked, active FROM monitors ORDER BY created_at DESC"
    ).fetchall()

    monitors = []
    for r in rows:
        monitors.append({
            "id": r[0],
            "topic": r[1],
            "type": r[2],
            "target": r[3],
            "frequency": r[4],
            "importance": r[5],
            "last_checked": r[6],
            "active": bool(r[7]),
        })

    return ToolResult(success=True, data={"monitors": monitors, "count": len(monitors)})


async def pause_monitor(monitor_id: str) -> ToolResult:
    """Pause a monitor temporarily."""
    db = _get_db()
    cursor = db.execute("UPDATE monitors SET active = 0 WHERE id = ?", (monitor_id,))
    db.commit()

    if cursor.rowcount == 0:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=f"Monitor '{monitor_id}' not found.",
                severity=Severity.LOW,
                recoverable=True,
            ),
        )

    return ToolResult(success=True, data={"monitor_id": monitor_id, "status": "paused"})


async def delete_monitor(monitor_id: str) -> ToolResult:
    """Delete a monitor permanently."""
    db = _get_db()

    # Delete events first
    db.execute("DELETE FROM monitor_events WHERE monitor_id = ?", (monitor_id,))
    cursor = db.execute("DELETE FROM monitors WHERE id = ?", (monitor_id,))
    db.commit()

    if cursor.rowcount == 0:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=f"Monitor '{monitor_id}' not found.",
                severity=Severity.LOW,
                recoverable=True,
            ),
        )

    return ToolResult(success=True, data={"monitor_id": monitor_id, "status": "deleted"})


async def get_monitor_history(monitor_id: str, limit: int = 10) -> ToolResult:
    """Get change history for a monitor."""
    db = _get_db()

    monitor = db.execute("SELECT topic, target FROM monitors WHERE id = ?", (monitor_id,)).fetchone()
    if not monitor:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=f"Monitor '{monitor_id}' not found.",
                severity=Severity.LOW,
                recoverable=True,
            ),
        )

    events = db.execute(
        "SELECT change_summary, diff, is_material, detected_at, delivered FROM monitor_events WHERE monitor_id = ? ORDER BY detected_at DESC LIMIT ?",
        (monitor_id, limit),
    ).fetchall()

    history = []
    for e in events:
        history.append({
            "summary": e[0],
            "diff": e[1],
            "material": bool(e[2]),
            "detected_at": e[3],
            "delivered": bool(e[4]),
        })

    return ToolResult(
        success=True,
        data={
            "monitor_id": monitor_id,
            "topic": monitor[0],
            "target": monitor[1],
            "events": history,
            "count": len(history),
        },
    )


async def force_check(monitor_id: str) -> ToolResult:
    """Force an immediate check on a monitor."""
    db = _get_db()

    row = db.execute("SELECT * FROM monitors WHERE id = ?", (monitor_id,)).fetchone()
    if not row:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=f"Monitor '{monitor_id}' not found.",
                severity=Severity.LOW,
                recoverable=True,
            ),
        )

    # Convert row to dict
    columns = [desc[0] for desc in db.execute("SELECT * FROM monitors LIMIT 0").description]
    monitor = dict(zip(columns, row))

    return await run_monitor_check(monitor)


async def run_monitor_check(monitor: dict) -> ToolResult:
    """Run a single check on a monitor. Used by scheduler and force_check."""
    db = _get_db()
    monitor_id = monitor["id"]

    # Fetch current state
    current_content = await _fetch_target(monitor["monitor_type"], monitor["target"])
    if not current_content:
        # Target unreachable — log but don't alert
        db.execute(
            "UPDATE monitors SET last_checked = ? WHERE id = ?",
            (datetime.now().isoformat(), monitor_id),
        )
        db.commit()
        return ToolResult(
            success=True,
            data={"monitor_id": monitor_id, "status": "unreachable", "changed": False},
        )

    current_hash = _hash(current_content)

    # Nothing changed
    if current_hash == monitor["content_hash"]:
        db.execute(
            "UPDATE monitors SET last_checked = ? WHERE id = ?",
            (datetime.now().isoformat(), monitor_id),
        )
        db.commit()
        return ToolResult(
            success=True,
            data={"monitor_id": monitor_id, "status": "no_change", "changed": False},
        )

    # Something changed — analyse the diff
    diff = _extract_diff(monitor["last_content"] or "", current_content)
    keywords = json.loads(monitor["keywords"] or "[]")
    is_material = _is_material_change(diff, keywords)
    summary = _summarise_diff(diff)

    # Store the change event
    db.execute(
        """INSERT INTO monitor_events (
            monitor_id, change_summary, diff, is_material, detected_at
        ) VALUES (?, ?, ?, ?, ?)""",
        (monitor_id, summary, diff[:2000], int(is_material), datetime.now().isoformat()),
    )

    # Update monitor state
    db.execute(
        """UPDATE monitors SET
            content_hash = ?, last_content = ?, last_checked = ?
        WHERE id = ?""",
        (current_hash, current_content[:5000], datetime.now().isoformat(), monitor_id),
    )

    # Queue for briefing
    priority = {"critical": 1, "high": 3, "normal": 5}.get(monitor["importance"], 5)
    if is_material:
        priority = min(priority, 2)  # Material changes always high priority

    db.execute(
        """INSERT INTO briefing_queue (source, content, priority, queued_at)
        VALUES (?, ?, ?, ?)""",
        (
            "monitor",
            json.dumps({
                "monitor_id": monitor_id,
                "topic": monitor["topic"],
                "target": monitor["target"],
                "summary": summary,
                "is_material": is_material,
                "importance": monitor["importance"],
            }),
            priority,
            datetime.now().isoformat(),
        ),
    )

    db.commit()

    return ToolResult(
        success=True,
        data={
            "monitor_id": monitor_id,
            "topic": monitor["topic"],
            "status": "changed",
            "changed": True,
            "material": is_material,
            "summary": summary,
            "importance": monitor["importance"],
        },
    )


# ── Tool Schemas ────────────────────────────────────────────────────────────

TOOL_SCHEMAS = {
    "create_monitor": {
        "fn": create_monitor,
        "schema": {
            "type": "function",
            "function": {
                "name": "create_monitor",
                "description": (
                    "Create a persistent monitor for a topic, URL, or keyword. "
                    "FRIDAY will alert Travis when something material changes. "
                    "Use for laws, visa rules, competitor activity, funding deadlines, news topics."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "What to monitor e.g. 'global talent visa'",
                        },
                        "monitor_type": {
                            "type": "string",
                            "enum": ["url", "search", "topic"],
                            "description": "url = watch specific page, search = recurring web search, topic = broad topic awareness",
                        },
                        "target": {
                            "type": "string",
                            "description": "URL or search query to monitor",
                        },
                        "frequency": {
                            "type": "string",
                            "enum": ["realtime", "hourly", "daily", "weekly"],
                            "description": "How often to check. realtime=15min, hourly, daily, weekly",
                        },
                        "importance": {
                            "type": "string",
                            "enum": ["critical", "high", "normal"],
                            "description": "critical=interrupt immediately, high=next interaction, normal=include in briefing",
                        },
                        "keywords": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Keywords that make a change material. Only alert if these appear in the diff.",
                        },
                    },
                    "required": ["topic", "monitor_type", "target", "frequency"],
                },
            },
        },
    },
    "list_monitors": {
        "fn": list_monitors,
        "schema": {
            "type": "function",
            "function": {
                "name": "list_monitors",
                "description": "List all active monitors Travis has set up.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
    },
    "pause_monitor": {
        "fn": pause_monitor,
        "schema": {
            "type": "function",
            "function": {
                "name": "pause_monitor",
                "description": "Pause a monitor temporarily.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "monitor_id": {"type": "string", "description": "Monitor ID to pause"},
                    },
                    "required": ["monitor_id"],
                },
            },
        },
    },
    "delete_monitor": {
        "fn": delete_monitor,
        "schema": {
            "type": "function",
            "function": {
                "name": "delete_monitor",
                "description": "Delete a monitor permanently.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "monitor_id": {"type": "string", "description": "Monitor ID to delete"},
                    },
                    "required": ["monitor_id"],
                },
            },
        },
    },
    "get_monitor_history": {
        "fn": get_monitor_history,
        "schema": {
            "type": "function",
            "function": {
                "name": "get_monitor_history",
                "description": "Get the change history for a monitor. Shows what changed and when.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "monitor_id": {"type": "string", "description": "Monitor ID"},
                        "limit": {"type": "integer", "description": "Max results (default 10)"},
                    },
                    "required": ["monitor_id"],
                },
            },
        },
    },
    "force_check": {
        "fn": force_check,
        "schema": {
            "type": "function",
            "function": {
                "name": "force_check",
                "description": "Force an immediate check on a monitor now.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "monitor_id": {"type": "string", "description": "Monitor ID to check"},
                    },
                    "required": ["monitor_id"],
                },
            },
        },
    },
}
