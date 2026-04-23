"""Direct tool dispatch — 1 LLM picks tool, execute, 1 LLM formats.

New Priority 2.5 in the routing chain. Sits between oneshot (regex)
and agent dispatch (ReAct loop). Handles the long tail of single-tool
queries that oneshot's regex can't pattern-match.

Flow: 1 LLM call (pick tool) → execute → 1 LLM call (format) = 2 LLM calls.
vs agent ReAct: 3-4 LLM calls = 45-90s.
"""

import json as _json
from datetime import datetime
from friday.core.llm import cloud_chat, extract_tool_calls, extract_text, extract_stream_content
from friday.core.types import ToolResult
from friday.memory.conversation_log import log_turn

# ── Slim prompt for tool selection ──────────────────────────────────────────

DISPATCH_PROMPT = """You are FRIDAY, the user's personal AI assistant. Pick the right tool for the task.
Rules:
- Call exactly ONE tool. Never two.
- If the task needs multiple steps (e.g. read calendar THEN draft email, or search THEN post), respond with just: NEEDS_AGENT
- IMPORTANT: Anything involving filling forms, completing forms, submitting applications, or interacting with browser forms is ALWAYS multi-step. Respond with: NEEDS_AGENT
- IMPORTANT: Job applications, CV tailoring, cover letters, "apply for [role] at [company]", "go to [careers page]", "find me a job", "tailor my CV" — ALL multi-step. Respond with: NEEDS_AGENT
- IMPORTANT: "open [website]", "go to [URL]", browser navigation → NEEDS_AGENT (system_agent handles this).
- IMPORTANT: "apply", "fill out", "submit" → NEEDS_AGENT. Never search_web for these.
- IMPORTANT: Writing and SAVING a document/report/paper/file: "write a report about X and save to desktop", "create a PDF of Y", "save a summary to my documents", "research X and write a document" → NEEDS_AGENT. Direct dispatch cannot create files; deep_research_agent or code_agent handles these. NEVER search_web and summarise when the user wants a SAVED FILE.
- IMPORTANT: Any verb like "save", "create a file", "write to", "make a pdf/docx/markdown", combined with a location ("desktop", "documents", "downloads", "~/...") → NEEDS_AGENT.
- IMPORTANT: Confirmations like "yes", "go ahead", "do it" that follow a previous agent task are continuations. Respond with: NEEDS_AGENT
- IMPORTANT: "check messages" / "read messages" / "what did X say" = read_imessages. create_watch is ONLY for setting up recurring background monitoring ("watch X's messages for the next hour"). Don't confuse one-time reads with standing orders.
- If it's casual chat, a greeting ("yo", "hey", "sup"), or an opinion question with no factual answer, respond with just the text: NO_TOOL
- IMPORTANT: If the recent conversation was about EMAILS (checking mail, order confirmations, email content), and the user asks a follow-up question about that content — use search_emails or read_emails to find the answer, NOT search_web. The answer is in the email, not on the web.
- If the user asks a factual question NOT related to their emails/calendar (specs, features, people, events, how something works), use search_web to find the answer.
- CRITICAL: When calling search_web, NEVER use pronouns like "it", "that", "this", "they" in the query. Replace them with the actual name from the conversation. Example: if talking about a product called Halo, search "Halo processor specs" NOT "what processor does it use".
- "send sms" / "text me on sms" / "sms me" → use send_sms. The user's own number is the CONTACT_PHONE env var. If sending to someone else, search_contacts first to get the number.
- "text Mom" / "message Mom" / "text [name]" → use send_imessage (iMessage), NOT send_sms. SMS is only for explicit "sms" requests.
- "draft email then X" / "check Y then do Z" → multiple steps, respond: NEEDS_AGENT
- Mac chained actions → NEEDS_AGENT. If the task has TWO verbs connected by and/then/plus (e.g. "open notes AND paste X", "take a screenshot AND describe it", "open app AND play Y", "open X and search Y"), you CANNOT handle it with one tool — respond: NEEDS_AGENT.
- "open [app] and type/paste/search/play [something]" → NEEDS_AGENT.
- "take a screenshot and [describe/analyze/explain/tell me what]" → NEEDS_AGENT.
Current time: {time}"""


