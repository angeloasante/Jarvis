"""Production Benchmark — FRIDAY's actual prompts, all 32 tools, 3 providers.

Uses the REAL system prompts from router.py, tool_dispatch.py, and prompts.py.
Uses the REAL 32-tool schema from FRIDAY's dispatch registry.
Tests classify, dispatch (32 tools), chat, and streaming TTFT.
Runs all 3 providers in parallel with 20s timeout.
"""

import os, sys, time, json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv(Path(__file__).parent.parent / ".env")

# Load FRIDAY's actual prompts and tools
from friday.core.router import _CLASSIFY_PROMPT
from friday.core.tool_dispatch import DISPATCH_PROMPT, _build_tools, DIRECT_TOOL_SCHEMAS
from friday.core.prompts import PERSONALITY_SLIM

_build_tools()
NOW = datetime.now().strftime("%A %d %B %Y, %H:%M")
CLASSIFY_SYS = _CLASSIFY_PROMPT.format(time=NOW)
DISPATCH_SYS = DISPATCH_PROMPT.format(time=NOW)
CHAT_SYS = PERSONALITY_SLIM

print(f"  Loaded {len(DIRECT_TOOL_SCHEMAS)} tools from FRIDAY's dispatch registry")

# ── Providers ──

groq = OpenAI(api_key=os.getenv("GROQ_API_KEY"), base_url="https://api.groq.com/openai/v1", timeout=20.0)
or_parasail = OpenAI(api_key=os.getenv("OPENROUTER_API_KEY"), base_url="https://openrouter.ai/api/v1", timeout=20.0)
or_gais = OpenAI(api_key=os.getenv("OPENROUTER_API_KEY"), base_url="https://openrouter.ai/api/v1", timeout=20.0)
google_direct = OpenAI(api_key=os.getenv("GOOGLE_API_KEY", "").split(" ")[0],
                       base_url="https://generativelanguage.googleapis.com/v1beta/openai/", timeout=20.0)

PROVIDERS = [
    ("Groq/Qwen3", groq, "qwen/qwen3-32b", None),
    ("OR/Parasail", or_parasail, "google/gemma-4-31b-it", {"provider": {"order": ["Parasail"]}}),
    ("OR/GoogAI", or_gais, "google/gemma-4-31b-it", {"provider": {"order": ["Google AI Studio"]}}),
    ("Google Direct", google_direct, "gemma-4-31b-it", None),
]

# ── Test Queries (50 total — comprehensive) ──

CLASSIFY_TESTS = [
    # Comms
    ("check my emails", "comms_agent"),
    ("text Mom saying I'll be late", "comms_agent"),
    ("what's on my calendar today", "comms_agent"),
    ("read my whatsapp from Teddy", "comms_agent"),
    ("sms me a summary", "comms_agent"),
    ("facetime Ellen's pap", "comms_agent"),
    # System
    ("take a screenshot", "system_agent"),
    ("what's my battery at", "system_agent"),
    ("open Safari", "system_agent"),
    ("fill the form on my screen", "system_agent"),
    # Household
    ("turn on the tv", "household_agent"),
    ("tv volume to 30", "household_agent"),
    ("put on Netflix", "household_agent"),
    # Social
    ("tweet this: just shipped v0.2", "social_agent"),
    ("search x for what people say about Claude", "social_agent"),
    ("check my mentions on twitter", "social_agent"),
    # Research
    ("what is quantum computing", "research_agent"),
    ("who is Jensen Huang", "research_agent"),
    # Job
    ("tailor my CV for ML engineer at Google", "job_agent"),
    ("apply for this job posting", "job_agent"),
    # Memory
    ("remember my RAEng app is due March 30", "memory_agent"),
    # Briefing
    ("catch me up", "briefing_agent"),
    ("any missed calls", "briefing_agent"),
    # Deep research
    ("write a detailed report about AI in healthcare", "deep_research_agent"),
    # Code
    ("create a Python script that scrapes HN", "code_agent"),
    # Monitor
    ("watch this URL for changes", "monitor_agent"),
    # Chat
    ("yo whats good bruv", "CHAT"),
    ("why did you say that", "CHAT"),
    ("who are you", "CHAT"),
    ("im going to work", "CHAT"),
]

