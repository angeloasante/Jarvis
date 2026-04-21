"""Fair 3-Way Benchmark — PARALLEL, with timeouts.

Runs all 3 providers simultaneously. Each request has a 20s hard timeout.
No more hanging on OpenRouter.
"""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env")

groq = OpenAI(api_key=os.getenv("GROQ_API_KEY"), base_url="https://api.groq.com/openai/v1", timeout=20.0)
openrouter = OpenAI(api_key=os.getenv("OPENROUTER_API_KEY"), base_url="https://openrouter.ai/api/v1", timeout=20.0)
google_ai = OpenAI(api_key=os.getenv("GOOGLE_API_KEY", "").split(" ")[0], base_url="https://generativelanguage.googleapis.com/v1beta/openai/", timeout=20.0)

PROVIDERS = [
    ("Groq (Qwen3-32B)", groq, "qwen/qwen3-32b"),
    ("OpenRouter (Gemma4)", openrouter, "google/gemma-4-31b-it"),
    ("Google AI (Gemma4)", google_ai, "gemma-4-31b-it"),
]

TOOLS = [
    {"type": "function", "function": {"name": "read_emails", "description": "Read emails.", "parameters": {"type": "object", "properties": {"filter": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "search_emails", "description": "Search Gmail.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "get_calendar", "description": "Get calendar.", "parameters": {"type": "object", "properties": {"view": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "search_web", "description": "Web search.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "read_imessages", "description": "Read iMessages.", "parameters": {"type": "object", "properties": {"contact": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "send_imessage", "description": "Send iMessage.", "parameters": {"type": "object", "properties": {"recipient": {"type": "string"}, "message": {"type": "string"}}, "required": ["recipient", "message"]}}},
    {"type": "function", "function": {"name": "send_sms", "description": "Send SMS. 'me'=Travis.", "parameters": {"type": "object", "properties": {"to": {"type": "string"}, "message": {"type": "string"}}, "required": ["to", "message"]}}},
    {"type": "function", "function": {"name": "store_memory", "description": "Store in memory.", "parameters": {"type": "object", "properties": {"content": {"type": "string"}, "category": {"type": "string"}}, "required": ["content", "category"]}}},
    {"type": "function", "function": {"name": "search_memory", "description": "Search memory.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
]

CLASSIFY_TESTS = [
    ("check my emails", "comms_agent"), ("what is quantum computing", "research_agent"),
    ("turn on tv and put on netflix", "household_agent"), ("remember RAEng app due March 30", "memory_agent"),
    ("catch me up", "briefing_agent"), ("take a screenshot", "system_agent"),
    ("tweet: just shipped v0.2", "social_agent"), ("tailor my CV for ML at Google", "job_agent"),
    ("create Python script scraping HN", "code_agent"), ("yo whats good bruv", "CHAT"),
    ("what's my battery at", "system_agent"), ("search x about Claude", "social_agent"),
    ("write report about AI healthcare", "deep_research_agent"), ("text Mom I'll be late", "comms_agent"),
    ("tv volume to 30", "household_agent"), ("why did you say that", "CHAT"),
]

DISPATCH_TESTS = [
    ("check my emails", "read_emails"), ("calendar today", "get_calendar"),
    ("search emails from Stripe", "search_emails"), ("what processor does M4 use", "search_web"),
    ("read messages from Ellen's pap", "read_imessages"), ("text Mom saying I'll be late", "send_imessage"),
    ("sms me saying server is down", "send_sms"), ("remember flight June 15", "store_memory"),
    ("what do I know about Halo glasses", "search_memory"), ("yo", "NO_TOOL"),
    ("draft email then check calendar", "NEEDS_AGENT"), ("find glasses shipping updates", "search_emails"),
]

CHAT_TESTS = [
    "hawfar", "yo whats good", "who are you", "im going to work",
    "chale im tired", "explain async/await in Python briefly", "time no dey",
]

SLOP = ["certainly", "of course!", "great question", "i'll be right here", "go crush it", "you got this", "we got this"]


def strip_think(text):
    if not text: return ""
    for tag in ["think", "thought"]:
        if f"<{tag}>" in text:
            text = text.split(f"</{tag}>")[-1].strip() if f"</{tag}>" in text else ""
    return text.strip()


def make_sys(prompt, model):
    return ("/no_think\n" + prompt) if "qwen" in model.lower() else prompt


def run_one_classify(client, model, query, expected):
    t0 = time.time()
    try:
        r = client.chat.completions.create(
            model=model, temperature=0, max_tokens=20,
            messages=[{"role": "system", "content": make_sys("Classify intent into one agent. Agents: code_agent, research_agent, memory_agent, comms_agent, system_agent, household_agent, monitor_agent, briefing_agent, job_agent, social_agent, deep_research_agent, CHAT. Respond with ONLY the agent name or CHAT.", model)},
                      {"role": "user", "content": query}],
        )
        answer = strip_think(r.choices[0].message.content or "").lower().replace(" ", "_")
        return expected.lower() in answer, time.time() - t0
    except: return False, time.time() - t0


def run_one_dispatch(client, model, query, expected):
    t0 = time.time()
    try:
        r = client.chat.completions.create(
            model=model, temperature=0, max_tokens=200, tools=TOOLS,
            messages=[{"role": "system", "content": make_sys("Pick ONE tool. Multi-step→NEEDS_AGENT. Chat→NO_TOOL.", model)},
                      {"role": "user", "content": query}],
        )
        msg = r.choices[0].message
        tc = msg.tool_calls
        text = strip_think((msg.content or "").strip())
        if expected in ("NO_TOOL", "NEEDS_AGENT"):
            return (not tc) and expected in text, time.time() - t0
        elif tc:
            return tc[0].function.name == expected, time.time() - t0
        return False, time.time() - t0
    except: return False, time.time() - t0


def run_one_chat(client, model, query):
    t0 = time.time()
    try:
        r = client.chat.completions.create(
            model=model, temperature=0.7, max_tokens=150,
            messages=[{"role": "system", "content": make_sys("You are FRIDAY. Travis's AI. Ghanaian founder Plymouth UK. Be concise for casual chat (1-2 sentences). Never say 'Certainly!' or 'Go crush it!'", model)},
                      {"role": "user", "content": query}],
        )
        text = strip_think(r.choices[0].message.content or "")
        words = len(text.split())
        has_slop = any(s in text.lower() for s in SLOP)
        passed = words <= 30 and not has_slop
        return passed, time.time() - t0, text[:50]
    except Exception as e:
        return False, time.time() - t0, str(e)[:40]


def run_one_stream(client, model, query, tools=None):
    t0 = time.time()
    try:
        kwargs = {"model": model, "stream": True, "max_tokens": 80,
                  "messages": [{"role": "system", "content": make_sys("Be concise.", model)},
                               {"role": "user", "content": query}]}
        if tools: kwargs["tools"] = tools
        stream = client.chat.completions.create(**kwargs)
        ttft = None
        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and (delta.content or delta.tool_calls) and ttft is None:
                ttft = time.time() - t0
        return ttft or (time.time() - t0), time.time() - t0
    except: return time.time() - t0, time.time() - t0


def run_provider(label, client, model):
    """Run all tests for one provider. Returns dict of results."""
    print(f"\n  Running {label}...", flush=True)
    results = {"label": label}

    # Classify
    c_results = []
    for q, exp in CLASSIFY_TESTS:
        p, t = run_one_classify(client, model, q, exp)
        c_results.append({"p": p, "t": t})
    results["classify"] = c_results

    # Dispatch
    d_results = []
    for q, exp in DISPATCH_TESTS:
        p, t = run_one_dispatch(client, model, q, exp)
        d_results.append({"p": p, "t": t})
    results["dispatch"] = d_results

    # Chat
    ch_results = []
    for q in CHAT_TESTS:
        p, t, txt = run_one_chat(client, model, q)
        ch_results.append({"p": p, "t": t, "txt": txt})
    results["chat"] = ch_results

    # Streaming TTFT
    stream_queries = [("check my emails", TOOLS), ("yo whats good", None),
                      ("what is quantum computing", None), ("explain WebSockets", None)]
    s_results = []
    for q, tools in stream_queries:
        ttft, total = run_one_stream(client, model, q, tools)
        s_results.append({"ttft": ttft, "total": total})
    results["stream"] = s_results

    return results


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("  FAIR 3-WAY BENCHMARK — PARALLEL, 20s TIMEOUT")
    print("  All thinking stripped. /no_think for Qwen.")
    print("=" * 70)

    # Run all 3 providers in parallel
    all_results = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(run_provider, label, client, model): label
                   for label, client, model in PROVIDERS}
        for future in as_completed(futures):
            r = future.result()
            all_results[r["label"]] = r
            print(f"  ✓ {r['label']} done", flush=True)

    # ── Print Results ──
    print(f"\n{'=' * 70}")
    print(f"  RESULTS")
    print(f"{'=' * 70}")

    for label in ["Groq (Qwen3-32B)", "OpenRouter (Gemma4)", "Google AI (Gemma4)"]:
        r = all_results[label]
        c_pass = sum(1 for x in r["classify"] if x["p"])
        d_pass = sum(1 for x in r["dispatch"] if x["p"])
        ch_pass = sum(1 for x in r["chat"] if x["p"])
        c_avg = sum(x["t"] for x in r["classify"]) / len(r["classify"])
        d_avg = sum(x["t"] for x in r["dispatch"]) / len(r["dispatch"])
        ch_avg = sum(x["t"] for x in r["chat"]) / len(r["chat"])
        s_ttft = sum(x["ttft"] for x in r["stream"]) / len(r["stream"])
        s_total = sum(x["total"] for x in r["stream"]) / len(r["stream"])

        print(f"\n  ── {label} ──")
        print(f"  Classify:  {c_pass:>2}/16  avg {c_avg:.2f}s")
        print(f"  Dispatch:  {d_pass:>2}/12  avg {d_avg:.2f}s")
        print(f"  Chat:      {ch_pass:>2}/7   avg {ch_avg:.2f}s")
        print(f"  TTFT:      avg {s_ttft:.2f}s  (total {s_total:.2f}s)")

        # Show chat responses
        print(f"  Chat samples:")
        for q, x in zip(CHAT_TESTS[:3], r["chat"][:3]):
            icon = "✅" if x["p"] else "⚠️"
            print(f"    {icon} \"{q}\" → \"{x['txt']}\"")

    # ── Final Table ──
    print(f"\n{'=' * 70}")
    print(f"  FINAL COMPARISON")
    print(f"{'=' * 70}")
    costs = {"Groq (Qwen3-32B)": "$6.82/mo", "OpenRouter (Gemma4)": "$3.43/mo", "Google AI (Gemma4)": "FREE"}

    print(f"\n  {'Provider':<25} {'Score':>7} {'Avg':>7} {'TTFT':>7} {'Cost':>10} {'Vision':>7}")
    print(f"  {'─' * 68}")
    for label in ["Groq (Qwen3-32B)", "OpenRouter (Gemma4)", "Google AI (Gemma4)"]:
        r = all_results[label]
        total = sum(1 for x in r["classify"] + r["dispatch"] + r["chat"] if x["p"])
        avg = sum(x["t"] for x in r["classify"] + r["dispatch"] + r["chat"]) / 35
        ttft = sum(x["ttft"] for x in r["stream"]) / len(r["stream"])
        cost = costs[label]
        vision = "No" if "Groq" in label else "Yes"
        print(f"  {label:<25} {total:>4}/35 {avg:>6.2f}s {ttft:>6.2f}s {cost:>10} {vision:>7}")

    # Winners
    scores = {l: sum(1 for x in r["classify"] + r["dispatch"] + r["chat"] if x["p"]) for l, r in all_results.items()}
    avgs = {l: sum(x["t"] for x in r["classify"] + r["dispatch"] + r["chat"]) / 35 for l, r in all_results.items()}
    ttfts = {l: sum(x["ttft"] for x in r["stream"]) / len(r["stream"]) for l, r in all_results.items()}

    print(f"\n  🏆 Accuracy: {max(scores, key=scores.get)} ({max(scores.values())}/35)")
    print(f"  ⚡ Speed:    {min(avgs, key=avgs.get)} ({min(avgs.values()):.2f}s avg)")
    print(f"  🚀 TTFT:     {min(ttfts, key=ttfts.get)} ({min(ttfts.values()):.2f}s)")
    print(f"  💰 Cost:     Google AI (Gemma4) — FREE")
    print()
