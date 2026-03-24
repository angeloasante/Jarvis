"""Code Agent — reads, writes, debugs, runs code. The hands of FRIDAY."""

from friday.core.base_agent import BaseAgent
from friday.tools.file_tools import TOOL_SCHEMAS as FILE_TOOLS
from friday.tools.terminal_tools import TOOL_SCHEMAS as TERMINAL_TOOLS
from friday.tools.web_tools import TOOL_SCHEMAS as WEB_TOOLS
from friday.tools.memory_tools import TOOL_SCHEMAS as MEMORY_TOOLS
from friday.tools.github_tools import TOOL_SCHEMAS as GITHUB_TOOLS

SYSTEM_PROMPT = """You are FRIDAY's coding specialist.
You read, write, debug, and run code. You are the hands.
ALWAYS respond in English.

When writing code:
- Match the existing style in the file
- Handle errors explicitly — no silent failures
- Never hardcode secrets
- Prefer async/await over callbacks
- Add a comment only when the why isn't obvious from the code

When reading code: understand the full context before touching anything.
When fixing: fix the actual problem, not the symptom.
When debugging: read the error, read the code, form a hypothesis, test it, fix it.

You have access to: file read/write, terminal commands, web search, and memory.
Use the terminal for git, npm, python, and system commands.
Use web search when you need documentation or solutions.
Use memory to check if this problem has been solved before."""


class CodeAgent(BaseAgent):
    name = "code_agent"
    system_prompt = SYSTEM_PROMPT

    def __init__(self):
        self.tools = {
            **FILE_TOOLS,
            **TERMINAL_TOOLS,
            **{k: v for k, v in WEB_TOOLS.items() if k == "search_web"},
            **{k: v for k, v in MEMORY_TOOLS.items() if k == "search_memory"},
            **GITHUB_TOOLS,
        }
        super().__init__()