def get_format_prompt() -> str:
    """Formatter prompt, personalised to the current user config."""
    from friday.core.user_config import USER
    header = f"You are {USER.assistant_name}."
    if USER.is_configured:
        header += f" {USER.possessive} AI. Built by them. Running on their machine."
        if USER.bio_line():
            header += f"\n{USER.display_name}: {USER.bio_line()}."
    return (
        f"{header}\n"
        "Voice: brilliant friend who's also an engineer. Witty, real. Never corporate.\n"
        "For simple results (email sent, draft saved): 1-2 sentences.\n"
        "For information/research results: give a proper answer with the key details. Don't cut short.\n\n"
        "HONESTY (CRITICAL):\n"
        "Describe ONLY what the tool actually did. Read the tool result and report it as-is.\n"
        "NEVER claim actions the tool didn't perform. If the user asked for \"open X and do Y\" but only "
        "open_application was called, say \"Opened X — I didn't do Y (needs more tools)\" and STOP. "
        "Don't fabricate that the second step happened."
    )


# Backwards-compat — frozen at import. Prefer get_format_prompt() for live reload.
FORMAT_PROMPT = get_format_prompt()


# ── Curated tool registry ───────────────────────────────────────────────────

_tools_built = False
DIRECT_TOOLS = {}
DIRECT_TOOL_SCHEMAS = []

TOOL_NAMES = [
    # Communication — most common single-tool queries
    "read_emails", "search_emails", "draft_email",
    "get_calendar",
    # iMessage + FaceTime
    "read_imessages", "send_imessage", "start_facetime", "search_contacts",
    # WhatsApp
    "read_whatsapp", "send_whatsapp", "search_whatsapp", "whatsapp_status",
    # SMS
    "send_sms", "read_sms",
    # Telegram (second channel — rich media since UK SMS can't carry MMS)
    "send_telegram_message", "send_telegram_photo", "send_telegram_audio",
    "send_telegram_voice", "send_telegram_document", "send_telegram_video",
    # Social
    "search_x", "get_my_mentions",
    # Information
    "search_web",
    # Memory
    "store_memory", "search_memory",
    # Cron management
    "create_cron", "list_crons", "delete_cron", "toggle_cron",
    # Watch tasks (standing orders)
    "create_watch", "list_watches", "cancel_watch",
    # Screen tools (OCR + vision + full page + solve + general read)
    "ocr_screen", "ask_about_screen", "capture_full_page", "solve_screen_questions", "read_screen",
    # Screen casting (AirPlay) + extended display
    "cast_screen_to", "stop_screencast", "open_on_extended_display", "list_displays",
    # Mac control (app launching, volume, dark mode, typing, music, URL open)
    "open_application", "close_application", "type_text", "set_volume", "toggle_dark_mode", "play_music", "open_url",
    # File conversion
    "convert_file",
    # Note: send_email, post_tweet excluded — usually need confirmation context.
    # Note: get_call_history, get_daily_digest excluded — briefing handles these.
]


