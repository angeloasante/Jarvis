---
name: job-analysis
description: How to analyze job postings, assess fit, compare to Travis's projects, and score.
agents: [job_agent, research_agent]
---

# Job Analysis

When Travis asks about a job posting or career opportunity, follow this reasoning chain:

## Step 1: Get the Job Details

- If URL provided → fetch the page, extract requirements
- If on screen → read screen, extract requirements
- List: role title, company, location, salary, key requirements, tech stack, nice-to-haves

## Step 2: Check Memory for Travis's Projects

Search memory for Travis's projects. Key projects to know:

- **FRIDAY / JARVIS** — Personal AI OS (Python, multi-agent, voice, gesture, TV control, browser automation)
- **MineWatch Ghana** — Satellite-based illegal mining detection (TensorFlow CNNs, Sentinel-2, geospatial, Google Earth Engine)
- **Diaspora AI** — Travel platform for African diaspora (voice AI backend, open-source visa data, SaaS)
- **Ama Twi AI** — Bilingual Twi-English AI agent (fine-tuned Llama 3.1 8B, NLP)
- **Reckall** — Shazam for Movies (AI video identification)
- **Kluxta** — AI video editor
- **SendComms** — Unified Communication API for Africa

GitHub: https://github.com/angeloasante

## Step 3: Score Fit

For each requirement in the job posting, check if Travis has:
- **Direct experience** (built something that matches) → Strong match
- **Transferable skills** (used similar tech in a different domain) → Good match
- **Gap** (no relevant experience) → Flag it, suggest what he could do

## Step 4: Identify the Closest Project

Pick the ONE project that's the strongest match for this specific role. Explain WHY:
- Which requirements does it cover?
- What tech stack overlap exists?
- What domain knowledge transfers?

## Step 5: Give a Verdict

- **Strong fit** — multiple projects align, core requirements met
- **Good fit** — some alignment, gaps are learnable
- **Stretch** — significant gaps, but some transferable skills
- **Not a fit** — core requirements don't match

## CRITICAL: Read vs Apply — Know the Difference

**"fetch", "assess", "what do you think", "score me", "is it a good fit"**
→ READ the posting and ANALYZE. Do NOT open application forms, tailor CVs, or fill anything.

**"apply", "go ahead", "submit", "fill the form", "tailor my CV"**
→ THEN and ONLY THEN start the application process.

If the user says "fetch this and assess me" — that means READ + ANALYZE. The word "assess" means give an opinion, not start applying. Never touch the Apply button unless explicitly told to apply.

## What NOT to Do

- Don't auto-apply unless Travis explicitly says "apply" or "go ahead"
- Don't tailor the CV unless Travis says "tailor" or "go ahead"
- Don't click Apply buttons during analysis — only during actual application
- Don't say "should I proceed?" — give the full analysis in one shot
- Don't make up skills Travis doesn't have — be honest about gaps
