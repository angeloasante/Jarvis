# FRIDAY System Map
### *"How one model, 35 agents, 100+ tools, and a skill library move together as one."*

---

## Table of Contents

1. [The Big Picture](#the-big-picture)
2. [Why This Architecture](#why-this-architecture)
3. [Skills vs Tools — The Core Distinction](#skills-vs-tools--the-core-distinction)
4. [The Full Connection Map](#the-full-connection-map)
5. [FRIDAY Core — The Brain](#friday-core--the-brain)
6. [Agent Clusters — The Hands](#agent-clusters--the-hands)
7. [The Skill Layer — The Wisdom](#the-skill-layer--the-wisdom)
8. [The Tool Layer — The Muscles](#the-tool-layer--the-muscles)
9. [The Memory Layer — The Soul](#the-memory-layer--the-soul)
10. [Request Lifecycle — Full Trace](#request-lifecycle--full-trace)
11. [Failure Propagation Map](#failure-propagation-map)
12. [The One Model Rule](#the-one-model-rule)
13. [Everything Connected](#everything-connected)

---

## The Big Picture

Three documents exist for FRIDAY:

```
FRIDAY_IDEA.md      → What FRIDAY is and how to build it
FRIDAY_SKILLSET.md  → What each agent knows before it acts
FRIDAY_SYSTEM_MAP.md → How everything moves together (this document)
```

This document is the **connective tissue.** It answers the questions the other two don't:

- How does a single voice input become 5 parallel agent calls?
- Why does an agent read a skill before touching a tool?
- What actually happens when something fails 3 levels deep?
- How does FRIDAY Core know which agent to wake up?
- How does a tool result flow back to your ear as a spoken sentence?

Read this when you're building. Read this when something breaks and
you don't know where in the chain the failure lives.

---

## Why This Architecture

Before the map, understand the philosophy. Every structural decision
in FRIDAY answers one of three questions:

### Question 1 — Why not just one big model that does everything?

```
One model, all tools, no agents:

You: "Fix the Kluxta bug, check my emails, and deploy when done"
     ↓
Model sees 100+ tools simultaneously
     ↓
Attention diluted across every tool definition
     ↓
Wrong tool called. Wrong arguments. Silent failures.
     ↓
Travis discovers the bug was "fixed" by deleting the function.
```

The agent society exists to give each task a **focused context.**
Code Agent sees only code tools. Email Agent sees only email tools.
Focus = reliability.

### Question 2 — Why not just tools with no skills?

```
Agent + tools, no skills:

Code Agent called to fix Supabase query
     ↓
No skill loaded
     ↓
Agent writes query without LIMIT clause
     ↓
50,000 rows returned
     ↓
API crashes
     ↓
3am incident
     ↓
Travis fixes it, explains to FRIDAY what went wrong
     ↓
Next week: different agent, same mistake
```

Tools are **what** an agent can do. Skills are **how** to do it
correctly in Travis's specific stack. Without skills, every agent
starts from zero knowledge of every hard-learned lesson.

### Question 3 — Why fine-tune instead of just prompting?

```
Base model + system prompt only:

"You are FRIDAY, Travis's AI. Here are his projects..."
     ↓
Model tries to route using general knowledge
     ↓
Calls wrong agent for ambiguous requests
     ↓
Personality feels generic
     ↓
Tool calling is inconsistent — args sometimes wrong
     ↓
Travis has to keep correcting the same mistakes
```

Fine-tuning bakes routing logic, personality, and tool calling
**into the weights.** The system prompt provides dynamic context.
The weights provide reliable behaviour. Both are required.

---

## Skills vs Tools — The Core Distinction

This is the most important concept in the entire architecture.
Get this wrong and the whole system is fragile.

```
TOOL:  A function that does something.
SKILL: Knowledge about how to use that function correctly
       in Travis's specific context.
```

### The Analogy

Imagine hiring a new developer for Diaspora AI.

You give them **access to the codebase** (tools).
But you also give them **an onboarding doc** that says:

- "We use Supabase. Free tier pauses after 7 days."
- "Paystack webhooks have a race condition — always use idempotency keys."
- "Never run migrations on production without telling Travis first."

That onboarding doc is the skill. The codebase is the tool.

A developer with just the codebase and no onboarding will
eventually cause an incident. A developer with both starts senior.

### The Layer Separation

```
┌─────────────────────────────────────────────┐
│                   AGENT                     │
│         "I need to write a query"           │
└──────────────────┬──────────────────────────┘
                   │ reads first
┌──────────────────▼──────────────────────────┐
│                   SKILL                     │
│    "Here's how to write queries safely      │
│     in Travis's Supabase setup.             │
│     Always add LIMIT. Check RLS.            │
│     Free tier pauses after 7 days."         │
└──────────────────┬──────────────────────────┘
                   │ then calls
┌──────────────────▼──────────────────────────┐
│                   TOOL                      │
│    run_supabase_query(                      │
│      query="SELECT * FROM bookings          │
│             WHERE status='pending'          │
│             LIMIT 100",                     │
│      params={}                              │
│    )                                        │
└─────────────────────────────────────────────┘
```

The skill sits **between** the agent's intention and the tool's
execution. It transforms a naive action into an informed one.

### Why Not Put Skill Knowledge In The Tool?

```python
# You could put guardrails in the tool itself:
def run_supabase_query(query: str) -> list:
    if "LIMIT" not in query.upper():
        query += " LIMIT 100"  # auto-add limit
    return execute(query)
```

This looks reasonable. Here's why it's wrong:

1. **Agents stop thinking.** If the tool handles everything, the
   agent never develops judgment. It just fires blindly and hopes
   the tool catches the mistake.

2. **Tools become bloated.** Every edge case gets added to the tool
   until it's 500 lines of guardrails instead of 20 lines of function.

3. **Silent corrections are dangerous.** An agent that thinks it wrote
   a correct query but the tool secretly modified it will never
   understand why results are different than expected.

4. **Skills are model-agnostic, tools are not.** You can swap FRIDAY's
   brain from Qwen to any future model. The skills travel with the
   system. Guardrails baked into tools don't teach anything.

**The rule:**
- Tools are pure. They do exactly what you ask.
- Skills are wise. They teach the agent what to ask.

---

## The Full Connection Map

```
┌──────────────────────────────────────────────────────────────────────┐
│                           YOU                                        │
│                   Voice / Text / Terminal                            │
└────────────────────────────┬─────────────────────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │  VOICE LAYER    │
                    │ Porcupine STT   │
                    │ Whisper → text  │
                    └────────┬────────┘
                             │
         ┌───────────────────▼───────────────────┐
         │            FRIDAY CORE                │
         │      Fine-tuned Qwen3.5-9B            │
         │                                       │
         │  1. Loads memory_preload.skill        │
         │  2. Loads routing.skill               │
         │  3. Classifies intent                 │
         │  4. Decides: thinking ON or OFF       │
         │  5. Dispatches to agent cluster(s)    │
         │  6. Assembles final response          │
         │  7. Sends to voice output             │
         └───────┬───────┬───────┬───────┬───────┘
                 │       │       │       │
        ┌────────▼─┐ ┌───▼────┐ ┌▼─────┐ ┌▼──────────┐
        │COGNITIVE │ │  CODE  │ │COMMS │ │ BUSINESS  │
        │CLUSTER   │ │CLUSTER │ │CLUSTER│ │ CLUSTER   │
        └────────┬─┘ └───┬────┘ └┬─────┘ └┬──────────┘
                 │       │       │        │
        ┌────────▼─┐ ┌───▼────┐ ┌▼─────┐ ┌▼──────────┐
        │RESEARCH  │ │CREATIVE│ │SYSTEM│ │  MEMORY   │
        │CLUSTER   │ │CLUSTER │ │CLUSTER│ │  CLUSTER  │
        └────────┬─┘ └───┬────┘ └┬─────┘ └┬──────────┘
                 │       │       │        │
                 └───────┴───┬───┴────────┘
                             │
         ┌───────────────────▼───────────────────┐
         │            SKILL LAYER                │
         │                                       │
         │  Agent reads relevant skill(s)        │
         │  before calling any tool              │
         │                                       │
         │  routing.skill                        │
         │  python.skill                         │
         │  supabase.skill                       │
         │  paystack.skill  ← revenue critical   │
         │  modal.skill                          │
         │  letta.skill                          │
         │  ama_model.skill                      │
         │  diaspora_ai_platform.skill           │
         │  ... (full library)                   │
         └───────────────────┬───────────────────┘
                             │
         ┌───────────────────▼───────────────────┐
         │             TOOL LAYER                │
         │          (MCP Servers)                │
         │                                       │
         │  search_web()    read_file()          │
         │  run_terminal()  git_commit()         │
         │  read_emails()   send_email()         │
         │  get_calendar()  dispatch_agent()     │
         │  run_supabase_query()                 │
         │  browser_navigate()  deploy_modal()   │
         │  ... (100+ tool functions)            │
         └───────────────────┬───────────────────┘
                             │
         ┌───────────────────▼───────────────────┐
         │            MEMORY LAYER               │
         │                                       │
         │  Letta    → long-term structured      │
         │  ChromaDB → semantic vector search    │
         │  SQLite   → fast structured queries   │
         │  Screenpipe → passive context capture │
         └───────────────────────────────────────┘
```

---

## FRIDAY Core — The Brain

FRIDAY Core is **not** an agent. It is the orchestrator. It never
does specialist work. It thinks, delegates, assembles, and responds.

### What FRIDAY Core Knows

```python
FRIDAY_CORE_KNOWLEDGE = {
    # Always loaded
    "always": [
        "routing.skill.md",
        "memory_preload.skill.md"
    ],
    
    # Access to
    "tools": [
        "dispatch_agent",    # Wake up any specialist agent
        "get_memory",        # Pull from Letta
        "store_memory",      # Write to Letta
        "create_reminder",   # Notification Agent shortcut
        "get_calendar_summary"  # Quick calendar check
    ],
    
    # Does NOT access directly
    "never_calls": [
        "run_supabase_query",  # That's Database Agent's job
        "git_commit",          # That's Git Agent's job
        "send_email",          # That's Email Agent's job
        "run_terminal"         # That's Terminal Agent's job
    ]
}
```

FRIDAY Core's access to tools is intentionally narrow. If Core
could call everything, it would skip the agent layer and lose
all the focused context that makes specialist agents reliable.

### How FRIDAY Core Decides

```
Input received
     │
     ▼
Load memory_preload.skill
Pull relevant context from Letta
     │
     ▼
Load routing.skill
Classify intent:
  - Which cluster(s) does this involve?
  - Simple or complex? (thinking mode decision)
  - Ambiguous? (ask one clarifying question)
  - Revenue-critical? (drop everything)
     │
     ▼
Thinking mode decision:
  
  OFF → Simple, clear, fast tasks
       "open cursor in kluxta"
       "what time is my next meeting"
       "push to github"
  
  ON  → Strategic, ambiguous, high-stakes
       "should I take this recruiter call"
       "how should I approach the YC application"
       "is this architecture decision right"
     │
     ▼
Dispatch plan:
  
  Single agent:
    dispatch_agent("code_agent", task, context)
  
  Parallel agents:
    await asyncio.gather(
        dispatch_agent("email_agent", "get unread"),
        dispatch_agent("calendar_agent", "get today"),
        dispatch_agent("news_agent", "relevant news"),
        dispatch_agent("monitoring_agent", "infra status")
    )
  
  Sequential pipeline:
    result_1 = await dispatch_agent("research_agent", task)
    result_2 = await dispatch_agent("file_agent", task, result_1)
     │
     ▼
Results assembled by Summariser Agent
     │
     ▼
Memory Agent stores what matters
     │
     ▼
Response delivered (text or voice)
```

### FRIDAY Core Personality Layer

The fine-tune bakes three things into Core's weights:

```
1. PERSONALITY
   How FRIDAY talks to Travis.
   Warm, direct, honest, sarcastic when earned.
   Never sycophantic. Pushes back when wrong.
   Ghanaian-aware. Late-night-fluent.

2. ROUTING LOGIC
   Which agent for which task.
   When to parallelize. When to sequence.
   When to ask for clarification first.
   When to drop everything (revenue-critical).

3. TOOL CALLING FORMAT
   Exact schema for dispatch_agent and memory tools.
   Reliable every time — baked in, not prompted in.
```

---

## Agent Clusters — The Hands

Each cluster is a group of specialist agents that share a domain.
Each agent is: same FRIDAY model + different system prompt +
scoped tool access + relevant skills pre-loaded.

---

### Cluster Map

```
FRIDAY CORE
     │
     ├── COGNITIVE CLUSTER
     │     ├── Planner Agent
     │     ├── Reasoning Agent
     │     ├── Critic Agent
     │     ├── Reflection Agent
     │     ├── Decision Agent
     │     └── Summariser Agent
     │
     ├── CODE CLUSTER
     │     ├── Code Agent
     │     ├── Debug Agent
     │     ├── Test Agent
     │     ├── Git Agent
     │     ├── DevOps Agent
     │     ├── Code Review Agent
     │     ├── Database Agent
     │     └── API Agent
     │
     ├── RESEARCH CLUSTER
     │     ├── Web Research Agent
     │     ├── Academic Agent
     │     ├── Competitor Agent
     │     ├── News Agent
     │     ├── Tech Radar Agent
     │     └── Funding Agent
     │
     ├── COMMS CLUSTER
     │     ├── Email Agent
     │     ├── Email Triage Agent
     │     ├── Calendar Agent
     │     ├── LinkedIn Agent
     │     └── Outreach Agent
     │
     ├── BUSINESS CLUSTER
     │     ├── Diaspora AI Agent
     │     ├── Analytics Agent
     │     ├── Investor Prep Agent
     │     ├── Legal Agent
     │     ├── Finance Agent
     │     ├── Hiring Agent
     │     └── Product Agent
     │
     ├── CREATIVE CLUSTER
     │     ├── Kluxta Agent
     │     ├── Ama Agent
     │     ├── Content Agent
     │     └── Naming Agent
     │
     ├── MEMORY CLUSTER
     │     ├── Memory Agent
     │     ├── Screenpipe Agent
     │     └── Project Context Agent
     │
     ├── SYSTEM CLUSTER
     │     ├── Mac Control Agent
     │     ├── Browser Agent
     │     ├── File Agent
     │     ├── Terminal Agent
     │     ├── Notification Agent
     │     └── Monitoring Agent
     │
     └── DOMAIN CLUSTER
           ├── Ghana Context Agent
           ├── Visa Intelligence Agent
           ├── Diaspora Market Agent
           └── Job Hunt Agent
```

---

### How An Agent Is Constructed

Every agent in every cluster is built the same way:

```python
class FridayAgent:
    def __init__(
        self,
        name: str,
        system_prompt: str,
        allowed_tools: list[str],    # Scoped — not all tools
        required_skills: list[str],  # Loaded before every run
        model: str = "friday-qwen3.5"  # Same model, always
    ):
        self.name = name
        self.system_prompt = system_prompt
        self.tools = load_tools(allowed_tools)
        self.skills = load_skills(required_skills)
        self.model = model
    
    async def run(self, task: str, context: str = None) -> AgentResult:
        # Step 1: Load skills into context
        skill_context = await self.load_skill_context()
        
        # Step 2: Build full prompt
        full_context = f"""
        {self.system_prompt}
        
        SKILL KNOWLEDGE:
        {skill_context}
        
        TASK CONTEXT:
        {context or "No additional context"}
        
        TASK:
        {task}
        """
        
        # Step 3: Run with scoped tools only
        response = await ollama.chat(
            model=self.model,
            messages=[{"role": "user", "content": full_context}],
            tools=self.tools
        )
        
        # Step 4: Execute any tool calls
        if response.has_tool_calls:
            results = await self.execute_tool_calls(response.tool_calls)
            response = await self.continue_with_results(results)
        
        return AgentResult(
            agent=self.name,
            output=response.content,
            tools_called=response.tool_calls,
            success=True
        )
```

The scoped tools are the key line. `Code Agent` cannot accidentally
call `send_email`. `Email Agent` cannot accidentally run `git push`.
The agent physically cannot make cross-domain mistakes.

---

### Agent Skill Map — Who Reads What

This is the complete map of which agent reads which skills
before acting. This is how knowledge flows through the system.

```
FRIDAY CORE
  └── routing.skill
  └── memory_preload.skill

COGNITIVE CLUSTER
  Planner Agent
    └── routing.skill
  Reasoning Agent
    └── [loads relevant skill per task domain]
  Critic Agent
    └── python.skill
    └── typescript.skill
    └── supabase.skill
    └── paystack.skill  ← always loads for code review
  Reflection Agent
    └── letta.skill
  Decision Agent
    └── memory_preload.skill
  Summariser Agent
    └── [no domain skills — pure compression]

CODE CLUSTER
  Code Agent
    └── python.skill
    └── typescript.skill
    └── supabase.skill
    └── paystack.skill
    └── stripe.skill
    └── git.skill
  Debug Agent
    └── python.skill
    └── typescript.skill
    └── supabase.skill
    └── paystack.skill  ← payment bugs are always critical
  Test Agent
    └── python.skill
    └── typescript.skill
    └── supabase.skill
  Git Agent
    └── git.skill
  DevOps Agent
    └── modal.skill
    └── terminal.skill
    └── git.skill
  Code Review Agent
    └── python.skill
    └── typescript.skill
    └── supabase.skill
    └── paystack.skill
    └── stripe.skill
  Database Agent
    └── supabase.skill
    └── python.skill
  API Agent
    └── paystack.skill
    └── stripe.skill
    └── python.skill
    └── typescript.skill

RESEARCH CLUSTER
  Web Research Agent
    └── web_research.skill
  Academic Agent
    └── arxiv.skill
    └── web_research.skill
  Competitor Agent
    └── web_research.skill
    └── diaspora_ai_platform.skill
  News Agent
    └── web_research.skill
  Tech Radar Agent
    └── web_research.skill
  Funding Agent
    └── web_research.skill

COMMS CLUSTER
  Email Agent
    └── gmail.skill
  Email Triage Agent
    └── gmail.skill
  Calendar Agent
    └── calendar.skill
  LinkedIn Agent
    └── [no domain skill yet — write linkedin.skill]
  Outreach Agent
    └── gmail.skill
    └── diaspora_ai_platform.skill

BUSINESS CLUSTER
  Diaspora AI Agent
    └── diaspora_ai_platform.skill
    └── paystack.skill
    └── stripe.skill
  Analytics Agent
    └── diaspora_ai_platform.skill
    └── supabase.skill
  Investor Prep Agent
    └── diaspora_ai_platform.skill
    └── web_research.skill
  Legal Agent
    └── [write legal.skill]
  Finance Agent
    └── diaspora_ai_platform.skill
    └── paystack.skill
    └── stripe.skill
  Hiring Agent
    └── gmail.skill
  Product Agent
    └── diaspora_ai_platform.skill

CREATIVE CLUSTER
  Kluxta Agent
    └── python.skill
    └── typescript.skill
    └── modal.skill
    └── terminal.skill
    └── git.skill
  Ama Agent
    └── ama_model.skill
    └── unsloth_qlora.skill
    └── modal.skill
    └── python.skill
  Content Agent
    └── [no domain skill — write content.skill]
  Naming Agent
    └── [no domain skill — write naming.skill]

MEMORY CLUSTER
  Memory Agent
    └── letta.skill
  Screenpipe Agent
    └── screenpipe.skill
  Project Context Agent
    └── letta.skill
    └── diaspora_ai_platform.skill
    └── ama_model.skill

SYSTEM CLUSTER
  Mac Control Agent
    └── open_interpreter.skill
    └── terminal.skill
  Browser Agent
    └── browser_use.skill
  File Agent
    └── terminal.skill
  Terminal Agent
    └── terminal.skill
    └── python.skill
  Notification Agent
    └── alerting.skill
    └── calendar.skill
  Monitoring Agent
    └── alerting.skill
    └── diaspora_ai_platform.skill
    └── modal.skill

DOMAIN CLUSTER
  Ghana Context Agent
    └── web_research.skill
  Visa Intelligence Agent
    └── diaspora_ai_platform.skill
    └── web_research.skill
  Diaspora Market Agent
    └── diaspora_ai_platform.skill
    └── web_research.skill
  Job Hunt Agent
    └── gmail.skill
```

---

## The Skill Layer — The Wisdom

The skill layer is **the moment between intention and action.**

Without it:
```
Agent → Tool (naive, uninformed)
```

With it:
```
Agent → Skill (informed) → Tool (precise, safe)
```

### How Skills Are Loaded

```python
class SkillLoader:
    
    SKILL_DIR = Path("friday/skills")
    
    async def load_for_agent(
        self, 
        agent_name: str, 
        task: str
    ) -> str:
        
        # 1. Get agent's required skills (always loaded)
        required = AGENT_SKILL_MAP[agent_name]
        
        # 2. Get task-triggered skills (loaded based on task content)
        triggered = self.detect_triggered_skills(task)
        
        # 3. Combine, deduplicate
        all_skills = list(set(required + triggered))
        
        # 4. Load and concatenate skill content
        skill_content = []
        for skill_name in all_skills:
            skill_path = self.SKILL_DIR / skill_name
            if skill_path.exists():
                content = skill_path.read_text()
                # Load only TL;DR + most relevant section for context efficiency
                skill_content.append(self.extract_relevant_sections(content, task))
        
        return "\n\n---\n\n".join(skill_content)
    
    def detect_triggered_skills(self, task: str) -> list[str]:
        """Detect additional skills based on task content"""
        triggered = []
        
        TASK_SKILL_TRIGGERS = {
            "paystack":     ["paystack.skill.md"],
            "stripe":       ["stripe.skill.md"],
            "supabase":     ["supabase.skill.md"],
            "modal":        ["modal.skill.md"],
            "fine-tune":    ["unsloth_qlora.skill.md"],
            "ama":          ["ama_model.skill.md"],
            "kluxta":       ["python.skill.md", "modal.skill.md"],
            "deploy":       ["modal.skill.md", "terminal.skill.md"],
            "git":          ["git.skill.md"],
            "webhook":      ["paystack.skill.md", "stripe.skill.md"],
            "email":        ["gmail.skill.md"],
            "calendar":     ["calendar.skill.md"],
            "memory":       ["letta.skill.md"],
            "scrape":       ["browser_use.skill.md"],
            "train":        ["unsloth_qlora.skill.md", "modal.skill.md"],
        }
        
        task_lower = task.lower()
        for keyword, skills in TASK_SKILL_TRIGGERS.items():
            if keyword in task_lower:
                triggered.extend(skills)
        
        return list(set(triggered))
```

### Skill Loading Is Selective — Not Wholesale

An agent does not load every skill. It loads:

1. **Required skills** — always loaded for that agent
2. **Triggered skills** — loaded when task keywords match

This prevents context bloat. A `git_commit` call doesn't need
the `ama_model.skill` in context. Loading irrelevant skills
dilutes the agent's attention on what actually matters.

---

## The Tool Layer — The Muscles

Tools are pure functions. They do exactly what you ask.
No hidden logic. No guardrails. No opinions.

### Why Tools Are Pure

```python
# Pure tool — does exactly what it's told
async def run_supabase_query(query: str, params: dict = None) -> list:
    result = await supabase.execute(query, params)
    return result.data

# Impure tool — has opinions baked in
async def run_supabase_query_smart(query: str, params: dict = None) -> list:
    if "LIMIT" not in query.upper():
        query += " LIMIT 100"  # Who decided 100? Why 100? This is now hidden.
    if "WHERE" not in query.upper():
        raise ValueError("Query must have WHERE clause")  # Now what?
    result = await supabase.execute(query, params)
    return result.data
```

The impure version looks safer. But:
- The agent never learns why LIMIT matters
- The agent is confused when results are different than expected
- The behaviour changes silently as someone "improves" the tool
- Another model reading the same skill has different tool behaviour

Pure tools + rich skills = transparent, learnable, portable system.

### Tool Access Matrix

```
                    FRIDAY  COGNITIVE  CODE  RESEARCH  COMMS  BUSINESS  CREATIVE  MEMORY  SYSTEM  DOMAIN
                    CORE    CLUSTER    CLUST CLUSTER   CLUST  CLUSTER   CLUSTER   CLUST   CLUST   CLUST

dispatch_agent        ✓        ✓        ✗       ✗        ✗       ✗        ✗        ✗       ✗       ✗
get_memory            ✓        ✓        ✓       ✓        ✓       ✓        ✓        ✓       ✓       ✓
store_memory          ✓        ✓        ✓       ✓        ✓       ✓        ✓        ✓       ✗       ✓
search_web            ✗        ✓        ✓       ✓        ✗       ✓        ✓        ✗       ✗       ✓
web_fetch             ✗        ✗        ✓       ✓        ✗       ✓        ✗        ✗       ✗       ✓
read_file             ✗        ✗        ✓       ✗        ✗       ✓        ✓        ✗       ✓       ✗
write_file            ✗        ✗        ✓       ✗        ✗       ✓        ✓        ✗       ✓       ✗
run_terminal          ✗        ✗        ✓       ✗        ✗       ✗        ✓        ✗       ✓       ✗
git_commit            ✗        ✗        ✓       ✗        ✗       ✗        ✓        ✗       ✗       ✗
git_push              ✗        ✗        ✓       ✗        ✗       ✗        ✓        ✗       ✗       ✗
read_emails           ✗        ✗        ✗       ✗        ✓       ✓        ✗        ✗       ✗       ✓
send_email            ✗        ✗        ✗       ✗        ✓       ✗        ✗        ✗       ✗       ✗
draft_email           ✗        ✗        ✗       ✗        ✓       ✓        ✓        ✗       ✗       ✓
get_calendar          ✓        ✗        ✗       ✗        ✓       ✓        ✗        ✗       ✓       ✗
create_event          ✗        ✗        ✗       ✗        ✓       ✗        ✗        ✗       ✗       ✗
run_supabase_query    ✗        ✗        ✓       ✗        ✗       ✓        ✗        ✗       ✗       ✗
check_deployments     ✗        ✗        ✓       ✗        ✗       ✓        ✓        ✗       ✓       ✗
deploy_modal          ✗        ✗        ✓       ✗        ✗       ✗        ✓        ✗       ✓       ✗
browser_navigate      ✗        ✗        ✗       ✓        ✗       ✗        ✗        ✗       ✓       ✗
run_applescript       ✗        ✗        ✗       ✗        ✗       ✗        ✗        ✗       ✓       ✗
search_screenpipe     ✗        ✗        ✗       ✗        ✗       ✗        ✗        ✓       ✗       ✗
query_letta           ✗        ✗        ✗       ✗        ✗       ✗        ✗        ✓       ✗       ✗
create_reminder       ✓        ✗        ✗       ✗        ✗       ✗        ✗        ✗       ✓       ✗
send_notification     ✗        ✗        ✗       ✗        ✗       ✗        ✗        ✗       ✓       ✗
```

An empty cell is not a gap. It is a **guardrail.**

---

## The Memory Layer — The Soul

Memory is what separates FRIDAY from a stateless chatbot.
Four layers, four purposes.

```
┌──────────────────────────────────────────────────────────┐
│                   LETTA (Tier 2-3)                       │
│                                                          │
│  Recall Memory:                                          │
│  → Searchable conversation history                       │
│  → "What did we decide about X last week?"               │
│                                                          │
│  Archival Memory:                                        │
│  → Permanent structured knowledge                        │
│  → Project contexts, preferences, decisions              │
│  → "Travis prefers Railway over Fly.io for backends"     │
│  → "Demucs OOM fix: chunk audio at 3-minute intervals"   │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│                  CHROMADB (Semantic)                     │
│                                                          │
│  → Find memories by meaning, not exact keywords          │
│  → "find decisions about the payment architecture"       │
│     matches "Travis chose dual Stripe+Paystack because   │
│     it covers 85% of diaspora payment methods"           │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│                   SQLITE (Structured)                    │
│                                                          │
│  → Fast exact queries on known fields                    │
│  → Project status: {name, phase, last_active, blockers}  │
│  → Tool call history: {agent, tool, args, result, time}  │
│  → Incident log: {type, time, cause, fix, prevention}    │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│                 SCREENPIPE (Passive)                     │
│                                                          │
│  → Everything Travis does on his Mac, indexed locally    │
│  → Screen frames, audio, browser history                 │
│  → "What was I looking at Tuesday at 2am?"               │
│  → The context Travis never had to provide               │
│  → Privacy: local only, never leaves the machine         │
└──────────────────────────────────────────────────────────┘
```

### When Each Layer Is Queried

```python
MEMORY_ROUTING = {
    "recent_decision": "letta.recall",
    "project_state": "sqlite + letta.archival",
    "preference_lookup": "letta.archival",
    "semantic_search": "chromadb",
    "past_screen_activity": "screenpipe",
    "past_browser_tab": "screenpipe",
    "incident_history": "sqlite",
    "tool_call_log": "sqlite",
    "anything_older_than_screenpipe_window": "letta"
}
```

### The Memory Write Protocol

Memory Agent follows this decision tree after every significant task:

```
Task completed
     │
     ▼
Was a technical decision made?
  YES → store in letta.archival tagged [project][technical][decision]
     │
     ▼
Was a bug fixed?
  YES → store in letta.archival tagged [project][bug][fix][file:line]
     │
     ▼
Did Travis express a preference?
  YES → store in letta.archival tagged [preference][topic]
     │
     ▼
Did a project status change?
  YES → update sqlite projects table
     │
     ▼
Was there an incident?
  YES → store in sqlite incident_log AND letta.archival
     │
     ▼
Routine task with no lasting significance?
  → Do not store (keep memory clean)
```

---

## Request Lifecycle — Full Trace

Three complete traces to show how the system actually moves.

---

### Trace 1 — Simple Request

**Input:** "yo friday what's good"

```
1. Porcupine: wake word not needed (text input)
   
2. FRIDAY CORE receives: "yo friday what's good"
   
3. Loads routing.skill
   → Intent: casual greeting
   → Complexity: simple
   → Thinking mode: OFF
   
4. Loads memory_preload.skill
   → Preloads: project contexts, pending reminders
   → Dispatches Memory Agent to pull daily context
   
5. Memory Agent queries SQLite:
   → Active projects: Kluxta, Ama, Diaspora AI
   → Project states: last commits, last deploy, last session
   
6. Memory Agent queries Letta:
   → Recent reminders: "review Paystack webhook"
   → Any pending issues flagged yesterday
   
7. Monitoring Agent (background, always running)
   → Reports: all deployments green
   
8. FRIDAY CORE assembles response from context:
   → No critical alerts
   → Surfaces: Ama fine-tune still queued, 
               4 unread emails,
               Kluxta last commit 2 days ago
   
9. Response delivered in <2 seconds:
   "Yo. Ama fine-tune still queued on RunPod.
    4 unread emails, nothing urgent.
    You haven't touched Kluxta in 2 days.
    What are we doing today?"

10. Memory Agent stores: "Travis greeted FRIDAY at [time]"
    → Skipped — routine, no lasting significance
```

Total agents involved: FRIDAY Core + Memory Agent + Monitoring Agent (3)
Skills loaded: routing.skill + memory_preload.skill
Tools called: get_memory, check_deployments, read_emails (summary)

---

### Trace 2 — Complex Parallel Request

**Input:** "give me a full morning briefing"

```
1. FRIDAY CORE receives input
   
2. routing.skill loaded
   → Intent: morning briefing
   → Complexity: multi-domain
   → Thinking mode: OFF (well-defined task)
   → Pattern: parallel fan-out
   
3. memory_preload.skill loaded
   → Context: no specific project mentioned
   → Load: pending reminders, any overnight alerts
   
4. FRIDAY CORE dispatches 5 agents IN PARALLEL:

   ┌─ Email Triage Agent
   │    Skills loaded: gmail.skill
   │    Tools: read_emails(filter="unread")
   │    Returns: {count: 4, urgent: 1 (Jack Breen), 
   │              summary: "Jack Breen replied, 3 low priority"}
   │
   ├─ Calendar Agent
   │    Skills loaded: calendar.skill
   │    Tools: get_calendar(date="today")
   │    Returns: {events: ["11am: recruiter call", "3pm: free"]}
   │
   ├─ News Agent
   │    Skills loaded: web_research.skill
   │    Tools: search_web("AI news today"), 
   │            search_web("Ghana tech today"),
   │            search_web("diaspora fintech today")
   │    Returns: {items: [3 relevant stories]}
   │
   ├─ Monitoring Agent
   │    Skills loaded: alerting.skill, diaspora_ai_platform.skill
   │    Tools: check_all_deployments(), get_diaspora_metrics()
   │    Returns: {status: "all green", metrics: {bookings: 3 overnight}}
   │
   └─ Memory Agent
        Skills loaded: letta.skill
        Tools: get_memory("pending tasks"), get_memory("overnight events")
        Returns: {reminders: ["review Paystack webhook"], 
                  context: "Ama fine-tune still queued"}

5. All 5 return roughly simultaneously (~2-3 seconds)

6. Summariser Agent assembles:
   → Priority order: Jack Breen email first (high value)
   → 3 overnight bookings on Diaspora AI
   → Paystack webhook review reminder
   → 11am call today
   → Ama fine-tune still waiting
   → Relevant news: [1 item about Qwen model update]

7. FRIDAY delivers briefing (voice or text)

8. Memory Agent stores:
   → "Morning briefing delivered [date]. Jack Breen email flagged as urgent."
```

Total agents: FRIDAY Core + Email Triage + Calendar + News +
              Monitoring + Memory + Summariser (7 concurrent)
Skills loaded: routing, memory_preload, gmail, calendar,
               web_research, alerting, diaspora_ai_platform, letta
Total wall-clock time: ~3-4 seconds despite 7 agents

---

### Trace 3 — Deep Agentic Pipeline

**Input:** "fix whatever's failing in the Kluxta build and deploy when done"

```
1. FRIDAY CORE receives input

2. routing.skill loaded
   → Intent: debug + fix + deploy
   → Complexity: high (multi-step, sequential)
   → Thinking mode: OFF (clear task, no ambiguity)
   → Pattern: sequential pipeline with decision points

3. memory_preload.skill loaded
   → Project: Kluxta
   → get_project_context("kluxta")
   → Returns: "Last session: Demucs OOM bug. Last commit: 2 days ago.
               Recent issue: null reference in audio_pipeline.ts"

4. FRIDAY CORE dispatches: Planner Agent

   Planner Agent:
     Skills: routing.skill
     Task: "Break down: fix Kluxta build, deploy when passing"
     Returns task tree:
       Step 1: Read build logs (Terminal Agent)
       Step 2: Identify failure (Debug Agent)
       Step 3: Fix failure (Code Agent)
       Step 4: Run tests (Test Agent)
       Step 5: If tests pass → Git commit (Git Agent)
       Step 6: Deploy to Modal (DevOps Agent)
       Step 7: Verify deployment health (Monitoring Agent)

5. Step 1 — Terminal Agent
   Skills loaded: terminal.skill
   Tools: read_build_logs(project="kluxta", limit=1)
   Returns: "TypeError: Cannot read properties of undefined
             reading 'audioBuffer' at demucs_pipeline.ts:189"

6. Step 2 — Debug Agent
   Skills loaded: python.skill, typescript.skill, modal.skill
   (modal.skill loaded because "demucs" triggered it)
   Tools: read_file("kluxta/demucs_pipeline.ts", lines="180-200")
          get_memory("kluxta audio pipeline null reference")
   
   Memory returns: "Previous fix: null check on audioBuffer.
                    Check track.audioBuffer?.slice() pattern"
   
   Debug Agent identifies: line 189 missing null check
   Returns: {file: "demucs_pipeline.ts", line: 189, 
             fix: "add optional chaining: track.audioBuffer?.slice()"}

7. Step 3 — Code Agent
   Skills loaded: typescript.skill, git.skill
   Tools: read_file("kluxta/demucs_pipeline.ts")
          write_file("kluxta/demucs_pipeline.ts", fixed_content)
   
   Code Agent reads full file, applies minimal fix,
   does not change unrelated code.

8. Step 4 — Critic Agent (automatic quality gate)
   Skills loaded: typescript.skill, python.skill
   Reviews the change:
   → "Optional chaining applied correctly"
   → "No other null references in affected code path"
   → "Change is minimal and targeted"
   Result: APPROVED

9. Step 5 — Test Agent
   Skills loaded: typescript.skill
   Tools: run_terminal("cd kluxta && npm test")
   Returns: "All 23 tests passing. Build successful."

10. Step 6 — Git Agent
    Skills loaded: git.skill
    Pre-commit check: no secrets, no unintended files
    Tools: git_commit(message="fix(kluxta): null check on audioBuffer 
                               in demucs pipeline ts:189")
           git_push()

11. Step 7 — DevOps Agent
    Skills loaded: modal.skill, terminal.skill
    Tools: deploy_modal("kluxta/render.py")
    Returns: "Deployed. Endpoint: kluxta--render.modal.run"

12. Step 8 — Monitoring Agent (verify)
    Skills loaded: alerting.skill
    Tools: ping_endpoint("kluxta--render.modal.run")
           check_deployment_health(service="kluxta")
    Returns: "Responding 200. Cold start: 4.2s. All healthy."

13. Step 9 — Memory Agent stores:
    "Bug fix [Kluxta] [2026-01-15]:
     Null reference on audioBuffer in demucs_pipeline.ts:189.
     Fix: optional chaining. Deployed to Modal.
     Pattern: always check audioBuffer before .slice()"

14. FRIDAY CORE responds:
    "Fixed. Null reference on line 189 — audioBuffer wasn't null-checked.
     Applied optional chaining, all 23 tests passed, deployed to Modal.
     Endpoint is healthy. Commit: 'fix(kluxta): null check on audioBuffer'"

15. Reflection Agent runs (background, async):
    "Could the build check have run earlier to catch this sooner?
     Consider: add pre-commit hook to run build check."
    Stores suggestion in Letta for next Kluxta session.
```

Total agents: FRIDAY Core + Planner + Terminal + Debug + Code +
              Critic + Test + Git + DevOps + Monitoring +
              Memory + Reflection (12 agents, sequential)
Skills loaded: routing, memory_preload, terminal, typescript,
               python, modal, git, alerting, letta
Total time: ~45-90 seconds for full pipeline
Travis involvement: zero — he asked once, FRIDAY did the rest

---

## Failure Propagation Map

What happens when something breaks at each layer.

```
FAILURE AT TOOL LAYER
     │
     ▼
Tool returns SkillResult(success=False, error=SkillError(...))
     │
     ▼
Agent reads error.action from SkillError
  → recoverable=True + retry_after → wait and retry
  → recoverable=False → stop and report up
     │
     ▼
Agent returns AgentResult(success=False, error=...)
     │
     ▼
FRIDAY CORE receives failed AgentResult
     │
     ▼
Checks error.severity:
  LOW    → Log, continue, mention in next response
  MEDIUM → Complete other tasks, report to Travis at end
  HIGH   → Report to Travis before completing other tasks
  CRITICAL → Interrupt everything, report immediately
     │
     ▼
Memory Agent stores incident:
  "Tool failure [agent][tool][error_code][time][action_taken]"
```

### Specific Failure Scenarios

```
SCENARIO: Paystack webhook 401 in production
     │
     ▼
API Agent: paystack.skill says 401 = auth error = escalate immediately
     │
     ▼
SkillError: severity=CRITICAL, escalate=True
     │
     ▼
FRIDAY CORE: drops current task
     │
     ▼
Notification Agent: desktop alert + voice interrupt
     │
     ▼
FRIDAY: "Boss. Paystack is returning 401 in production.
         No payments are processing.
         Checking PAYSTACK_WEBHOOK_SECRET in Railway now."
     │
     ▼
DevOps Agent: check_railway_env("PAYSTACK_WEBHOOK_SECRET")
     │
     ▼
[Resolution path continues...]

---

SCENARIO: Research Agent times out
     │
     ▼
Web Research Agent: request times out after 30s
     │
     ▼
SkillError: severity=MEDIUM, recoverable=True, action="retry once"
     │
     ▼
Agent retries once
     │
     ▼
Still fails
     │
     ▼
Agent returns: "Research agent failed. Falling back to direct search."
     │
     ▼
FRIDAY CORE: dispatch search_web directly
     │
     ▼
[Task completes via fallback, Travis sees slightly degraded result]
[Memory Agent logs: "Research agent timeout at [time] — monitor"]

---

SCENARIO: Critic Agent rejects code output
     │
     ▼
Code Agent produces fix
     │
     ▼
Critic Agent reviews:
  → Finds: hardcoded API key in test file
  → Severity: BLOCKER
     │
     ▼
Critic returns: REJECT with specific file:line
     │
     ▼
FRIDAY CORE: sends back to Code Agent with critic's findings
     │
     ▼
Code Agent fixes: removes hardcoded key, uses env var
     │
     ▼
Critic Agent re-reviews: APPROVED
     │
     ▼
Pipeline continues

[Travis never sees the rejected version]
[Memory Agent logs: "Hardcoded key caught in Kluxta PR — Code Agent pattern to watch"]
```

---

## The One Model Rule

This is the architectural north star. Do not violate it.

```
ONE fine-tuned model.
ONE source of personality.
ONE source of routing logic.
ONE source of tool calling behaviour.

35 agents.
100+ tools.
20+ skills.

But ONE brain.
```

### Why This Is The Right Call

**Option A: One model per agent (35 models)**
```
+ Each model perfectly specialised
- 35 fine-tuning runs
- 35 sets of weights to manage
- 35 different personalities (inconsistent FRIDAY)
- Impossible to maintain
- Each model drifts independently over time
```

**Option B: One model, all agents use it**
```
+ One fine-tuning run
+ One personality (consistent FRIDAY)
+ One set of weights to manage
+ Specialisation via system prompts + skills (cheap)
+ Swap the brain once, everything updates
```

The specialisation cost is near-zero with system prompts and
scoped tools. The consistency benefit is enormous. One model wins.

### The Model Swap Guarantee

Because the skill layer sits between agents and tools, and because
all tools are pure functions exposed via MCP, you can swap
FRIDAY's brain entirely without rewriting a single agent:

```python
# Today
FRIDAY_MODEL = "friday-qwen3.5-finetuned"

# Future — if a better base model exists
FRIDAY_MODEL = "friday-qwen4-finetuned"

# Or for heavy reasoning tasks only
FRIDAY_MODEL = "claude-api"  # Falls back to Claude for 
                              # complex reasoning
```

The agents don't care what model is running. The skills don't care.
The tools don't care. Only the config changes.

---

## Everything Connected

The final map. Every layer, every connection, every flow.

```
REQUEST ENTERS
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│                    VOICE PIPELINE                           │
│   Wake Word → Whisper STT → Clean Text                      │
└──────────────────────────┬──────────────────────────────────┘
                           │
      ┌────────────────────▼─────────────────────────┐
      │               FRIDAY CORE                    │
      │         Fine-tuned Qwen3.5-9B                │
      │                                              │
      │  Reads: routing.skill                        │
      │         memory_preload.skill                 │
      │                                              │
      │  Queries: Memory Layer (always)              │
      │  Decides: intent / complexity / routing      │
      │  Plans: parallel or sequential dispatch       │
      └────────────────────┬─────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
    parallel           parallel          sequential
    dispatch           dispatch          dispatch
         │                 │                 │
         ▼                 ▼                 ▼
  ┌──────────┐      ┌──────────┐      ┌──────────┐
  │  AGENT   │      │  AGENT   │      │  AGENT   │
  │    A     │      │    B     │      │    C     │
  └────┬─────┘      └────┬─────┘      └────┬─────┘
       │                 │                 │
       ▼                 ▼                 ▼
  SKILL LAYER       SKILL LAYER       SKILL LAYER
  (reads relevant   (reads relevant   (reads relevant
   skills for task)  skills for task)  skills for task)
       │                 │                 │
       ▼                 ▼                 ▼
  TOOL LAYER        TOOL LAYER        TOOL LAYER
  (pure functions   (pure functions   (pure functions
   via MCP)          via MCP)          via MCP)
       │                 │                 │
       └─────────────────┼─────────────────┘
                         │
                         ▼
               MEMORY LAYER
               (Letta + ChromaDB + SQLite + Screenpipe)
               - Read at start: preload context
               - Write at end: store what matters
                         │
                         ▼
               CRITIC AGENT
               (quality gate before Travis sees anything)
                         │
                         ▼
               SUMMARISER AGENT
               (compress for voice / text)
                         │
                         ▼
               MEMORY AGENT WRITE
               (store decisions, fixes, lessons)
                         │
                         ▼
               VOICE OUTPUT
               (Kokoro TTS → Speaker)
                         │
                         ▼
              TRAVIS HEARS THE ANSWER
```

---

### The Three Laws Of This Architecture

**Law 1: Skills before tools.**
No agent touches a tool without reading the relevant skill first.
A skilled agent makes informed calls. An unskilled agent makes
lucky or unlucky calls.

**Law 2: Scope everything.**
Every agent has a tool access list. Every skill has an agent list.
Nothing talks to everything. Narrow scope = predictable behaviour
= reliable system = Travis sleeping instead of debugging at 3am.

**Law 3: Memory closes the loop.**
Every significant action writes to memory.
Every significant request reads from memory.
An agent that doesn't remember is a tool.
An agent that remembers is a colleague.
FRIDAY is a colleague.

---

*Three files. One system. Thirty-five agents. One model.
Start with FRIDAY Core and three agents. Ship something.
The architecture scales. You already have the map.*
