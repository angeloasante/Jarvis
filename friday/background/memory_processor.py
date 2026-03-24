"""Background memory processor — watches conversations and extracts structured memories.

After each agent dispatch, this processor takes the conversation + result
and extracts meaningful facts/decisions/context worth remembering.
Runs in background thread, no blocking the main loop.
"""

import json
import logging
import threading
from queue import Queue, Empty

from friday.core.llm import chat, extract_text
from friday.memory.store import get_memory_store

log = logging.getLogger(__name__)

# Extraction prompt — fast, no thinking, just facts
_EXTRACT_PROMPT = """You are a memory extraction system. Given a conversation exchange, extract ONLY facts worth remembering for future conversations.

Rules:
- Extract decisions, outcomes, preferences, people, projects, and actionable facts
- Do NOT extract: greetings, filler, questions that were asked, agent status messages
- Each memory should be a single clear sentence
- Category must be one of: project, decision, lesson, preference, person, general
- Importance 1-10 (10 = will definitely need this again)
- If nothing worth remembering, return empty array
- Maximum 3 memories per exchange

Return ONLY valid JSON array:
[{"content": "...", "category": "...", "importance": N}]

If nothing worth storing, return: []"""


class MemoryProcessor:
    """Background memory processor — singleton."""

    def __init__(self):
        self._queue: Queue = Queue()
        self._thread = None
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._worker, daemon=True, name="friday-memory-bg"
        )
        self._thread.start()

    def stop(self):
        self._running = False

    def process(self, user_input: str, response: str, agent_name: str | None = None):
        """Queue a conversation exchange for memory extraction.

        Only queues if the exchange looks like it contains new information
        (agent results, not just casual chat).
        """
        # Skip trivial exchanges — greetings, short chats, errors
        if not response or len(response) < 50:
            return
        if agent_name is None and len(response) < 100:
            return  # Short conversational response, skip

        self._queue.put({
            "user_input": user_input,
            "response": response,
            "agent": agent_name,
        })

    def _worker(self):
        """Background worker — processes queued exchanges."""
        store = get_memory_store()

        while self._running:
            try:
                item = self._queue.get(timeout=2.0)
            except Empty:
                continue

            try:
                self._extract_and_store(item, store)
            except Exception as e:
                log.debug(f"Memory extraction failed: {e}")

    def _extract_and_store(self, item: dict, store):
        """Extract memories from a single exchange via fast LLM call."""
        user_input = item["user_input"]
        response = item["response"]
        agent = item.get("agent", "conversation")

        # Truncate long responses to save tokens
        if len(response) > 1500:
            response = response[:1500] + "..."

        messages = [
            {"role": "system", "content": _EXTRACT_PROMPT},
            {"role": "user", "content": f"User asked: {user_input}\n\nFRIDAY responded (via {agent}):\n{response}"},
        ]

        result = chat(messages=messages, think=False)
        text = extract_text(result)

        # Parse JSON
        try:
            # Handle markdown wrapping
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            memories = json.loads(text.strip())
        except (json.JSONDecodeError, IndexError):
            return

        if not isinstance(memories, list):
            return

        for mem in memories[:3]:
            content = mem.get("content", "").strip()
            category = mem.get("category", "general")
            importance = mem.get("importance", 5)

            if not content or len(content) < 10:
                continue

            # Dedupe: check if similar memory exists
            existing = store.search(content, n_results=1)
            if existing and existing[0].get("distance", 1.0) < 0.15:
                continue  # Too similar to existing memory

            store.store(
                content=content,
                category=category,
                importance=min(max(importance, 1), 10),
            )
            log.debug(f"Memory stored: [{category}] {content[:60]}")


# Singleton
_processor = None


def get_memory_processor() -> MemoryProcessor:
    global _processor
    if _processor is None:
        _processor = MemoryProcessor()
    return _processor
