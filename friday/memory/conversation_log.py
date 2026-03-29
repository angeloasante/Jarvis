"""Conversation Logger — append-only JSONL for fine-tuning datasets.

Captures EVERYTHING:
- User input + final response (every turn)
- Route taken (fast_path, fast_chat, oneshot, direct_dispatch, agent)
- Agent name, tool calls with args, tool results
- Full ReAct trace from base_agent (system prompt, thinking, tool loop)
- Timestamps, latency, session ID

Output: data/training/conversations.jsonl — one JSON object per line per interaction.
Each line is a complete training example with the full message chain.

Format follows OpenAI fine-tuning spec (messages array) so it's directly
usable with most fine-tuning APIs.
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from friday.core.config import DATA_DIR

log = logging.getLogger("friday.conversation_log")

TRAINING_DIR = DATA_DIR / "training"
CONVERSATIONS_FILE = TRAINING_DIR / "conversations.jsonl"
REACT_TRACES_FILE = TRAINING_DIR / "react_traces.jsonl"


def _ensure_dir():
    TRAINING_DIR.mkdir(parents=True, exist_ok=True)


def _append_jsonl(path: Path, data: dict):
    """Append a single JSON line to a file. Thread-safe via append mode."""
    try:
        _ensure_dir()
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, default=str, ensure_ascii=False) + "\n")
    except Exception as e:
        log.debug(f"Failed to write conversation log: {e}")


def log_turn(
    session_id: str,
    user_input: str,
    response: str,
    route: str,
    agent_name: Optional[str] = None,
    tools_called: Optional[list[str]] = None,
    tool_trace: Optional[list[dict]] = None,
    duration_ms: Optional[int] = None,
    model: Optional[str] = None,
):
    """Log a single conversation turn (user → FRIDAY).

    Args:
        session_id: Session identifier.
        user_input: What the user said.
        response: FRIDAY's final response text.
        route: How it was handled: fast_path, fast_chat, oneshot, direct_dispatch, agent.
        agent_name: Which agent handled it (if route=agent).
        tools_called: List of tool names invoked.
        tool_trace: Full tool call/result trace [{tool, args, result, success, ms}].
        duration_ms: End-to-end latency.
        model: Which model was used.
    """
    entry = {
        "timestamp": datetime.now().isoformat(),
        "session_id": session_id,
        "route": route,
        "duration_ms": duration_ms,
        "model": model,
        # Fine-tuning format: messages array
        "messages": [
            {"role": "user", "content": user_input},
            {"role": "assistant", "content": response},
        ],
    }

    if agent_name:
        entry["agent"] = agent_name
    if tools_called:
        entry["tools_called"] = tools_called
    if tool_trace:
        entry["tool_trace"] = tool_trace

    _append_jsonl(CONVERSATIONS_FILE, entry)


def log_react_trace(
    session_id: str,
    agent_name: str,
    task: str,
    messages: list[dict],
    tools_called: list[str],
    final_answer: str,
    success: bool,
    duration_ms: int,
    iterations: int,
):
    """Log the FULL ReAct trace from a base_agent run.

    This is the richest data — the complete multi-turn agent loop:
    system prompt → user task → assistant thinking + tool_calls → tool results → ... → final answer.

    Directly usable for fine-tuning tool-calling models.
    """
    # Clean messages for serialization (strip large tool results to keep file manageable)
    clean_messages = []
    for msg in messages:
        m = {**msg}
        # Truncate very large tool results (keep first 2000 chars)
        if m.get("role") == "tool" and len(m.get("content", "")) > 2000:
            content = m["content"][:2000] + "... [truncated]"
            m = {**m, "content": content}
        # tool_calls contain function dicts — ensure serializable
        if "tool_calls" in m:
            m["tool_calls"] = _clean_tool_calls(m["tool_calls"])
        clean_messages.append(m)

    entry = {
        "timestamp": datetime.now().isoformat(),
        "session_id": session_id,
        "agent": agent_name,
        "task": task,
        "messages": clean_messages,
        "tools_called": tools_called,
        "final_answer": final_answer,
        "success": success,
        "duration_ms": duration_ms,
        "iterations": iterations,
    }

    _append_jsonl(REACT_TRACES_FILE, entry)


def _clean_tool_calls(tool_calls: list) -> list:
    """Ensure tool_calls are JSON-serializable."""
    clean = []
    for tc in tool_calls:
        if isinstance(tc, dict):
            c = {**tc}
            # Ensure arguments are dicts, not strings
            func = c.get("function", {})
            if isinstance(func.get("arguments"), str):
                try:
                    func["arguments"] = json.loads(func["arguments"])
                except (json.JSONDecodeError, TypeError):
                    pass
            clean.append(c)
        else:
            clean.append(tc)
    return clean
