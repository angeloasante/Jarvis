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

# ── Slim prompt for tool selection ──────────────────────────────────────────

DISPATCH_PROMPT = """You are FRIDAY, Travis's AI assistant. Pick the right tool for the task.
Rules:
- Call exactly ONE tool. Never two.
- If the task needs multiple steps (e.g. read calendar THEN draft email, or search THEN post), respond with just: NEEDS_AGENT
- If it's casual chat, a greeting, or an opinion question with no factual answer, respond with just: NO_TOOL
- IMPORTANT: If the recent conversation was about EMAILS (checking mail, order confirmations, email content), and the user asks a follow-up question about that content — use search_emails or read_emails to find the answer, NOT search_web. The answer is in the email, not on the web.
- If the user asks a factual question NOT related to their emails/calendar (specs, features, people, events, how something works), use search_web to find the answer.
- CRITICAL: When calling search_web, NEVER use pronouns like "it", "that", "this", "they" in the query. Replace them with the actual name from the conversation. Example: if talking about the Brilliant Labs Halo, search "Brilliant Labs Halo processor" NOT "what processor does it use".
Current time: {time}"""

FORMAT_PROMPT = """You are FRIDAY. Travis's AI. Built by him. Running on his machine.
Travis: Ghanaian founder based in Plymouth UK.
Voice: brilliant friend who's also an engineer. Witty, real. Never corporate.
For simple results (email sent, draft saved): 1-2 sentences.
For information/research results: give a proper answer with the key details. Don't cut short."""


# ── Curated tool registry ───────────────────────────────────────────────────

_tools_built = False
DIRECT_TOOLS = {}
DIRECT_TOOL_SCHEMAS = []

TOOL_NAMES = [
    # Communication — most common single-tool queries
    "read_emails", "search_emails", "draft_email",
    "get_calendar",
    # Social
    "search_x", "get_my_mentions",
    # Information
    "search_web",
    # Memory
    "store_memory", "search_memory",
    # Note: system tools (screenshot, open, battery) already handled by oneshot regex.
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

    all_schemas = {}
    for src in [email, cal, calls, web, x, mac, mem, files, brief]:
        all_schemas.update(src)

    DIRECT_TOOLS.update({n: all_schemas[n] for n in TOOL_NAMES if n in all_schemas})
    DIRECT_TOOL_SCHEMAS.extend([t["schema"] for t in DIRECT_TOOLS.values()])
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

    # Build messages — slim prompt + conversation context
    now = datetime.now().strftime("%A %d %B %Y, %H:%M")
    messages = [{"role": "system", "content": DISPATCH_PROMPT.format(time=now)}]

    # Last 4 conversation messages for topic context (critical for pronoun resolution)
    for msg in conversation[-4:]:
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
        {"role": "system", "content": FORMAT_PROMPT},
        {"role": "user", "content": user_input},
        {"role": "system", "content": f"Tool results:\n{data_str}\n\nRespond based on these results. Stay on topic — answer what Travis actually asked. Be direct and conversational."},
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
    if mem_processor:
        mem_processor.process(user_input, response_text, "direct_dispatch")

    return True
