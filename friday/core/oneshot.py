"""Oneshot tool calls — regex match → direct tool call → 1 LLM format.

Handles queries where we know exactly which tool to call.
Skips the entire ReAct loop. 1 LLM call instead of 3-4.
"""

import re
import json as _json

from friday.core.llm import cloud_chat, extract_stream_content
from friday.core.prompts import PERSONALITY_SLIM
from friday.core.router import extract_topic_from_conversation


async def try_oneshot(
    s: str,
    raw: str,
    conversation: list[dict],
    memory,
    session_id: str,
    mem_processor,
    _ack,
    _status,
    _chunk,
) -> bool:
    """Try to handle query with direct tool call + 1 LLM format.

    Returns True if handled, False to fall through to agent dispatch.
    """
    # ── X/Twitter search ──
    x_search = re.match(
        r"(?:search|check|look|find|what(?:'s| is| are))(?: (?:on|for))?"
        r"(?: x| twitter| tweets?)?\s+(?:for |about |on )?(.+)",
        s,
    )
    if not x_search and re.match(r"(?:check x|search x|look on x|search twitter)\b", s):
        x_search = re.match(r"(?:check|search|look on)\s+(?:x|twitter)\s+(?:for |about )?(.+)", s)

    if x_search and any(kw in s for kw in ("x ", "twitter", "tweet")):
        query = x_search.group(1).strip().rstrip("?.")
        if query and len(query) > 2:
            _ack("searching X")
            _status("searching X")

            from friday.tools.x_tools import search_x
            result = await search_x(query=query, max_results=10)

            if result.success:
                return await _oneshot_format(
                    raw, result.data, "social_agent",
                    conversation, memory, session_id, mem_processor,
                    _status, _chunk,
                    fmt_hint="Summarize these tweets conversationally. Note who said what and engagement levels.",
                )

    # ── X/Twitter mentions ──
    if re.match(r"(check |get |show |any )?(my )?(mentions|@mentions)", s):
        _ack("checking mentions")
        _status("fetching mentions")
        from friday.tools.x_tools import get_my_mentions
        result = await get_my_mentions(max_results=10)
        if result.success:
            return await _oneshot_format(
                raw, result.data, "social_agent",
                conversation, memory, session_id, mem_processor,
                _status, _chunk,
                fmt_hint="Summarize who mentioned Travis, what they said, highlight anything worth replying to.",
            )

    # ── X/Twitter user lookup ──
    x_user = re.match(r"who\s+is\s+@(\w+)", s)
    if not x_user:
        x_user = re.match(r"who\s+is\s+(\w+)\s+on\s+(?:x|twitter)", s)
    if x_user:
        username = x_user.group(1)
        _ack(f"looking up @{username}")
        _status(f"fetching @{username}")
        from friday.tools.x_tools import get_x_user
        result = await get_x_user(username=username)
        if result.success:
            return await _oneshot_format(
                raw, result.data, "social_agent",
                conversation, memory, session_id, mem_processor,
                _status, _chunk,
                fmt_hint="Give a natural overview of this X profile — who they are, stats, anything notable.",
            )

    # ── Email ──
    email_match = (
        re.match(r"(check|read|show|get|whats in) ?(my |the )?(email|emails|inbox|unread|mail)", s) or
        re.match(r"any ?(new |unread |recent )?(email|emails|mail|messages)", s) or
        re.match(r"do i have ?(any |new )?(email|emails|mail|messages)", s)
    )
    if email_match:
        search_term = None
        search_match = re.search(r"\b(?:for|from|about|regarding|re)\s+(.+?)(?:\s+and\s+(?:gist|tell|summarize|sum up|read|show).*)?$", s)
        if search_match:
            search_term = re.sub(r"^(anything|any|something|stuff)\s+", "", search_match.group(1).strip())

        if search_term:
            _ack("searching emails")
            _status("search emails")
            from friday.tools.email_tools import read_emails
            result = await read_emails(filter=search_term, limit=5, include_body=True)
            fmt_hint = f"Summarize these emails about '{search_term}'. Include key details from the email bodies — dates, order info, shipping status, announcements. Answer what Travis is actually asking about."
        else:
            _ack("checking email")
            _status("fetching emails")
            from friday.tools.email_tools import read_emails
            result = await read_emails(filter="unread", limit=10)
            fmt_hint = "Summarize emails naturally. Group by priority. Highlight urgent/important ones."

        if result.success:
            return await _oneshot_format(
                raw, result.data, "comms_agent",
                conversation, memory, session_id, mem_processor,
                _status, _chunk,
                fmt_hint=fmt_hint,
            )
        else:
            err = result.error.message if result.error else "Couldn't fetch emails."
            return _oneshot_instant(raw, err, "comms_agent", conversation, memory, session_id, _chunk)

    # ── Calendar ──
    if re.match(r"(check|show|get|whats on|what'?s on|any) ?(my |the )?(calendar|schedule|agenda)", s):
        _ack("checking calendar")
        _status("fetching calendar")
        from friday.tools.calendar_tools import get_calendar
        view = "week" if "week" in s else "day"
        result = await get_calendar(view=view)
        if result.success:
            return await _oneshot_format(
                raw, result.data, "comms_agent",
                conversation, memory, session_id, mem_processor,
                _status, _chunk,
                fmt_hint="Summarize calendar events naturally. Note times, what's coming up, any conflicts.",
            )
        else:
            err = result.error.message if result.error else "Couldn't fetch calendar."
            return _oneshot_instant(raw, err, "comms_agent", conversation, memory, session_id, _chunk)

    # ── Screenshot ── (instant — no LLM needed)
    if re.match(r"(take |grab |capture )?(a )?(screenshot|screen ?shot|screencap|screen ?grab|screeny|ss)\b", s):
        _ack("taking screenshot")
        from friday.tools.mac_tools import take_screenshot
        result = await take_screenshot()
        if result.success:
            path = result.data.get("saved_path", "") if isinstance(result.data, dict) else ""
            return _oneshot_instant(raw, f"Screenshot saved. {path}", "system_agent", conversation, memory, session_id, _chunk)

    # ── Open app ── (instant — no LLM needed)
    app_match = re.match(r"open\s+(.+)", s)
    if app_match:
        app_name = app_match.group(1).strip().rstrip("?.")
        if app_name and len(app_name) < 30:
            _ack(f"opening {app_name}")
            from friday.tools.mac_tools import open_application
            result = await open_application(app=app_name)
            if result.success:
                return _oneshot_instant(raw, f"{app_name.title()} is open.", "system_agent", conversation, memory, session_id, _chunk)

    # ── System info / battery ── (instant — format data directly, no LLM)
    if re.match(r"(whats|what'?s|what is|what was|show|get|check|tell me) ?(my )?(battery|system|storage|disk|ram|cpu|memory|uptime)", s) or \
       re.match(r"how much (battery|storage|disk|ram|memory|cpu)", s) or \
       re.match(r"(battery|storage) ?(level|status|left|remaining|percentage|percent|life)", s) or \
       re.search(r"\b(battery)\s*(percentage|percent|level|status|left|life|remaining)\b", s):
        _ack("checking system")
        from friday.tools.mac_tools import get_system_info
        result = await get_system_info()
        if result.success and isinstance(result.data, dict):
            d = result.data
            parts = []
            if d.get("cpu"):
                parts.append(d["cpu"])
            if d.get("memory_gb"):
                parts.append(f"RAM: {d['memory_gb']}")
            if d.get("disk_usage"):
                pct = re.search(r"(\d+)%", d["disk_usage"])
                if pct:
                    parts.append(f"Disk: {pct.group(1)}% used")
            if d.get("uptime"):
                up = d["uptime"].split("up ")[-1].split(",")[0].strip() if "up " in d["uptime"] else ""
                if up:
                    parts.append(f"Up {up}")
            msg = ". ".join(parts) if parts else str(d)
            return _oneshot_instant(raw, msg, "system_agent", conversation, memory, session_id, _chunk)

    # ── Volume ── (instant — no LLM needed)
    vol_match = re.match(r"(?:set |change )?(volume|vol)\s*(?:to\s*)?(\d+)", s)
    if vol_match:
        level = int(vol_match.group(2))
        _ack(f"setting volume to {level}")
        from friday.tools.mac_tools import set_volume
        result = await set_volume(level=level)
        if result.success:
            return _oneshot_instant(raw, f"Volume set to {level}.", "system_agent", conversation, memory, session_id, _chunk)

    # ── Web search (factual queries) ──
    web_match = re.match(
        r"(?:what is|what are|what'?s|who is|who are|who'?s|where is|when is|when did|how does|how do|how did)"
        r"\s+(.+)", s
    )
    if not web_match:
        web_match = re.match(r"(?:search|look up|google|search for|look for|search the web for)\s+(.+)", s)

    if web_match:
        query = web_match.group(1).strip().rstrip("?.")
        if query and len(query) > 2:
            _ack("looking it up")
            _status("searching web")
            from friday.tools.web_tools import search_web
            # Resolve pronouns using conversation context
            search_query = raw
            if conversation and re.search(r"\b(it|that|them|this|their|those|its)\b", s):
                topic = extract_topic_from_conversation(conversation)
                if topic:
                    search_query = f"{topic} {raw}"
            result = await search_web(query=search_query, num_results=3)
            if result.success:
                return await _oneshot_format(
                    raw, result.data, "research_agent",
                    conversation, memory, session_id, mem_processor,
                    _status, _chunk,
                    fmt_hint="Answer Travis's question using these search results. Be thorough — include key facts, numbers, and details. Don't cut short.",
                )
            else:
                err = result.error.message if result.error else "Search failed."
                return _oneshot_instant(raw, err, "research_agent", conversation, memory, session_id, _chunk)

    return False


