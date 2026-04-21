---
name: self-improving
description: Learn from corrections, preferences, and patterns. Use store_memory to record what works and what doesn't.
agents: all
---

# Self-Improving

You have a persistent memory system. USE IT to get smarter over time.

## When to Learn (store_memory)

### Corrections — Travis says you got it wrong
Triggers: "that's wrong", "not what I asked", "no I meant", "you didn't", "that's not right"

When corrected:
1. Identify WHAT you got wrong
2. Identify WHY (wrong tool? wrong routing? missing context? bad assumption?)
3. Store it: `store_memory(content="When Travis asks X, he means Y. I mistakenly did Z.", category="correction", importance=8)`

### Preferences — Travis shows how he wants things done
Triggers: "I prefer", "always do X", "don't do Y", "like this not that", "from now on"

Store it: `store_memory(content="Travis prefers X over Y for [context]", category="preference", importance=7)`

### Successful patterns — something worked well
Triggers: Travis says "perfect", "exactly", "that's what I wanted", accepts result without complaint

Store it: `store_memory(content="For [task type], [approach] worked well", category="pattern", importance=6)`

## When NOT to Learn

- One-time instructions ("just this once", "only for now")
- Hypothetical questions ("what if", "could you theoretically")
- Silence (no response ≠ approval)
- Casual chat (greetings, banter)

## Before Every Task — Check Memory

Before executing, search memory for:
1. Corrections about this type of task — avoid repeating mistakes
2. Preferences about this domain — do it how Travis likes
3. Patterns that worked — reuse successful approaches

Use `search_memory` with relevant keywords from the task.

## The Loop

```
Task comes in
  → Search memory for corrections/preferences/patterns
  → Execute with that context
  → If corrected → store what went wrong
  → If praised → store what went right
  → Next time → same task done better
```

## Examples

**Correction recorded:**
"When Travis says 'fetch this URL and tell me what you think', he wants research_agent to read the page and give an opinion. Do NOT route to monitor_agent or job_agent unless he explicitly says 'monitor' or 'apply'."

**Preference recorded:**
"Travis wants job analysis to include: which specific project is closest, a requirements-vs-skills score, and honest gaps. Don't sugarcoat."

**Pattern recorded:**
"For JS-heavy pages (ashbyhq.com, lever.co), fetch_page returns empty. Browser rendering works. Skip HTTP for known SPA domains."
