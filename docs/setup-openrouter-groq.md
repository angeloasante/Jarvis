# Setup: OpenRouter + Groq

Step-by-step setup for FRIDAY's two first-class cloud LLM providers. For the broader provider abstraction (custom endpoints, priority rules, `CLOUD_API_KEY`, layered env files, local Ollama fallback), see [llm-providers.md](./llm-providers.md).

---

## 1. Overview

Both OpenRouter and Groq are **OpenAI-compatible** cloud LLM providers — FRIDAY talks to either using the same `cloud_chat()` wrapper in [`friday/core/llm.py`](../friday/core/llm.py). You don't need to pick forever; switching is a one-line env change.

| Provider       | Model catalogue                              | Typical latency | Pricing           | Best for                                  |
|----------------|----------------------------------------------|-----------------|-------------------|-------------------------------------------|
| **OpenRouter** | Hundreds of models (Gemma, Qwen, Llama, GPT, Claude, DeepSeek, …) | ~1–3 s          | Free tier + pay-as-you-go | Widest choice, cheapest default (~$3.43/mo for Gemma 4 31B) |
| **Groq**       | Small curated set (Qwen3-32B, Llama 3.x, Mixtral, Gemma) | ~0.5 s (~500 tok/s) | Generous free tier, then rate-limit | Low-latency UX — voice, interactive REPL  |

**Tradeoff in one line each:**

- **OpenRouter** — widest selection + free tier + lets you pick any tool-capable model the wizard surfaces. Normal cloud latency.
- **Groq** — blazing fast (~500 tok/s, sub-100 ms first token). Fewer models, but the ones it has are fine for most FRIDAY workloads.

