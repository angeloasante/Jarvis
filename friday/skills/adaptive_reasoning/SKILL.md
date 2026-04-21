---
name: adaptive-reasoning
description: Assess task complexity before responding. Simple tasks get fast answers. Complex tasks get deep analysis.
agents: all
---

# Adaptive Reasoning

Before responding, quickly assess how complex this task is.

## Complexity Score (0-10)

| Signal | Points |
|--------|--------|
| Multi-step logic (planning, debugging chains) | +3 |
| Ambiguity ("it depends", trade-offs) | +2 |
| Needs multiple tool calls | +2 |
| Math or formal reasoning | +2 |
| Novel problem, no clear pattern | +1 |
| High stakes (sending money, applying to job) | +1 |

**Subtract:**
| Signal | Points |
|--------|--------|
| Routine task (check email, read messages) | -2 |
| Clear single answer | -2 |
| Simple lookup/fetch | -3 |

## Response Strategy

| Score | How to Respond |
|-------|----------------|
| 0-2 | **Fast.** One sentence. No filler. |
| 3-5 | **Standard.** Brief explanation + action. |
| 6-7 | **Thorough.** Think through steps, explain reasoning. |
| 8-10 | **Deep.** Full analysis, consider alternatives, structured output. |

## Applied Examples

**Score 1:** "what time is it" → Answer immediately. Don't search the web.
**Score 2:** "mute the tv" → Execute tool. Say "Muted." Done.
**Score 3:** "check my email" → Fetch emails, brief summary.
**Score 5:** "what do you think of this job posting" → Read it, compare to skills, give verdict.
**Score 7:** "which of my projects is closest to this job" → Check memory, fetch GitHub, compare requirements, score each project, give ranking.
**Score 9:** "design a system architecture for X" → Deep analysis, consider trade-offs, structured recommendation.

## Key Rule

Match effort to complexity. Don't write 3 paragraphs for "mute the tv". Don't give one sentence for "analyze this job posting against my skills".
