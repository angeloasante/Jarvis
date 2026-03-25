"""Research Agent — 2 LLM calls: 1 to pick tools + fetch, 1 to answer."""

import json as _json
import asyncio
from datetime import datetime
from typing import Optional, Callable

from friday.core.base_agent import BaseAgent
from friday.core.llm import cloud_chat, extract_tool_calls, extract_text, extract_stream_content
from friday.core.types import AgentResponse, ToolResult
from friday.tools.web_tools import TOOL_SCHEMAS as WEB_TOOLS
from friday.tools.memory_tools import TOOL_SCHEMAS as MEMORY_TOOLS
from friday.tools.github_tools import TOOL_SCHEMAS as GITHUB_TOOLS


# Known authoritative sources for common topics.
KNOWN_SOURCES = {
    "global talent visa": [
        "https://www.gov.uk/global-talent",
        "https://www.gov.uk/global-talent/eligibility",
    ],
    "uk visa": [
        "https://www.gov.uk/browse/visas-immigration",
    ],
    "stripe": ["https://stripe.com/docs"],
    "paystack": ["https://paystack.com/docs"],
    "supabase": ["https://supabase.com/docs"],
    "modal": ["https://modal.com/docs"],
    "railway": ["https://docs.railway.com"],
    "vercel": ["https://vercel.com/docs"],
    "ollama": ["https://github.com/ollama/ollama/blob/main/docs/api.md"],
}


TOOL_PICK_PROMPT = """You are FRIDAY's research specialist. Your job: call the right tools to gather information.

Rules:
- Call search_web with a good query. You can also call fetch_page if you need a specific URL.
- Call ALL the tools you need in ONE response. Do not hold back.
- If there are known authoritative URLs, fetch_page them directly.
- NEVER respond with text. ONLY make tool calls.
Current time: {time}"""

ANSWER_PROMPT = """You are FRIDAY. Travis's AI. Built by him. Running on his machine.
Travis: Ghanaian founder based in Plymouth UK.
Voice: brilliant friend who's also an engineer. Real, not corporate.

Answer the question using ONLY the research data below.
Match depth to the question: simple question = concise answer. Detailed/technical question = thorough answer with key facts, numbers, and context.
NEVER deflect with "let's go build" or "let's code" — just answer the question properly.
If data is insufficient, say what's missing."""


class ResearchAgent(BaseAgent):
    name = "research_agent"
    system_prompt = TOOL_PICK_PROMPT
    max_iterations = 2  # not used — we override run()

    def __init__(self):
        self.tools = {
            **WEB_TOOLS,
            **{k: v for k, v in MEMORY_TOOLS.items() if k in ("store_memory", "search_memory")},
            **GITHUB_TOOLS,
        }
        super().__init__()

    async def run(self, task: str, context: str = "", on_tool_call: Optional[Callable] = None, on_chunk: Optional[Callable] = None) -> AgentResponse:
        """2 LLM calls: 1 picks tools + execute all, 1 formats answer."""
        import time
        t0 = time.time()

        # Inject known source hints
        task_lower = task.lower()
        source_hints = []
        for topic, urls in KNOWN_SOURCES.items():
            if topic in task_lower:
                source_hints.extend(urls)

        task_with_hints = task
        if source_hints:
            urls_str = "\n".join(f"  - {u}" for u in source_hints)
            task_with_hints += f"\n\nFetch these authoritative sources directly:\n{urls_str}"

        # ── LLM Call 1: Pick tools ──
        now = datetime.now().strftime("%A %d %B %Y, %H:%M")
        tool_schemas = [t["schema"] for t in self.tools.values()]

        messages = [
            {"role": "system", "content": TOOL_PICK_PROMPT.format(time=now)},
        ]
        if context:
            messages.append({"role": "system", "content": f"Recent conversation:\n{context[:500]}"})
        messages.append({"role": "user", "content": task_with_hints})

        response = cloud_chat(messages=messages, tools=tool_schemas)
        tool_calls = extract_tool_calls(response)

        if not tool_calls:
            return AgentResponse(
                agent_name=self.name, success=False,
                result="I couldn't figure out what to search for.",
                tools_called=[], duration_ms=int((time.time() - t0) * 1000),
            )

        # ── Execute ALL tool calls in parallel ──
        results = {}
        tools_called = []

        async def _exec(tc):
            name = tc["name"]
            args = tc["arguments"]
            tools_called.append(name)
            if on_tool_call:
                on_tool_call(name, args)
            if name in self.tools:
                try:
                    result = await self.tools[name]["fn"](**args)
                    return (name, result)
                except Exception as e:
                    return (name, f"Error: {e}")
            return (name, "Unknown tool")

        executed = await asyncio.gather(*[_exec(tc) for tc in tool_calls])
        for name, result in executed:
            if isinstance(result, ToolResult):
                results[name] = _json.dumps(result.data, default=str)[:3000] if result.success else f"Failed: {result.error}"
            else:
                results[name] = str(result)[:3000]

        # ── LLM Call 2: Generate answer ──
        research_data = "\n\n".join(f"[{name}]\n{data}" for name, data in results.items())
        if len(research_data) > 4000:
            research_data = research_data[:4000] + "..."

        answer_messages = [
            {"role": "system", "content": ANSWER_PROMPT},
            {"role": "user", "content": task},
            {"role": "system", "content": f"Research data:\n{research_data}"},
        ]

        if on_chunk:
            # Stream answer token by token
            response_stream = cloud_chat(messages=answer_messages, stream=True, max_tokens=400)
            answer_parts = []
            for chunk in response_stream:
                content = extract_stream_content(chunk)
                if content:
                    on_chunk(content)
                    answer_parts.append(content)
            answer = "".join(answer_parts)
        else:
            answer_response = cloud_chat(messages=answer_messages, max_tokens=400)
            answer = extract_text(answer_response)

        duration = int((time.time() - t0) * 1000)
        return AgentResponse(
            agent_name=self.name, success=True,
            result=answer, tools_called=tools_called,
            duration_ms=duration,
        )
