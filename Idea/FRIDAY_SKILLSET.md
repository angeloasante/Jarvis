# FRIDAY Agent Skillset System
### *"An agent without a skill is a developer without documentation. It will work until it doesn't."*

---

## Table of Contents

1. [What Is A Skill](#what-is-a-skill)
2. [Why Skills Exist](#why-skills-exist)
3. [Skill Anatomy](#skill-anatomy)
4. [How To Create A Skill](#how-to-create-a-skill)
5. [Error Handling Standards](#error-handling-standards)
6. [Agent Skills — Full Library](#agent-skills--full-library)
7. [Skill Versioning](#skill-versioning)
8. [Skill Testing](#skill-testing)
9. [Skill Inheritance](#skill-inheritance)
10. [Anti-Patterns](#anti-patterns)

---

## What Is A Skill

A **skill** is a structured knowledge document that an agent reads before executing a category of tasks. It is not code. It is not a prompt. It is the condensed result of every failure, edge case, and hard-learned lesson in a specific domain — written so that an agent never has to learn the same lesson twice.

Think of it as the difference between:

**Without skill:**
```
Agent: "I'll write a Supabase query"
→ Writes query without LIMIT clause
→ Returns 50,000 rows
→ Crashes the API
→ Travis wakes up to a 3am incident
```

**With skill:**
```
Agent: reads supabase.skill.md
→ Sees: "ALWAYS add LIMIT. Free tier returns unbounded results."
→ Writes query with LIMIT 100
→ Works first time
→ Travis sleeps
```

Skills make agents **senior by default.**

---

## Why Skills Exist

### The Core Problem

LLMs have general knowledge. They do not have *your specific* knowledge. They know what Supabase is. They do not know:

- That your free tier pauses after 7 days of inactivity
- That your Paystack webhook has a known race condition
- That Demucs crashes on audio files over 4 minutes in Kluxta
- That you always use Railway for backends and Vercel for frontends
- That your Qwen model uses a specific chat template that breaks if wrong

Without skills, every agent starts from zero knowledge of your stack. With skills, every agent starts from senior knowledge of your stack.

### The Second Problem

Even with a great fine-tune, FRIDAY cannot bake in dynamic knowledge — things that change. New API rate limits. Updated library breaking changes. Infrastructure changes. Skills are **living documents** that update as the stack evolves. The model weights don't need to change. The skill does.

### The Third Problem

Agents fail silently without guidance. An agent that hits a 429 rate limit without a skill telling it what to do will either crash, retry infinitely, or return a confusing error. A skill tells it exactly what to do: wait 60 seconds, retry with exponential backoff, notify Travis if it fails 3 times.

---

## Skill Anatomy

Every skill file follows this exact structure. No exceptions.

```markdown
# [SKILL_NAME] Skill
**Version:** X.Y.Z
**Last Updated:** YYYY-MM-DD
**Applies To:** [list of agents that use this skill]
**Trigger:** [what situation causes an agent to load this skill]

---

## TL;DR
[3 sentences max. The single most important thing to know.
An agent in a hurry reads only this.]

---

## Context
[Why this skill exists. What problem it solves.
What went wrong before it existed.]

---

## Prerequisites
[What must be true before attempting this task.
Environment variables, dependencies, running services, permissions.]

---

## Core Knowledge
[The actual knowledge. Patterns, gotchas, best practices.
Specific to Travis's stack. Not generic.]

---

## Step-By-Step
[When there is a clear procedure, write it step by step.
Numbered. Specific. No ambiguity.]

---

## Error Handling
[Every known error. Exact error message or code.
What it means. What to do. When to escalate to Travis.]

---

## Edge Cases
[Known unusual situations and how to handle them.]

---

## Do Not
[Explicit anti-patterns. Things that seem right but are wrong.
Written because someone (or an agent) already did them wrong.]

---

## Examples
[Concrete code or command examples for the most common scenarios.]

---

## Escalation
[When to stop trying and surface the problem to Travis.
Clear thresholds.]

---

## Changelog
[What changed and when. So Travis knows if a skill is stale.]
```

---

## How To Create A Skill

### Step 1 — Identify The Knowledge Gap

A skill should be created when any of these are true:

- An agent failed at something and the failure was preventable
- You find yourself explaining the same thing to FRIDAY repeatedly
- A task has specific, non-obvious requirements in your stack
- A service has quirks that aren't in public documentation
- There's a hard-learned lesson that should never be relearned

### Step 2 — Scope It Correctly

One skill = one domain. Do not create a "general coding skill." Create:
- `supabase.skill.md` — Supabase-specific knowledge
- `paystack.skill.md` — Paystack-specific knowledge
- `modal.skill.md` — Modal deployment knowledge

Wide skills become useless because agents load context they don't need. Narrow skills are loaded precisely when needed.

### Step 3 — Write The TL;DR First

If you cannot summarise the skill in 3 sentences, you don't understand it well enough yet. Write the TL;DR first. It forces clarity.

### Step 4 — Write From Failure, Not Theory

Every line in a skill should answer: "what would cause an agent to get this wrong without this information?" Generic best practices belong in documentation. Skills contain the specific, hard-won, this-exact-stack knowledge.

### Step 5 — Test It

Give the skill to FRIDAY without any other context. Ask her to do the task the skill covers. If she still fails, the skill is incomplete. Iterate.

### Step 6 — Version It

Every change to a skill gets a version bump. Patch (0.0.X) for corrections. Minor (0.X.0) for new sections. Major (X.0.0) for complete rewrites.

---

## Error Handling Standards

Every skill must follow these error handling standards. This is not optional.

### Error Response Structure

Every tool that can fail must return a structured error:

```python
from dataclasses import dataclass
from typing import Any, Optional
from enum import Enum

class ErrorSeverity(Enum):
    LOW = "low"           # Can retry, not urgent
    MEDIUM = "medium"     # Needs attention soon
    HIGH = "high"         # Needs attention now
    CRITICAL = "critical" # Revenue/data at risk, interrupt Travis immediately

@dataclass
class SkillError:
    code: str                    # Machine-readable error code
    message: str                 # Human-readable description
    severity: ErrorSeverity      # How bad is this?
    recoverable: bool            # Can the agent retry?
    retry_after: Optional[int]   # Seconds to wait before retry
    action: str                  # What the agent should do
    escalate: bool               # Should Travis be notified?
    context: dict                # Any relevant context for debugging

@dataclass
class SkillResult:
    success: bool
    data: Optional[Any]
    error: Optional[SkillError]
```

### Retry Policy

```python
RETRY_POLICY = {
    # Rate limits — always retry with backoff
    "rate_limit": {
        "max_retries": 3,
        "backoff": "exponential",
        "base_delay": 60,  # seconds
        "notify_after": 2  # notify Travis after 2 failed retries
    },
    
    # Network errors — retry quickly
    "network_error": {
        "max_retries": 3,
        "backoff": "linear",
        "base_delay": 5,
        "notify_after": 3
    },
    
    # Auth errors — do not retry, escalate immediately
    "auth_error": {
        "max_retries": 0,
        "backoff": None,
        "notify_after": 0  # Immediately
    },
    
    # Timeout — retry once with longer timeout
    "timeout": {
        "max_retries": 1,
        "backoff": "none",
        "base_delay": 0,
        "timeout_multiplier": 2,
        "notify_after": 1
    },
    
    # Data errors — do not retry, report exact error
    "data_error": {
        "max_retries": 0,
        "backoff": None,
        "notify_after": 0
    }
}
```

### Escalation Thresholds

```python
ESCALATION_RULES = {
    # Always interrupt Travis immediately
    "immediate": [
        "payment_processing_failure",
        "database_corruption",
        "auth_token_expired_production",
        "deployment_health_check_failed",
        "revenue_drop_over_20_percent",
        "data_loss_risk"
    ],
    
    # Surface in next interaction
    "next_interaction": [
        "test_suite_failing",
        "build_warning",
        "api_rate_limit_approaching",
        "disk_space_low",
        "cost_spike_detected"
    ],
    
    # Include in daily digest
    "daily_digest": [
        "minor_warnings",
        "non_critical_deprecation_notices",
        "performance_degradation_minor"
    ],
    
    # Log but do not surface
    "log_only": [
        "successful_retries",
        "cache_misses",
        "minor_latency_variations"
    ]
}
```

---

## Agent Skills — Full Library

---

### FRIDAY CORE SKILLS

---

#### `routing.skill.md`

**Applies To:** FRIDAY Core
**Trigger:** Every single request

```markdown
# Routing Skill
**Version:** 1.0.0

## TL;DR
Route by intent, not by keywords. Simple tasks use thinking OFF.
Complex or strategic tasks use thinking ON. Revenue-critical tasks
drop everything else and go first. When ambiguous, ask one question.

## Routing Decision Tree

IF task involves payment failures or production outages:
  → severity = CRITICAL
  → thinking = OFF (speed over deliberation)
  → drop current task, handle immediately, notify Travis

IF task is ambiguous (missing project name, pronouns without
antecedents like "fix it", "send that"):
  → ask ONE clarifying question
  → do not guess and proceed
  → do not ask multiple questions at once

IF task involves strategic decisions (should I / is it worth /
which option / career choices):
  → thinking = ON
  → load memory context first
  → reason before responding

IF task is simple and clear (open file, check emails, what time is X):
  → thinking = OFF
  → dispatch immediately

## Parallel Dispatch Rules
Dispatch agents in parallel when:
- Subtasks do not depend on each other's output
- Morning briefings (always parallel)
- Status checks (always parallel)

Dispatch agents sequentially when:
- Agent B needs Agent A's output
- A failure in step 1 should stop step 2

## Ambiguity Examples

AMBIGUOUS — ask before routing:
- "Fix the bug" → which project? which bug?
- "Send the update" → to whom? which update?
- "Check if it's working" → what is "it"?

CLEAR — route immediately:
- "Fix the null reference in kluxta/audio_pipeline.ts"
- "Send the freelancer brief to the designer"
- "Check if Diaspora AI API is returning 200s"

## Escalation
If routing produces no clear agent match after reasoning:
→ FRIDAY Core handles directly with full tool access
→ Store the miss as a routing gap for future skill update
```

---

#### `memory_preload.skill.md`

**Applies To:** FRIDAY Core
**Trigger:** Every request involving Travis's projects

```markdown
# Memory Preload Skill
**Version:** 1.0.0

## TL;DR
Always preload memory before responding to anything project-related.
A FRIDAY that doesn't remember is just a chatbot. Pull context first,
respond second. Never ask Travis something his previous sessions
already told you.

## What To Always Preload

For any mention of a specific project:
→ get_project_context(project_name)
→ get_memory(query=f"{project_name} recent issues")
→ get_memory(query=f"{project_name} last session")

For any mention of a person (recruiter, investor, freelancer):
→ get_memory(query=person_name)

For strategic questions:
→ get_memory(query=topic)
→ get_memory(query="Travis preference on " + topic)

## Memory Miss Handling
If memory returns empty for a project Travis clearly knows:
→ Do NOT say "I don't have information about this"
→ DO say "I don't have recent context on this — what's the current state?"
→ Store whatever Travis tells you immediately

## Context Injection Pattern
```python
async def preload_context(user_input: str) -> str:
    projects = extract_project_mentions(user_input)
    memory_context = []
    
    for project in projects:
        ctx = await memory_agent.get_project_context(project)
        if ctx:
            memory_context.append(ctx)
    
    general = await memory_agent.query(user_input, limit=3)
    memory_context.extend(general)
    
    return format_context_for_prompt(memory_context)
```
```

---

### CODE CLUSTER SKILLS

---

#### `python.skill.md`

**Applies To:** Code Agent, Debug Agent, Test Agent, Terminal Agent
**Trigger:** Any Python file operation or execution

```markdown
# Python Skill
**Version:** 1.2.0

## TL;DR
Always use the project's virtual environment. Use uv, not pip.
Async first. Type hints everywhere. Ruff for linting.
If there's no venv, create one before touching anything.

## Environment Setup
```bash
# Check for existing venv
ls .venv || uv venv

# Always activate before running
source .venv/bin/activate

# Install with uv, not pip
uv add package_name

# Run scripts in venv context
uv run python script.py
```

## Code Standards
- Python 3.11+ minimum
- Type hints on all function signatures
- Async/await for all I/O operations
- Dataclasses or Pydantic for data structures, not raw dicts
- f-strings only, no .format() or %
- pathlib.Path for all file paths, not os.path

## Async Patterns
```python
# CORRECT: parallel async calls
results = await asyncio.gather(
    search_web(query1),
    read_emails(filter="unread"),
    get_calendar(date="today")
)

# WRONG: sequential when parallel is possible
r1 = await search_web(query1)
r2 = await read_emails(filter="unread")
r3 = await get_calendar(date="today")
```

## Error Handling Pattern
```python
async def tool_call_with_handling(func, *args, **kwargs):
    try:
        result = await func(*args, **kwargs)
        return SkillResult(success=True, data=result, error=None)
    except httpx.RateLimitError:
        return SkillResult(
            success=False,
            data=None,
            error=SkillError(
                code="rate_limit",
                message="Rate limit hit",
                severity=ErrorSeverity.MEDIUM,
                recoverable=True,
                retry_after=60,
                action="Wait 60s and retry",
                escalate=False,
                context={"function": func.__name__}
            )
        )
    except Exception as e:
        return SkillResult(
            success=False,
            data=None,
            error=SkillError(
                code="unexpected_error",
                message=str(e),
                severity=ErrorSeverity.HIGH,
                recoverable=False,
                retry_after=None,
                action="Log and escalate",
                escalate=True,
                context={"function": func.__name__, "args": str(args)}
            )
        )
```

## Common Errors
| Error | Cause | Fix |
|---|---|---|
| ModuleNotFoundError | Wrong venv active | source .venv/bin/activate |
| RecursionError | Circular imports | Check __init__.py files |
| RuntimeError: no running event loop | sync calling async | Use asyncio.run() |
| PicklingError in multiprocessing | Lambda in pool | Use named function |

## Do Not
- Never use sys.exit() in agent code — raise exceptions instead
- Never use mutable default arguments (def f(x=[]) is a bug)
- Never use bare except: — always catch specific exceptions
- Never hardcode paths — use pathlib and config
- Never print() for logging — use the logging module
- Never import * from anything
```

---

#### `typescript.skill.md`

**Applies To:** Code Agent, Debug Agent, Test Agent
**Trigger:** Any TypeScript/Next.js file operation

```markdown
# TypeScript / Next.js Skill
**Version:** 1.1.0

## TL;DR
Travis's frontends are Next.js 14+ App Router. Never use Pages Router
patterns. Supabase for data. Tailwind for styling.
Strict TypeScript — no any, no type assertions without justification.

## Project Structure Pattern
```
app/
  (auth)/login/page.tsx
  (dashboard)/layout.tsx
  api/webhooks/paystack/route.ts
components/
  ui/           ← shadcn components
  [feature]/    ← feature-specific
lib/
  supabase/
    client.ts   ← browser client
    server.ts   ← server client
types/
  database.ts   ← generated Supabase types
```

## API Route Pattern (App Router)
```typescript
import { NextRequest, NextResponse } from 'next/server'

export async function POST(request: NextRequest) {
  try {
    const signature = request.headers.get('x-paystack-signature')
    if (!signature) {
      return NextResponse.json({ error: 'No signature' }, { status: 401 })
    }
    
    const body = await request.text() // text() not json() for sig verification
    const isValid = verifyPaystackSignature(body, signature)
    
    if (!isValid) {
      return NextResponse.json({ error: 'Invalid signature' }, { status: 401 })
    }
    
    return NextResponse.json({ received: true })
  } catch (error) {
    console.error('[Webhook]', error)
    return NextResponse.json({ error: 'Internal error' }, { status: 500 })
  }
}
```

## Common Errors in Travis's Stack
| Error | Cause | Fix |
|---|---|---|
| Hydration mismatch | Server/client render difference | Check for window/document usage |
| Edge runtime error | Node API in edge runtime | Add runtime = 'nodejs' to route |
| Supabase RLS 403 | Missing Row Level Security policy | Check auth.uid() policies |
| Headers already sent | NextResponse called after await | Return immediately after response |

## Do Not
- Never use getServerSideProps or getStaticProps (App Router)
- Never put secrets in client components (they ship to browser)
- Never use router.push in Server Components (use redirect())
- Never fetch in loops — batch queries
- Never ignore Supabase error returns
```

---

#### `supabase.skill.md`

**Applies To:** Code Agent, Database Agent, Debug Agent, DevOps Agent
**Trigger:** Any Supabase operation

```markdown
# Supabase Skill
**Version:** 1.3.0

## TL;DR
Free tier pauses after 7 days of inactivity — check health before
querying in production. Always add LIMIT. Always check RLS policies
before assuming data visibility. Never skip error returns.

## Critical Facts
- Free tier pauses after 7 days — this has caused incidents before
- Always check .error before accessing .data
- RLS is enabled by default on all tables
- Service key bypasses RLS — never use in client-side code

## Query Patterns
```python
# CORRECT: Always handle errors, always limit
result = supabase.table('bookings') \
    .select('id, status, user_id') \
    .eq('status', 'pending') \
    .limit(100) \
    .execute()

if result.error:
    raise DatabaseError(result.error.message)

data = result.data

# WRONG: Unbounded query, no error check
data = supabase.table('bookings').select('*').execute().data
```

## Migration Rules
```sql
-- ALWAYS write both up and down migrations
-- up.sql
ALTER TABLE bookings ADD COLUMN payment_method TEXT DEFAULT 'card';

-- down.sql
ALTER TABLE bookings DROP COLUMN payment_method;
```

Never run migrations directly on production without Travis's confirmation.

## Common Errors
| Error | Message | Cause | Fix |
|---|---|---|---|
| Paused instance | connection refused | Free tier inactive 7+ days | Wake via dashboard |
| RLS violation | 403 Forbidden | Policy blocks operation | Use service key for admin ops |
| Max connections | too many connections | Pool exhausted | Use pgbouncer |
| Duplicate key | 23505 unique violation | Duplicate insert | Use upsert() with onConflict |

## Escalation
IMMEDIATE escalation if:
- Production database connection fails for > 2 minutes
- Any migration runs on production without Travis's confirmation
- Data appears missing after a query that should return results

## Do Not
- Never use the service key in client-side code
- Never run DROP TABLE without explicit Travis confirmation
- Never disable RLS without explicit Travis confirmation
- Never use .single() unless certain exactly 1 row exists
```

---

#### `paystack.skill.md`

**Applies To:** Code Agent, Debug Agent, API Agent, Finance Agent
**Trigger:** Any Paystack operation

```markdown
# Paystack Skill
**Version:** 2.0.0
**REVENUE CRITICAL — Read entirely before touching anything**

## TL;DR
Verify webhook signature before processing anything.
ALWAYS implement idempotency — Paystack retries failed webhooks.
Duplicate event handling is the #1 historical bug.
Any payment failure = immediate escalation, no silent retries.

## Critical Incident History
- Incident 1: Race condition on duplicate webhook events caused
  double-charging. Root cause: no idempotency check.
- Incident 2: 422 errors for 2 hours because PAYSTACK_WEBHOOK_SECRET
  was missing from Railway env vars.

## Webhook Verification (Non-Negotiable)
```python
import hmac
import hashlib

def verify_paystack_signature(payload: bytes, signature: str) -> bool:
    secret = os.environ.get('PAYSTACK_WEBHOOK_SECRET')
    if not secret:
        raise ConfigurationError(
            "PAYSTACK_WEBHOOK_SECRET not set. "
            "Check Railway environment variables immediately."
        )
    
    expected = hmac.new(
        secret.encode('utf-8'),
        payload,
        hashlib.sha512
    ).hexdigest()
    
    return hmac.compare_digest(expected, signature)
```

## Idempotency Pattern (Mandatory)
```python
async def handle_payment_webhook(event_id: str, event_data: dict):
    # Check if already processed
    existing = await db.get_processed_event(event_id)
    if existing:
        return {"status": "already_processed", "event_id": event_id}
    
    await process_payment(event_data)
    await db.mark_event_processed(event_id)
    
    return {"status": "processed", "event_id": event_id}
```

## Mobile Money (West Africa Async Pattern)
Mobile money payments are async. Never assume synchronous completion.
1. Return 200 immediately to Paystack
2. Set booking status to 'pending_payment'
3. Update to 'confirmed' only on charge.success webhook

## Common Errors
| Code | Meaning | Action |
|---|---|---|
| 401 | Invalid API key or wrong environment | Check key prefix (test vs live) |
| 402 | Insufficient funds | Notify user, do not retry |
| 422 | Signature verification failed | Check PAYSTACK_WEBHOOK_SECRET in Railway |
| 429 | Rate limit | Wait 60s, retry once, then escalate |

## Escalation
IMMEDIATELY notify Travis for:
- Any 401 in production (no payments processing)
- Any signature verification failure (potential security issue)
- 3+ consecutive webhook delivery failures
- charge.failed on bookings > £100
```

---

#### `stripe.skill.md`

**Applies To:** Code Agent, Debug Agent, API Agent, Finance Agent
**Trigger:** Any Stripe operation

```markdown
# Stripe Skill
**Version:** 1.1.0

## TL;DR
Stripe webhook signature verification is mandatory.
Use Stripe's idempotency keys on all charge requests.
Test with Stripe CLI locally before touching production.
card_error is user error — do not alert Travis.

## Webhook Verification
```python
import stripe

def verify_stripe_webhook(payload: bytes, signature: str) -> stripe.Event:
    webhook_secret = os.environ['STRIPE_WEBHOOK_SECRET']
    
    try:
        event = stripe.Webhook.construct_event(
            payload, signature, webhook_secret
        )
        return event
    except stripe.error.SignatureVerificationError:
        raise WebhookVerificationError("Invalid Stripe signature")
```

## Idempotency
```python
stripe.PaymentIntent.create(
    amount=10000,  # in pence/cents
    currency="gbp",
    idempotency_key=f"booking_{booking_id}_{timestamp}"
)
```

## Apple Pay Notes
Apple Pay works through Stripe Payment Request Button.
Test in Safari only — Chrome does not support Apple Pay.
Domain verification file must be at:
/.well-known/apple-developer-merchantid-domain-association

## Error Categories
```python
STRIPE_ERRORS = {
    "card_error": "user_error",       # Declined — notify user, not Travis
    "rate_limit_error": "retry",      # Wait and retry
    "invalid_request_error": "bug",   # Code problem — alert Travis
    "authentication_error": "urgent", # API key issue — alert Travis immediately
    "api_connection_error": "retry",  # Network — retry 3x then alert
}
```

## Test Cards
```
Success: 4242 4242 4242 4242
Decline: 4000 0000 0000 0002
Auth required: 4000 0025 0000 3155
```

## Do Not
- Never log full card numbers (PCI compliance)
- Never store raw card data in your database
- Never disable webhook signature verification for testing
```

---

#### `modal.skill.md`

**Applies To:** DevOps Agent, Code Agent, Ama Agent, Kluxta Agent
**Trigger:** Any Modal deployment or inference operation

```markdown
# Modal Skill
**Version:** 1.2.0

## TL;DR
Always quantise models before deploying — full precision OOMs.
Cold starts are real — build warmup into critical endpoints.
Jobs that don't terminate keep billing. Always set timeouts.
Check billing weekly — a runaway job will not notify you.

## Deployment Pattern
```python
import modal

app = modal.App("ama-inference")

@app.function(
    gpu="A10G",                    # Specify GPU explicitly, not "any"
    timeout=300,                   # Always set timeout
    memory=16384,
    retries=modal.Retries(
        max_retries=2,
        backoff_coef=2.0
    )
)
async def run_inference(prompt: str) -> str:
    ...
```

## Quantisation (Mandatory For 7B+ Models)
```python
# WRONG: Full precision — will OOM
model = AutoModelForCausalLM.from_pretrained("Qwen/Qwen2.5-9B")

# CORRECT: 4-bit quantisation
from transformers import BitsAndBytesConfig
quantization_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_compute_dtype=torch.float16
)
model = AutoModelForCausalLM.from_pretrained(
    "Qwen/Qwen2.5-9B",
    quantization_config=quantization_config
)
```

## Warmup Strategy
```python
# Revenue-critical endpoint (Diaspora AI)
@app.function(keep_warm=1, gpu="A10G", timeout=300)
async def diaspora_ai_inference(prompt: str) -> str: ...

# Non-critical (Ama, dev)
@app.function(keep_warm=0, gpu="A10G", timeout=300)
async def ama_inference(prompt: str) -> str: ...
```

## Cost Estimates
```
A100: ~$3.40/hr
A10G: ~$1.10/hr
T4:   ~$0.59/hr

Ama fine-tune (3 epochs, 900 examples): ~45 mins on A100 = ~$2.55
Kluxta render (10 min video): ~5 mins on A10G = ~$0.09
```

## Common Errors
| Error | Cause | Fix |
|---|---|---|
| SIGKILL OOM | Model too large for instance | Add 4-bit quantisation |
| Cold start > 60s | Model loading from scratch | Pre-load in container image |
| CUDA not available | Wrong function decorator | Add gpu= parameter |
| Import error | Package not in image | Add to modal.Image pip_install() |

## Escalation
IMMEDIATELY alert Travis if:
- Any job runs > 2x expected duration (billing runaway risk)
- Production inference endpoint errors for > 5 minutes
- Monthly Modal bill exceeds $50
```

---

#### `git.skill.md`

**Applies To:** Git Agent, Code Agent, DevOps Agent
**Trigger:** Any git operation

```markdown
# Git Skill
**Version:** 1.0.0

## TL;DR
Always check status before committing. Rebase, don't merge.
Conventional commits only. Never commit secrets.
Never force-push to main.

## Pre-Commit Checklist
```bash
git status
git diff --staged
grep -r "sk_live\|sk_test\|password\|secret" --include="*.ts" --include="*.py"
# If above returns anything — STOP and remove secrets first
```

## Commit Message Format
```
<type>(<scope>): <description>

Types: feat / fix / chore / docs / refactor / test / perf / ci

Good:
  feat(payments): add Paystack mobile money support
  fix(kluxta): null check on audioBuffer in demucs pipeline
  
Bad:
  fix: bug
  update stuff
  WIP
```

## Rebase Not Merge
```bash
# CORRECT: keeps history clean
git pull --rebase origin main

# WRONG: creates merge commit noise
git pull origin main
```

## Common Errors
| Error | Cause | Fix |
|---|---|---|
| rejected non-fast-forward | Remote has commits you don't | git pull --rebase then push |
| detached HEAD | Checked out a commit hash | git checkout main |
| merge conflict | Diverged branches | Resolve conflicts, git rebase --continue |

## Do Not
- Never git push --force on main
- Never commit .env files
- Never commit node_modules, .venv, model weights
- Never amend commits that have been pushed
```

---

### RESEARCH CLUSTER SKILLS

---

#### `web_research.skill.md`

**Applies To:** Web Research Agent, Competitor Agent, News Agent, Tech Radar Agent
**Trigger:** Any web search or information gathering task

```markdown
# Web Research Skill
**Version:** 1.0.0

## TL;DR
Short specific queries beat long ones. Fetch full pages — snippets lie.
Check publication dates. One good primary source beats five aggregators.
Flag anything that contradicts Travis's existing assumptions.

## Query Construction
```python
# GOOD queries (1-4 words, specific):
"Qwen3 fine-tuning 2025"
"Paystack mobile money Ghana"
"Agno multi-agent framework"

# BAD queries (too long, operators don't help):
"what are the best practices for fine-tuning the Qwen3 model..."
"site:arxiv.org Qwen fine-tuning"
```

## Source Quality Hierarchy
1. Official docs
2. GitHub repos and READMEs
3. ArXiv papers
4. Engineering blogs (Anthropic, HuggingFace, etc.)
5. Recent news articles (verify date)
6. Stack Overflow (check answer date, not question date)
7. Reddit/forums (real-world issues, not best practices)

## Date Checking Rule
For AI models: only trust content < 6 months old
For API docs: check "last updated" date
For pricing: always verify with current docs

## Contradiction Protocol
If research contradicts what Travis believes:
1. Surface the contradiction directly
2. Give the source and date
3. Give your assessment of reliability
4. Do NOT quietly adopt the new information without flagging

## Common Errors
| Scenario | Problem | Fix |
|---|---|---|
| No relevant results | Query too specific | Broaden, remove specifics |
| Conflicting information | Topic contested | Report both, note recency |
| Paywalled content | Can't access | Note paywall, summarise excerpt |
| All results are old | Fast-moving topic | Add current year to query |
```

---

### COMMS CLUSTER SKILLS

---

#### `gmail.skill.md`

**Applies To:** Email Agent, Email Triage Agent, Outreach Agent
**Trigger:** Any Gmail operation

```markdown
# Gmail Skill
**Version:** 1.0.0

## TL;DR
Always read before replying — never reply blind.
Triage by impact, not arrival time.
Payment-related emails are always highest priority.
Travis's style: direct, no fluff, professional but not stiff.

## Priority Tiers
```python
EMAIL_PRIORITY = {
    "CRITICAL": ["payment failure", "Paystack", "Stripe",
                 "production down", "legal notice"],
    "HIGH": ["Jack Breen", "investor", "YC",
             "freelancer deadline", "contract review"],
    "NORMAL": ["collaboration request", "product feedback"],
    "LOW": ["newsletter", "GitHub notification",
            "automated receipt", "cold outreach"]
}
```

## Travis's Email Voice
```
DO:     "Hi [name], I'm interested. Can we schedule a call Thursday?"
DO:     "Following up on my application from last week."
DO NOT: "I hope this email finds you well."
DO NOT: "Please don't hesitate to reach out if..."
DO NOT: "I wanted to circle back on..."
```

## Draft Before Send — Always For:
- Investor emails
- Recruiter emails about specific roles
- Anything with legal implications
- Cold outreach

Auto-send acceptable for:
- Calendar replies (accept/decline)
- Simple acknowledgments Travis explicitly pre-approved

## Common Errors
| Error | Cause | Fix |
|---|---|---|
| 429 Too Many Requests | Gmail API rate limit | Wait 60s, retry |
| 401 Unauthorized | Token expired | Re-authenticate via Google OAuth |
| Thread not updating | Wrong threadId | Re-fetch thread before replying |
```

---

#### `calendar.skill.md`

**Applies To:** Calendar Agent, Notification Agent
**Trigger:** Any Google Calendar operation

```markdown
# Google Calendar Skill
**Version:** 1.0.0

## TL;DR
Travis does deep work mornings or late nights. Never book calls
10pm-4am without asking. Always check conflicts before creating.
Add video links to all remote events.

## Schedule Preferences
```python
SCHEDULE_PREFERENCES = {
    "deep_work_windows": ["06:00-10:00", "21:00-02:00"],
    "call_preferred_windows": ["10:00-13:00", "14:00-17:00"],
    "avoid_for_calls": "10pm-4am",     # Coding hours
    "preferred_call_length": 30,        # minutes
    "buffer_before_important": 30       # minutes
}
```

## Event Creation — Always:
1. Check for conflicts first
2. Add video link for remote events
3. Add prep reminder 30 mins before important calls
4. Confirm if booking falls in coding hours

## Do Not
- Never delete an event without Travis's confirmation
- Never move a recurring event without asking (affects all instances)
- Never book calls during coding hours without explicit permission
```

---

### MEMORY CLUSTER SKILLS

---

#### `letta.skill.md`

**Applies To:** Memory Agent, Project Context Agent
**Trigger:** Any long-term memory operation

```markdown
# Letta Memory Skill
**Version:** 1.0.0

## TL;DR
Letta manages its own memory tiers automatically. Write specific,
tagged memories — vague memories return vague results.
Never ask Travis something memory already knows.

## Writing Good Memories
```python
# GOOD: specific, tagged, actionable
await letta.archival_memory_insert(
    content="""
    Technical decision [Kluxta] [audio]:
    Demucs fails with OOM on audio > 4 minutes on A10G.
    Fix: chunk audio into 3-minute segments, concatenate stems after.
    Implemented: 2026-01-15. Verified on files up to 45 minutes.
    """,
    tags=["kluxta", "demucs", "audio", "modal", "fix"]
)

# BAD: vague, no context
await letta.archival_memory_insert(
    content="Fixed the audio bug in Kluxta"
)
```

## Query Patterns
```python
# Natural language queries work better than keywords
good_queries = [
    "What issues has Travis had with Demucs in Kluxta?",
    "What did Travis decide about collaborating with TwiChat professor?",
]

# Keyword-only misses context
bad_queries = ["Demucs", "TwiChat"]
```

## What To Always Store
- Technical decisions + rationale + alternatives rejected
- Bugs found, root cause, fix applied, file:line
- Travis's stated preferences
- Project status changes
- Incidents: what failed, when, how fixed, how to prevent

## What NOT To Store
- Raw search results (ephemeral)
- Sensitive credentials
- Anything Travis says to forget

## Do Not
- Never overwrite an existing memory — append with date prefix
- Never store verbatim API responses — store summaries
```

---

#### `screenpipe.skill.md`

**Applies To:** Screenpipe Agent, Memory Agent
**Trigger:** Any query about what Travis was doing/looking at

```markdown
# Screenpipe Skill
**Version:** 1.0.0

## TL;DR
Screenpipe captures everything locally — screen, audio, browser history.
Use it when Travis asks about past activity on his Mac.
All data stays local. Never send to external APIs. Non-negotiable.

## Query Types
```python
# Browser history
await screenpipe.query(
    query="arxiv catastrophic forgetting",
    content_type="browser_history",
    limit=10
)

# Screen content
await screenpipe.query(
    query="Kluxta audio pipeline error",
    content_type="screen",
    limit=5
)
```

## When To Use Screenpipe vs Memory
```
Screenpipe: "what was I looking at", "find that tab", today's activity
Memory (Letta): decisions, discussions, project state, older history
Both: uncertain which has the answer — try both in parallel
```

## Privacy Rules (Non-Negotiable)
- Never send Screenpipe data to external APIs
- Never include in prompts sent to cloud models
- Only use local Ollama model to process Screenpipe data
- Screenpipe data is for Travis only
```

---

### SYSTEM CLUSTER SKILLS

---

#### `terminal.skill.md`

**Applies To:** Terminal Agent, Code Agent, DevOps Agent
**Trigger:** Any shell command execution

```markdown
# Terminal Skill
**Version:** 1.1.0

## TL;DR
Show destructive commands before running. Always set timeouts.
Capture stderr, not just stdout. Use the project venv.
If a command runs > 5 minutes, surface it to Travis immediately.

## Safety Tiers

SAFE — run without confirmation:
```bash
ls, cat, grep, find, git status, git log, git diff
npm run dev, npm run build, npm test
```

CONFIRM FIRST — show command, wait for go-ahead:
```bash
rm -rf anything
DROP TABLE, DROP DATABASE
git push --force
modal deploy, vercel deploy
kill -9
```

NEVER RUN — refuse and explain:
```bash
sudo rm -rf /
format, fdisk
curl ... | sudo bash  (except verified sources)
```

## Timeout Policy
```python
TIMEOUTS = {
    "quick_command": 30,
    "build": 300,
    "test_suite": 600,
    "modal_deploy": 120,
    "fine_tune": None,  # No timeout but monitor and report
    "default": 60
}
```

## Output Handling
Always capture and return both stdout AND stderr.
returncode != 0 means failure — always report this to the calling agent.

## Common Errors
| Error | Cause | Fix |
|---|---|---|
| command not found | Not in PATH or not installed | Check venv, check package |
| permission denied | Missing execute permission | chmod +x, or use python/node |
| port already in use | Dev server running | lsof -i :[port] then kill PID |
| out of memory | Process used too much RAM | Reduce batch size, add chunking |
```

---

#### `open_interpreter.skill.md`

**Applies To:** Mac Control Agent, Terminal Agent
**Trigger:** Natural language computer control requests

```markdown
# Open Interpreter Skill
**Version:** 1.0.0

## TL;DR
Open Interpreter executes code on Travis's actual machine.
Confirm before irreversible actions. Never run as sudo.
Screenshot to verify state before and after important actions.

## Safety Protocol
```python
REQUIRES_CONFIRMATION = [
    "delete", "remove", "rm", "overwrite",
    "send email", "post to", "submit",
    "deploy to production", "payment", "purchase",
    "git push", "git force"
]

async def execute_task(task: str):
    if any(word in task.lower() for word in REQUIRES_CONFIRMATION):
        confirmed = await ask_travis(
            f"About to: {task}\nThis cannot be easily undone. Confirm?"
        )
        if not confirmed:
            return "Cancelled."
    return await open_interpreter.run(task)
```

## Good Use Cases
- "Open Cursor with the Kluxta project"
- "Find all Python files modified in the last 24 hours"
- "Check how much disk space the models folder is using"

## Always Confirm Before:
- Deleting any files
- Closing applications or browser tabs
- Pushing to GitHub
- Any payment or purchase action

## Do Not
- Never run with sudo/admin
- Never use for payment transactions
- Never use to modify system files
```

---

#### `browser_use.skill.md`

**Applies To:** Browser Agent
**Trigger:** Web automation requiring real browser interaction

```markdown
# Browser Use Skill
**Version:** 1.0.0

## TL;DR
Screenshot first, act second. Never click blindly.
Confirm before form submissions with consequences.
Use web_fetch for static content — Browser Use for interactive pages.

## Decision: Browser Use vs web_fetch
```python
# Use Browser Use when:
browser_cases = [
    "fill out form", "log in to", "click button",
    "javascript-heavy", "single page app",
    "download file requiring interaction"
]

# Use web_fetch when:
fetch_cases = [
    "read content", "extract text",
    "get article", "static page"
]
```

## Standard Workflow
1. Navigate to URL
2. Screenshot — understand current page state
3. Plan actions based on actual state, not assumptions
4. Confirm before any form submission or destructive action
5. Final screenshot to verify result

## Common Failures
| Failure | Cause | Fix |
|---|---|---|
| Element not found | Dynamic content not loaded | Wait for element explicitly |
| Form won't submit | JavaScript validation | Check screenshot for error messages |
| Session expired | Logged out mid-task | Re-authenticate and retry |
| Captcha | Bot detection | Surface to Travis — cannot bypass |
```

---

### DOMAIN SKILLS

---

#### `diaspora_ai_platform.skill.md`

**Applies To:** Diaspora AI Agent, Analytics Agent, Product Agent
**Trigger:** Any question about Diaspora AI's platform or tech

```markdown
# Diaspora AI Platform Skill
**Version:** 1.4.0

## TL;DR
Diaspora AI is an OTA travel platform for diaspora communities.
Dual payment (Stripe + Paystack) is the core differentiator.
~85% payment coverage vs ~40% for cards-only competitors.
Travis built this solo in ~1 year. Live and generating revenue.

## Platform Stack
```
Frontend:  Next.js (Vercel)
Backend:   Next.js API Routes + Railway services
Database:  Supabase (PostgreSQL)
Payments:  Stripe (cards, Apple Pay) + Paystack (mobile money, USSD, EFT)
Messaging: WhatsApp Business API
Monitoring: VFS Global slot scraping
AI:        Itinerary planning (Claude API)
```

## The Payment Thesis
```python
COVERAGE = {
    "cards_only_competitors": 0.40,
    "diaspora_ai_dual_gateway": 0.85,
    
    "paystack_methods": [
        "Mpesa (Kenya, Tanzania)",
        "MTN Mobile Money (Ghana, Uganda)",
        "Airtel Money", "USSD transfers",
        "EFT (South Africa)", "Ghana Pay"
    ],
    "stripe_methods": [
        "Visa / Mastercard", "Apple Pay",
        "Google Pay", "UK bank transfers"
    ]
}
```

## Known Issues (Track These)
- VFS monitor: sending duplicate alerts (race condition in scheduler)
- Reckall analytics: no formal tracking set up
- Mobile money: async webhooks required (never assume synchronous)

## Metrics To Track Weekly
- Total bookings (volume)
- Payment success rate by method
- VFS alert accuracy
- API error rate on payment endpoints

## Escalation
IMMEDIATELY notify Travis if:
- Payment success rate drops below 90%
- Any payment integration stops accepting payments
- VFS monitor goes down
```

---

#### `ama_model.skill.md`

**Applies To:** Ama Agent, Code Agent during Ama development
**Trigger:** Anything about Ama training, inference, or dataset

```markdown
# Ama Model Skill
**Version:** 1.2.0

## TL;DR
Ama is Ghana's first bilingual Twi/English AI.
Base: Qwen3.5-9B. SINGLE mixed training run — never sequential.
Set correct Qwen chat template or everything breaks.
Lesson learned from Llama: sequential fine-tuning = catastrophic forgetting.

## The Catastrophic Forgetting Lesson
Previous failure on Llama 3.1 8B:
Step 1: Fine-tune on Twi → Step 2: Fine-tune on English
Result: Model forgot Twi. Classic catastrophic forgetting.

Fix: Single mixed run. 30% Bible translations + 70% conversational.
Both languages, one run. Never split. Ever.

## Training Configuration
```python
TRAINING_CONFIG = {
    "base_model": "Qwen/Qwen2.5-9B-Instruct",
    "method": "QLoRA",
    "lora_r": 16,
    "dataset_split": {
        "bible_translations": 0.30,
        "conversational": 0.70
    },
    "chat_template": "qwen",   # CRITICAL — set explicitly
    "epochs": 3,
    "learning_rate": 2e-4
}
```

## Chat Template — The Critical Step
```python
# WRONG: Default template — causes broken outputs
tokenizer = AutoTokenizer.from_pretrained(model_name)

# CORRECT: Explicitly set Qwen template
from unsloth.chat_templates import get_chat_template
tokenizer = get_chat_template(tokenizer, chat_template="qwen-2.5")
```

## Twi Language Edge Cases
```python
TWI_NOTES = {
    "code_switching": "Speakers mix Twi and English mid-sentence — normal",
    "tonal_text": "Written Twi doesn't always capture tones — be tolerant",
    "formal_vs_casual": "Bible Twi is formal — balance with casual examples",
    "ghanaian_english": "Distinct patterns — not errors, don't correct them"
}
```

## Collaboration Boundary (Hard Rule)
TwiChat professor collaboration, if it proceeds:
- Dataset layer only
- ZERO frontend access for professor
- Travis controls all model training and API endpoints
This boundary is non-negotiable. Do not agree to any arrangement
that gives frontend access to anyone outside Travis.

## Post-Deploy Checks
After every Modal deployment:
1. Run 3 Twi prompts — verify Twi responses
2. Run 3 English prompts — verify English responses
3. Run 1 code-switching prompt
4. Check response latency — alert if > 5s

## Escalation
Alert Travis if:
- Training loss not decreasing after epoch 1
- Post-deployment Twi responses are in English only (template issue)
- Eval perplexity on Twi is worse than English (dataset imbalance)
```

---

#### `unsloth_qlora.skill.md`

**Applies To:** Ama Agent, Code Agent during fine-tuning
**Trigger:** Any fine-tuning operation on RunPod or Modal

```markdown
# Unsloth QLoRA Fine-Tuning Skill
**Version:** 1.0.0

## TL;DR
Always use Unsloth — half the VRAM, same quality.
A100 40GB handles Qwen 9B comfortably with 4-bit.
Set chat template BEFORE tokenisation or outputs are garbage.
Monitor loss — not decreasing by epoch 2 means something is wrong.

## Full Training Pattern
```python
from unsloth import FastLanguageModel
from unsloth.chat_templates import get_chat_template
import torch

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="Qwen/Qwen2.5-9B-Instruct",
    max_seq_length=2048,
    load_in_4bit=True,
    dtype=torch.float16
)

model = FastLanguageModel.get_peft_model(
    model,
    r=16,
    target_modules=["q_proj", "v_proj", "k_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
    lora_alpha=32,
    lora_dropout=0.05,
    use_gradient_checkpointing="unsloth"
)

# CRITICAL: Set template before any tokenisation
tokenizer = get_chat_template(tokenizer, chat_template="qwen-2.5")
```

## Training Health Checks
```python
HEALTHY_LOSS = {
    "after_epoch_1": "< 1.5",
    "after_epoch_2": "< 1.0",
    "after_epoch_3": "< 0.8",
}

WARNING_SIGNS = [
    "Loss not decreasing after 100 steps",
    "Loss oscillating wildly (LR too high — reduce to 1e-4)",
    "Loss suddenly spikes (gradient explosion)",
    "VRAM OOM (reduce batch_size or max_seq_length)"
]
```

## Cost Estimates
```
RunPod A100 40GB: ~$2.49/hr

Ama full train (900 examples, 3 epochs): ~45 mins = ~$1.87
FRIDAY full train (900 examples, 3 epochs): ~45 mins = ~$1.87
```

## Common Errors
| Error | Cause | Fix |
|---|---|---|
| SIGKILL OOM | Full precision, batch too large | load_in_4bit=True, reduce batch_size |
| Loss = NaN | Gradient explosion | Reduce learning_rate to 1e-4 |
| Tokenizer error | Wrong chat template | Use get_chat_template() from Unsloth |
| Slow training | Not using Unsloth | Verify Unsloth installed, not vanilla transformers |
```

---

### MONITORING SKILLS

---

#### `alerting.skill.md`

**Applies To:** Notification Agent, Monitoring Agent
**Trigger:** Any alerting or notification task

```markdown
# Alerting Skill
**Version:** 1.0.0

## TL;DR
Alert on signal, not noise. Notification fatigue makes all alerts
useless. One important alert ignored is worse than ten unimportant
ones surfaced. Revenue-critical = always interrupt.

## Alert Severity Levels
```python
ALERT_LEVELS = {
    "INTERRUPT": {
        "triggers": [
            "Payment processing failure",
            "Production API 500s",
            "Database connection lost",
            "Deploy failed on main"
        ],
        "delivery": "Desktop notification + voice",
        "timing": "Any time, including coding hours"
    },
    "SURFACE_NEXT": {
        "triggers": [
            "Build warnings", "Test suite failing",
            "Recruiter email received",
            "Hackathon deadline in 48 hours",
            "Cost spike detected"
        ],
        "delivery": "Desktop notification",
        "timing": "Business hours or when active"
    },
    "DAILY_DIGEST": {
        "triggers": [
            "Deprecation notices",
            "Non-critical perf changes",
            "Successful background tasks"
        ],
        "delivery": "Batched morning report at 09:00"
    },
    "LOG_ONLY": {
        "triggers": [
            "Successful retries",
            "Cache operations",
            "Routine health checks passing"
        ],
        "delivery": "Log file only, never surface"
    }
}
```

## Deduplication — Prevent Alert Storms
```python
class AlertDeduplicator:
    def __init__(self):
        self.recent_alerts = {}
        self.cooldown_minutes = 30
    
    def should_alert(self, alert_code: str) -> bool:
        last = self.recent_alerts.get(alert_code)
        if not last:
            self.recent_alerts[alert_code] = datetime.now()
            return True
        
        elapsed = (datetime.now() - last).seconds / 60
        if elapsed >= self.cooldown_minutes:
            self.recent_alerts[alert_code] = datetime.now()
            return True
        
        return False  # Suppress duplicate
```

## Morning Briefing Format
```
FRIDAY Morning Briefing — [Date]

NEEDS YOUR ATTENTION (if any)
  - [Critical items only]

EMAILS
  - [n unread, x need response]
  - Key: [notable emails]

CALENDAR
  - [Today's events]

INFRASTRUCTURE
  - [Issues, or "All systems green"]

ON YOUR RADAR
  - [Relevant news/tech for Travis's projects]
```

## Do Not
- Never alert on the same issue twice within 30 minutes (deduplication)
- Never bundle revenue-critical alerts into digest
- Never suppress INTERRUPT level for any reason
```

---

## Skill Versioning

```
Version format: MAJOR.MINOR.PATCH

PATCH (1.0.X):
  Typo fixes, clarifications, adding examples

MINOR (1.X.0):
  New error cases, new edge cases, new do-not rules

MAJOR (X.0.0):
  Complete rewrite, fundamental change, previous version was wrong
```

## Skill Changelog Format
```markdown
## Changelog

### 1.2.0 — 2026-01-15
- Added: Demucs chunking pattern for files > 4 minutes
- Fixed: Incorrect timeout value (was 60s, should be 300s for builds)

### 1.1.0 — 2025-12-20
- Added: Cold start mitigation with keep_warm parameter

### 1.0.0 — 2025-12-01
- Initial version
```

---

## Skill Testing

Before any skill is considered complete, run these five tests:

### Test 1 — Ignorance Test
Remove the skill. Give the agent the same task. Did it fail or produce
something wrong? If yes — the skill is needed. If the agent succeeds
anyway — the skill may be unnecessary.

### Test 2 — Completeness Test
Give the agent 10 varied scenarios from the skill's domain.
The skill is complete when the agent handles all 10 correctly.
Fail 2 or more — skill is incomplete.

### Test 3 — TL;DR Test
Can a completely new agent read ONLY the TL;DR and not cause a
production incident? If no — the TL;DR needs work.

### Test 4 — Error Coverage Test
Deliberately trigger each error in the error table.
Verify the agent responds exactly as specified.

### Test 5 — Staleness Test (Run Monthly)
Review each skill monthly. Ask:
- Has anything in Travis's stack changed?
- Have any new errors been discovered?
- Is the version still accurate?

---

## Skill Inheritance

Agents inherit base skills then add specifics.

```python
# Base skills all code agents read
CODE_BASE_SKILLS = [
    "python.skill.md",
    "typescript.skill.md",
    "git.skill.md",
    "terminal.skill.md"
]

# Specialised agents inherit base + specific
CODE_AGENT_SKILLS = CODE_BASE_SKILLS + [
    "supabase.skill.md",
    "paystack.skill.md",
    "stripe.skill.md"
]

KLUXTA_AGENT_SKILLS = CODE_BASE_SKILLS + [
    "remotion.skill.md",    # Future
    "demucs.skill.md",      # Future
    "modal.skill.md",
    "ffmpeg.skill.md"        # Future
]

AMA_AGENT_SKILLS = CODE_BASE_SKILLS + [
    "unsloth_qlora.skill.md",
    "ama_model.skill.md",
    "modal.skill.md"
]

DEVOPS_AGENT_SKILLS = [
    "modal.skill.md",
    "git.skill.md",
    "terminal.skill.md",
    "supabase.skill.md"
]

COMMS_AGENT_SKILLS = [
    "gmail.skill.md",
    "calendar.skill.md"
]

MEMORY_AGENT_SKILLS = [
    "letta.skill.md",
    "screenpipe.skill.md"
]

DOMAIN_AGENT_SKILLS = {
    "diaspora_ai_agent": ["diaspora_ai_platform.skill.md", "paystack.skill.md"],
    "ama_agent": ["ama_model.skill.md", "unsloth_qlora.skill.md", "modal.skill.md"],
    "job_hunt_agent": ["gmail.skill.md"],
    "visa_intelligence_agent": ["diaspora_ai_platform.skill.md"],
}
```

---

## Anti-Patterns

These are the ways agents misuse the skill system. Know them.

### Anti-Pattern 1 — Skill Overload
Loading every skill for every task. A calendar agent processing an
event does not need the Paystack skill. Overloading context wastes
tokens and dilutes relevance.

**Fix:** Skills are loaded on-demand, triggered by task type.

### Anti-Pattern 2 — Generic Skills
Writing a skill called "coding best practices" with 50 generic rules
no one reads. Generic skills get ignored.

**Fix:** One skill per specific domain. Narrow and precise.

### Anti-Pattern 3 — Stale Skills
A skill that documents how things worked 6 months ago but hasn't
been updated. Stale skills are worse than no skills — they mislead.

**Fix:** Version and date every skill. Monthly staleness review.

### Anti-Pattern 4 — Skill As Documentation
Writing skills that describe what a tool does rather than how to use
it correctly in Travis's specific stack.

**Fix:** Every line in a skill answers: "what would an agent get wrong
without this specific information?"

### Anti-Pattern 5 — No Error Coverage
Skills that only cover the happy path. The error handling section
is where the real value lives — it prevents 3am incidents.

**Fix:** Error table is mandatory in every skill. No exceptions.

### Anti-Pattern 6 — Missing Escalation
Skills that handle errors silently without telling Travis. An agent
that quietly retries a failed payment 10 times is dangerous.

**Fix:** Every skill has explicit escalation thresholds.
Revenue-critical always surfaces immediately. Always.

---

## Skill Directory

```
friday/skills/
  ├── core/
  │   ├── routing.skill.md
  │   └── memory_preload.skill.md
  │
  ├── code/
  │   ├── python.skill.md
  │   ├── typescript.skill.md
  │   ├── supabase.skill.md
  │   ├── paystack.skill.md
  │   ├── stripe.skill.md
  │   ├── git.skill.md
  │   ├── terminal.skill.md
  │   └── modal.skill.md
  │
  ├── research/
  │   ├── web_research.skill.md
  │   └── arxiv.skill.md
  │
  ├── comms/
  │   ├── gmail.skill.md
  │   └── calendar.skill.md
  │
  ├── memory/
  │   ├── letta.skill.md
  │   └── screenpipe.skill.md
  │
  ├── system/
  │   ├── terminal.skill.md
  │   ├── open_interpreter.skill.md
  │   └── browser_use.skill.md
  │
  ├── domain/
  │   ├── diaspora_ai_platform.skill.md
  │   ├── ama_model.skill.md
  │   └── unsloth_qlora.skill.md
  │
  └── monitoring/
      └── alerting.skill.md

# Skills to write as stack grows:
  ├── code/
  │   ├── remotion.skill.md
  │   ├── demucs.skill.md
  │   ├── ffmpeg.skill.md
  │   └── runpod.skill.md
  ├── domain/
  │   ├── visa_intelligence.skill.md
  │   ├── friday_fine_tuning.skill.md
  │   └── reckall.skill.md
  └── comms/
      ├── whatsapp.skill.md
      └── linkedin.skill.md
```

---

*Skills are the institutional memory that survives context windows.
Every failure Travis has had that could have been prevented by
better documented knowledge — that's a skill waiting to be written.
Write the skill. Don't repeat the incident.*
