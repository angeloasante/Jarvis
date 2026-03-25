"""LLM client — wraps Ollama (local) and OpenAI-compatible APIs (cloud)."""

import json
import ollama
from typing import Optional
from friday.core.config import MODEL_NAME, USE_CLOUD, CLOUD_API_KEY, CLOUD_BASE_URL, CLOUD_MODEL_NAME


# ── Local Ollama ──────────────────────────────────────────────────────────────

def chat(
    messages: list[dict],
    tools: Optional[list[dict]] = None,
    model: str = MODEL_NAME,
    think: bool | None = None,
    stream: bool = False,
    max_tokens: int | None = None,
):
    """Single LLM call via local Ollama.

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


# ── Cloud LLM (OpenAI-compatible: Groq, Fireworks, Modal, etc.) ──────────────

_cloud_client = None


def _get_cloud_client():
    """Lazy-init the OpenAI client for cloud LLM."""
    global _cloud_client
    if _cloud_client is None and CLOUD_API_KEY:
        from openai import OpenAI
        _cloud_client = OpenAI(base_url=CLOUD_BASE_URL, api_key=CLOUD_API_KEY)
    return _cloud_client


def _normalize_openai_response(response) -> dict:
    """Convert OpenAI ChatCompletion to the same dict format as Ollama.

    This means extract_tool_calls() and extract_text() work unchanged.
    """
    choice = response.choices[0]
    msg = choice.message

    result = {
        "message": {
            "role": msg.role or "assistant",
            "content": msg.content or "",
            "tool_calls": [],
        }
    }

    if msg.tool_calls:
        for tc in msg.tool_calls:
            # Parse arguments from JSON string to dict
            args = tc.function.arguments
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            result["message"]["tool_calls"].append({
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": args,
                }
            })

    return result


def cloud_chat(
    messages: list[dict],
    tools: Optional[list[dict]] = None,
    stream: bool = False,
    max_tokens: int | None = None,
    model: str | None = None,
):
    """LLM call via cloud API. Falls back to local Ollama if unavailable.

    Uses OpenAI-compatible endpoint (Groq, Fireworks, Together, Modal, etc.).
    Tool schemas are automatically wrapped in OpenAI format.
    Response is normalized to match Ollama's dict format.
    """
    client = _get_cloud_client()
    if not client:
        # No cloud configured — fall back to local
        return chat(messages=messages, tools=tools, stream=stream,
                    max_tokens=max_tokens, think=False)

    try:
        # Sanitize messages — OpenAI API requires tool_calls arguments as JSON strings
        # with id and type fields, but our normalized responses store args as dicts.
        sanitized_messages = []
        for msg in messages:
            if msg.get("tool_calls"):
                fixed_tcs = []
                for tc in msg["tool_calls"]:
                    if "function" not in tc:
                        fixed_tcs.append(tc)
                        continue
                    args = tc["function"].get("arguments", {})
                    fixed_tcs.append({
                        "id": tc.get("id", f"call_{id(tc)}"),
                        "type": "function",
                        "function": {
                            **tc["function"],
                            "arguments": json.dumps(args) if isinstance(args, dict) else (args or "{}"),
                        },
                    })
                msg = {**msg, "tool_calls": fixed_tcs}
            sanitized_messages.append(msg)

        kwargs = {
            "model": model or CLOUD_MODEL_NAME,
            "messages": sanitized_messages,
        }

        if tools:
            # Wrap in OpenAI format if not already wrapped
            wrapped = []
            for t in tools:
                if t.get("type") == "function" and "function" in t:
                    wrapped.append(t)  # Already in OpenAI format
                else:
                    wrapped.append({"type": "function", "function": t})
            kwargs["tools"] = wrapped

        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        if stream:
            kwargs["stream"] = True

        # Tell Qwen 3 not to use thinking mode
        if "qwen" in (model or CLOUD_MODEL_NAME).lower():
            # Prepend instruction to suppress thinking
            if kwargs["messages"] and kwargs["messages"][0]["role"] == "system":
                kwargs["messages"][0]["content"] = "/no_think\n" + kwargs["messages"][0]["content"]
            else:
                kwargs["messages"].insert(0, {"role": "system", "content": "/no_think"})

        response = client.chat.completions.create(**kwargs)

        if stream:
            # Wrap stream to filter out <think> blocks
            return _filtered_stream(response)

        result = _normalize_openai_response(response)
        # Strip any thinking blocks from non-streamed response
        content = result.get("message", {}).get("content", "")
        if "<think>" in content:
            result["message"]["content"] = strip_thinking(content)
        return result

    except Exception as e:
        # Cloud failed — fall back to local Ollama
        import logging
        logging.getLogger(__name__).warning(f"Cloud LLM failed ({type(e).__name__}: {e}), falling back to local")
        return chat(messages=messages, tools=tools, stream=stream,
                    max_tokens=max_tokens, think=False)


# ── Shared extraction helpers ─────────────────────────────────────────────────

def extract_tool_calls(response: dict) -> list[dict]:
    """Pull tool calls from an Ollama/normalized response."""
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
    """Pull the text content from an Ollama/normalized response."""
    content = response.get("message", {}).get("content", "") or ""
    return content.strip()


class _ThinkingFilter:
    """Strips <think>...</think> blocks from streamed text."""
    def __init__(self):
        self._in_think = False
        self._buf = ""

    def feed(self, text: str) -> str:
        out = []
        for ch in text:
            self._buf += ch
            if not self._in_think:
                if self._buf.endswith("<think>"):
                    self._in_think = True
                    self._buf = ""
                elif len(self._buf) > 7:
                    out.append(self._buf[0])
                    self._buf = self._buf[1:]
            else:
                if self._buf.endswith("</think>"):
                    self._in_think = False
                    self._buf = ""
        if not self._in_think and self._buf and "<" not in self._buf:
            out.append(self._buf)
            self._buf = ""
        return "".join(out)

    def flush(self) -> str:
        if not self._in_think:
            result = self._buf
            self._buf = ""
            return result
        return ""


def _filtered_stream(raw_stream):
    """Wrap an OpenAI stream to filter out <think> blocks."""
    filt = _ThinkingFilter()
    for chunk in raw_stream:
        text = extract_stream_content(chunk)
        if text:
            cleaned = filt.feed(text)
            if cleaned:
                # Yield a simple dict so extract_stream_content can read it
                yield {"message": {"content": cleaned}}
        else:
            yield chunk
    # Flush remaining buffer
    remaining = filt.flush()
    if remaining:
        yield {"message": {"content": remaining}}


def extract_stream_content(chunk) -> str:
    """Extract text content from a streaming chunk (Ollama or OpenAI format)."""
    # Ollama format: chunk.message.content
    if hasattr(chunk, "message") and hasattr(chunk.message, "content"):
        return chunk.message.content or ""
    # Ollama dict format
    if isinstance(chunk, dict):
        return chunk.get("message", {}).get("content", "") or ""
    # OpenAI format: chunk.choices[0].delta.content
    choices = getattr(chunk, "choices", None)
    if choices:
        delta = getattr(choices[0], "delta", None)
        if delta:
            return getattr(delta, "content", "") or ""
    return ""


def strip_thinking(text: str) -> str:
    """Remove any leftover <think> blocks (safety net for think=True responses)."""
    if "<think>" in text and "</think>" in text:
        text = text.split("</think>")[-1].strip()
    elif text.startswith("<think>"):
        return ""
    return text
