# LLM Providers

FRIDAY is provider-agnostic. Anything that speaks the OpenAI Chat Completions API works — OpenRouter, Groq, Google AI, Together, Fireworks, RunPod, Modal, your own vLLM, or local Ollama. You pick where inference runs by setting one env var.

This document is the single reference for provider support. It replaces the former "Cloud Inference", "Cloud vs Local", and "Configuration" sections of the README.

---

## 1. Overview

FRIDAY resolves a **primary** provider at config-load time and builds a **runtime fallback chain** from every other configured provider. The logic lives in [`friday/core/config.py`](../friday/core/config.py) and [`friday/core/llm.py`](../friday/core/llm.py).

### Primary provider priority (highest to lowest)

1. **`CLOUD_API_KEY`** + `CLOUD_BASE_URL` + `CLOUD_MODEL` — fully manual escape hatch for any OpenAI-compatible endpoint.
2. **`OPENROUTER_API_KEY`** — base URL `https://openrouter.ai/api/v1`, default model `google/gemma-4-31b-it:free`.
3. **`GROQ_API_KEY`** — base URL `https://api.groq.com/openai/v1`, default model `qwen/qwen3-32b`.
4. **None set** — `USE_CLOUD` is false, every LLM call goes to local Ollama at `http://localhost:11434`.

### Google AI Studio is opt-in only

Google AI Studio (Gemini / hosted Gemma) is **intentionally excluded from the default chain** — two reasons:

1. **Gemma on AI Studio rejects `system`-role messages** with "Developer instruction is not enabled". Every FRIDAY prompt uses a system message for identity + constraints, so Gemma via Google is DOA.
2. **Gemini 2.5 Flash refuses dual-use OSINT work** on "helpful and harmless" grounds. If you're using FRIDAY for fraud / due-diligence investigations, Gemini will return blanket refusals mid-cascade, masking real failures and wasting requests.

