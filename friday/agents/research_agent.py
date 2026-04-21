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
from friday.tools.file_tools import TOOL_SCHEMAS as FILE_TOOLS


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

def _answer_header() -> str:
    """Personalised preamble for the answer prompt. Falls back to generic."""
    from friday.core.user_config import USER
    if USER.is_configured:
        line = f"You are {USER.assistant_name}. {USER.possessive} AI. Built by them. Running on their machine."
        if USER.bio_line():
            line += f"\n{USER.display_name}: {USER.bio_line()}."
        return line
    return f"You are {USER.assistant_name} — a personal AI operating system."


def get_answer_prompt() -> str:
    return f"""{_answer_header()}
Voice: brilliant friend who's also an engineer. Real, not corporate.

Answer the question using ONLY the research data below.
Match depth to the question: simple question = concise answer. Detailed/technical question = thorough answer with key facts, numbers, and context.
NEVER deflect with "let's go build" or "let's code" — just answer the question properly.
If data is insufficient, say what's missing."""


ANSWER_PROMPT = get_answer_prompt()


DOCUMENT_PROMPT = """You are writing a well-structured document file that will be SAVED TO DISK for the user to read later.

Write the FULL document. Not a summary. Not a preview. The actual document.

Structure:
- Clear title as a markdown H1
- Short intro paragraph framing the topic
- 4-8 sections with H2 headings, each with 2-4 paragraphs of substantive content
- Use bullet points and numbered lists where they aid readability
- Include specific facts, numbers, names, dates, and direct quotes from the research data
- Cite sources inline as [Source: URL]. The research data includes these URLs — use the exact ones
- End with a "Key Takeaways" section (3-5 bullets) and a "Sources" section listing all URLs

Length: 1,500-2,500 words. This is a DOCUMENT, not a tweet. Go deep.

Use ONLY facts from the research data. Do NOT invent. If the research data is thin on some angle, say so honestly or skip that section."""


