---
name: web-research
description: How to research URLs, web pages, and topics properly. Fetch first, summarize, give opinion.
agents: [research_agent, job_agent, deep_research_agent]
---

# Web Research

When Travis sends a URL or asks you to research something, follow this flow:

## URL Research Flow

1. **Fetch the page** using `search_web` or `fetch_page`
2. If fetch returns "JavaScript required" or empty content → use `browser_navigate` to render it
3. **Read the full content** — don't skim
4. **Summarize** what you found — key points, not a wall of text
5. **Give your opinion** if asked ("what do you think")
6. **Connect to Travis's context** — how does this relate to his projects, skills, goals?

## Search Flow

1. Search with specific queries, not generic ones
2. If first search is weak, refine and search again — don't give up after one try
3. Cross-reference multiple sources when possible
4. Always cite where information came from

## "Fetch and tell me what you think" Pattern

This means: read the page → summarize → give an honest assessment. Do NOT:
- Create a monitor for the URL
- Apply to a job
- Take a screenshot
- Ask "should I analyze it?"

Just read it, summarize it, say what you think.

## Job Posting URLs

When the URL is a job posting (jobs.ashbyhq.com, lever.co, greenhouse.io, careers pages):
1. Fetch and read the full posting
2. Summarize: role, company, requirements, salary, location
3. If Travis asks "what do you think" → assess fit based on his projects and skills in memory
4. If Travis asks to apply → THEN switch to CV tailoring mode
5. Don't auto-apply unless explicitly asked

## Failed Fetches

If a page won't load (JS-heavy SPA, blocked, timeout):
- Tell Travis it needs JavaScript rendering
- Offer to open it in the browser tools instead
- Don't return empty results and pretend you analyzed something
