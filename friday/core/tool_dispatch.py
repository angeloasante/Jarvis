"""Direct tool dispatch — 1 LLM picks tool, execute, 1 LLM formats.

New Priority 2.5 in the routing chain. Sits between oneshot (regex)
and agent dispatch (ReAct loop). Handles the long tail of single-tool
queries that oneshot's regex can't pattern-match.

Flow: 1 LLM call (pick tool) → execute → 1 LLM call (format) = 2 LLM calls.
vs agent ReAct: 3-4 LLM calls = 45-90s.
"""

import json as _json
from datetime import datetime
from friday.core.llm import chat, extract_tool_calls, extract_text
from friday.core.types import ToolResult

# ── Slim prompt for tool selection ──────────────────────────────────────────

DISPATCH_PROMPT = """You are FRIDAY, Travis's AI assistant. Pick the right tool for the task.
Rules:
- Call exactly ONE tool. Never two.
- If the task needs multiple steps (e.g. read calendar THEN draft email, or search THEN post), respond with just: NEEDS_AGENT
- If no tool fits the task, respond with just: NO_TOOL
Current time: {time}"""

FORMAT_PROMPT = """You are FRIDAY. Travis's AI. Built by him. Running on his machine.
Travis: Ghanaian founder, Plymouth UK, self-taught, builds at 2-4am.
Voice: brilliant friend who's also an engineer. Witty, short, real. Never corporate.
Reply in ONE or TWO sentences MAX. Be direct and conversational."""


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

    # Skip dispatch for obvious chat — don't waste 10s on LLM tool selection
    s = user_input.strip().lower()
    if len(s) < 15 and not any(kw in s for kw in (
        "email", "search", "calendar", "tweet", "post", "check", "find",
        "look", "open", "screenshot", "remember", "recall", "read", "draft",
        "send", "monitor", "battery", "volume", "file", "call", "mention",
    )):
        return False

    # Build messages — slim prompt + minimal context
    now = datetime.now().strftime("%A %d %B %Y, %H:%M")
    messages = [{"role": "system", "content": DISPATCH_PROMPT.format(time=now)}]

    # Last 2 conversation messages, truncated for speed
    for msg in conversation[-2:]:
        messages.append({**msg, "content": msg["content"][:200]})
    messages.append({"role": "user", "content": user_input})

    _status("thinking...")
    response = chat(messages=messages, tools=DIRECT_TOOL_SCHEMAS, think=False)

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
    if len(data_str) > 1500:
        data_str = data_str[:1500] + "..."

    messages = [
        {"role": "system", "content": FORMAT_PROMPT},
        {"role": "user", "content": user_input},
        {"role": "system", "content": f"Tool results:\n{data_str}\n\nRespond based on these results. Be direct and conversational."},
    ]

    response_stream = chat(messages=messages, think=False, stream=True, max_tokens=100)
    full_text = []
    for chunk in response_stream:
        if hasattr(chunk, "message") and hasattr(chunk.message, "content"):
            content = chunk.message.content
        elif isinstance(chunk, dict):
            content = chunk.get("message", {}).get("content", "")
        else:
            continue
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
