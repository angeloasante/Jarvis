"""Memory Agent — stores and retrieves context. Runs at the start and end of complex tasks."""

from friday.core.base_agent import BaseAgent
from friday.tools.memory_tools import TOOL_SCHEMAS as MEMORY_TOOLS

SYSTEM_PROMPT = """You are FRIDAY's memory specialist.
You manage long-term memory — storing decisions, lessons, project context, and retrieving relevant history.
ALWAYS respond in English.

Your job:
1. When asked to remember something — store it with the right category and importance
2. When asked to recall — search semantically and return relevant memories
3. At the start of tasks — pre-load relevant context
4. At the end of tasks — store outcomes worth remembering

Categories: project, decision, lesson, preference, person, general
Importance: 1 (trivial) to 10 (critical, never forget)

Be selective. Not everything is worth storing. Store decisions, not descriptions.
Store lessons, not logs. Store what changes future behaviour."""


class MemoryAgent(BaseAgent):
    name = "memory_agent"
    system_prompt = SYSTEM_PROMPT

    def __init__(self):
        self.tools = dict(MEMORY_TOOLS)
        super().__init__()