SUMMARY_PROMPT = """You are FRIDAY. The user just asked you to produce a report. You wrote the full document and saved it. Now you're telling them what you did.

Write a SHORT chat message (2-4 sentences). What it covers, where it's saved, one interesting finding. Voice: your usual friend-who's-an-engineer energy.

DO NOT:
- Repeat the entire document in the chat
- Use markdown headings or bullet lists — this is a conversational message, not the document
- Say "Here's the full report:" followed by dumping content

DO:
- Say something like: "Report's on your desktop. Covers X, Y, and Z. Interesting bit: [one specific insight from the doc]."
- Be punchy. 2-4 sentences max."""


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
        if len(research_data) > 6000:
            research_data = research_data[:6000] + "..."

        # Decide whether the user wants a saved file. If yes, we generate a
        # LONG detailed document for the file AND a SHORT summary for the chat.
        # If no, we just stream a concise answer to the chat.
        wants_file = self._wants_file(task)

        media_paths: list[str] = []
        saved_path: str | None = None
        chat_answer: str = ""

        if wants_file:
            # 1. Generate the FULL document (long, detailed) — NOT streamed to chat
            doc_messages = [
                {"role": "system", "content": DOCUMENT_PROMPT},
                {"role": "user", "content": task},
                {"role": "system", "content": f"Research data:\n{research_data}"},
            ]
            doc_response = cloud_chat(messages=doc_messages, max_tokens=3000)
            full_document = extract_text(doc_response)

            # 2. Save the full document to disk
            saved_path = self._save_to_disk(task, full_document)
            if saved_path:
                media_paths.append(saved_path)
                tools_called.append("write_file")

            # 3. Generate a SHORT summary for the chat (streamed)
            summary_messages = [
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": f"Task: {task}\n\nFull document:\n{full_document[:4000]}"},
            ]
            if on_chunk:
                stream = cloud_chat(messages=summary_messages, stream=True, max_tokens=250)
                parts = []
                for chunk in stream:
                    c = extract_stream_content(chunk)
                    if c:
                        on_chunk(c)
                        parts.append(c)
                chat_answer = "".join(parts)
            else:
                resp = cloud_chat(messages=summary_messages, max_tokens=250)
                chat_answer = extract_text(resp)

            if on_chunk and saved_path:
                on_chunk(f"\n\nSaved to {saved_path}")

        else:
            # No file requested — just stream a normal answer
            answer_messages = [
                {"role": "system", "content": get_answer_prompt()},
                {"role": "user", "content": task},
                {"role": "system", "content": f"Research data:\n{research_data}"},
            ]
            if on_chunk:
                response_stream = cloud_chat(messages=answer_messages, stream=True, max_tokens=600)
                parts = []
                for chunk in response_stream:
                    c = extract_stream_content(chunk)
                    if c:
                        on_chunk(c)
                        parts.append(c)
                chat_answer = "".join(parts)
            else:
                resp = cloud_chat(messages=answer_messages, max_tokens=600)
                chat_answer = extract_text(resp)

        duration = int((time.time() - t0) * 1000)
        return AgentResponse(
            agent_name=self.name, success=True,
            result=chat_answer, tools_called=tools_called,
            duration_ms=duration,
            media_paths=media_paths,
        )

    @staticmethod
    def _wants_file(task: str) -> bool:
        """True if the user explicitly asked for a saved file/report."""
        import re
        low = task.lower()
        if not re.search(r"\b(save|write|create|make|store|export|draft|generate|produce)\b", low):
            return False
        if re.search(r"\b(file|pdf|docx?|markdown|\.md|\.txt|report|document|paper|summary|note|brief)\b", low):
            return True
        if re.search(r"(desktop|downloads|documents|~/|/users/)", low):
            return True
        return False

    @staticmethod
    def _save_to_disk(task: str, content: str) -> str | None:
        """Write content to a file at a sensible path. Returns absolute path."""
        import re
        from pathlib import Path
        import datetime as _dt

        low = task.lower()

        # Location: desktop / documents / downloads / explicit path
        home = Path.home()
        if "desktop" in low:
            base = home / "Desktop"
        elif "downloads" in low:
            base = home / "Downloads"
        elif "documents" in low:
            base = home / "Documents" / "friday_files"
            base.mkdir(parents=True, exist_ok=True)
        else:
            base = home / "Documents" / "friday_files"
            base.mkdir(parents=True, exist_ok=True)

        # Format (default md)
        fmt = "md"
        if re.search(r"\b(pdf)\b", low):
            fmt = "pdf"
        elif re.search(r"\b(docx|word)\b", low):
            fmt = "docx"
        elif re.search(r"\b(txt|text file)\b", low):
            fmt = "txt"

        # Build filename from task topic
        topic = re.sub(r"\b(write|save|create|make|store|export|a|an|the|short|brief|detailed|"
                       r"report|paper|document|summary|file|pdf|docx?|markdown|md|txt|"
                       r"on|about|for|to|my|desktop|downloads|documents|please)\b", "",
                       low, flags=re.IGNORECASE)
        topic = re.sub(r"[^\w\s-]", "", topic).strip()
        topic = re.sub(r"\s+", "_", topic)[:60] or "report"
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M")
        path = base / f"{topic}_{stamp}.{fmt}"

        # For markdown/txt — write directly. For PDF/DOCX — delegate.
        try:
            if fmt == "md" or fmt == "txt":
                path.write_text(content, encoding="utf-8")
            elif fmt == "docx":
                from docx import Document
                doc = Document()
                for para in content.split("\n\n"):
                    if para.strip():
                        doc.add_paragraph(para)
                doc.save(str(path))
            elif fmt == "pdf":
                # Reuse the deep_research PDF saver for quality output
                from friday.agents.deep_research_agent import _save_pdf
                _save_pdf(path, topic.replace("_", " ").title(), [{"name": "Report", "content": content}], "", set())
            return str(path)
        except Exception:
            return None
