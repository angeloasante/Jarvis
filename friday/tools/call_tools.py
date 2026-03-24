"""Call history tools — phone calls, FaceTime, WhatsApp.

Reads call logs from macOS databases:
  - Native (Phone + FaceTime): ~/Library/Application Support/CallHistoryDB/CallHistory.storedata
    Requires Full Disk Access for Terminal/Python.
  - WhatsApp: ~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/CallHistory.sqlite
    No special permissions needed.

Voicemail is NOT available on macOS (stays on iPhone/carrier only).
"""

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from friday.core.types import ToolResult, ToolError, ErrorCode, Severity


# Database paths
CALL_HISTORY_DB = Path.home() / "Library" / "Application Support" / "CallHistoryDB" / "CallHistory.storedata"
WHATSAPP_CALL_DB = Path.home() / "Library" / "Group Containers" / "group.net.whatsapp.WhatsApp.shared" / "CallHistory.sqlite"

# CoreData epoch offset (2001-01-01 vs 1970-01-01)
COREDATA_EPOCH = 978307200


def _coredata_to_datetime(timestamp: float) -> str:
    """Convert CoreData timestamp to readable datetime."""
    if not timestamp:
        return "unknown"
    try:
        dt = datetime.fromtimestamp(timestamp + COREDATA_EPOCH, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError):
        return "unknown"


def _seconds_to_duration(seconds: float) -> str:
    """Convert seconds to human-readable duration."""
    if not seconds or seconds <= 0:
        return "0s"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m}m"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


