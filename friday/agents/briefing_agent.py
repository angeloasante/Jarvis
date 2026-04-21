"""Briefing Agent — synthesises monitor alerts, emails, calendar into tight briefings.

Two types:
  Morning briefing — comprehensive, proactive
  Quick briefing — one thing, two sentences
"""

from friday.core.base_agent import BaseAgent
from friday.core.user_config import USER
from friday.tools.briefing_tools import TOOL_SCHEMAS as BRIEFING_TOOLS
from friday.tools.email_tools import TOOL_SCHEMAS as EMAIL_TOOLS
from friday.tools.calendar_tools import TOOL_SCHEMAS as CALENDAR_TOOLS
from friday.tools.call_tools import TOOL_SCHEMAS as CALL_TOOLS
from friday.tools.x_tools import TOOL_SCHEMAS as X_TOOLS


_CORE_PROMPT = """You are FRIDAY's briefing specialist.

ALWAYS respond in English.

CRITICAL: You have ZERO knowledge about the user's emails, calendar, calls, or X feed.
Your FIRST action MUST be tool calls. NEVER generate a briefing from imagination.
NEVER say "I'll check" or "let me pull" — just call the tools immediately.

YOUR JOB: synthesise information into a tight, useful briefing.
Not a wall of text. Not a list of everything.
The things that actually matter right now.

MORNING BRIEFING FORMAT:
Lead with anything critical (monitor alerts, urgent emails).
Then: what's on today (calendar).
Then: anything worth knowing before the day starts.
End with one question or focus prompt.
Max 150 words unless something is genuinely important.

EVENING BRIEFING FORMAT:
What happened today — monitor alerts, emails.
Tomorrow's calendar.
One honest reflection if warranted.
Max 100 words.

QUICK BRIEFING FORMAT:
One thing. The most important thing.
Two sentences max.

HOW TO BUILD A BRIEFING:
1. Call get_daily_digest() to get monitor alerts + queued items
2. Call read_emails(filter="unread") to get latest emails
3. Call get_calendar() to get today's schedule
4. Call get_call_history(limit=10) to check for missed calls
5. Pull X updates (see X MONITORING below)
6. Synthesise into the briefing format
7. Call mark_briefing_delivered() with the IDs of items you included

CALLS:
- Always check for missed calls and mention them
- If someone called and it was missed, say who and when
- WhatsApp calls show up too
- Don't list every call — just missed ones and important recent ones
- If no missed calls, don't mention calls at all
"""


_X_DEFAULT = """X (TWITTER) MONITORING:
- Pull @mentions only (get_my_mentions) — no personalised watchlist configured.
- Don't pad X output. If no mentions, say so and move on.
"""


_TONE_DEFAULT = """TONE RULES:
- No corporate summary language.
- Lead with what the user needs to act on, not what happened.
- If nothing important: say "all quiet" and move on.
- If something is urgent: say so first, plainly.
"""


_MONITOR_AND_EXAMPLES = """MONITOR ALERT INTEGRATION:
When a monitor alert is in the queue:
- Always surface it, even in quick briefings
- State what changed, not just that something changed
- Give the source URL
- State the implication for the user specifically

EXAMPLES OF GOOD BRIEFING:
"Three things.
Monitored page updated — new docs dropped worth reading.
You've got nothing on calendar today.
Two new bookings overnight.
What are we working on?"

EXAMPLES OF BAD BRIEFING:
"Good morning! Here is your daily summary:
- Email: You have 4 unread emails
- Calendar: No events today
- Monitors: 1 update detected
Please review the above items."

AFTER DELIVERING:
Mark all included items as delivered so they don't repeat."""


def _x_block() -> str:
    """Render X monitoring section from USER.briefing_watchlist.

    watchlist entry shape: {"handle": "@samgeorgegh", "note": "..."}
                      or: {"query": "galamsey OR illegal mining Ghana", "note": "..."}
    """
    if not USER.briefing_watchlist:
        return _X_DEFAULT

    lines = ["X (TWITTER) MONITORING:",
             "- Always pull X data during morning/evening briefings",
             "- get_my_mentions() — any new @mentions (surface first, they're actionable)"]
    for entry in USER.briefing_watchlist:
        handle = entry.get("handle", "").strip()
        query = entry.get("query", "").strip()
        note = entry.get("note", "").strip() or "(no note)"
        if handle:
            lines.append(
                f'- search_x(query="from:{handle.lstrip("@")}", max_results=10) — {note}'
            )
        elif query:
            lines.append(
                f'- search_x(query="{query}", max_results=10) — {note}'
            )
    lines.append("- Don't dump all tweets. Pick the 2-3 most interesting. Skip noise.")
    lines.append('- If nothing interesting on X, say "X is quiet" and move on. Don\'t pad it.')
    return "\n".join(lines)


def _tone_block() -> str:
    """Tone block — add user-context line if configured."""
    if not USER.is_configured:
        return _TONE_DEFAULT
    parts = ["TONE RULES:"]
    bio = USER.bio_line()
    if bio:
        parts.append(f"- Context on who you're briefing: {bio}.")
    parts.extend([
        "- No corporate summary language.",
        "- Lead with what they need to act on, not what happened.",
        '- If nothing important: say "all quiet" and move on.',
        "- If something is urgent: say so first, plainly.",
    ])
    if USER.tone:
        parts.append(f"- Voice note: {USER.tone}.")
    return "\n".join(parts)


def get_system_prompt() -> str:
    return "\n\n".join([
        _CORE_PROMPT,
        _x_block(),
        _tone_block(),
        _MONITOR_AND_EXAMPLES,
    ])


SYSTEM_PROMPT = get_system_prompt()


class BriefingAgent(BaseAgent):
    name = "briefing_agent"
    system_prompt = SYSTEM_PROMPT
    max_iterations = 10

    def __init__(self):
        # Rebuild the system prompt from current config (so UI edits take effect
        # without a restart — any new BriefingAgent instance picks up fresh USER).
        self.system_prompt = get_system_prompt()
        self.tools = {
            **BRIEFING_TOOLS,
            "read_emails": EMAIL_TOOLS["read_emails"],
            "get_calendar": CALENDAR_TOOLS["get_calendar"],
            "get_call_history": CALL_TOOLS["get_call_history"],
            "search_x": X_TOOLS["search_x"],
            "get_my_mentions": X_TOOLS["get_my_mentions"],
        }
        super().__init__()

    async def run(self, task: str, context: str = "", on_tool_call=None, on_chunk=None):
        return await super().run(task=task, context=context, on_tool_call=on_tool_call, on_chunk=on_chunk)
