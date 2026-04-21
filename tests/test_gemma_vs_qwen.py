"""Head-to-head: Gemma 4 31B (OpenRouter) vs Qwen3-32B (Groq)

Tests: tool calling accuracy, speed, response quality.
Uses FRIDAY's actual tool schemas — not synthetic benchmarks.
"""

import json
import os
import time
from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env")

# ── Clients ──────────────────────────────────────────────────────────────────

groq = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1",
)

openrouter = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
)

# ── FRIDAY's actual tool schemas (subset used in direct dispatch) ────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_emails",
            "description": "Read emails from Gmail inbox. Returns subject, sender, date, body.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filter": {"type": "string", "description": "Filter: 'unread', 'today', 'all'"},
                    "include_body": {"type": "boolean", "description": "Include email body text"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_emails",
            "description": "Search Gmail with query syntax (from:, subject:, has:attachment).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Gmail search query"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_calendar",
            "description": "Get calendar events. Supports: today, tomorrow, this week, specific date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "view": {"type": "string", "description": "View: 'today', 'tomorrow', 'week', or ISO date"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the web using Tavily. Returns AI answer + sources.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_imessages",
            "description": "Read iMessage conversations. Filter by contact name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "contact": {"type": "string", "description": "Contact name to filter"},
                    "limit": {"type": "integer", "description": "Number of messages"},
                    "direction": {"type": "string", "description": "'sent', 'received', or both"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_imessage",
            "description": "Send an iMessage text to a contact.",
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient": {"type": "string", "description": "Contact name or phone number"},
                    "message": {"type": "string", "description": "Message text"},
                    "confirm": {"type": "boolean", "description": "Must be true to actually send"},
                },
                "required": ["recipient", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_sms",
            "description": "Send SMS via Twilio. Use 'me' to send to Travis.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Phone number or 'me'"},
                    "message": {"type": "string", "description": "Message text"},
                },
                "required": ["to", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "store_memory",
            "description": "Store information in FRIDAY's memory for future recall.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "What to remember"},
                    "category": {"type": "string", "description": "project, decision, lesson, preference, person, general"},
                    "importance": {"type": "integer", "description": "1 (trivial) to 10 (critical)"},
                },
                "required": ["content", "category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": "Search FRIDAY's memory for stored information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
        },
    },
]

SYSTEM_PROMPT = """You are FRIDAY, Travis's AI assistant. Pick the right tool for the task.
Rules:
- Call exactly ONE tool. Never two.
- If the task needs multiple steps, respond with just: NEEDS_AGENT
- If it's casual chat or a greeting, respond with just: NO_TOOL
Current time: Wednesday 09 April 2026, 01:30"""

# ── Test queries with expected answers ───────────────────────────────────────

TESTS = [
    # (query, expected_tool, expected_args_check, description)
    ("check my emails", "read_emails", lambda a: a.get("filter") in ("unread", "all"), "Basic email check"),
    ("what's on my calendar today", "get_calendar", lambda a: "today" in str(a.get("view", "")).lower(), "Calendar today"),
    ("search emails from Stripe", "search_emails", lambda a: "stripe" in a.get("query", "").lower(), "Email search"),
    ("what is quantum computing", "search_web", lambda a: "quantum" in a.get("query", "").lower(), "Web search"),
    ("read messages from Ellen's pap", "read_imessages", lambda a: "ellen" in a.get("contact", "").lower(), "iMessage read"),
    ("text Mom saying I'll be home late", "send_imessage", lambda a: a.get("recipient", "").lower() in ("mom", "mum"), "iMessage send"),
    ("sms me saying the server is down", "send_sms", lambda a: a.get("to", "").lower() == "me", "SMS send"),
    ("remember that my RAEng app is due March 30", "store_memory", lambda a: "raeng" in a.get("content", "").lower(), "Store memory"),
    ("what do I know about the Halo glasses", "search_memory", lambda a: "halo" in a.get("query", "").lower(), "Search memory"),
    ("yo whats good", None, None, "Greeting (should be NO_TOOL)"),
    ("draft an email to John about the meeting then check my calendar", None, None, "Multi-step (should be NEEDS_AGENT)"),
    ("find emails about my Brilliant Labs glasses shipping", "search_emails", lambda a: "brilliant" in a.get("query", "").lower(), "Specific email search"),
]


