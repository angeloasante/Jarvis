"""Base agent class. All FRIDAY agents inherit from this.

Implements the ReAct loop:
  THOUGHT -> ACTION (tool call) -> OBSERVATION -> ... -> FINAL ANSWER
"""

import asyncio
import time
import json
from typing import Optional, Callable
from friday.core.llm import cloud_chat, extract_tool_calls, extract_text
from friday.core.types import AgentResponse, ToolResult
from friday.memory.conversation_log import log_react_trace


def _compact_data(data):
    """Trim tool result data so it fits in a 9B model's working context.

    Large tool results (e.g. 10 emails with full bodies) overwhelm small models.
    Keep only the fields the agent needs to summarize.
    """
    if not isinstance(data, list):
        # Single item or primitive — truncate if string
        if isinstance(data, str) and len(data) > 4000:
            return data[:4000] + "... (truncated)"
        return data

    compacted = []
    for item in data:
        if not isinstance(item, dict):
            compacted.append(item)
            continue

        # Email — keep only what's needed for summary
        if "subject" in item and "from" in item:
            compacted.append({
                "id": item.get("id"),
                "subject": item.get("subject"),
                "from": item.get("from"),
                "date": item.get("date"),
                "snippet": (item.get("snippet") or "")[:150],
                "unread": item.get("unread"),
                "priority": item.get("priority"),
            })
        # Calendar event — keep only what's needed
        elif "title" in item and "start_time" in item:
            compacted.append({
                "title": item.get("title"),
                "start_time": item.get("start_time"),
                "end_time": item.get("end_time"),
                "location": item.get("location"),
                "video_link": item.get("video_link"),
                "warning": item.get("warning"),
            })
        else:
            # Unknown shape — pass through but truncate large strings
            trimmed = {}
            for k, v in item.items():
                if isinstance(v, str) and len(v) > 200:
                    trimmed[k] = v[:200] + "..."
                else:
                    trimmed[k] = v
            compacted.append(trimmed)

    return compacted