def _oneshot_instant(
    user_input: str,
    response_text: str,
    agent_name: str,
    conversation: list[dict],
    memory,
    session_id: str,
    _chunk,
) -> bool:
    """Instant oneshot — no LLM, just return a canned response. Sub-second."""
    conversation.append({"role": "user", "content": user_input})
    conversation.append({"role": "assistant", "content": response_text})
    _chunk(response_text)
    if memory:
        memory.log_agent_call(
            session_id=session_id, agent=agent_name, tool="oneshot_instant",
            args={"task": user_input}, result_summary=response_text[:200],
            success=True, duration_ms=0,
        )
    return True


async def _oneshot_format(
    user_input,
    tool_data,
    agent_name,
    conversation: list[dict],
    memory,
    session_id: str,
    mem_processor,
    _status,
    _chunk,
    fmt_hint="",
) -> bool:
    """Format tool results with 1 streamed LLM call."""
    _status("formatting...")

    data_str = _json.dumps(tool_data, default=str)
    if len(data_str) > 6000:
        data_str = data_str[:6000] + "..."

    # Include recent conversation for context
    conv_context = ""
    if conversation:
        recent = conversation[-4:]
        conv_lines = []
        for msg in recent:
            role = "Travis" if msg["role"] == "user" else "FRIDAY"
            conv_lines.append(f"{role}: {msg['content'][:200]}")
        conv_context = "\n\nRecent conversation:\n" + "\n".join(conv_lines)

    messages = [
        {"role": "system", "content": f"{PERSONALITY_SLIM}\n\n{fmt_hint}"},
        {"role": "user", "content": user_input},
        {"role": "system", "content": f"Tool results:\n{data_str}{conv_context}\n\nRespond based on these results. Stay on topic — answer what Travis actually asked. Be direct and conversational."},
    ]

    response_stream = cloud_chat(messages=messages, stream=True, max_tokens=400)
    full_text = []
    for chunk in response_stream:
        content = extract_stream_content(chunk)
        if content:
            _chunk(content)
            full_text.append(content)

    response_text = "".join(full_text)
    conversation.append({"role": "user", "content": user_input})
    conversation.append({"role": "assistant", "content": response_text})

    if memory:
        memory.log_agent_call(
            session_id=session_id,
            agent=agent_name,
            tool="oneshot",
            args={"task": user_input},
            result_summary=response_text[:200] if response_text else "",
            success=True,
            duration_ms=0,
        )
    if mem_processor:
        mem_processor.process(user_input, response_text, agent_name)
    return True