def test_model(client, model_name, label):
    """Run all tests against a model, return results."""
    results = []
    total_time = 0

    print(f"\n{'='*60}")
    print(f"  {label} ({model_name})")
    print(f"{'='*60}")

    for query, expected_tool, args_check, desc in TESTS:
        t0 = time.time()
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": query},
                ],
                tools=TOOLS,
                temperature=0,
                max_tokens=200,
            )
            elapsed = time.time() - t0
            total_time += elapsed

            # Extract result
            msg = response.choices[0].message
            tool_calls = msg.tool_calls
            text = msg.content or ""

            if expected_tool is None:
                # Should NOT call a tool
                if not tool_calls and ("NO_TOOL" in text or "NEEDS_AGENT" in text):
                    status = "PASS"
                    detail = text.strip()[:30]
                elif tool_calls:
                    status = "FAIL"
                    detail = f"called {tool_calls[0].function.name} (should be NO_TOOL/NEEDS_AGENT)"
                else:
                    status = "PASS"
                    detail = text.strip()[:30]
            else:
                if not tool_calls:
                    status = "FAIL"
                    detail = f"no tool call, got: {text[:40]}"
                else:
                    tc = tool_calls[0]
                    name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments)
                    except:
                        args = {}

                    if name != expected_tool:
                        status = "FAIL"
                        detail = f"called {name}, expected {expected_tool}"
                    elif args_check and not args_check(args):
                        status = "PARTIAL"
                        detail = f"right tool, wrong args: {json.dumps(args)[:60]}"
                    else:
                        status = "PASS"
                        detail = f"{name}({json.dumps(args)[:40]})"

        except Exception as e:
            elapsed = time.time() - t0
            total_time += elapsed
            status = "ERROR"
            detail = str(e)[:60]

        icon = {"PASS": "✅", "FAIL": "❌", "PARTIAL": "⚠️", "ERROR": "💥"}[status]
        print(f"  {icon} {elapsed:.1f}s | {desc:30} | {detail}")
        results.append({"desc": desc, "status": status, "time": elapsed})

    # Summary
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    partial = sum(1 for r in results if r["status"] == "PARTIAL")
    errors = sum(1 for r in results if r["status"] == "ERROR")
    avg_time = total_time / len(results)

    print(f"\n  Score: {passed}/{len(results)} pass, {failed} fail, {partial} partial, {errors} error")
    print(f"  Avg time: {avg_time:.1f}s | Total: {total_time:.1f}s")
    return results, avg_time


if __name__ == "__main__":
    print("\n  FRIDAY Tool Calling Benchmark")
    print("  Gemma 4 31B (OpenRouter) vs Qwen3-32B (Groq)")
    print("  12 queries, FRIDAY's actual tool schemas\n")

    qwen_results, qwen_avg = test_model(groq, "qwen/qwen3-32b", "QWEN3-32B (Groq)")
    gemma_results, gemma_avg = test_model(openrouter, "google/gemma-4-31b-it", "GEMMA 4 31B (OpenRouter)")

    # Head to head
    print(f"\n{'='*60}")
    print(f"  HEAD TO HEAD")
    print(f"{'='*60}")

    qwen_pass = sum(1 for r in qwen_results if r["status"] == "PASS")
    gemma_pass = sum(1 for r in gemma_results if r["status"] == "PASS")

    print(f"  Accuracy:  Qwen3 {qwen_pass}/{len(TESTS)}  vs  Gemma4 {gemma_pass}/{len(TESTS)}")
    print(f"  Avg speed: Qwen3 {qwen_avg:.1f}s  vs  Gemma4 {gemma_avg:.1f}s")

    # Per-query comparison
    print(f"\n  {'Query':<32} {'Qwen3':>8} {'Gemma4':>8} {'Winner':>8}")
    print(f"  {'-'*56}")
    for q, g in zip(qwen_results, gemma_results):
        qtime = f"{q['time']:.1f}s"
        gtime = f"{g['time']:.1f}s"
        if q["status"] == "PASS" and g["status"] != "PASS":
            winner = "Qwen"
        elif g["status"] == "PASS" and q["status"] != "PASS":
            winner = "Gemma"
        elif q["time"] < g["time"]:
            winner = "Qwen"
        else:
            winner = "Gemma"
        print(f"  {q['desc']:<32} {qtime:>8} {gtime:>8} {winner:>8}")
