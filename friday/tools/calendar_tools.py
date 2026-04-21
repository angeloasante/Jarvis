"""Calendar tools — reads from native macOS Calendar (iCloud/local).

Uses AppleScript to read from the macOS Calendar app. Works with iCloud,
Google, Exchange, or any calendar synced to the Mac. No API keys needed.

Creating events also uses AppleScript — events sync to iCloud automatically.
"""

import asyncio
import subprocess
import re
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from friday.core.types import ToolResult, ToolError, ErrorCode, Severity

TZ = ZoneInfo("Europe/London")


def _run_applescript(script: str, timeout: int = 30) -> str:
    """Run AppleScript and return stdout."""
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "AppleScript failed")
    return result.stdout.strip()


def _parse_date_range(date: str, view: str) -> tuple[str, str]:
    """Parse date/view into AppleScript date range strings.
    Returns (start_applescript, days_to_add) for the AppleScript query."""
    now = datetime.now(TZ)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if date == "today":
        start = today
    elif date == "tomorrow":
        start = today + timedelta(days=1)
    elif date == "next_event":
        # For next_event, look ahead 7 days
        start = now
        return start.strftime("%Y-%m-%d"), (start + timedelta(days=7)).strftime("%Y-%m-%d")
    else:
        try:
            start = datetime.fromisoformat(date).replace(tzinfo=TZ)
        except ValueError:
            start = today

    if view == "week":
        end = start + timedelta(days=7)
    else:
        end = start + timedelta(days=1)

    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _parse_event_line(line: str) -> Optional[dict]:
    """Parse a pipe-delimited event line from AppleScript output."""
    parts = [p.strip() for p in line.split(" | ")]
    if len(parts) < 4:
        return None

    cal_name = parts[0]
    title = parts[1]
    start_str = parts[2]
    end_str = parts[3]
    location = parts[4] if len(parts) > 4 else ""
    description = parts[5] if len(parts) > 5 else ""
    all_day = parts[6] if len(parts) > 6 else "false"
    uid = parts[7] if len(parts) > 7 else ""

    # Parse macOS date strings like "Saturday, 22 March 2026 at 2:00:00 PM"
    parsed_start = _parse_macos_date(start_str)
    parsed_end = _parse_macos_date(end_str)

    event = {
        "title": title,
        "calendar": cal_name,
        "start_time": parsed_start or start_str,
        "end_time": parsed_end or end_str,
        "location": location,
        "description": description[:200] if description else "",
        "is_all_day": all_day.lower() == "true",
        "uid": uid,
    }

    # Flag events during coding hours (10pm-4am)
    if parsed_start:
        try:
            hour = datetime.fromisoformat(parsed_start).hour
            if hour >= 22 or hour <= 4:
                event["warning"] = "Scheduled during coding hours (10pm-4am)"
        except Exception:
            pass

    return event


def _parse_macos_date(date_str: str) -> Optional[str]:
    """Parse macOS date string to ISO format."""
    # "Saturday, 22 March 2026 at 2:00:00 PM" or "Sunday, 22 March 2026 at 2:00:00 pm"
    formats = [
        "%A, %d %B %Y at %I:%M:%S %p",  # 12-hour with seconds
        "%A, %d %B %Y at %H:%M:%S",      # 24-hour with seconds
        "%d %B %Y at %I:%M:%S %p",       # Without day name
        "%d %B %Y at %H:%M:%S",          # Without day name, 24h
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            dt = dt.replace(tzinfo=TZ)
            return dt.isoformat()
        except ValueError:
            continue
    return None


# ── Tools ────────────────────────────────────────────────────────────────────


async def get_calendar(
    date: str = "today",
    view: str = "day",
) -> ToolResult:
    """Get calendar events from macOS Calendar. Date: 'today', 'tomorrow', 'next_event', or ISO date. View: 'day' or 'week'."""
    try:
        start_date, end_date = _parse_date_range(date, view)

        # Skip system calendars that are slow or irrelevant
        skip_cals = {"Birthdays", "Siri Suggestions", "Scheduled Reminders", "UK Holidays"}

        script = f'''
set startDate to current date
set year of startDate to {int(start_date[:4])}
set month of startDate to {int(start_date[5:7])}
set day of startDate to {int(start_date[8:10])}
set time of startDate to 0

set endDate to current date
set year of endDate to {int(end_date[:4])}
set month of endDate to {int(end_date[5:7])}
set day of endDate to {int(end_date[8:10])}
set time of endDate to 0

tell application "Calendar"
    set output to ""
    repeat with cal in calendars
        set calName to name of cal
        if calName is not in {{{", ".join('"' + c + '"' for c in skip_cals)}}} then
            try
                set evts to (every event of cal whose start date >= startDate and start date < endDate)
                repeat with evt in evts
                    set evtSummary to summary of evt
                    set evtStart to start date of evt as string
                    set evtEnd to end date of evt as string
                    set evtLocation to ""
                    try
                        set evtLocation to location of evt
                        if evtLocation is missing value then set evtLocation to ""
                    end try
                    set evtAllDay to allday event of evt
                    set evtUID to uid of evt
                    set output to output & calName & " | " & evtSummary & " | " & evtStart & " | " & evtEnd & " | " & evtLocation & " | " & " | " & evtAllDay & " | " & evtUID & linefeed
                end repeat
            end try
        end if
    end repeat
    return output
end tell
'''
        raw = await asyncio.to_thread(_run_applescript, script)

        events = []
        if raw:
            for line in raw.split("\n"):
                line = line.strip()
                if line:
                    event = _parse_event_line(line)
                    if event:
                        events.append(event)

        # Sort by start time
        events.sort(key=lambda e: e.get("start_time", ""))

        # For next_event, just return the first upcoming one
        if date == "next_event" and events:
            now_iso = datetime.now(TZ).isoformat()
            future = [e for e in events if e.get("start_time", "") >= now_iso]
            events = future[:1] if future else events[:1]

        return ToolResult(
            success=True,
            data=events,
            metadata={
                "date": date,
                "view": view,
                "event_count": len(events),
                "source": "macOS Calendar (iCloud)",
            },
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=f"Calendar read failed: {e}",
                severity=Severity.MEDIUM,
                recoverable=True,
            ),
        )


