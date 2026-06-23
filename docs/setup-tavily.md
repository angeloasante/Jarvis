# Tavily Web Search Setup

## Overview

Tavily is a web-search API built for AI agents. Unlike Google or Bing, it returns clean JSON — title, URL, snippet, and extracted page content — with no ads, navigation chrome, or cookie banners to parse around. FRIDAY's `research_agent`, `deep_research_agent`, and morning briefing agents all lean on it as the primary search backend.

The free tier covers 1,000 API calls per month (as of 2026), which is more than enough for personal use.

## Why Tavily vs Google / Bing / DuckDuckGo

- **Agent-optimised output** — clean extracted content, not raw HTML. Saves a token-expensive HTML-to-text pass.
- **No scraping / terms issues** — Tavily is a proper API with a licence to return content. Google's search API is expensive and Bing shut theirs down. Scraping DuckDuckGo breaks their ToS.
- **Free tier is generous** — 1,000 calls/month covers a research-heavy user.
- **Fast** — typical response is 1-2 seconds, including content extraction.
- **Built-in ranked answer** — Tavily's `include_answer=true` returns a synthesised short answer alongside sources, which FRIDAY uses for quick facts.

## Setup Walkthrough

1. Sign up at [https://app.tavily.com](https://app.tavily.com) (free, email-only).
2. Grab your API key from the dashboard. It starts with `tvly-…`.
3. Run the setup wizard:

   ```bash
   friday setup tavily
   ```

4. Paste the key when prompted.
5. The wizard writes it to `~/.friday/.env` as:

   ```
   TAVILY_API_KEY=tvly-xxxxxxxxxxxxxxxxxxxx
   ```

That's it — the research agent will pick it up on next launch.

## The Tools That Use It

Defined in [`friday/tools/web_tools.py`](../friday/tools/web_tools.py):

```python
async def search_web(query: str, num_results: int = 5) -> ToolResult:
    """Search the web using Tavily. Returns structured results with content."""

async def fetch_page(url: str) -> ToolResult:
    """Fetch a web page. Auto-falls back to browser rendering for JS-heavy sites."""
```

- `search_web` — returns a ranked list of results (`title`, `url`, `content`, `score`) plus a Tavily-generated short answer. Caps at 3 results internally regardless of `num_results` to keep context small.
- `fetch_page` — not a Tavily call. Uses `httpx` to pull the raw page, strips HTML, and falls back to Playwright for JS-heavy SPAs. Used after `search_web` when the agent needs the full page body.

## Bundled Key in the Mac App

The Mac app ships a shared Tavily key in `friday_defaults.env` inside the `.app` bundle so users don't have to sign up just to try web search. See [`Friday-mac/build_bundle.sh`](../Friday-mac/build_bundle.sh) — the build script copies `TAVILY_API_KEY` from the repo `.env` into `Contents/Resources/friday_defaults.env` at bundle time.

Load order (lowest priority first) from [`friday/core/config.py`](../friday/core/config.py):

1. `friday_defaults.env` inside the `.app` bundle (shared key)
2. `~/.friday/.env` (per-user overrides)
3. `<repo>/.env` (dev environment)
4. Subprocess environment (highest — this is how the Mac app injects per-user secrets)

To override the bundled key, set your own `TAVILY_API_KEY` in `~/.friday/.env` or run `friday setup tavily`.

## Alternatives / No-Tavily Mode

If you don't want Tavily, remove `TAVILY_API_KEY` from your env. `search_web` soft-fails — it returns a `ToolResult` with:

```
"Web search isn't available right now — the Tavily API key isn't configured."
```

The agent sees this and either skips the search or tells the user it can't search. There is currently **no automatic fallback** to DuckDuckGo, Brave, or SerpAPI. `fetch_page` still works without Tavily — you can feed the agent a URL directly and it'll pull the page.

A DuckDuckGo / Brave Search fallback is not yet wired up; if you want it, it's a small addition to `web_tools.py`.

## Testing

There's no dedicated `friday test tavily` command today. Easiest test:

```bash
friday
# then in the REPL:
> who's Sam Altman
```

Watch for `search_web` in the tool-call log. If the agent responds with fresh info (recent news, current role), Tavily is working. If it says it can't search, check `TAVILY_API_KEY` in `~/.friday/.env`.

## Usage Patterns

From [`friday/agents/research_agent.py`](../friday/agents/research_agent.py) and [`friday/agents/deep_research_agent.py`](../friday/agents/deep_research_agent.py):

- **research_agent** — calls `search_web` once with the user's query, then optionally `fetch_page` on the top result if it needs more depth. Single-turn, fast.
- **deep_research_agent** — generates 3-5 sub-queries, runs `search_web` on all of them in parallel with `asyncio.gather`, then fetches the top 2 URLs. Trades latency for coverage.
- **fast_path** handles greetings and simple chitchat without calling search at all — saves quota.
- **oneshot** doesn't re-search within a conversation on trivial follow-ups; it reuses context from the prior turn.

## Rate Limits

- **Free tier**: 1,000 API calls/month. Resets monthly.
- **Paid tiers** (as of 2026): start around $30/mo for 4,000 calls, scaling up from there. Check [tavily.com/pricing](https://tavily.com/pricing) for current numbers.
- Each `search_web` call is one API credit. `fetch_page` is not a Tavily call and has no Tavily cost.

## Cost Control

FRIDAY minimises redundant searches in several ways:

- `fast_path` short-circuits greetings/small-talk before the agent is even invoked
- `oneshot` mode reuses the prior turn's context for quick follow-ups
- `search_web` internally caps at 3 results (`max_results=min(num_results, 3)`) regardless of what the model requests
- `search_depth="advanced"` is set — this costs slightly more per call but returns better content, reducing the need for follow-up `fetch_page` calls

A typical day of use runs 20-50 searches.

## Troubleshooting

- **`401 Unauthorized`** — bad key. Re-run `friday setup tavily` and double-check you copied the full `tvly-…` string.
- **`429 Rate Limit`** — free tier exhausted. Wait until the monthly reset or upgrade at [app.tavily.com](https://app.tavily.com).
- **Empty results** — query too specific or niche. Try broadening it. Tavily's index skews toward general web content; very recent news (last few hours) or obscure technical forums may not be indexed yet.
- **Network errors** — `search_web` returns a `ToolResult` with `ErrorCode.NETWORK_ERROR`. Check your connection and Tavily's status page.
- **Bundled key ignored** — the dotenv loader uses `override=False`, so if you already have `TAVILY_API_KEY` set in your shell or `~/.friday/.env`, that takes precedence over the bundled default.

## Related Files

- [`friday/tools/web_tools.py`](../friday/tools/web_tools.py) — `search_web`, `fetch_page` implementations
- [`friday/core/setup_wizard.py`](../friday/core/setup_wizard.py) — `setup_tavily()`
- [`friday/core/config.py`](../friday/core/config.py) — env layering
- [`friday/agents/research_agent.py`](../friday/agents/research_agent.py) — single-search usage
- [`friday/agents/deep_research_agent.py`](../friday/agents/deep_research_agent.py) — parallel multi-query usage
- [`Friday-mac/build_bundle.sh`](../Friday-mac/build_bundle.sh) — bundled key packaging
- [`pyproject.toml`](../pyproject.toml) — `tavily-python>=0.7.23` dependency