def _build_tools():
    """Lazy-load tool schemas from all relevant modules."""
    global _tools_built, DIRECT_TOOLS, DIRECT_TOOL_SCHEMAS
    if _tools_built:
        return

    from friday.tools.email_tools import TOOL_SCHEMAS as email
    from friday.tools.calendar_tools import TOOL_SCHEMAS as cal
    from friday.tools.call_tools import TOOL_SCHEMAS as calls
    from friday.tools.web_tools import TOOL_SCHEMAS as web
    from friday.tools.x_tools import TOOL_SCHEMAS as x
    from friday.tools.mac_tools import TOOL_SCHEMAS as mac
    from friday.tools.memory_tools import TOOL_SCHEMAS as mem
    from friday.tools.file_tools import TOOL_SCHEMAS as files
    from friday.tools.briefing_tools import TOOL_SCHEMAS as brief
    from friday.tools.imessage_tools import TOOL_SCHEMAS as imsg
    from friday.tools.cron_tools import TOOL_SCHEMAS as cron
    from friday.tools.watch_tools import TOOL_SCHEMAS as watch
    from friday.tools.screen_tools import TOOL_SCHEMAS as screen
    from friday.tools.screencast_tools import TOOL_SCHEMAS as cast

    # WhatsApp — optional
    try:
        from friday.tools.whatsapp_tools import TOOL_SCHEMAS as wa
    except Exception:
        wa = {}

    # SMS — optional
    try:
        from friday.tools.sms_tools import TOOL_SCHEMAS as sms
    except Exception:
        sms = {}

    # Telegram — optional (rich media fallback when SMS can't carry MMS)
    try:
        from friday.tools.telegram_tools import TOOL_SCHEMAS as tg
    except Exception:
        tg = {}

    all_schemas = {}
    for src in [email, cal, calls, web, x, mac, mem, files, brief, imsg, cron, watch, screen, cast, wa, sms, tg]:
        all_schemas.update(src)

    DIRECT_TOOLS.update({n: all_schemas[n] for n in TOOL_NAMES if n in all_schemas})
    # Normalize all schemas to OpenAI format: {"type": "function", "function": {...}}
    for t in DIRECT_TOOLS.values():
        s = t["schema"]
        if s.get("type") == "function" and "function" in s:
            DIRECT_TOOL_SCHEMAS.append(s)  # Already wrapped
        else:
            DIRECT_TOOL_SCHEMAS.append({"type": "function", "function": s})
    _tools_built = True


# ── Core dispatch function ──────────────────────────────────────────────────