async def create_event(
    title: str,
    date: str,
    start_time: str,
    duration: int = 30,
    calendar_name: str = "Calendar",
    location: Optional[str] = None,
    description: Optional[str] = None,
    confirm: bool = False,
) -> ToolResult:
    """Create a calendar event in macOS Calendar. REQUIRES confirm=True — always preview first."""
    if not confirm:
        details = (
            f"Event NOT created. Review first:\n"
            f"  Title: {title}\n"
            f"  Date: {date} at {start_time}\n"
            f"  Duration: {duration} mins\n"
            f"  Calendar: {calendar_name}\n"
            f"  Location: {location or 'none'}\n\n"
            f"Call create_event again with confirm=True to create."
        )
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.DATA_VALIDATION,
                message=details,
                severity=Severity.LOW,
                recoverable=True,
                context={"title": title, "date": date, "start_time": start_time},
            ),
        )

    try:
        # Parse date/time
        start_dt = datetime.fromisoformat(f"{date}T{start_time}:00")
        end_dt = start_dt + timedelta(minutes=duration)

        # Escape strings for AppleScript
        safe_title = title.replace('"', '\\"')
        safe_loc = (location or "").replace('"', '\\"')
        safe_desc = (description or "").replace('"', '\\"')
        safe_cal = calendar_name.replace('"', '\\"')

        script = f'''
tell application "Calendar"
    set targetCal to first calendar whose name is "{safe_cal}"

    set startDate to current date
    set year of startDate to {start_dt.year}
    set month of startDate to {start_dt.month}
    set day of startDate to {start_dt.day}
    set time of startDate to ({start_dt.hour} * 3600 + {start_dt.minute} * 60)

    set endDate to current date
    set year of endDate to {end_dt.year}
    set month of endDate to {end_dt.month}
    set day of endDate to {end_dt.day}
    set time of endDate to ({end_dt.hour} * 3600 + {end_dt.minute} * 60)

    set newEvent to make new event at end of events of targetCal with properties {{summary:"{safe_title}", start date:startDate, end date:endDate, location:"{safe_loc}", description:"{safe_desc}"}}

    return uid of newEvent
end tell
'''
        uid = await asyncio.to_thread(_run_applescript, script)

        return ToolResult(
            success=True,
            data={
                "uid": uid,
                "title": title,
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "calendar": calendar_name,
                "location": location,
            },
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=f"Event creation failed: {e}",
                severity=Severity.MEDIUM,
                recoverable=True,
            ),
        )


# ── Tool Schemas ─────────────────────────────────────────────────────────────

TOOL_SCHEMAS = {
    "get_calendar": {
        "fn": get_calendar,
        "schema": {
            "type": "function",
            "function": {
                "name": "get_calendar",
                "description": "Get calendar events from macOS Calendar (iCloud). Returns events with times, location, calendar name.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "Date: 'today', 'tomorrow', 'next_event', or ISO date like '2026-03-25'",
                        },
                        "view": {
                            "type": "string",
                            "enum": ["day", "week"],
                            "description": "View: 'day' (default) or 'week'",
                        },
                    },
                    "required": [],
                },
            },
        },
    },
    "create_event": {
        "fn": create_event,
        "schema": {
            "type": "function",
            "function": {
                "name": "create_event",
                "description": "Create a calendar event in macOS Calendar. IMPORTANT: Set confirm=True only after the user has reviewed. Always preview first.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Event title"},
                        "date": {"type": "string", "description": "Date in ISO format: '2026-03-25'"},
                        "start_time": {"type": "string", "description": "Start time: '14:00'"},
                        "duration": {"type": "integer", "description": "Duration in minutes (default 30)"},
                        "calendar_name": {"type": "string", "description": "Calendar name (default 'Calendar'). Options: Calendar, Home, Work, etc."},
                        "location": {"type": "string", "description": "Event location"},
                        "description": {"type": "string", "description": "Event description"},
                        "confirm": {"type": "boolean", "description": "Must be true to actually create. False = preview only."},
                    },
                    "required": ["title", "date", "start_time"],
                },
            },
        },
    },
}