async def get_call_history(
    limit: int = 20,
    call_type: str = "all",
    missed_only: bool = False,
) -> ToolResult:
    """Get recent phone/FaceTime call history from macOS.

    Args:
        limit: Number of recent calls to return (default 20).
        call_type: "all", "phone", "facetime", or "whatsapp".
        missed_only: If True, only show missed calls.

    Requires Full Disk Access for phone/FaceTime calls.
    WhatsApp calls are always accessible.
    """

    def _read_native():
        """Read native Phone + FaceTime call history."""
        if not CALL_HISTORY_DB.exists():
            return None, "Call history database not found. iPhone may not be synced to this Mac."

        try:
            conn = sqlite3.connect(f"file:{CALL_HISTORY_DB}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # CoreData table for call records
            query = """
                SELECT
                    ZCALLRECORD.ZDATE as date,
                    ZCALLRECORD.ZDURATION as duration,
                    ZCALLRECORD.ZANSWERED as answered,
                    ZCALLRECORD.ZORIGINATED as originated,
                    ZCALLRECORD.ZCALLTYPE as call_type,
                    ZCALLRECORD.ZJUNKCONFIDENCE as junk_confidence,
                    ZCALLRECORD.ZREAD as is_read,
                    ZHANDLE.ZVALUE as contact
                FROM ZCALLRECORD
                LEFT JOIN ZHANDLE ON ZCALLRECORD.ZHANDLE = ZHANDLE.Z_PK
                ORDER BY ZCALLRECORD.ZDATE DESC
                LIMIT ?
            """
            cursor.execute(query, (limit * 2,))  # Fetch extra for filtering
            rows = cursor.fetchall()
            conn.close()

            calls = []
            for row in rows:
                is_answered = bool(row["answered"])
                is_outgoing = bool(row["originated"])
                ct = row["call_type"] or 0

                # Filter by type
                is_facetime = ct in (8, 16)  # Video/audio FaceTime
                if call_type == "phone" and is_facetime:
                    continue
                if call_type == "facetime" and not is_facetime:
                    continue

                # Filter missed
                is_missed = not is_answered and not is_outgoing
                if missed_only and not is_missed:
                    continue

                call = {
                    "contact": row["contact"] or "Unknown",
                    "date": _coredata_to_datetime(row["date"]),
                    "duration": _seconds_to_duration(row["duration"] or 0),
                    "direction": "outgoing" if is_outgoing else "incoming",
                    "answered": is_answered,
                    "missed": is_missed,
                    "type": "facetime" if is_facetime else "phone",
                }

                if row["junk_confidence"] and row["junk_confidence"] > 0.5:
                    call["likely_spam"] = True

                calls.append(call)
                if len(calls) >= limit:
                    break

            return calls, None

        except sqlite3.OperationalError as e:
            err = str(e)
            if "unable to open" in err or "not permitted" in err or "authorization denied" in err:
                return None, (
                    "Full Disk Access needed. Go to System Settings → Privacy & Security → "
                    "Full Disk Access → add Terminal (or your Python app)."
                )
            return None, f"Database error: {err}"
        except Exception as e:
            return None, f"Failed to read call history: {e}"

    def _read_whatsapp():
        """Read WhatsApp call history from aggregate events."""
        if not WHATSAPP_CALL_DB.exists():
            return None, "WhatsApp not installed or no call history."

        try:
            conn = sqlite3.connect(f"file:{WHATSAPP_CALL_DB}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # ZWAAGGREGATECALLEVENT has the cleanest data:
            # ZVIDEO, ZMISSED, ZINCOMING, ZFIRSTDATE
            # Contact info isn't easily available (uses LIDs not phone numbers)
            query = """
                SELECT
                    ZFIRSTDATE as date,
                    ZVIDEO as is_video,
                    ZMISSED as missed,
                    ZINCOMING as incoming
                FROM ZWAAGGREGATECALLEVENT
                ORDER BY ZFIRSTDATE DESC
                LIMIT ?
            """
            cursor.execute(query, (limit * 2,))
            rows = cursor.fetchall()
            conn.close()

            calls = []
            for row in rows:
                is_missed = bool(row["missed"])
                is_incoming = bool(row["incoming"])

                # Filter missed only
                if missed_only and not is_missed:
                    continue

                call = {
                    "contact": "WhatsApp contact",
                    "date": _coredata_to_datetime(row["date"]),
                    "duration": "0s" if is_missed else "answered",
                    "direction": "incoming" if is_incoming else "outgoing",
                    "missed": is_missed,
                    "type": "whatsapp_video" if row["is_video"] else "whatsapp",
                }
                calls.append(call)
                if len(calls) >= limit:
                    break

            return calls, None

        except Exception as e:
            return None, f"Failed to read WhatsApp calls: {e}"

    # Run reads
    results = {"calls": [], "sources": [], "errors": []}

    if call_type in ("all", "phone", "facetime"):
        native_calls, native_err = await asyncio.to_thread(_read_native)
        if native_calls:
            results["calls"].extend(native_calls)
            results["sources"].append("phone/facetime")
        if native_err:
            results["errors"].append(native_err)

    if call_type in ("all", "whatsapp"):
        wa_calls, wa_err = await asyncio.to_thread(_read_whatsapp)
        if wa_calls:
            results["calls"].extend(wa_calls)
            results["sources"].append("whatsapp")
        if wa_err:
            results["errors"].append(wa_err)

    # Sort all calls by date (newest first)
    results["calls"].sort(key=lambda c: c.get("date", ""), reverse=True)
    results["calls"] = results["calls"][:limit]

    # Count stats
    missed = [c for c in results["calls"] if c.get("missed")]
    results["total"] = len(results["calls"])
    results["missed_count"] = len(missed)

    if not results["calls"] and results["errors"]:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED,
            message=" | ".join(results["errors"]),
            severity=Severity.MEDIUM, recoverable=True))

    return ToolResult(success=True, data=results)


# ═════════════════════════════════════════════════════════════════════════════
# TOOL SCHEMAS
# ═════════════════════════════════════════════════════════════════════════════

TOOL_SCHEMAS = {
    "get_call_history": {
        "fn": get_call_history,
        "schema": {"type": "function", "function": {
            "name": "get_call_history",
            "description": (
                "Get recent phone, FaceTime, and WhatsApp call history. "
                "Shows caller, time, duration, direction, and missed status. "
                "Phone/FaceTime needs Full Disk Access; WhatsApp always works."
            ),
            "parameters": {"type": "object", "properties": {
                "limit": {"type": "integer", "description": "Number of calls (default 20)"},
                "call_type": {
                    "type": "string",
                    "enum": ["all", "phone", "facetime", "whatsapp"],
                    "description": "Filter by call type (default: all)",
                },
                "missed_only": {"type": "boolean", "description": "Only show missed calls (default: false)"},
            }, "required": []},
        }},
    },
}