async def try_direct_dispatch(
    user_input: str,
    conversation: list[dict],
    _ack,
    _status,
    _chunk,
    session_id=None,
    memory=None,
    mem_processor=None,
) -> bool:
    """Try to handle with 1 LLM tool call + 1 LLM format.

    Returns True if handled, False to fall through to agent dispatch.
    """
    import re

    _build_tools()

    if not DIRECT_TOOL_SCHEMAS:
        return False

    # Let the LLM decide if a tool is needed for most queries.
    # Skip only for obvious casual chat to avoid wasting an LLM call.
    s = user_input.strip().lower()
    word_count = len(s.split())

    # Short greetings/reactions — never need tools
    if word_count <= 4 and "?" not in user_input and not re.search(r"\b(search|check|find|email|calendar|tweet|draft)\b", s):
        return False

    # Obvious casual chat patterns — skip dispatch, go straight to fast_chat
    if re.match(r"^(yo|hey|sup|hi|hello|hawfar|whats good|whats up|how are you|lol|haha|nah|yeah|ok|sure|thanks|cheers)\b", s):
        if word_count <= 8 and "?" not in user_input:
            return False

    # Follow-ups, complaints, corrections — these are conversational, not tool calls
    if re.search(r"\b(that wasnt|that wasn.t|that.s not|thats not|i didn.t|i said|not what i|you didn.t|wrong|i meant|i was asking|no i want)\b", s):
        return False

    # Research + save queries need research_agent (or deep_research_agent),
    # not direct_dispatch. Direct dispatch would call search_web and return
    # text without ever creating a file. Bail out so priority 3 can classify.
    if re.search(r"\b(write|create|save|make|draft|build|generate|produce)\b", s) \
       and re.search(r"\b(report|paper|document|summary|analysis|file|note|essay|article|brief|overview|pdf|docx|markdown|md|txt)\b", s):
        return False

    # "save to [location]" is always multi-step
    if re.search(r"\b(save|write|export|put)\b.*\b(desktop|documents|downloads|to\s+my|to\s+a\s+file|~/|/users/)", s):
        return False

    # Form filling is multi-step (discover → fill → verify) — needs agent, not single tool
    if "fill" in s and ("form" in s or "field" in s or "application" in s):
        return False

    # If input contains a URL, skip — URLs need research_agent for full page fetch + analysis
    if re.search(r'https?://\S+', s):
        return False

    # Code/file tasks need code_agent's full tool set, not the limited direct dispatch
    # Let LLM classify route these to code_agent instead
    if re.search(r"\b(write|create|build|save)\s+.*(\.py|\.js|\.html|\.css|file|script|function|page|component)\b", s):
        return False

    # Chained tasks starting with "open/launch/start [app]" + " and/then " are
    # multi-step. Direct dispatch only does 1 tool call — it would open the app
    # and the LLM would hallucinate the second step. Bail to system_agent.
    words = s.split()
    if words and words[0] in ("open", "launch", "start") and (" and " in s or " then " in s):
        return False


    # Build messages — slim prompt + conversation context
    now = datetime.now().strftime("%A %d %B %Y, %H:%M")
    messages = [{"role": "system", "content": DISPATCH_PROMPT.format(time=now)}]

    # Last 10 conversation messages for topic context
    for msg in conversation[-10:]:
        messages.append({**msg, "content": msg["content"][:300]})
    messages.append({"role": "user", "content": user_input})

    _status("thinking...")
    response = cloud_chat(messages=messages, tools=DIRECT_TOOL_SCHEMAS)

    tool_calls = extract_tool_calls(response)
    text = extract_text(response)

    # ── Fallthrough cases ──

    # Model says it needs an agent for multi-step work
    if not tool_calls and "NEEDS_AGENT" in text:
        return False

    # Model says no tool fits
    if not tool_calls and "NO_TOOL" in text:
        return False

    # Multiple tool calls = multi-step, needs agent
    if len(tool_calls) > 1:
        return False

    # No tool call, just conversational text → let fast_chat handle (better personality)
    if not tool_calls:
        return False

    # ── Single tool call — execute it ──

    tc = tool_calls[0]
    name = tc["name"]
    args = tc["arguments"]

    if name not in DIRECT_TOOLS:
        return False

    label = name.replace("_", " ")
    _ack(f"on it")
    _status(f"{label}...")

    try:
        result = await DIRECT_TOOLS[name]["fn"](**args)
    except Exception:
        return False  # let agent try with domain knowledge

    # ── Handle result ──

    if isinstance(result, ToolResult) and not result.success:
        err = result.error.message if result.error else "That didn't work."
        _chunk(err)
        # Log + update conversation
        if memory:
            memory.log_agent_call(
                session_id=session_id, agent="direct_dispatch", tool=name,
                args=args, result_summary=err[:200], success=False, duration_ms=0,
            )
        return True

    # Extract data from ToolResult
    data = result.data if isinstance(result, ToolResult) else result

    # Some tools just need a confirmation, not an LLM format call
    INSTANT_CONFIRM = {"store_memory"}
    if name in INSTANT_CONFIRM:
        _chunk("Got it, remembered.")
        if memory:
            memory.log_agent_call(
                session_id=session_id, agent="direct_dispatch", tool=name,
                args=args, result_summary="instant confirm", success=True, duration_ms=0,
            )
        return True

    # Format with 1 streamed LLM call
    return await _format_and_stream(
        user_input, data, name, _status, _chunk,
        session_id=session_id, memory=memory, mem_processor=mem_processor,
    )


async def _format_and_stream(
    user_input, tool_data, tool_name, _status, _chunk,
    session_id=None, memory=None, mem_processor=None,
) -> bool:
    """Format tool results with 1 streamed LLM call."""
    _status("formatting...")

    data_str = _json.dumps(tool_data, default=str)
    if len(data_str) > 6000:
        data_str = data_str[:6000] + "..."

    messages = [
        {"role": "system", "content": get_format_prompt()},
        {"role": "user", "content": user_input},
        {"role": "system", "content": f"Tool results:\n{data_str}\n\nRespond based on these results. Stay on topic — answer what the user actually asked. Be direct and conversational."},
    ]

    response_stream = cloud_chat(messages=messages, stream=True, max_tokens=400)
    full_text = []
    for chunk in response_stream:
        content = extract_stream_content(chunk)
        if content:
            _chunk(content)
            full_text.append(content)

    response_text = "".join(full_text)

    # Log + memory
    if memory:
        memory.log_agent_call(
            session_id=session_id, agent="direct_dispatch", tool=tool_name,
            args={"task": user_input}, result_summary=response_text[:200],
            success=True, duration_ms=0,
        )
    log_turn(session_id, user_input, response_text, route="direct_dispatch", tools_called=[tool_name])
    if mem_processor:
        mem_processor.process(user_input, response_text, "direct_dispatch")

    return True