DISPATCH_TESTS = [
    # Should pick specific tools from the 32 available
    ("check my emails", "read_emails"),
    ("search emails from Stripe about payments", "search_emails"),
    ("what's on my calendar today", "get_calendar"),
    ("what is the M4 MacBook Air processor", "search_web"),
    ("read messages from Ellen's pap", "read_imessages"),
    ("text Mom saying I'll be home late", "send_imessage"),
    ("sms me saying the server is down", "send_sms"),
    ("remember my flight is June 15 to Accra", "store_memory"),
    ("what do I know about the Halo glasses", "search_memory"),
    ("check my whatsapp from Teddy", "read_whatsapp"),
    ("send Teddy a whatsapp saying yo", "send_whatsapp"),
    ("search my whatsapp for the address", "search_whatsapp"),
    ("check mentions on twitter", "get_my_mentions"),
    ("search x for AI startups UK", "search_x"),
    ("what's on my screen", "read_screen"),
    ("facetime Mom", "start_facetime"),
    ("find Mom's number", "search_contacts"),
    ("every weekday at 8am run my briefing", "create_cron"),
    ("list my crons", "list_crons"),
    ("watch Ellen's messages for the next hour", "create_watch"),
    ("list my watches", "list_watches"),
    ("convert my thesis to pdf", "convert_file"),
    # Edge cases
    ("yo", "NO_TOOL"),
    ("draft email then check calendar", "NEEDS_AGENT"),
    ("fill the form on my screen", "NEEDS_AGENT"),
]

CHAT_TESTS = [
    "hawfar", "yo whats good", "who are you", "im going to work",
    "chale im tired", "time no dey", "explain async/await in Python briefly",
    "what do you think about AI taking over jobs",
]

SLOP = ["certainly", "of course!", "great question", "go crush it", "you got this",
        "we got this", "i'm here to help", "i'll be right here"]

STREAM_TESTS = [
    ("check my emails", True), ("yo whats good", False),
    ("what is quantum computing", False), ("search emails from Stripe", True),
    ("explain how WebSockets work briefly", False),
]


def strip(text):
    if not text: return ""
    for tag in ["think", "thought"]:
        if f"<{tag}>" in text:
            text = text.split(f"</{tag}>")[-1].strip() if f"</{tag}>" in text else ""
    return text.strip()


def make_sys(prompt, model):
    return ("/no_think\n" + prompt) if "qwen" in model.lower() else prompt