To opt back in (e.g. for non-OSINT agents where Gemini's multimodal is useful):

```bash
FRIDAY_USE_GOOGLE_AI_STUDIO=true
GEMINI_API_KEY=<your AI Studio key>    # or GOOGLE_AI_STUDIO_KEY
```

When that flag is set, Google slots into the fallback chain below OpenRouter and above Groq with model `gemini-2.5-flash`.

### Runtime fallback chain

`CLOUD_FALLBACK_CHAIN` is built from every configured provider that isn't the primary. When `cloud_chat()` calls the primary and it errors (HTTP 429/4xx/5xx/timeout/auth), the cascade walks the chain in order until one succeeds. If every cloud provider fails, it drops to local Ollama.

Three properties of the cascade you should know about:

- **OpenAI SDK retries are disabled** (`max_retries=0`). The SDK's built-in exponential-backoff loop used to burn 3 requests per provider before our cascade took over — on free tiers with 50 req/day, that's 6% of your daily cap blown on one request. We now fail immediately on the first 429 and cascade.
- **Daily-limit exhaustion is cached per session** (`_exhausted_providers`). When a provider returns a daily-cap error — `free-models-per-day`, `usage limit`, `quota exceeded`, `resource_exhausted` — we mark that provider skipped for the rest of the process lifetime. No point burning ~500ms cascading through the same guaranteed failure hundreds of times. Restart FRIDAY to retry.
- **Transient 429s** (upstream rate-limit, temporary model outage) cascade on every call — they might clear within seconds.

### Env file layering

`config.py` loads `.env` files with `override=False`, lowest priority first:

1. `Friday.app/Contents/Resources/friday_defaults.env` (Mac app bundle)
2. `~/Friday/.env` (primary user env — visible, colocated with `user.json`)
3. `~/.friday/.env` (legacy hidden location, kept for backwards compat)
4. `<repo>/.env` (dev checkout)

Subprocess environment (Mac app subprocess, CI, your shell) still wins over all of them.

---

## 2. Supported providers

### OpenRouter (recommended default)

- Base URL: `https://openrouter.ai/api/v1`
- Default model: `google/gemma-4-31b-it`
- Free tier: yes (subset of models)
- Tool-calling coverage: widest of any provider
- Signup: [openrouter.ai/settings/keys](https://openrouter.ai/settings/keys) — keys start `sk-or-v1-…`

Single API key gets you routing across ~300 models (Anthropic, OpenAI, Google, Mistral, Meta, Qwen, DeepSeek, etc.). Strong default because `friday setup openrouter` ships a live model picker that filters to tool-capable models and sorts by cost.

### Groq

- Base URL: `https://api.groq.com/openai/v1`
- Default model: `qwen/qwen3-32b`
- Latency: ~500 tok/s (fastest cloud provider as of early 2026)
- Tool-calling coverage: small but solid catalogue (Qwen3, Llama 3.x, DeepSeek)
- Signup: [console.groq.com/keys](https://console.groq.com/keys) — keys start `gsk_…`

Pick Groq if you care more about latency than catalogue size — especially for voice mode, where TTFT dominates perceived responsiveness.

### Google AI (Gemini) — opt-in only

**Not in the default fallback chain.** Two hard blockers for FRIDAY's workload:

- **Gemma via AI Studio rejects system-role messages**: `"Developer instruction is not enabled for models/gemma-3-27b-it"`. Every FRIDAY prompt is `{role: system} + {role: user}`, so the native Gemma endpoint is unusable.
- **Gemini 2.5 Flash refuses dual-use OSINT**: background checks, fraud investigation, journalism-style research — all blocked with "helpful and harmless" refusals. For a personal investigator's toolkit this is useless at best and misleading at worst (refusals masquerade as genuine agent output).

If you still want Google in the chain for non-OSINT agents (it's genuinely multimodal and the free tier is OK for vision tasks):

```bash
# ~/Friday/.env
FRIDAY_USE_GOOGLE_AI_STUDIO=true
GEMINI_API_KEY=<your AI Studio key>     # or GOOGLE_AI_STUDIO_KEY
```

Once enabled, FRIDAY uses `gemini-2.5-flash` as the model (not Gemma — see above). Slots between OpenRouter and Groq in the fallback chain.

You can also still route Google manually via the `CLOUD_*` triplet if you want total control:

```bash
CLOUD_API_KEY=<your Gemini key>
CLOUD_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
CLOUD_MODEL=gemini-2.5-flash
```

Note: Google's free-tier cap dropped to roughly 10 req/day per model in January 2026, down from 250 — it's now tighter than OpenRouter's 50/day free tier.

### Anthropic (via proxy)

Anthropic's native API is **not** OpenAI-compatible out of the box — the Messages API returns a different response shape and doesn't use the `tool_calls` field on the assistant message. FRIDAY does not special-case it.

Two ways to still use Claude:

1. **OpenRouter** — the simplest path. Set `OPENROUTER_API_KEY` and either use the model picker to select `anthropic/claude-opus-4.7` (or similar) or set `CLOUD_MODEL=anthropic/claude-sonnet-4.7`. OpenRouter translates between the OpenAI shape and Anthropic internally.
2. **Your own proxy** — run something like [`claude-api-proxy`](https://github.com/1rgs/claude-code-proxy) or [`litellm`](https://docs.litellm.ai/) locally, point `CLOUD_BASE_URL` at `http://localhost:<port>/v1`, and set `CLOUD_MODEL=claude-sonnet-4.7`. From FRIDAY's perspective this looks like any other OpenAI-compatible server.

### Any OpenAI-compatible endpoint

Everything that speaks `POST /chat/completions` works. Drop in the triplet:

```bash
CLOUD_API_KEY=<key>
CLOUD_BASE_URL=<url>      # must end in /v1
CLOUD_MODEL=<model-id>
```

Tested endpoints: Together, Fireworks, DeepInfra, Lepton, RunPod (serverless vLLM), Modal (custom deployment), and a local `vllm serve ...` on a GPU box.

### Local Ollama (offline fallback)

Runs at `http://localhost:11434`. Default local model is `qwen3.5:9b` (`MODEL_NAME` in [`friday/core/config.py`](../friday/core/config.py)). Full install instructions live in [`docs/ollama-setup.md`](./ollama-setup.md); this doc only covers how it fits into provider selection.

---

## 3. Setup wizards

The CLI ships two one-shot wizards. Both are subcommands of `friday setup` and live in [`friday/core/setup_wizard.py`](../friday/core/setup_wizard.py).

### `friday setup openrouter`

What it does, in order:

1. Opens a clickable link to [openrouter.ai/settings/keys](https://openrouter.ai/settings/keys).
2. Prompts for the key via `getpass` so it doesn't echo. Validates it starts with `sk-or`.
3. If you confirm the model picker, calls `_fetch_openrouter_models()` to grab the live catalogue.
4. Filters to models whose `supported_parameters` includes `tools`, sorts by prompt price per token.
5. Renders the top 20 as a table (id, $/1M prompt, context length).
6. You pick by number or paste a model id; it writes both `OPENROUTER_API_KEY` and `CLOUD_MODEL` to `~/.friday/.env`.

If you skip the picker it just saves the key; the default `google/gemma-4-31b-it` kicks in via `config.py`.

### `friday setup groq`

Simpler — no model picker. Shells out to `_simple_key_setup()`, which:

1. Opens [console.groq.com/keys](https://console.groq.com/keys).
2. Prompts for the key (must start `gsk_`).
3. Writes `GROQ_API_KEY` to `~/.friday/.env`.

Default model (`qwen/qwen3-32b`) is baked into `config.py`. To pick something else, add `CLOUD_MODEL=<id>` manually.

### Guided onboarding

`friday onboard` runs `_step_llm()`, which offers option 1 (OpenRouter), option 2 (Groq), or option 3 (skip → local Ollama). It wraps both setup functions above.

### Diagnostics

- `friday doctor` — prints a table with one row per integration. The "LLM cloud provider" row reports which key was detected.
- `friday test llm` — sends a real `say hi in 3 words` prompt via `cloud_chat()` and prints the response. Fastest way to verify your key works.

---

## 4. The live OpenRouter model picker

Source: [`_fetch_openrouter_models`](../friday/core/setup_wizard.py) in `setup_wizard.py`.

```python
def _fetch_openrouter_models() -> list[dict]:
    """Return models that support tool calling. No auth needed for listing."""
    with urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=10) as r:
        data = json.loads(r.read())
    models = data.get("data", [])
    tool_capable = [
        m for m in models
        if "tools" in (m.get("supported_parameters") or [])
    ]
    def cost(m):
        try:
            return float(m.get("pricing", {}).get("prompt", 0))
        except (TypeError, ValueError):
            return 9.0
    tool_capable.sort(key=cost)
    return tool_capable
```

Why this matters: FRIDAY is a tool-calling agent. A model that doesn't expose the `tools` parameter simply cannot drive the dispatcher. The filter skips every chat-only model so you can't accidentally pick one. Sort-by-cost means the cheapest tool-capable models float to the top — which, on OpenRouter, is usually a free tier offering like Gemma 4 via Google AI Studio.

The 20-row cap in the picker is a UX choice — if you want a specific model outside the top 20, paste its id when prompted instead of picking a number.

---

## 5. Switching providers

There is no code to edit. Change the env var, restart FRIDAY.

```bash
# Use OpenRouter
export OPENROUTER_API_KEY=sk-or-v1-...
unset GROQ_API_KEY CLOUD_API_KEY

# Switch to Groq
export GROQ_API_KEY=gsk_...
unset OPENROUTER_API_KEY CLOUD_API_KEY

# Run local only
unset OPENROUTER_API_KEY GROQ_API_KEY CLOUD_API_KEY
```

Or edit `~/.friday/.env` — which is what the setup wizards do. The priority rules in `config.py` mean the highest-precedence key wins even if several are present; you don't have to unset the others, but it's cleaner.

---

## 6. Model recommendations

Three models have been end-to-end tested for FRIDAY's 32-tool dispatch registry. Benchmarks live in [`tests/test_production_benchmark.py`](../tests/test_production_benchmark.py) and [`tests/test_gemma_vs_qwen.py`](../tests/test_gemma_vs_qwen.py). The benchmark script loads FRIDAY's real system prompts (`_CLASSIFY_PROMPT`, `DISPATCH_PROMPT`, `PERSONALITY_SLIM`) and the real tool schema, then scores classify / dispatch / chat accuracy and streaming TTFT.

| Model | Recommended when | Notes |
|---|---|---|
| `google/gemma-4-31b-it` | Default for cloud | Strong tool-call formatting, no thinking overhead, cheap via Google AI Studio. |
| `qwen/qwen3-32b` | Groq users | Fastest latency. Needs `/no_think` prefix to suppress reasoning tokens (handled automatically — see §9). |
| `openai/gpt-oss-20b` | Small-context jobs | Open-weight, clean tool calls, usable at ~20B params. |
| `qwen3.5:9b` (local) | Offline / private | FRIDAY's baked-in Ollama default. 8/8 on the tool-calling accuracy suite. |

What Travis ships in production: **`google/gemma-4-31b-it` via OpenRouter, routed through the Google AI Studio provider** (the free tier is cheapest). Groq/Qwen3 is the fallback when OpenRouter has capacity issues.

---

## 7. Cost comparison (early 2026)

Rough pricing per 1M tokens. Use the live picker for exact current rates — providers change pricing monthly.

| Provider / model | $/1M input | $/1M output | Free tier? |
|---|---|---|---|
| OpenRouter → Google AI Studio, `google/gemma-4-31b-it` | ~$0 | ~$0 | yes (rate-limited) |
| OpenRouter → Parasail, `google/gemma-4-31b-it` | ~$0.15 | ~$0.20 | no |
| Groq, `qwen/qwen3-32b` | ~$0.30 | ~$0.40 | yes (dev tier) |
| Groq, `llama-3.3-70b-versatile` | ~$0.60 | ~$0.80 | yes (dev tier) |
| Google direct, `gemma-4-31b-it` | ~$0 | ~$0 | yes (generous) |
| OpenRouter → Anthropic, `claude-sonnet-4.7` | ~$3.00 | ~$15.00 | no |
| Together, `Qwen/Qwen3-235B-A22B` | ~$0.80 | ~$2.40 | no |
| Local Ollama, `qwen3.5:9b` | $0 (electricity) | $0 | always |

A typical FRIDAY session (30 turns, average 2-3k tokens per turn with the dispatch prompt) costs well under $0.05 on Gemma 4. Heavy research sessions with deep-research agent calls can reach $0.20-$0.50. The actual ratios from `test_production_benchmark.py` (50-query suite): Groq/Qwen3 $6.82, OR/Parasail $3.43, OR/GoogAI $3.43, Google Direct FREE.

---

## 8. Why Gemma 4 specifically

1. **Open weights.** You can run the same model locally via Ollama if you ever pull the plug on cloud.
2. **Tool-calling reliability.** In FRIDAY's 50-query production benchmark it hits 100% on classification and 96%+ on dispatch — parity with the closed-weight heavyweights at a fraction of the price.
3. **No reasoning overhead.** Unlike Qwen3 it doesn't emit `<think>` blocks that have to be stripped.
4. **Fits on consumer hardware.** The 31B variant runs in 8GB RAM at 4-bit quantization; the 9B local default is lighter still.
5. **Price.** Free tier via Google AI Studio. Paid tier elsewhere is ~$0.15/1M input — cheaper than Llama 3.x at comparable quality.

The downside: context limit is 128k, which is less than some frontier models. For FRIDAY this has never mattered — dispatch rarely exceeds 8k tokens.

---

## 9. Tool-calling quirks

Every provider formats tool calls slightly differently. FRIDAY normalises them in [`friday/core/llm.py`](../friday/core/llm.py):

```python
# friday/core/llm.py
def _normalize_openai_response(response) -> dict:
    """Convert OpenAI ChatCompletion to the same dict format as Ollama."""
    choice = response.choices[0]
    msg = choice.message
    result = {"message": {"role": msg.role or "assistant",
                          "content": msg.content or "",
                          "tool_calls": []}}
    if msg.tool_calls:
        for tc in msg.tool_calls:
            args = tc.function.arguments
            if isinstance(args, str):
                try: args = json.loads(args)
                except json.JSONDecodeError: args = {}
            result["message"]["tool_calls"].append({
                "id": tc.id, "type": "function",
                "function": {"name": tc.function.name, "arguments": args},
            })
    return result
```

Downstream, `extract_tool_calls()` and `extract_text()` work against the Ollama-shaped dict regardless of whether the response came from Ollama or a cloud provider.

### Provider-specific gotchas

- **Qwen3 on any provider** emits `<think>…</think>` blocks unless prefixed with `/no_think`. `cloud_chat()` injects that prefix automatically when the model name contains `qwen`.
- **Gemma 4** doesn't need thinking suppression.
- **Groq** returns tool call arguments as JSON strings. FRIDAY parses them to dicts on ingestion, then re-serialises to strings in the outbound sanitize step (`cloud_chat` → `sanitized_messages`) because the OpenAI API spec requires strings.
- **OpenRouter** sometimes returns upstream errors (503, 429) that `cloud_chat` catches and falls back to local Ollama for.
- **Streaming** is wrapped in `_filtered_stream()` which strips `<think>` blocks mid-stream so voice mode never speaks reasoning tokens.

---

## 10. Local Ollama setup (short version)

Full guide: [`docs/ollama-setup.md`](./ollama-setup.md). Three-step summary:

```bash
brew install ollama
ollama pull qwen3.5:9b        # ~6 GB
ollama serve                   # or launch the Ollama.app
```

FRIDAY auto-detects the server on `http://localhost:11434`. Hardware: 16 GB RAM minimum; M-series Macs keep the model resident in VRAM via `keep_alive: -1`, so after first load every call is sub-second context rebuild.

---

## 11. Hybrid mode (cascade, then local Ollama)

Nothing to enable — this is the default behaviour of `cloud_chat()`. Call flow:

1. Try the **primary** provider (whichever resolved from §1).
2. On any non-fatal error — `RateLimitError`, `APIError`, `APIConnectionError`, timeouts, auth failures — step to the next entry in `CLOUD_FALLBACK_CHAIN`.
3. If the error is a daily-limit (`free-models-per-day`, `usage limit`, etc.), mark that provider **exhausted for the session** so later calls don't waste time trying it.
4. When every cloud provider either errors or is already marked exhausted, drop to local Ollama at `http://localhost:11434`.
5. Log which provider actually answered (`cloud_chat answered via fallback provider: …`) for debug / `friday doctor`.

Design decisions baked in:

- **`max_retries=0`** on every OpenAI client. The SDK's built-in exponential-backoff used to burn 3 requests per provider before cascading. On free tiers (50 req/day) that's 6% of your daily cap on one call.
- **Daily-limit errors don't retry within the session.** When OpenRouter says `free-models-per-day`, the cap resets at midnight UTC — retrying in 30 seconds won't help. We cache the exhaustion and skip the provider until restart.
- **Transient 429s** (upstream model overload) DO cascade every call — they might clear within seconds.

So if your plane loses wifi mid-session, FRIDAY keeps working as long as Ollama is running. If Ollama isn't running either, the user sees a concrete error with the last cloud exception in the log.

To force local-only (e.g. privacy-sensitive session), `unset` the cloud keys before launch.

---

## 12. Environment variable reference

| Variable | Effect | Example |
|---|---|---|
| `CLOUD_API_KEY` | Manual mode. Wins over everything. | `sk-…` |
| `CLOUD_BASE_URL` | Required when `CLOUD_API_KEY` is set. | `https://api.together.xyz/v1` |
| `CLOUD_MODEL` | Required when `CLOUD_API_KEY` is set. Also overrides the default model for OpenRouter/Groq. | `meta-llama/Llama-3.3-70B-Instruct-Turbo` |
| `OPENROUTER_API_KEY` | Auto-configures OpenRouter. Default model `google/gemma-4-31b-it:free`. | `sk-or-v1-…` |
| `GROQ_API_KEY` | Auto-configures Groq. Default model `qwen/qwen3-32b`. | `gsk_…` |
| `FRIDAY_USE_GOOGLE_AI_STUDIO` | Set to `true` to opt Google AI Studio back into the fallback chain. Off by default — see §2. | `true` |
| `GEMINI_API_KEY` / `GOOGLE_AI_STUDIO_KEY` | Google AI Studio key — only loaded when `FRIDAY_USE_GOOGLE_AI_STUDIO=true`. | `AI…` |
| `OLLAMA_BASE_URL` | Hardcoded to `http://localhost:11434` in config. Change in `friday/core/config.py` if you need a remote Ollama. | — |
| `MODEL_NAME` | Local Ollama model id. Constant in `config.py` (not env-driven). | `qwen3.5:9b` |

`USE_CLOUD` is a derived boolean (`bool(CLOUD_API_KEY)`), not a user-settable env var. `CLOUD_FALLBACK_CHAIN` is a derived list of `(name, key, base_url, model)` tuples for every non-primary provider — read by `llm.py`, not user-settable.

---

## 13. Debugging

### See which provider is in use

```bash
friday doctor
```

The "LLM cloud provider" row prints one of `CLOUD_API_KEY (manual)`, `Groq`, `OpenRouter`, or a hint to run a setup wizard. The "Ollama (local)" row reports whether the local server is up.

At runtime, the model being called is in `friday.core.config.CLOUD_MODEL_NAME`:

```python
python -c "from friday.core.config import CLOUD_MODEL_NAME, CLOUD_BASE_URL; print(CLOUD_BASE_URL, CLOUD_MODEL_NAME)"
```

### Log raw LLM responses

`cloud_chat()` uses the standard `logging` module. Enable debug output:

```bash
export PYTHONLOGLEVEL=DEBUG
friday
```

For a one-off inspection, wrap the call:

```python
from friday.core.llm import cloud_chat
resp = cloud_chat(messages=[{"role": "user", "content": "hello"}])
print(resp)
```

The response is already in Ollama-shaped dict form, so `resp["message"]["content"]` / `resp["message"]["tool_calls"]` give you the normalised output.

### Verify a specific model works for tool calls

```bash
python tests/test_production_benchmark.py
```

Runs 50 real FRIDAY queries against every configured provider in parallel, reports per-provider accuracy and cost.

---

## 14. Cost control

- **`max_tokens`** — every dispatcher call in `friday/core/tool_dispatch.py` caps output. Lower `max_tokens` on chat responses if you're bleeding tokens on verbose models.
- **Conversation truncation** — the orchestrator keeps a rolling window; history older than N turns is summarised and dropped. See `friday/core/orchestrator.py` for the exact window size.
- **Fast path** — `friday/core/fast_path.py` short-circuits trivial queries ("what time is it", "battery level") without hitting the LLM at all. If a query matches, you pay zero tokens. Don't bypass it with overly specific phrasing.
- **Classify → dispatch → chat split** — the three-stage pipeline uses the same (small) model for classification + dispatch, only invoking the chat-style response once the tool results are back. Compared to a single monolithic agent call this cuts total tokens roughly 40%.
- **Pick the cheapest tool-capable model** — `_fetch_openrouter_models()` already sorts the picker by cost. Rule of thumb: if you don't need frontier reasoning, Gemma 4 via Google AI Studio is free and good enough.

---

## Related docs

- [`docs/ollama-setup.md`](./ollama-setup.md) — full local Ollama install + hardware notes.
- [`docs/architecture.md`](./architecture.md) — how the orchestrator / router / dispatcher call the LLM.
- [`docs/cli-commands.md`](./cli-commands.md) — `friday setup`, `friday doctor`, `friday test`.
- [`friday/core/llm.py`](../friday/core/llm.py) — `chat()`, `cloud_chat()`, normalisation helpers.
- [`friday/core/config.py`](../friday/core/config.py) — provider priority resolution.
- [`friday/core/setup_wizard.py`](../friday/core/setup_wizard.py) — wizards and the live model picker.
- [`tests/test_production_benchmark.py`](../tests/test_production_benchmark.py) — accuracy + cost benchmark across providers.
