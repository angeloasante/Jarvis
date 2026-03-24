"""Research Agent — searches the web, reads pages, synthesises findings."""

from friday.core.base_agent import BaseAgent
from friday.tools.web_tools import TOOL_SCHEMAS as WEB_TOOLS
from friday.tools.memory_tools import TOOL_SCHEMAS as MEMORY_TOOLS
from friday.tools.github_tools import TOOL_SCHEMAS as GITHUB_TOOLS


# Known authoritative sources for common topics.
# The agent should fetch these directly instead of relying on search snippets.
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


SYSTEM_PROMPT = """You are FRIDAY's research specialist.

ALWAYS respond in English. Never respond in any other language.

CRITICAL RULES:
- NEVER just talk about researching. Actually DO IT. Call the tools.
- NEVER respond without calling at least search_web first.
- DO NOT announce what you're going to do. Just do it.

SPEED IS CRITICAL — minimize tool calls:

1. search_web with a specific query. The search returns an AI answer + source content.
2. If the search answer + source content is sufficient, RESPOND IMMEDIATELY.
   Do NOT fetch pages unless the search results are clearly incomplete.
3. Only use fetch_page for official/government sources where you need exact wording
   (e.g. gov.uk, official docs). Max 1 page fetch per query.
4. NEVER fetch more than 1 page. The search results already include content.

OUTPUT FORMAT:
- Lead with the direct answer (2-4 sentences)
- Key facts as bullet points
- Sources with URLs
- Caveats if any

Be direct. No fluff. Travis needs facts not essays.
If you're uncertain, say so and say why."""


class ResearchAgent(BaseAgent):
    name = "research_agent"
    system_prompt = SYSTEM_PROMPT
    max_iterations = 5

    def __init__(self):
        self.tools = {
            **WEB_TOOLS,
            **{k: v for k, v in MEMORY_TOOLS.items() if k in ("store_memory", "search_memory")},
            **GITHUB_TOOLS,
        }
        super().__init__()

    async def run(self, task: str, context: str = "", on_tool_call=None):
        """Override to inject known source hints into the task."""
        task_lower = task.lower()
        source_hints = []
        for topic, urls in KNOWN_SOURCES.items():
            if topic in task_lower:
                source_hints.extend(urls)

        if source_hints:
            urls_str = "\n".join(f"  - {u}" for u in source_hints)
            task += f"\n\nAuthoritative sources to fetch directly:\n{urls_str}"

        return await super().run(task=task, context=context, on_tool_call=on_tool_call)
