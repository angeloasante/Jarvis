---
name: browser-use
description: Advanced browser automation patterns. Connect to existing Chrome, handle SPAs, manage sessions, extract data efficiently.
agents: [system_agent, job_agent, research_agent]
---

# Browser Use — Advanced Patterns

FRIDAY has browser tools (Playwright). Use them smartly.

## When to Use Browser vs HTTP Fetch

| Situation | Tool |
|-----------|------|
| Simple page, static content | `fetch_page` (HTTP, fast) |
| JS-heavy SPA (React, Next.js) | `browser_navigate` (renders JS) |
| Need to log in | `browser_navigate` + `browser_wait_for_login` |
| Fill a form | `browser_navigate` → `browser_snapshot` → `browser_fill` |
| Page behind Cloudflare/captcha | `browser_navigate` with user's Chrome profile |
| YouTube, Twitter, LinkedIn | `browser_navigate` (need JS + auth) |

## fetch_page Auto-Fallback

`fetch_page` now auto-detects JS-only pages and falls back to browser rendering.
You don't need to manually decide — just call `fetch_page(url)` and it handles it.

Known SPA domains that always need browser: ashbyhq.com, lever.co, greenhouse.io, workday.com

## The Snapshot → Act → Verify Pattern

For any multi-step browser interaction:

1. `browser_navigate(url)` — go to the page
2. `browser_snapshot()` — get all elements with @refs
3. Act: `browser_click(@e5)` or `browser_fill(@e3, "text")`
4. `browser_snapshot(diff=True)` — see what changed
5. Repeat 3-4 until done

NEVER guess element selectors. ALWAYS snapshot first to get @refs.

## Form Filling Best Practices

1. `browser_navigate(url)` — load the page
2. `browser_snapshot()` — discover all form fields
3. Fill ALL fields in ONE call: `browser_fill_form({"@e3": "value", "@e5": "value"})`
4. `browser_snapshot()` — verify fields are filled
5. Only click Submit if Travis explicitly asked to submit

## Handling Login Pages

If `browser_navigate` returns `login_required: true`:
1. Tell Travis: "This page needs login. I'll wait while you log in."
2. Call `browser_wait_for_login(timeout=120)`
3. Once logged in, the session persists for future visits

## Session Persistence

The browser uses a persistent profile at `~/.friday/browser_data/`.
Cookies and sessions survive across FRIDAY restarts. If Travis logged into
LinkedIn once, he doesn't need to again.

## Performance Tips

- First browser call: ~3s (launches Chromium)
- Every call after: ~100-200ms (persistent daemon)
- Don't call `browser_close()` between pages — let it stay open
- Only close when explicitly done or on `/quit`

## What NOT to Do

- Don't use browser for simple HTTP fetches (waste of resources)
- Don't click "Apply" or "Submit" buttons without explicit user permission
- Don't fill payment forms or enter credit card info
- Don't navigate to sites the user didn't ask about
- Don't leave the browser open on sensitive pages (banking, email)
