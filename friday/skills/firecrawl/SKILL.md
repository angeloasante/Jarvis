---
name: firecrawl
description: How to use Firecrawl for web search and clean page scraping inside FRIDAY. Use when an agent needs reliable web context, when Tavily caps out, or when fetch_page returns thin/JS-shell content.
agents: [research_agent, deep_research_agent, code_agent, system_agent, investigation_agent, job_agent, briefing_agent]
---

# Firecrawl

Firecrawl helps agents search first, scrape clean content, and interact
with live pages when plain extraction is not enough.

## How FRIDAY uses Firecrawl

FRIDAY follows **Path D** (REST API direct, no CLI install). The
plumbing already lives at `friday/tools/firecrawl_client.py` and is
wired into the existing tools:

| When you'd reach for | Call | What happens |
|---|---|---|
| Web search | `search_web(query, num_results)` | Tavily → Firecrawl → DuckDuckGo cascade. You don't pick the provider; the wrapper falls through on failure. |
| Single page → clean markdown | `fetch_page(url)` | Firecrawl primary, httpx fallback, Playwright for JS shells. |
| You need both search AND inline page content in one call | (advanced) `firecrawl_client.search(query, with_content=True)` | Costs more credits but eliminates a follow-up fetch_page round trip. Use when you know you'll read the top results. |

`FIRECRAWL_API_KEY` lives in `~/Friday/.env`. If you don't see it set,
run `friday setup firecrawl` (500 free credits, no card required).

## When Firecrawl helps most

- **Tavily plan limit reached** — search_web logs `:: Tavily plan limit
  reached — routing to Firecrawl` and the answer flows through.
- **JS-heavy site fetching** — Firecrawl renders server-side, so
  `fetch_page` returns clean markdown instead of `__next_data__` shell
  HTML or "you need to enable JavaScript".
- **PDF / structured-data pages** — Firecrawl extracts cleaner content
  than the regex stripper.
- **Investigation work** — when scraping a subject's website, Wayback
  snapshot, or Companies House profile, prefer fetch_page → it'll route
  through Firecrawl first.

## When NOT to call Firecrawl directly

- The user just asked a casual question — don't search at all. Route to
  CHAT (the LLM router handles this; you shouldn't be reaching for
  search_web for "why is the sky blue").
- The site is in your local library / already in memory — search the
  memory store first (`search_memory`) before going to the web.
- A known-good URL the user gave you — `fetch_page(url)` directly. The
  cascade picks Firecrawl when configured.

## Cost model

Each search request = 2 credits. Adding `with_content=True` adds
~1 credit per result scraped. `fetch_page` via Firecrawl scrape =
1 credit per call. The 500 free credits cover ~250 plain searches OR
~500 plain page-scrapes OR ~70 search-with-scrape calls. After that:
$83 per 100k credits (~$0.83 per 1k searches without scrape).

## Choose Your Path (verbatim from Firecrawl docs)

The original Firecrawl onboarding lays out four paths. FRIDAY uses
**Path D**, but the others are documented here for context:

- **Path A** — install Firecrawl's CLI (`npx -y firecrawl-cli@latest
  init --all --browser`) for live web work. Useful for ad-hoc shell
  use; FRIDAY doesn't need it.
- **Path B** — Firecrawl's build skills for integrating into an app.
  Useful when you're writing fresh code that calls Firecrawl directly;
  FRIDAY's integration is already in `friday/tools/firecrawl_client.py`.
- **Path C** — browser-auth flow to obtain an API key without leaving
  the agent loop. FRIDAY uses the simpler `friday setup firecrawl`
  wizard; reach for Path C if you ever want to script unattended
  enrolment.
- **Path D (FRIDAY default)** — REST API direct. Documented below.

### Path D: Use Firecrawl Without Installing Anything

You still need an API key. Two ways to get one:

- **Human pastes it in** — `FIRECRAWL_API_KEY=fc-...` in `~/Friday/.env`
  (or run `friday setup firecrawl`).
- **Automated flow** — Path C walks the human through browser auth and
  receives the key automatically.

**Base URL:** `https://api.firecrawl.dev/v2`

**Auth header:** `Authorization: Bearer fc-YOUR_API_KEY`

#### Available endpoints

- `POST /search` — discover pages by query, returns results with
  optional full-page content
- `POST /scrape` — extract clean markdown from a single URL
- `POST /interact` — browser actions on live pages (clicks, forms,
  navigation) — *not currently exposed via FRIDAY tools*

#### Documentation and references

- **API reference:** https://docs.firecrawl.dev
- **Skills repo** (for agent integration patterns): https://github.com/firecrawl/skills

## Quick recipes

```python
# 1. Search the web (uses cascade — Tavily → Firecrawl → DDGS)
result = await search_web("anthropic claude opus 4", num_results=5)
# result.metadata["provider"] tells you which one answered

# 2. Scrape a single URL into clean markdown
page = await fetch_page("https://example.com/article")
# page.metadata["provider"] == "firecrawl" when Firecrawl handled it

# 3. Search + inline scrape (advanced, costs more credits)
from friday.tools.firecrawl_client import search
payload = await search("react hooks 2026", limit=3, with_content=True)
# each payload["results"][i]["content"] now contains full markdown
```