class BaseAgent:
    name: str = "base_agent"
    system_prompt: str = ""
    tools: dict = {}  # name -> callable
    tool_definitions: list[dict] = []  # Ollama tool schemas
    max_iterations: int = 10

    def __init__(self):
        self._build_tool_definitions()

    def _build_tool_definitions(self):
        """Auto-generate Ollama tool schemas from registered tools."""
        self.tool_definitions = []
        for name, tool_info in self.tools.items():
            self.tool_definitions.append(tool_info["schema"])

    async def execute_tool(self, name: str, arguments: dict) -> ToolResult:
        """Execute a registered tool by name."""
        if name not in self.tools:
            return ToolResult(
                success=False,
                error=None,
                data=f"Unknown tool: {name}",
            )
        fn = self.tools[name]["fn"]
        try:
            result = await fn(**arguments)
            return result
        except Exception as e:
            return ToolResult(success=False, data=str(e))

    async def run(self, task: str, context: str = "", on_tool_call: Optional[Callable] = None, on_chunk: Optional[Callable] = None) -> AgentResponse:
        """Run the ReAct loop for a given task.

        on_tool_call: optional callback(tool_name, tool_args) called before each tool executes.
                      Useful for showing progress in the CLI.
        """
        start = time.monotonic()
        tools_called = []

        messages = [
            {"role": "system", "content": self.system_prompt},
        ]
        if context:
            messages.append({"role": "system", "content": f"Context:\n{context}"})
        messages.append({"role": "user", "content": task})

        for iteration in range(self.max_iterations):
            # After first tool execution, strip tools so the model generates
            # a text answer instead of wasting prompt eval on tool schemas.
            # Only strip for agents with max_iterations <= 2 (truly single-tool).
            # Most agents need 2+ calls (read → send, discover → fill, etc.)
            offer_tools = self.tool_definitions if self.tool_definitions else None
            if iteration > 0 and tools_called and self.max_iterations <= 2:
                offer_tools = None

            response = cloud_chat(
                messages=messages,
                tools=offer_tools,
            )

            tool_calls = extract_tool_calls(response)

            if not tool_calls:
                # No tool calls — agent is done
                text = extract_text(response)
                if on_chunk and text:
                    on_chunk(text)
                dur = int((time.monotonic() - start) * 1000)
                log_react_trace(
                    session_id="", agent_name=self.name, task=task,
                    messages=messages, tools_called=tools_called,
                    final_answer=text or "", success=True,
                    duration_ms=dur, iterations=iteration + 1,
                )
                return AgentResponse(
                    agent_name=self.name,
                    success=True,
                    result=text,
                    tools_called=tools_called,
                    duration_ms=dur,
                )

            # Process tool calls
            msg = response.get("message", {})
            raw_tool_calls = msg.get("tool_calls", [])

            # Generate synthetic IDs if missing (local fallback doesn't produce them)
            import uuid
            for rtc in raw_tool_calls:
                if not rtc.get("id"):
                    rtc["id"] = f"call_{uuid.uuid4().hex[:8]}"

            # Add assistant message with tool calls to history
            messages.append({
                "role": msg.get("role", "assistant"),
                "content": msg.get("content", ""),
                "tool_calls": raw_tool_calls,
            })

            if len(tool_calls) == 1:
                # Single tool — run directly
                tc = tool_calls[0]
                tool_name = tc["name"]
                tool_args = tc["arguments"]
                tools_called.append(tool_name)

                if on_tool_call:
                    on_tool_call(tool_name, tool_args)

                result = await self.execute_tool(tool_name, tool_args)

                tool_content = {
                    "success": result.success,
                    "data": _compact_data(result.data),
                }
                if not result.success and result.error:
                    tool_content["error"] = str(result.error.message) if hasattr(result.error, "message") else str(result.error)

                tool_msg = {
                    "role": "tool",
                    "content": json.dumps(tool_content, default=str),
                }
                # Add tool_call_id if available (required by OpenAI/Groq API)
                if raw_tool_calls and raw_tool_calls[0].get("id"):
                    tool_msg["tool_call_id"] = raw_tool_calls[0]["id"]
                messages.append(tool_msg)
            else:
                # Multiple tools — run in parallel for speed
                async def _run_tool(tc_item):
                    name = tc_item["name"]
                    args = tc_item["arguments"]
                    if on_tool_call:
                        on_tool_call(name, args)
                    return name, await self.execute_tool(name, args)

                results = await asyncio.gather(
                    *[_run_tool(tc) for tc in tool_calls],
                    return_exceptions=True,
                )

                for i, res in enumerate(results):
                    tc = tool_calls[i]
                    tool_name = tc["name"]
                    tools_called.append(tool_name)

                    if isinstance(res, Exception):
                        tool_content = {"success": False, "data": str(res)}
                    else:
                        _, result = res
                        tool_content = {
                            "success": result.success,
                            "data": _compact_data(result.data),
                        }
                        if not result.success and result.error:
                            tool_content["error"] = str(result.error.message) if hasattr(result.error, "message") else str(result.error)

                    tool_msg = {
                        "role": "tool",
                        "content": json.dumps(tool_content, default=str),
                    }
                    if i < len(raw_tool_calls) and raw_tool_calls[i].get("id"):
                        tool_msg["tool_call_id"] = raw_tool_calls[i]["id"]
                    messages.append(tool_msg)

        # Hit max iterations
        dur = int((time.monotonic() - start) * 1000)
        log_react_trace(
            session_id="", agent_name=self.name, task=task,
            messages=messages, tools_called=tools_called,
            final_answer="Max iterations reached.", success=False,
            duration_ms=dur, iterations=self.max_iterations,
        )
        return AgentResponse(
            agent_name=self.name,
            success=False,
            result="Max iterations reached without final answer.",
            tools_called=tools_called,
            duration_ms=dur,
            error="max_iterations_exceeded",
        )
