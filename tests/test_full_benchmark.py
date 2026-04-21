"""Full FRIDAY Architecture Benchmark — Gemma 4 31B vs Qwen3-32B

Tests all 3 LLM paths that FRIDAY actually uses:
  1. CLASSIFY — intent routing (~20 token response, slim prompt)
  2. DISPATCH — tool selection (9+ tools, pick one)
  3. CHAT — personality response (FRIDAY voice, casual/deep)

Each path has different system prompts, different tool schemas,
different expected behaviors. This tests the REAL architecture.
"""

import json
import os
import time
from datetime import datetime
from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env")

groq = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1",
)
openrouter = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
)

NOW = datetime.now().strftime("%A %d %B %Y, %H:%M")

# ═══════════════════════════════════════════════════════════════════════════════
# PATH 1: CLASSIFY — Intent Router (~1s, 20 tokens max)
# ═══════════════════════════════════════════════════════════════════════════════

CLASSIFY_PROMPT = f"""You are a router. Classify the user's intent into one agent.

Agents:
- code_agent: Code, files, git, terminal, debugging, scripts, deploy
- research_agent: Web search, factual questions about the WORLD, topic lookup
- memory_agent: ONLY for explicit memory requests — "remember this", "recall X"
- comms_agent: Email, calendar, schedule, iMessage, WhatsApp, SMS, FaceTime
- system_agent: Battery, system info, open app, screenshot, PDF, screen vision, forms
- household_agent: TV control — volume, mute, power, launch apps, pause/play
- monitor_agent: "monitor this URL", "watch for changes", "alert me when"
- briefing_agent: "Catch me up", morning brief, "any updates", "did anyone call"
- job_agent: CV, resume, cover letter, job application, apply
- social_agent: X/Twitter — tweet, post, mentions, search X
- deep_research_agent: Deep research, write a paper, detailed report
- CHAT: Casual conversation, greetings, opinions, banter

IMPORTANT: Follow-ups about YOUR OWN response → CHAT.
IMPORTANT: TV anything → household_agent, NOT memory_agent.
IMPORTANT: Device queries (battery, RAM) → system_agent, NOT research_agent.

Respond with ONLY the agent name or "CHAT". Nothing else.
Current time: {NOW}"""

CLASSIFY_TESTS = [
    ("check my emails", "comms_agent"),
    ("what is quantum computing", "research_agent"),
    ("turn on the tv and put on netflix", "household_agent"),
    ("remember that my RAEng app is due March 30", "memory_agent"),
    ("catch me up", "briefing_agent"),
    ("take a screenshot", "system_agent"),
    ("tweet this: just shipped v0.2", "social_agent"),
    ("tailor my CV for a ML engineer role at Google", "job_agent"),
    ("create a Python script that scrapes HN", "code_agent"),
    ("yo whats good bruv", "CHAT"),
    ("what's my battery at", "system_agent"),
    ("search x for what people say about Claude", "social_agent"),
    ("write a detailed report about AI in healthcare", "deep_research_agent"),
    ("text Mom saying I'll be late", "comms_agent"),
    ("put my tv volume to 30", "household_agent"),
    ("why did you say that", "CHAT"),
]

# ═══════════════════════════════════════════════════════════════════════════════
# PATH 2: DISPATCH — Direct Tool Selection (pick 1 from 9+ tools)
# ═══════════════════════════════════════════════════════════════════════════════

DISPATCH_PROMPT = f"""You are FRIDAY, Travis's AI assistant. Pick the right tool for the task.
Rules:
- Call exactly ONE tool. Never two.
- If the task needs multiple steps, respond with just: NEEDS_AGENT
- If it's casual chat or a greeting, respond with just: NO_TOOL
- "send sms" / "sms me" → use send_sms with to="me" for Travis.
Current time: {NOW}"""

