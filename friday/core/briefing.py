"""Briefing — parallel tool calls + 1 LLM synthesis.

Old flow (12 LLM calls, ~360s):
  LLM route → LLM pick tool → execute → LLM pick tool → ... → LLM synth

New flow (1 LLM call, ~30-40s):
  Parallel tool calls → 1 LLM synthesis
"""

import asyncio
import json

from friday.core.llm import cloud_chat, extract_text, extract_stream_content
from friday.core.types import ToolResult


async def direct_briefing(conversation: list[dict], on_status=None) -> str:
    """Call ALL briefing tools in parallel, then ONE LLM synthesis."""
    from friday.tools.briefing_tools import get_daily_digest
    from friday.tools.email_tools import TOOL_SCHEMAS as _E
    from friday.tools.call_tools import TOOL_SCHEMAS as _K
    from friday.tools.x_tools import TOOL_SCHEMAS as _X

    read_emails = _E["read_emails"]["fn"]
    get_call_history = _K["get_call_history"]["fn"]
    get_my_mentions = _X["get_my_mentions"]["fn"]

    if on_status:
        on_status("pulling everything at once...")

    results = {}

    async def _run(name, coro, timeout=30):
        if on_status:
            on_status(f"checking {name}...")
        try:
            r = await asyncio.wait_for(coro, timeout=timeout)
            results[name] = r
            if on_status:
                on_status(f"✓ {name} done")
            return r
        except asyncio.TimeoutError:
            results[name] = Exception(f"{name} timed out after {timeout}s")
            if on_status:
                on_status(f"✗ {name} timed out")
        except Exception as e:
            results[name] = e
            if on_status:
                on_status(f"✗ {name} failed")

    await asyncio.gather(
        _run("digest", get_daily_digest(), timeout=20),
        _run("emails", read_emails(filter="unread"), timeout=15),
        _run("calls", get_call_history(limit=10), timeout=15),
        _run("x_mentions", get_my_mentions(), timeout=15),
        return_exceptions=True,
    )

    if on_status:
        on_status("synthesizing briefing...")

    summary_parts = _build_summary(results)
    tool_data = "\n\n".join(summary_parts)

    briefing_slim = """You are FRIDAY. Synthesize this data into a tight briefing for Travis.
Lead with anything urgent. Then anything worth knowing. Max 150 words.
Be direct, no fluff. Use Travis's voice — casual, real."""
    messages = [
        {"role": "system", "content": briefing_slim},
        {"role": "user", "content": f"Briefing data:\n\n{tool_data}"},
    ]

    response = cloud_chat(messages=messages, max_tokens=200)
    text = extract_text(response)

    conversation.append({"role": "user", "content": "catch me up"})
    conversation.append({"role": "assistant", "content": text})
    return text


async def direct_briefing_streamed(
    conversation: list[dict],
    _status,
    _chunk,
    user_input: str,
):
    """Direct briefing with parallel tools + streamed synthesis."""
    from friday.tools.briefing_tools import get_daily_digest
    from friday.tools.email_tools import TOOL_SCHEMAS as _E
    from friday.tools.call_tools import TOOL_SCHEMAS as _K
    from friday.tools.x_tools import TOOL_SCHEMAS as _X

    read_emails = _E["read_emails"]["fn"]
    get_call_history = _K["get_call_history"]["fn"]
    get_my_mentions = _X["get_my_mentions"]["fn"]

    _status("pulling everything at once...")
    results = {}

    async def _run(name, coro, timeout=30):
        _status(f"checking {name}...")
        try:
            r = await asyncio.wait_for(coro, timeout=timeout)
            results[name] = r
            _status(f"✓ {name} done")
            return r
        except asyncio.TimeoutError:
            results[name] = Exception(f"{name} timed out after {timeout}s")
            _status(f"✗ {name} timed out")
        except Exception as e:
            results[name] = e
            _status(f"✗ {name} failed")

    await asyncio.gather(
        _run("digest", get_daily_digest(), timeout=20),
        _run("emails", read_emails(filter="unread"), timeout=15),
        _run("calls", get_call_history(limit=10), timeout=15),
        _run("x_mentions", get_my_mentions(), timeout=15),
        return_exceptions=True,
    )

    _status("synthesizing briefing...")

    summary_parts = _build_summary(results)
    tool_data = "\n\n".join(summary_parts)

    briefing_slim = """You are FRIDAY. Synthesize this data into a tight briefing for Travis.
Lead with anything urgent. Then anything worth knowing. Max 150 words.
Be direct, no fluff. Use Travis's voice — casual, real."""
    messages = [
        {"role": "system", "content": briefing_slim},
        {"role": "user", "content": f"Briefing data:\n\n{tool_data}"},
    ]

    response_stream = cloud_chat(messages=messages, stream=True, max_tokens=300)
    full_text = ""
    for chunk in response_stream:
        content = extract_stream_content(chunk)
        if content:
            full_text += content
            _chunk(content)

    conversation.append({"role": "user", "content": user_input})
    conversation.append({"role": "assistant", "content": full_text.strip()})


def _build_summary(results: dict) -> list[str]:
    """Build tool results summary for the LLM."""
    summary_parts = []
    for name, r in results.items():
        if isinstance(r, Exception):
            summary_parts.append(f"[{name}] Error: {r}")
        elif isinstance(r, ToolResult) and r.success:
            data = r.data
            if isinstance(data, list):
                summary_parts.append(f"[{name}] {len(data)} items: {json.dumps(data[:5], default=str)[:1500]}")
            elif isinstance(data, dict):
                summary_parts.append(f"[{name}] {json.dumps(data, default=str)[:1500]}")
            elif data:
                summary_parts.append(f"[{name}] {str(data)[:1500]}")
            else:
                summary_parts.append(f"[{name}] No data")
        else:
            err = r.error.message if hasattr(r, 'error') and r.error else "unknown"
            summary_parts.append(f"[{name}] Failed: {err}")
    return summary_parts