def run_provider(label, client, model, extra_body):
    eb = extra_body or {}
    r = {"label": label, "classify": [], "dispatch": [], "chat": [], "stream": []}

    # ── Classify (30 queries) ──
    for q, exp in CLASSIFY_TESTS:
        t0 = time.time()
        try:
            kwargs = {"model": model, "temperature": 0, "max_tokens": 20,
                      "messages": [{"role": "system", "content": make_sys(CLASSIFY_SYS, model)},
                                   {"role": "user", "content": q}]}
            if eb: kwargs["extra_body"] = eb
            resp = client.chat.completions.create(**kwargs)
            ans = strip(resp.choices[0].message.content or "").lower().replace(" ", "_")
            r["classify"].append({"p": exp.lower() in ans, "t": time.time() - t0, "q": q, "exp": exp, "got": ans})
        except Exception as e:
            r["classify"].append({"p": False, "t": time.time() - t0, "q": q, "exp": exp, "got": str(e)[:30]})

    # ── Dispatch with ALL 32 tools (25 queries) ──
    for q, exp in DISPATCH_TESTS:
        t0 = time.time()
        try:
            kwargs = {"model": model, "temperature": 0, "max_tokens": 200,
                      "tools": DIRECT_TOOL_SCHEMAS,
                      "messages": [{"role": "system", "content": make_sys(DISPATCH_SYS, model)},
                                   {"role": "user", "content": q}]}
            if eb: kwargs["extra_body"] = eb
            resp = client.chat.completions.create(**kwargs)
            msg = resp.choices[0].message
            tc = msg.tool_calls
            text = strip((msg.content or "").strip())
            if exp in ("NO_TOOL", "NEEDS_AGENT"):
                got = text[:25]
                passed = (not tc) and exp in text
            elif tc:
                got = tc[0].function.name
                passed = got == exp
            else:
                got = text[:25] or "(empty)"
                passed = False
            r["dispatch"].append({"p": passed, "t": time.time() - t0, "q": q, "exp": exp, "got": got})
        except Exception as e:
            r["dispatch"].append({"p": False, "t": time.time() - t0, "q": q, "exp": exp, "got": str(e)[:30]})

    # ── Chat with FRIDAY personality (8 queries) ──
    for q in CHAT_TESTS:
        t0 = time.time()
        try:
            kwargs = {"model": model, "temperature": 0.7, "max_tokens": 150,
                      "messages": [{"role": "system", "content": make_sys(CHAT_SYS, model)},
                                   {"role": "user", "content": q}]}
            if eb: kwargs["extra_body"] = eb
            resp = client.chat.completions.create(**kwargs)
            text = strip(resp.choices[0].message.content or "")
            words = len(text.split())
            slop = any(s in text.lower() for s in SLOP)
            short_q = q in ("hawfar", "yo whats good", "im going to work", "chale im tired", "time no dey")
            passed = (not slop) and (not short_q or words <= 30)
            r["chat"].append({"p": passed, "t": time.time() - t0, "q": q, "txt": text[:55]})
        except Exception as e:
            r["chat"].append({"p": False, "t": time.time() - t0, "q": q, "txt": str(e)[:40]})

    # ── Streaming TTFT (5 queries) ──
    for q, use_tools in STREAM_TESTS:
        t0 = time.time()
        ttft = None
        try:
            kwargs = {"model": model, "stream": True, "max_tokens": 80,
                      "messages": [{"role": "system", "content": make_sys("Be concise.", model)},
                                   {"role": "user", "content": q}]}
            if use_tools: kwargs["tools"] = DIRECT_TOOL_SCHEMAS
            if eb: kwargs["extra_body"] = eb
            stream = client.chat.completions.create(**kwargs)
            for chunk in stream:
                d = chunk.choices[0].delta if chunk.choices else None
                if d and (d.content or d.tool_calls) and ttft is None:
                    ttft = time.time() - t0
            r["stream"].append({"ttft": ttft or (time.time() - t0), "total": time.time() - t0})
        except:
            r["stream"].append({"ttft": time.time() - t0, "total": time.time() - t0})

    return r


