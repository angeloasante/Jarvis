"""E2E test — Top 3 OpenRouter providers for Gemma 4 31B.

Full FRIDAY pipeline: classify + dispatch + chat + streaming TTFT.
Pinned to Parasail, Lightning AI, Google AI Studio.
All thinking stripped. Fair fight.
"""

import os, time, json
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env")

key = os.getenv("OPENROUTER_API_KEY")

def make_client():
    return OpenAI(api_key=key, base_url="https://openrouter.ai/api/v1", timeout=20.0)

PROVIDERS = [
    ("Parasail", {"order": ["Parasail"]}),
    ("Lightning AI", {"order": ["Lightning"]}),
    ("Google AI Studio", {"order": ["Google AI Studio"]}),
]
MODEL = "google/gemma-4-31b-it"

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
    ("turn on tv and put on netflix", "household_agent"), ("remember RAEng due March 30", "memory_agent"),
    ("catch me up", "briefing_agent"), ("take a screenshot", "system_agent"),
    ("tweet: just shipped v0.2", "social_agent"), ("tailor CV for ML at Google", "job_agent"),
    ("create Python script scraping HN", "code_agent"), ("yo whats good bruv", "CHAT"),
    ("what's my battery at", "system_agent"), ("search x about Claude", "social_agent"),
    ("write report about AI healthcare", "deep_research_agent"), ("text Mom I'll be late", "comms_agent"),
    ("tv volume to 30", "household_agent"), ("why did you say that", "CHAT"),
]

DISPATCH_TESTS = [
    ("check my emails", "read_emails"), ("calendar today", "get_calendar"),
    ("search emails from Stripe", "search_emails"), ("what processor does M4 use", "search_web"),
    ("read messages from Ellen's pap", "read_imessages"), ("text Mom saying late", "send_imessage"),
    ("sms me saying server down", "send_sms"), ("remember flight June 15", "store_memory"),
    ("what do I know about Halo", "search_memory"), ("yo", "NO_TOOL"),
    ("draft email then check calendar", "NEEDS_AGENT"), ("find glasses shipping", "search_emails"),
]

CHAT_TESTS = ["hawfar", "yo whats good", "who are you", "im going to work",
              "chale im tired", "time no dey", "explain async/await briefly"]

SLOP = ["certainly", "of course!", "great question", "go crush it", "you got this", "we got this", "i'm here to help"]

STREAM_TESTS = [("check my emails", TOOLS), ("yo whats good", None),
                ("what is quantum computing", None), ("search emails from Stripe", TOOLS)]


def strip(text):
    if not text: return ""
    for tag in ["think", "thought"]:
        if f"<{tag}>" in text:
            text = text.split(f"</{tag}>")[-1].strip() if f"</{tag}>" in text else ""
    return text.strip()