**Set either or both.** If both keys are present the resolution rules in [`friday/core/config.py`](../friday/core/config.py) decide which wins — see [Priority](#4-how-priority-works) below.

---

## 2. OpenRouter setup walkthrough

### 2.1 Get a key

1. Sign up at <https://openrouter.ai> (free, email or GitHub).
2. Open <https://openrouter.ai/settings/keys> and create a key. It starts with `sk-or-v1-…`.
3. (Optional) Top up $5 once — unlocks the paid models. Free-tier-only users can skip this and stick to `:free` variants.

### 2.2 Run the wizard

```bash
friday setup openrouter
```

The wizard:

1. Prints a clickable link to the keys page.
2. Prompts for the key (input is hidden via `getpass`).
3. Validates the `sk-or` prefix. Aborts on mismatch.
4. Offers to open the **live model picker**.

Source: [`setup_openrouter()` in friday/core/setup_wizard.py](../friday/core/setup_wizard.py).

### 2.3 The live model picker

When you say yes to "Pick a specific model?", the wizard hits `https://openrouter.ai/api/v1/models` (no auth required), filters to **tool-capable** models (`supported_parameters` contains `"tools"`), sorts **cheapest prompt-price first**, and shows the top 20:

```
 #  Model                                $/1M prompt   Ctx
 1  google/gemma-4-31b-it:free           free          131072
 2  qwen/qwen3-coder:free                free          262144
 3  deepseek/deepseek-chat-v3:free       free          163840
 …
 9  google/gemma-4-31b-it                $0.14         131072
 …
```

**What the columns mean:**

- **`#`** — pick a number, or paste any model id the list doesn't include.
- **Model** — the string that ends up in `CLOUD_MODEL`.
- **`$/1M prompt`** — price per 1 million input tokens. `free` means the free tier; `$0.14` means 14¢ per million. Output tokens are priced separately (usually 2–3× prompt); see the OpenRouter model page for the full breakdown.
- **Ctx** — context window in tokens. 131 072 = 128K. Most FRIDAY conversations need ≤16K, so anything above that is plenty.

### 2.4 Tested favourites

From FRIDAY's own benchmarks ([`tests/test_full_benchmark.py`](../tests/test_full_benchmark.py), [`tests/test_gemma_vs_qwen.py`](../tests/test_gemma_vs_qwen.py)):

- **`google/gemma-4-31b-it`** — 97 % tool-calling accuracy, ~3 s avg, ~$3.43/mo typical. FRIDAY's default when `OPENROUTER_API_KEY` is set alone.
- **`google/gemma-4-31b-it:free`** — same model, free tier, rate-limited.
- **`qwen/qwen3-coder:free`** — good for code agent tasks.
- **`deepseek/deepseek-chat-v3`** — cheap and capable, slower than Gemma.

Paid Gemma 4 was the winner across accuracy, cost, and stability — that's why it's the default.

### 2.5 What gets written

`~/.friday/.env` gets two keys appended (or updated in place):

```
OPENROUTER_API_KEY=sk-or-v1-…
CLOUD_MODEL=google/gemma-4-31b-it
```

The wizard also pushes the values into `os.environ` so the current shell session picks them up without a restart.

---

## 3. Groq setup walkthrough

### 3.1 Get a key

1. Sign up at <https://console.groq.com> (free, Google/GitHub login).
2. Open <https://console.groq.com/keys> and create a key. It starts with `gsk_…`.

### 3.2 Run the wizard

```bash
friday setup groq
```

The wizard (backed by `_simple_key_setup()` in [`setup_wizard.py`](../friday/core/setup_wizard.py)):

1. Shows the keys link.
2. Prompts for the key (hidden input).
3. Validates the `gsk_` prefix. Aborts on mismatch.
4. Writes `GROQ_API_KEY=gsk_…` to `~/.friday/.env`.

That's it — no model picker. FRIDAY's default on Groq is `qwen/qwen3-32b`, hardcoded in `friday/core/config.py`:

```python
elif _groq_key:
    CLOUD_API_KEY    = _groq_key
    CLOUD_BASE_URL   = os.getenv("CLOUD_BASE_URL", "https://api.groq.com/openai/v1")
    CLOUD_MODEL_NAME = os.getenv("CLOUD_MODEL", "qwen/qwen3-32b")
```

Override by setting `CLOUD_MODEL=…` in `~/.friday/.env` — see [Changing models](#6-changing-models-after-setup).

---

## 4. How priority works

With both keys set, `config.py` resolves **explicit first, Groq second, OpenRouter third**:

```python
# friday/core/config.py — the actual branching
_explicit_key   = os.getenv("CLOUD_API_KEY", "")
_openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
_groq_key       = os.getenv("GROQ_API_KEY", "")

if _explicit_key:
    CLOUD_API_KEY    = _explicit_key
    CLOUD_BASE_URL   = os.getenv("CLOUD_BASE_URL", "")
    CLOUD_MODEL_NAME = os.getenv("CLOUD_MODEL", "")
elif _groq_key:
    CLOUD_API_KEY    = _groq_key
    CLOUD_BASE_URL   = os.getenv("CLOUD_BASE_URL", "https://api.groq.com/openai/v1")
    CLOUD_MODEL_NAME = os.getenv("CLOUD_MODEL", "qwen/qwen3-32b")
elif _openrouter_key:
    CLOUD_API_KEY    = _openrouter_key
    CLOUD_BASE_URL   = os.getenv("CLOUD_BASE_URL", "https://openrouter.ai/api/v1")
    CLOUD_MODEL_NAME = os.getenv("CLOUD_MODEL", "google/gemma-4-31b-it")
else:
    CLOUD_API_KEY = CLOUD_BASE_URL = CLOUD_MODEL_NAME = ""

USE_CLOUD = bool(CLOUD_API_KEY)
```

Resolution rules:

1. `CLOUD_API_KEY` wins if set — fully manual, you supply `CLOUD_BASE_URL` and `CLOUD_MODEL` too. Use this for any OpenAI-compatible endpoint.
2. Otherwise `GROQ_API_KEY` wins if set.
3. Otherwise `OPENROUTER_API_KEY` wins if set.
4. None of the above → `USE_CLOUD = False` and FRIDAY routes to local Ollama.

If you want OpenRouter to take effect while a Groq key is also present, either remove `GROQ_API_KEY` from `~/.friday/.env` or set `CLOUD_API_KEY` + `CLOUD_BASE_URL` explicitly.

---

## 5. Testing the connection

```bash
friday test llm
```

This calls `test_llm()` in [`setup_wizard.py`](../friday/core/setup_wizard.py), which sends `"say hi in 3 words"` through `cloud_chat()` with `max_tokens=20` and prints the response. It validates three things at once:

- Your API key is accepted (401 → bad/revoked key).
- The network path to the provider works.
- The selected model is reachable on that provider (404 → typo or unavailable).

Expected output:

```
─ Test · LLM ────────────────────────────────────────
  model: google/gemma-4-31b-it
  sending: 'say hi in 3 words'…
  ✓ response: Hi there, friend!
```

`friday doctor` also surfaces whether a cloud provider is configured (see the `LLM cloud provider` row).

---

## 6. Changing models after setup

### OpenRouter

Either re-run the wizard (fastest — gives you the live picker again):

```bash
friday setup openrouter
```

…or edit `~/.friday/.env` by hand and set:

```
CLOUD_MODEL=anthropic/claude-sonnet-4.5
```

Any tool-capable model id from `https://openrouter.ai/api/v1/models` works.

### Groq

There's no picker — set `CLOUD_MODEL` directly in `~/.friday/.env`. Values that work today on Groq's catalogue (<https://console.groq.com/docs/models>):

```
CLOUD_MODEL=qwen/qwen3-32b               # FRIDAY default — tool-capable, thinking filtered
CLOUD_MODEL=llama-3.3-70b-versatile      # Strong general reasoning
CLOUD_MODEL=llama-3.1-70b-versatile      # Previous-gen equivalent
CLOUD_MODEL=llama-3.1-8b-instant         # Fastest, smaller, cheaper
CLOUD_MODEL=gemma2-9b-it                 # Lightweight
CLOUD_MODEL=mixtral-8x7b-32768           # Long context (32K), mixture-of-experts
```

Groq deprecates models periodically — if you get a 404, check their current list.

Restart FRIDAY after editing `.env` so `config.py` re-reads it. (The wizard pushes to `os.environ` live; manual edits don't.)

---

## 7. Cost awareness

### OpenRouter

- **Free tier** — `:free` model variants are rate-limited (commonly ~20 req/min, daily caps) but cost $0. If you exceed the quota you get `429 Rate Limit` — wait a minute or swap to the paid variant.
- **Paid** — pay-as-you-go off the credit balance you top up. Gemma 4 31B typically lands around $3–5/month for sustained FRIDAY use. Track real-time spend at <https://openrouter.ai/activity>.

### Groq

- **Free tier** — generous (thousands of req/day) but not unlimited. When you exceed it, Groq returns `429 Too Many Requests` with a `retry-after` header; FRIDAY surfaces the error via the cloud-chat fallback to Ollama.
- **Paid tier** — per-token pricing similar to other hosts; Qwen3-32B sustained lands near $6.82/month in FRIDAY's benchmarks.

If you exceed *either* free tier mid-conversation and FRIDAY has Ollama running locally, the cloud-call exception handler in `cloud_chat()` falls back to the local model automatically — you'll see a warning in the log but the REPL keeps working.

---

## 8. Switching between the two

No wizard needed. Edit `~/.friday/.env`:

```
# Switch from Groq → OpenRouter: comment/delete the Groq key
# GROQ_API_KEY=gsk_…
OPENROUTER_API_KEY=sk-or-v1-…
CLOUD_MODEL=google/gemma-4-31b-it
```

Restart FRIDAY. `config.py` re-runs the priority ladder on import and `USE_CLOUD_MODEL_NAME` reflects the active provider.

Or keep both keys and flip `CLOUD_API_KEY` / `CLOUD_BASE_URL` in `.env` to force a specific endpoint regardless of the ladder.

---

## 9. Troubleshooting

| Symptom                      | Likely cause                                         | Fix                                                                 |
|------------------------------|------------------------------------------------------|---------------------------------------------------------------------|
| `401 Unauthorized`           | Wrong key, revoked key, or whitespace around it      | Regenerate on the provider dashboard, re-run `friday setup …`       |
| `404 Model Not Found`        | Typo in `CLOUD_MODEL`, or the model isn't on that provider | Re-run the OpenRouter picker, or fix the id manually                |
| `429 Rate Limit` / `Too Many Requests` | Free-tier quota hit                         | Wait, switch to the paid variant, or run the other provider         |
| `context_length_exceeded`    | Conversation history longer than the model's context | In the REPL, run `/clear` to wipe history; or swap to a larger-ctx model |
| `Couldn't fetch model list`  | OpenRouter API unreachable from your network         | Retry, check VPN / firewall; wizard still saves the key without a model pick |
| Cloud call silently falls back to Ollama | Exception during `cloud_chat()` — see logs | `friday test llm` to reproduce. Check the warning from `friday/core/llm.py` |

All errors bubble up through the fallback logic in [`cloud_chat()` at llm.py:213](../friday/core/llm.py), which logs the warning and retries against local Ollama.

---

## 10. Advanced: any OpenAI-compatible endpoint

OpenRouter and Groq are just two of many. FRIDAY also works with Together, Fireworks, Modal, RunPod, vLLM, LM Studio, or your own server — anything that speaks the OpenAI Chat Completions API.

Set the three `CLOUD_*` vars instead of a provider-specific key:

```
CLOUD_API_KEY=your-key
CLOUD_BASE_URL=https://api.provider.com/v1
CLOUD_MODEL=provider/model-id
```

`CLOUD_API_KEY` takes priority over both `GROQ_API_KEY` and `OPENROUTER_API_KEY` — see the "Any OpenAI-Compatible Provider" section of [llm-providers.md](./llm-providers.md#3-any-openai-compatible-provider) for the full matrix, including Modal + vLLM examples.

---

## See also

- [llm-providers.md](./llm-providers.md) — full provider abstraction, layered env files, local Ollama fallback
- [`friday/core/config.py`](../friday/core/config.py) — the resolution ladder
- [`friday/core/llm.py`](../friday/core/llm.py) — `cloud_chat()`, thinking-block filter, Ollama fallback
- [`friday/core/setup_wizard.py`](../friday/core/setup_wizard.py) — `setup_openrouter()`, `setup_groq()`, `test_llm()`
