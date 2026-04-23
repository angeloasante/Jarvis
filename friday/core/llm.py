"""LLM client — wraps Ollama (local) and OpenAI-compatible APIs (cloud)."""

import json
import ollama
from typing import Optional
from friday.core.config import (
    MODEL_NAME, USE_CLOUD, CLOUD_API_KEY, CLOUD_BASE_URL, CLOUD_MODEL_NAME,
    CLOUD_FALLBACK_CHAIN,
)


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
    """Lazy-init the OpenAI client for cloud LLM (primary provider only)."""
    global _cloud_client
    if _cloud_client is None and CLOUD_API_KEY:
        from openai import OpenAI
        _cloud_client = OpenAI(base_url=CLOUD_BASE_URL, api_key=CLOUD_API_KEY)
    return _cloud_client


# Cache of per-provider OpenAI clients used by the fallback chain.
_provider_clients: dict[str, object] = {}


def _client_for(base_url: str, api_key: str):
    """Return a cached OpenAI client for an arbitrary (base_url, api_key) pair."""
    key = f"{base_url}|{api_key[:8]}"
    client = _provider_clients.get(key)
    if client is None:
        from openai import OpenAI
        client = OpenAI(base_url=base_url, api_key=api_key)
        _provider_clients[key] = client
    return client


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


def _sanitize_messages(messages: list[dict]) -> list[dict]:
    """OpenAI expects tool_call args as JSON strings; our format stores dicts."""
    out = []
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
        out.append(msg)
    return out


def _wrap_tools(tools: Optional[list[dict]]) -> Optional[list[dict]]:
    if not tools:
        return None
    wrapped = []
    for t in tools:
        if t.get("type") == "function" and "function" in t:
            wrapped.append(t)
        else:
            wrapped.append({"type": "function", "function": t})
    return wrapped


def _call_one_provider(
    client, model: str,
    messages: list[dict],
    tools: Optional[list[dict]],
    stream: bool,
    max_tokens: int | None,
):
    """Make a single cloud call against one provider. Raises on failure."""
    sanitized = _sanitize_messages(messages)

    # Qwen3 on Groq needs /no_think to suppress its reasoning chain.
    # Gemma doesn't, neither do the other providers we support.
    _m = model.lower()
    if "qwen" in _m and "gemma" not in _m:
        if sanitized and sanitized[0]["role"] == "system":
            sanitized = [{**sanitized[0], "content": "/no_think\n" + sanitized[0]["content"]}] + sanitized[1:]
        else:
            sanitized = [{"role": "system", "content": "/no_think"}] + sanitized

    kwargs: dict = {"model": model, "messages": sanitized}
    if tools:
        kwargs["tools"] = _wrap_tools(tools)
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    if stream:
        kwargs["stream"] = True

    response = client.chat.completions.create(**kwargs)

    if stream:
        return _filtered_stream(response)

    result = _normalize_openai_response(response)
    content = result.get("message", {}).get("content", "")
    if "<think>" in content:
        result["message"]["content"] = strip_thinking(content)
    return result


def _is_retriable(exc: BaseException) -> bool:
    """Return True for errors worth cascading to the next provider.

    Covers: HTTP 4xx/5xx from upstream, network errors, OpenAI SDK errors
    that indicate the provider is unhappy (rate limit, not found, auth).
    """
    name = exc.__class__.__name__
    # Treat absolutely every exception except KeyboardInterrupt as retriable —
    # we'd rather try the next provider than hard-fail the user's request.
    return not isinstance(exc, (KeyboardInterrupt, SystemExit))


def cloud_chat(
    messages: list[dict],
    tools: Optional[list[dict]] = None,
    stream: bool = False,
    max_tokens: int | None = None,
    model: str | None = None,
):
    """LLM call with runtime provider fallback.

    Chain (configured in ``friday.core.config``):
      1. Primary provider (Gemma via OpenRouter → Google AI Studio → Groq,
         whichever is configured first and has a key).
      2. Every other configured provider, in priority order. On any error
         (HTTP 4xx/5xx, network timeout, rate-limit, model-not-found) the
         next provider in the chain gets the request.
      3. If every cloud provider fails, drop to local Ollama (which always
         works if ``ollama serve`` is running).

    The first successful response wins and returns. We log which provider
    answered so ``friday doctor`` / debug output reflects reality.
    """
    import logging
    log = logging.getLogger(__name__)

    # Primary: what config.py resolved at startup
    primary = _get_cloud_client()
    primary_attempts: list[tuple[object, str, str]] = []  # (client, model, label)
    if primary and CLOUD_API_KEY:
        primary_attempts.append(
            (primary, model or CLOUD_MODEL_NAME, f"primary ({CLOUD_BASE_URL})")
        )

    # Fallback chain: every OTHER configured provider, in priority order
    for name, key, base_url, default_model in CLOUD_FALLBACK_CHAIN:
        client = _client_for(base_url, key)
        primary_attempts.append((client, default_model, name))

    if not primary_attempts:
        # No cloud providers configured at all — straight to local Ollama.
        return chat(messages=messages, tools=tools, stream=stream,
                    max_tokens=max_tokens, think=False)

    last_error: BaseException | None = None
    for client, mdl, label in primary_attempts:
        try:
            result = _call_one_provider(
                client, mdl, messages, tools, stream, max_tokens,
            )
            if label != primary_attempts[0][2]:
                # We used a fallback — note it. Useful for doctor/debug.
                log.info("cloud_chat answered via fallback provider: %s", label)
            return result
        except Exception as e:
            if not _is_retriable(e):
                raise
            last_error = e
            log.warning("cloud_chat provider '%s' failed (%s: %s) — trying next",
                        label, type(e).__name__, str(e)[:140])
            continue

    # Every cloud provider failed — drop to local Ollama as final fallback.
    log.warning("All cloud providers failed (last: %s) — falling back to local Ollama",
                last_error.__class__.__name__ if last_error else "unknown")
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
