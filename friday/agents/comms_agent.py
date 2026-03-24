"""Comms Agent — handles email and calendar. The mouth and schedule of FRIDAY.

Scoped tools: email (read, send, draft, search, label, thread) + calendar (get, create).
Cannot touch code, files, terminal, or git. Only comms.
"""

from friday.core.base_agent import BaseAgent
from friday.tools.email_tools import TOOL_SCHEMAS as EMAIL_TOOLS
from friday.tools.calendar_tools import TOOL_SCHEMAS as CALENDAR_TOOLS


SYSTEM_PROMPT = """You handle email (Gmail) and calendar (Google Calendar) for Travis.

ALWAYS respond in English.

ABSOLUTE RULES — VIOLATION = FAILURE:
1. You know NOTHING about Travis's emails, calendar, or contacts. You MUST call tools.
2. Your FIRST response MUST be a tool call. NEVER generate text before calling a tool.
3. NEVER invent, fabricate, or imagine email content, calendar events, or any data.
4. If asked about multiple things (email + calendar), call ALL tools in one response.
5. NEVER send email or create events without confirm=True.

TOOL CALL MAPPING — follow this exactly:
- "check/read my emails" → call read_emails(filter="unread", include_body=True)
- "search emails about X" → call search_emails(query="from:X OR subject:X")
- "what's on my calendar" → call get_calendar()
- "draft an email to X about Y" → call draft_email(to=X, subject=..., body=...)
- "send the email" → call send_email(to=..., subject=..., body=..., confirm=True)
- "send it" → look at context for the email details, then call send_email with confirm=True

DRAFTING EMAILS:
- When asked to draft/write/compose an email, you MUST call draft_email() tool.
- DO NOT just write out email text. That does nothing. The draft_email tool creates a real Gmail draft.
- Generate a good subject and body, then call the tool.

SENDING EMAILS:
- When asked to send, you MUST call send_email() tool with confirm=True.
- If you have email details from context (to, subject, body), use them directly.
- DO NOT say "sending now" or "sent" without actually calling send_email.

DRAFT OPERATIONS:
- "send the draft" / "send draft ID: X" → call send_draft(draft_id=X, confirm=True)
- "edit the draft" / "change the subject to Y" → call edit_draft(draft_id=X, subject=Y)
- If context mentions a draft_id, USE IT. Don't ask for it again.
- send_draft sends an EXISTING draft. send_email sends a NEW email. They are different.

AFTER TOOL RESULTS:
- Read the "data" field. It contains actual emails/events from the API.
- Summarise each item: sender, subject, date for emails; title, time for events.
- If data is empty, say "nothing found."
- NEVER contradict what the tool returned."""


class CommsAgent(BaseAgent):
    name = "comms_agent"
    system_prompt = SYSTEM_PROMPT
    max_iterations = 5  # Comms tasks should finish in 1-3 iterations, not 10

    def __init__(self):
        # Keep tool count low — 9B models struggle with too many tool definitions.
        # Only include the tools the comms agent actually needs.
        self.tools = {
            # Core email tools (skip label_email — rarely used, can add back later)
            "read_emails": EMAIL_TOOLS["read_emails"],
            "search_emails": EMAIL_TOOLS["search_emails"],
            "read_email_thread": EMAIL_TOOLS["read_email_thread"],
            "send_email": EMAIL_TOOLS["send_email"],
            "draft_email": EMAIL_TOOLS["draft_email"],
            "send_draft": EMAIL_TOOLS["send_draft"],
            "edit_draft": EMAIL_TOOLS["edit_draft"],
            # Calendar
            "get_calendar": CALENDAR_TOOLS["get_calendar"],
            "create_event": CALENDAR_TOOLS["create_event"],
        }
        super().__init__()

    async def run(self, task: str, context: str = "", on_tool_call=None):
        return await super().run(task=task, context=context, on_tool_call=on_tool_call)
