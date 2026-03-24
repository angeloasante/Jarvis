"""Memory tools — store and retrieve memories. Exposed to agents as callable tools."""

from friday.core.types import ToolResult
from friday.memory.store import get_memory_store


async def store_memory(content: str, category: str = "general", importance: int = 5) -> ToolResult:
    """Store a piece of information in long-term memory."""
    store = get_memory_store()
    mem_id = store.store(content=content, category=category, importance=importance)
    return ToolResult(success=True, data=f"Memory stored: {mem_id}", metadata={"id": mem_id})


async def search_memory(query: str, n_results: int = 5) -> ToolResult:
    """Search memories semantically."""
    store = get_memory_store()
    results = store.search(query=query, n_results=n_results)
    return ToolResult(success=True, data=results, metadata={"count": len(results)})


async def get_recent_memories(limit: int = 10) -> ToolResult:
    """Get most recent memories."""
    store = get_memory_store()
    results = store.get_recent(limit=limit)
    return ToolResult(success=True, data=results)


TOOL_SCHEMAS = {
    "store_memory": {
        "fn": store_memory,
        "schema": {
            "type": "function",
            "function": {
                "name": "store_memory",
                "description": "Store information in long-term memory for future reference. Use for decisions, lessons, project updates, preferences.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "What to remember"},
                        "category": {
                            "type": "string",
                            "description": "Category: project, decision, lesson, preference, person, general",
                        },
                        "importance": {
                            "type": "integer",
                            "description": "1-10 importance rating (10 = critical)",
                        },
                    },
                    "required": ["content"],
                },
            },
        },
    },
    "search_memory": {
        "fn": search_memory,
        "schema": {
            "type": "function",
            "function": {
                "name": "search_memory",
                "description": "Search memories semantically. Use to recall past decisions, context, project details.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "What to search for"},
                        "n_results": {"type": "integer", "description": "Max results (default 5)"},
                    },
                    "required": ["query"],
                },
            },
        },
    },
    "get_recent_memories": {
        "fn": get_recent_memories,
        "schema": {
            "type": "function",
            "function": {
                "name": "get_recent_memories",
                "description": "Get the most recent memories stored.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "Number of memories to return (default 10)"},
                    },
                    "required": [],
                },
            },
        },
    },
}
