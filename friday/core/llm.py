"""LLM client — wraps Ollama for all agent calls."""

import ollama
from typing import Optional
from friday.core.config import MODEL_NAME


def chat(
    messages: list[dict],
    tools: Optional[list[dict]] = None,
    model: str = MODEL_NAME,
    think: bool | None = None,
    stream: bool = False,
    max_tokens: int | None = None,
):
    """Single LLM call.

    Args:
        think: True = enable thinking (deep reasoning), False = disable (fast mode).
               None = let the model decide. Uses Ollama's native think parameter
               which controls the thinking pipeline at the engine level.
        stream: If True, returns an iterator yielding chunks.
    """
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "keep_alive": -1,  # Never unload — model stays in VRAM permanently
    }

    if tools:
        kwargs["tools"] = tools

    # Ollama native thinking control — this actually disables the thinking
    # pipeline at the engine level, not just hiding output.
    # With think=False: ~1-2s for simple queries (11 tokens)
    # Without:          ~90s for the same query (1123 tokens wasted on hidden thinking)
    if think is not None:
        kwargs["think"] = think

    if think:
        kwargs["options"] = {"num_ctx": 16384}

    if max_tokens:
        opts = kwargs.get("options", {})
        opts["num_predict"] = max_tokens
        kwargs["options"] = opts

    if stream:
        kwargs["stream"] = True

    try:
        response = ollama.chat(**kwargs)
    except ollama.ResponseError as e:
        # Ollama 500 errors often mean the model generated malformed tool XML.
        # Retry once WITHOUT tools so the model responds in plain text instead.
        if e.status_code == 500 and tools:
            no_tool_kwargs = {k: v for k, v in kwargs.items() if k != "tools"}
            response = ollama.chat(**no_tool_kwargs)
        else:
            raise

    if stream:
        return response  # Returns iterator

    # Normalize to dict — Ollama SDK returns ChatResponse objects
    if hasattr(response, "model_dump"):
        return response.model_dump()
    elif hasattr(response, "__dict__"):
        return response.__dict__
    return response


def extract_tool_calls(response: dict) -> list[dict]:
    """Pull tool calls from an Ollama response."""
    message = response.get("message", {})
    tool_calls = message.get("tool_calls") or []
    return [
        {
            "name": tc["function"]["name"],
            "arguments": tc["function"]["arguments"],
        }
        for tc in tool_calls
    ]


def extract_text(response: dict) -> str:
    """Pull the text content from an Ollama response."""
    content = response.get("message", {}).get("content", "") or ""
    return content.strip()


def strip_thinking(text: str) -> str:
    """Remove any leftover <think> blocks (safety net for think=True responses)."""
    if "<think>" in text and "</think>" in text:
        text = text.split("</think>")[-1].strip()
    elif text.startswith("<think>"):
        return ""
    return text