if __name__ == "__main__":
    print("\n" + "=" * 78)
    print("  FRIDAY PRODUCTION BENCHMARK — REAL PROMPTS, ALL 32 TOOLS")
    print("  4 providers | 30 classify + 25 dispatch + 8 chat + 5 stream = 68 tests each")
    print("=" * 78)

    all_results = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(run_provider, l, c, m, e): l for l, c, m, e in PROVIDERS}
        for f in as_completed(futures):
            r = f.result()
            all_results[r["label"]] = r
            # Quick summary
            cp = sum(1 for x in r["classify"] if x["p"])
            dp = sum(1 for x in r["dispatch"] if x["p"])
            chp = sum(1 for x in r["chat"] if x["p"])
            print(f"  ✓ {r['label']:15} classify={cp}/30 dispatch={dp}/25 chat={chp}/8", flush=True)

    # ── Detailed Results ──
    for label in ["Groq/Qwen3", "OR/Parasail", "OR/GoogAI", "Google Direct"]:
        r = all_results[label]
        print(f"\n{'━' * 78}")
        print(f"  {label}")
        print(f"{'━' * 78}")

        # Classify
        cp = sum(1 for x in r["classify"] if x["p"])
        ca = sum(x["t"] for x in r["classify"]) / len(r["classify"])
        print(f"\n  CLASSIFY: {cp}/30  avg {ca:.2f}s")
        for x in r["classify"]:
            if not x["p"]:
                print(f"    ❌ \"{x['q'][:40]}\" → {x['got'][:25]} (want: {x['exp']})")

        # Dispatch
        dp = sum(1 for x in r["dispatch"] if x["p"])
        da = sum(x["t"] for x in r["dispatch"]) / len(r["dispatch"])
        print(f"\n  DISPATCH (32 tools): {dp}/25  avg {da:.2f}s")
        for x in r["dispatch"]:
            if not x["p"]:
                print(f"    ❌ \"{x['q'][:40]}\" → {x['got'][:25]} (want: {x['exp']})")

        # Chat
        chp = sum(1 for x in r["chat"] if x["p"])
        cha = sum(x["t"] for x in r["chat"]) / len(r["chat"])
        print(f"\n  CHAT: {chp}/8  avg {cha:.2f}s")
        for x in r["chat"]:
            icon = "✅" if x["p"] else "⚠️"
            print(f"    {icon} \"{x['q'][:25]}\" → \"{x['txt']}\"")

        # Stream
        sa = sum(x["ttft"] for x in r["stream"]) / len(r["stream"])
        st = sum(x["total"] for x in r["stream"]) / len(r["stream"])
        print(f"\n  STREAMING: TTFT avg {sa:.2f}s  Total avg {st:.2f}s")

    # ── Final Table ──
    print(f"\n{'=' * 78}")
    print(f"  FINAL SCOREBOARD")
    print(f"{'=' * 78}")
    costs = {"Groq/Qwen3": "$6.82", "OR/Parasail": "$3.43", "OR/GoogAI": "$3.43", "Google Direct": "FREE"}

    print(f"\n  {'Provider':<16} {'Classify':>9} {'Dispatch':>9} {'Chat':>6} {'TOTAL':>8} {'Avg':>7} {'TTFT':>7} {'Cost':>7} {'Vision':>7}")
    print(f"  {'─' * 80}")
    for label in ["Groq/Qwen3", "OR/Parasail", "OR/GoogAI", "Google Direct"]:
        r = all_results[label]
        cp = sum(1 for x in r["classify"] if x["p"])
        dp = sum(1 for x in r["dispatch"] if x["p"])
        chp = sum(1 for x in r["chat"] if x["p"])
        total = cp + dp + chp
        avg = sum(x["t"] for x in r["classify"] + r["dispatch"] + r["chat"]) / 63
        ttft = sum(x["ttft"] for x in r["stream"]) / len(r["stream"])
        cost = costs[label]
        vis = "No" if "Groq" in label else "Yes"
        print(f"  {label:<16} {cp:>6}/30 {dp:>6}/25 {chp:>3}/8 {total:>5}/63 {avg:>6.2f}s {ttft:>6.2f}s {cost:>7} {vis:>7}")

    scores = {l: sum(1 for x in r["classify"] + r["dispatch"] + r["chat"] if x["p"]) for l, r in all_results.items()}
    avgs = {l: sum(x["t"] for x in r["classify"] + r["dispatch"] + r["chat"]) / 63 for l, r in all_results.items()}
    ttfts = {l: sum(x["ttft"] for x in r["stream"]) / len(r["stream"]) for l, r in all_results.items()}

    print(f"\n  🏆 Accuracy: {max(scores, key=scores.get)} ({max(scores.values())}/63)")
    print(f"  ⚡ Speed:    {min(avgs, key=avgs.get)} ({min(avgs.values()):.2f}s avg)")
    print(f"  🚀 TTFT:     {min(ttfts, key=ttfts.get)} ({min(ttfts.values()):.2f}s)")
    print(f"  💰 Cost:     Google Direct — FREE")
    print()