DISPATCH_TOOLS = [
    {"type": "function", "function": {"name": "read_emails", "description": "Read emails from Gmail.", "parameters": {"type": "object", "properties": {"filter": {"type": "string"}, "include_body": {"type": "boolean"}}}}},
    {"type": "function", "function": {"name": "search_emails", "description": "Search Gmail with query syntax.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "get_calendar", "description": "Get calendar events.", "parameters": {"type": "object", "properties": {"view": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "search_web", "description": "Search the web using Tavily.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "read_imessages", "description": "Read iMessage conversations.", "parameters": {"type": "object", "properties": {"contact": {"type": "string"}, "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "send_imessage", "description": "Send an iMessage.", "parameters": {"type": "object", "properties": {"recipient": {"type": "string"}, "message": {"type": "string"}, "confirm": {"type": "boolean"}}, "required": ["recipient", "message"]}}},
    {"type": "function", "function": {"name": "send_sms", "description": "Send SMS via Twilio. 'me' = Travis.", "parameters": {"type": "object", "properties": {"to": {"type": "string"}, "message": {"type": "string"}}, "required": ["to", "message"]}}},
    {"type": "function", "function": {"name": "store_memory", "description": "Store info in memory.", "parameters": {"type": "object", "properties": {"content": {"type": "string"}, "category": {"type": "string"}, "importance": {"type": "integer"}}, "required": ["content", "category"]}}},
    {"type": "function", "function": {"name": "search_memory", "description": "Search FRIDAY's memory.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
]

DISPATCH_TESTS = [
    # (query, expected_tool_or_keyword, description)
    ("check my emails", "read_emails", "Email check"),
    ("what's on my calendar today", "get_calendar", "Calendar"),
    ("search emails from Stripe about payments", "search_emails", "Email search"),
    ("what processor does the M4 MacBook Air use", "search_web", "Web search"),
    ("read messages from Ellen's pap", "read_imessages", "iMessage read"),
    ("text Mom saying I'll be home late", "send_imessage", "iMessage send"),
    ("sms me saying the server is down", "send_sms", "SMS send"),
    ("remember my flight is June 15 to Accra", "store_memory", "Store memory"),
    ("what do I know about Halo glasses", "search_memory", "Memory search"),
    ("yo", "NO_TOOL", "Greeting → NO_TOOL"),
    ("draft email then check my calendar", "NEEDS_AGENT", "Multi-step → NEEDS_AGENT"),
    ("find shipping updates for Brilliant Labs glasses", "search_emails", "Specific search"),
]

# ═══════════════════════════════════════════════════════════════════════════════
# PATH 3: CHAT — Personality + Conversation (FRIDAY voice)
# ═══════════════════════════════════════════════════════════════════════════════

CHAT_PROMPT = """You are FRIDAY. Travis's AI. Built by him. Running on his machine.
Travis: 19yo Ghanaian founder based in Plymouth UK.
Voice: brilliant friend who's also an engineer. Witty, real. Never corporate.
Ghanaian slang: hawfar=what's good, oya=let's go, chale=bro, abeg=please.
Match energy. Keep casual chat to 1-2 sentences. Technical answers go deep.
NEVER say "Certainly!", "I'll be right here!", "Go crush it!" — that's AI slop.
NEVER mention agents or internal tools. You are one entity."""

CHAT_TESTS = [
    ("hawfar", ["short", "casual", "no_slop"], "Ghanaian greeting"),
    ("yo whats good", ["short", "casual"], "English greeting"),
    ("who are you", ["short", "identity", "no_slop"], "Identity question"),
    ("im going to work", ["short", "casual", "no_slop"], "Leaving message"),
    ("chale im tired", ["short", "empathy", "no_slop"], "Tired complaint"),
    ("what do you think about AI taking over jobs", ["medium", "opinion", "no_slop"], "Opinion question"),
    ("explain how async/await works in Python", ["long", "technical"], "Technical deep dive"),
    ("time no dey", ["short", "casual"], "Ghanaian urgency"),
]

SLOP_PHRASES = [
    "certainly", "of course!", "great question", "i'll be right here",
    "go crush it", "you got this", "we got this", "don't worry",
    "i'm here to help", "feel free to", "don't hesitate",
    "let me know if there's anything", "i'd be happy to",
]


# ═══════════════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════════════

def _strip_thinking(text: str) -> str:
    """Strip <think>...</think> blocks from model output."""
    if "<think>" in text:
        if "</think>" in text:
            text = text.split("</think>")[-1].strip()
        else:
            text = ""
    return text


def _make_kwargs(client, model, messages, tools=None, max_tokens=200, temperature=0):
    """Build kwargs with provider-specific settings (e.g. disable thinking for Groq/Qwen)."""
    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        kwargs["tools"] = tools

    # Qwen on Groq needs /no_think in system prompt to suppress reasoning
    # (matches how FRIDAY production code does it in llm.py)
    if "qwen" in model.lower():
        if kwargs["messages"] and kwargs["messages"][0]["role"] == "system":
            kwargs["messages"][0]["content"] = "/no_think\n" + kwargs["messages"][0]["content"]
        else:
            kwargs["messages"].insert(0, {"role": "system", "content": "/no_think"})

    return kwargs


def run_classify(client, model, label):
    print(f"\n{'─'*60}")
    print(f"  PATH 1: CLASSIFY — {label}")
    print(f"{'─'*60}")

    results = []
    for query, expected in CLASSIFY_TESTS:
        t0 = time.time()
        try:
            kwargs = _make_kwargs(client, model, [
                {"role": "system", "content": CLASSIFY_PROMPT},
                {"role": "user", "content": query},
            ], max_tokens=20)
            r = client.chat.completions.create(**kwargs)
            elapsed = time.time() - t0
            answer = _strip_thinking((r.choices[0].message.content or "").strip())
            answer = answer.lower().replace(" ", "_")
            # Normalize
            if "chat" in answer: answer = "CHAT"
            expected_l = expected.lower()
            passed = expected_l in answer.lower()
            icon = "✅" if passed else "❌"
            print(f"  {icon} {elapsed:.1f}s | {query:45} | got: {answer:25} | want: {expected}")
            results.append({"passed": passed, "time": elapsed})
        except Exception as e:
            elapsed = time.time() - t0
            print(f"  💥 {elapsed:.1f}s | {query:45} | ERROR: {str(e)[:40]}")
            results.append({"passed": False, "time": elapsed})

    passed = sum(1 for r in results if r["passed"])
    avg = sum(r["time"] for r in results) / len(results)
    print(f"\n  Score: {passed}/{len(results)} | Avg: {avg:.2f}s")
    return results


def run_dispatch(client, model, label):
    print(f"\n{'─'*60}")
    print(f"  PATH 2: DISPATCH — {label}")
    print(f"{'─'*60}")

    results = []
    for query, expected, desc in DISPATCH_TESTS:
        t0 = time.time()
        try:
            kwargs = _make_kwargs(client, model, [
                {"role": "system", "content": DISPATCH_PROMPT},
                {"role": "user", "content": query},
            ], tools=DISPATCH_TOOLS, max_tokens=200)
            r = client.chat.completions.create(**kwargs)
            elapsed = time.time() - t0
            msg = r.choices[0].message
            tc = msg.tool_calls
            text = _strip_thinking((msg.content or "").strip())

            if expected in ("NO_TOOL", "NEEDS_AGENT"):
                passed = (not tc) and (expected in text)
                got = text[:30] if text else "(empty)"
            elif tc:
                got = tc[0].function.name
                passed = got == expected
            else:
                got = text[:30] if text else "(no tool, no text)"
                passed = False

            icon = "✅" if passed else "❌"
            print(f"  {icon} {elapsed:.1f}s | {desc:25} | got: {got:25} | want: {expected}")
            results.append({"passed": passed, "time": elapsed})
        except Exception as e:
            elapsed = time.time() - t0
            print(f"  💥 {elapsed:.1f}s | {desc:25} | ERROR: {str(e)[:50]}")
            results.append({"passed": False, "time": elapsed})

    passed = sum(1 for r in results if r["passed"])
    avg = sum(r["time"] for r in results) / len(results)
    print(f"\n  Score: {passed}/{len(results)} | Avg: {avg:.2f}s")
    return results


def run_chat(client, model, label):
    print(f"\n{'─'*60}")
    print(f"  PATH 3: CHAT — {label}")
    print(f"{'─'*60}")

    results = []
    for query, checks, desc in CHAT_TESTS:
        t0 = time.time()
        try:
            kwargs = _make_kwargs(client, model, [
                {"role": "system", "content": CHAT_PROMPT},
                {"role": "user", "content": query},
            ], max_tokens=300, temperature=0.7)
            r = client.chat.completions.create(**kwargs)
            elapsed = time.time() - t0
            text = _strip_thinking((r.choices[0].message.content or "").strip())
            low = text.lower()

            issues = []
            # Check for AI slop
            if "no_slop" in checks:
                for phrase in SLOP_PHRASES:
                    if phrase in low:
                        issues.append(f"slop: '{phrase}'")
            # Check length
            words = len(text.split())
            if "short" in checks and words > 25:
                issues.append(f"too long ({words} words)")
            if "long" in checks and words < 30:
                issues.append(f"too short ({words} words)")

            passed = len(issues) == 0
            icon = "✅" if passed else "⚠️"
            preview = text.replace("\n", " ")[:60]
            detail = f" [{', '.join(issues)}]" if issues else ""
            print(f"  {icon} {elapsed:.1f}s | {desc:25} | \"{preview}\"{detail}")
            results.append({"passed": passed, "time": elapsed, "text": text})
        except Exception as e:
            elapsed = time.time() - t0
            print(f"  💥 {elapsed:.1f}s | {desc:25} | ERROR: {str(e)[:50]}")
            results.append({"passed": False, "time": elapsed, "text": ""})

    passed = sum(1 for r in results if r["passed"])
    avg = sum(r["time"] for r in results) / len(results)
    print(f"\n  Score: {passed}/{len(results)} | Avg: {avg:.2f}s")
    return results


def print_summary(label, classify, dispatch, chat):
    c_pass = sum(1 for r in classify if r["passed"])
    d_pass = sum(1 for r in dispatch if r["passed"])
    ch_pass = sum(1 for r in chat if r["passed"])
    total_pass = c_pass + d_pass + ch_pass
    total_tests = len(classify) + len(dispatch) + len(chat)

    c_avg = sum(r["time"] for r in classify) / len(classify)
    d_avg = sum(r["time"] for r in dispatch) / len(dispatch)
    ch_avg = sum(r["time"] for r in chat) / len(chat)
    total_avg = (sum(r["time"] for r in classify + dispatch + chat)) / total_tests

    print(f"\n  {label}")
    print(f"  ├─ Classify:  {c_pass}/{len(classify)}  avg {c_avg:.2f}s")
    print(f"  ├─ Dispatch:  {d_pass}/{len(dispatch)}  avg {d_avg:.2f}s")
    print(f"  ├─ Chat:      {ch_pass}/{len(chat)}  avg {ch_avg:.2f}s")
    print(f"  └─ TOTAL:     {total_pass}/{total_tests}  avg {total_avg:.2f}s")
    return total_pass, total_tests, total_avg


if __name__ == "__main__":
    print("\n" + "═" * 60)
    print("  FRIDAY FULL ARCHITECTURE BENCHMARK")
    print("  Qwen3-32B (Groq) vs Gemma 4 31B (OpenRouter)")
    print("  3 paths × 36 queries = 72 total tests")
    print("═" * 60)

    # Qwen3 on Groq
    q_classify = run_classify(groq, "qwen/qwen3-32b", "Qwen3-32B (Groq)")
    q_dispatch = run_dispatch(groq, "qwen/qwen3-32b", "Qwen3-32B (Groq)")
    q_chat = run_chat(groq, "qwen/qwen3-32b", "Qwen3-32B (Groq)")

    # Gemma 4 on OpenRouter
    g_classify = run_classify(openrouter, "google/gemma-4-31b-it", "Gemma 4 31B (OpenRouter)")
    g_dispatch = run_dispatch(openrouter, "google/gemma-4-31b-it", "Gemma 4 31B (OpenRouter)")
    g_chat = run_chat(openrouter, "google/gemma-4-31b-it", "Gemma 4 31B (OpenRouter)")

    # Final summary
    print("\n" + "═" * 60)
    print("  FINAL RESULTS")
    print("═" * 60)

    q_total, q_tests, q_avg = print_summary("QWEN3-32B (Groq)", q_classify, q_dispatch, q_chat)
    g_total, g_tests, g_avg = print_summary("GEMMA 4 31B (OpenRouter)", g_classify, g_dispatch, g_chat)

    print(f"\n{'─'*60}")
    print(f"  WINNER BY ACCURACY: {'Qwen3' if q_total > g_total else 'Gemma 4' if g_total > q_total else 'TIE'} ({max(q_total, g_total)}/{q_tests})")
    print(f"  WINNER BY SPEED:    {'Qwen3' if q_avg < g_avg else 'Gemma 4'} ({min(q_avg, g_avg):.2f}s avg)")
    print(f"{'─'*60}")