def run_provider(name, pref):
    client = make_client()
    eb = {"provider": pref}
    r = {"name": name, "classify": [], "dispatch": [], "chat": [], "stream": []}

    # Classify
    for q, exp in CLASSIFY_TESTS:
        t0 = time.time()
        try:
            resp = client.chat.completions.create(
                model=MODEL, temperature=0, max_tokens=20, extra_body=eb,
                messages=[{"role": "system", "content": "Classify intent. Agents: code_agent, research_agent, memory_agent, comms_agent, system_agent, household_agent, monitor_agent, briefing_agent, job_agent, social_agent, deep_research_agent, CHAT. Respond with ONLY the agent name or CHAT."},
                          {"role": "user", "content": q}])
            ans = strip(resp.choices[0].message.content or "").lower().replace(" ", "_")
            r["classify"].append({"p": exp.lower() in ans, "t": time.time() - t0, "q": q, "a": ans})
        except Exception as e:
            r["classify"].append({"p": False, "t": time.time() - t0, "q": q, "a": str(e)[:30]})

    # Dispatch
    for q, exp in DISPATCH_TESTS:
        t0 = time.time()
        try:
            resp = client.chat.completions.create(
                model=MODEL, temperature=0, max_tokens=200, tools=TOOLS, extra_body=eb,
                messages=[{"role": "system", "content": "Pick ONE tool. Multi-step→NEEDS_AGENT. Chat→NO_TOOL."},
                          {"role": "user", "content": q}])
            msg = resp.choices[0].message
            tc = msg.tool_calls
            text = strip((msg.content or "").strip())
            if exp in ("NO_TOOL", "NEEDS_AGENT"):
                got = text[:20]
                passed = (not tc) and exp in text
            elif tc:
                got = tc[0].function.name
                passed = got == exp
            else:
                got = text[:20] or "(empty)"
                passed = False
            r["dispatch"].append({"p": passed, "t": time.time() - t0, "q": q, "a": got})
        except Exception as e:
            r["dispatch"].append({"p": False, "t": time.time() - t0, "q": q, "a": str(e)[:30]})

    # Chat
    for q in CHAT_TESTS:
        t0 = time.time()
        try:
            resp = client.chat.completions.create(
                model=MODEL, temperature=0.7, max_tokens=150, extra_body=eb,
                messages=[{"role": "system", "content": "You are FRIDAY. Travis's AI. Ghanaian founder Plymouth UK. Casual=1-2 sentences. Never 'Certainly!' or 'Go crush it!'"},
                          {"role": "user", "content": q}])
            text = strip(resp.choices[0].message.content or "")
            words = len(text.split())
            slop = any(s in text.lower() for s in SLOP)
            passed = words <= 30 and not slop
            r["chat"].append({"p": passed, "t": time.time() - t0, "q": q, "a": text[:50]})
        except Exception as e:
            r["chat"].append({"p": False, "t": time.time() - t0, "q": q, "a": str(e)[:30]})

    # Streaming TTFT
    for q, tools in STREAM_TESTS:
        t0 = time.time()
        ttft = None
        try:
            kwargs = {"model": MODEL, "stream": True, "max_tokens": 80, "extra_body": eb,
                      "messages": [{"role": "user", "content": q}]}
            if tools: kwargs["tools"] = tools
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
    print("\n" + "=" * 70)
    print("  TOP 3 OPENROUTER PROVIDERS — E2E BENCHMARK")
    print("  Parasail vs Lightning AI vs Google AI Studio")
    print("  Gemma 4 31B | 35 accuracy tests + 4 streaming tests each")
    print("=" * 70)

    # Run all 3 in parallel
    results = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(run_provider, name, pref): name for name, pref in PROVIDERS}
        for f in as_completed(futures):
            r = f.result()
            results[r["name"]] = r
            print(f"  ✓ {r['name']} done", flush=True)

    # Print detailed results per provider
    for name in ["Parasail", "Lightning AI", "Google AI Studio"]:
        r = results[name]
        print(f"\n{'━' * 70}")
        print(f"  {name}")
        print(f"{'━' * 70}")

        c_pass = sum(1 for x in r["classify"] if x["p"])
        d_pass = sum(1 for x in r["dispatch"] if x["p"])
        ch_pass = sum(1 for x in r["chat"] if x["p"])
        c_avg = sum(x["t"] for x in r["classify"]) / len(r["classify"])
        d_avg = sum(x["t"] for x in r["dispatch"]) / len(r["dispatch"])
        ch_avg = sum(x["t"] for x in r["chat"]) / len(r["chat"])
        s_ttft = sum(x["ttft"] for x in r["stream"]) / len(r["stream"])

        print(f"  Classify:  {c_pass}/16  avg {c_avg:.2f}s")
        # Show misses
        for x in r["classify"]:
            if not x["p"]:
                print(f"    ❌ \"{x['q']}\" → {x['a']}")

        print(f"  Dispatch:  {d_pass}/12  avg {d_avg:.2f}s")
        for x in r["dispatch"]:
            if not x["p"]:
                print(f"    ❌ \"{x['q']}\" → {x['a']}")

        print(f"  Chat:      {ch_pass}/7   avg {ch_avg:.2f}s")
        for x in r["chat"]:
            icon = "✅" if x["p"] else "⚠️"
            print(f"    {icon} \"{x['q']}\" → \"{x['a']}\"")

        print(f"  TTFT:      avg {s_ttft:.2f}s")
        for x in r["stream"]:
            print(f"    {x['ttft']:.2f}s ttft / {x['total']:.2f}s total")

    # Final table
    print(f"\n{'=' * 70}")
    print(f"  FINAL COMPARISON")
    print(f"{'=' * 70}")
    print(f"\n  {'Provider':<20} {'Score':>7} {'Classify':>9} {'Dispatch':>9} {'Chat':>6} {'Avg':>7} {'TTFT':>7}")
    print(f"  {'─' * 62}")

    for name in ["Parasail", "Lightning AI", "Google AI Studio"]:
        r = results[name]
        c = sum(1 for x in r["classify"] if x["p"])
        d = sum(1 for x in r["dispatch"] if x["p"])
        ch = sum(1 for x in r["chat"] if x["p"])
        total = c + d + ch
        avg = sum(x["t"] for x in r["classify"] + r["dispatch"] + r["chat"]) / 35
        ttft = sum(x["ttft"] for x in r["stream"]) / len(r["stream"])
        print(f"  {name:<20} {total:>4}/35 {c:>6}/16 {d:>6}/12 {ch:>3}/7 {avg:>6.2f}s {ttft:>6.2f}s")

    # Winner
    scores = {n: sum(1 for x in r["classify"] + r["dispatch"] + r["chat"] if x["p"]) for n, r in results.items()}
    avgs = {n: sum(x["t"] for x in r["classify"] + r["dispatch"] + r["chat"]) / 35 for n, r in results.items()}
    ttfts = {n: sum(x["ttft"] for x in r["stream"]) / len(r["stream"]) for n, r in results.items()}

    print(f"\n  🏆 Accuracy: {max(scores, key=scores.get)} ({max(scores.values())}/35)")
    print(f"  ⚡ Speed:    {min(avgs, key=avgs.get)} ({min(avgs.values()):.2f}s avg)")
    print(f"  🚀 TTFT:     {min(ttfts, key=ttfts.get)} ({min(ttfts.values()):.2f}s)")
    print()
