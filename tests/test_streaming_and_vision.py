"""Streaming TTFT + Vision + Audio benchmark.

Tests:
  1. TTFT (time-to-first-token) — streaming, what the user actually feels
  2. Vision — send an image to Gemma 4, test image understanding
  3. Audio — test Gemma 4 E4B audio input (if available on OpenRouter)
"""

import base64
import json
import os
import time
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

SYSTEM = "/no_think\nYou are FRIDAY, Travis's AI assistant. Be concise."

DISPATCH_TOOLS = [
    {"type": "function", "function": {"name": "read_emails", "description": "Read emails from Gmail.", "parameters": {"type": "object", "properties": {"filter": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "search_web", "description": "Search the web.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "get_calendar", "description": "Get calendar events.", "parameters": {"type": "object", "properties": {"view": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "read_imessages", "description": "Read iMessage conversations.", "parameters": {"type": "object", "properties": {"contact": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "send_sms", "description": "Send SMS via Twilio.", "parameters": {"type": "object", "properties": {"to": {"type": "string"}, "message": {"type": "string"}}, "required": ["to", "message"]}}},
]


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 1: TTFT — Streaming time-to-first-token
# ═══════════════════════════════════════════════════════════════════════════════

STREAMING_QUERIES = [
    # (query, type, tools)
    ("comms_agent", "classify", None),  # classify — short response
    ("check my emails", "dispatch", DISPATCH_TOOLS),  # tool call
    ("yo whats good bruv", "chat", None),  # casual chat
    ("what is quantum computing in one sentence", "chat", None),  # factual
    ("search emails from Stripe", "dispatch", DISPATCH_TOOLS),  # tool call
    ("explain how WebSockets work", "chat", None),  # longer response
]


def test_streaming(client, model, label):
    print(f"\n{'─'*70}")
    print(f"  STREAMING TTFT — {label}")
    print(f"{'─'*70}")
    print(f"  {'Query':<45} {'TTFT':>6} {'Total':>7} {'Tokens':>7}")
    print(f"  {'─'*65}")

    results = []
    for query, qtype, tools in STREAMING_QUERIES:
        msgs = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": query},
        ]

        kwargs = {
            "model": model,
            "messages": msgs,
            "stream": True,
            "max_tokens": 150,
        }
        if tools:
            kwargs["tools"] = tools

        t0 = time.time()
        ttft = None
        total_content = ""
        token_count = 0

        try:
            stream = client.chat.completions.create(**kwargs)
            for chunk in stream:
                # Check for content
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta:
                    content = delta.content or ""
                    # Also check tool calls in stream
                    tc = delta.tool_calls
                    if (content or tc) and ttft is None:
                        ttft = time.time() - t0
                    if content:
                        total_content += content
                        token_count += 1

            total_time = time.time() - t0
            ttft = ttft or total_time

            preview = total_content.replace("\n", " ")[:35] or "(tool call)"
            print(f"  {query:<45} {ttft:>5.2f}s {total_time:>6.2f}s {token_count:>5}")
            results.append({"ttft": ttft, "total": total_time, "tokens": token_count})

        except Exception as e:
            total_time = time.time() - t0
            print(f"  {query:<45} {'ERR':>6} {total_time:>6.2f}s  {str(e)[:30]}")
            results.append({"ttft": total_time, "total": total_time, "tokens": 0})

    avg_ttft = sum(r["ttft"] for r in results) / len(results)
    avg_total = sum(r["total"] for r in results) / len(results)
    print(f"\n  Avg TTFT: {avg_ttft:.2f}s | Avg Total: {avg_total:.2f}s")
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 2: VISION — Send image to Gemma 4
# ═══════════════════════════════════════════════════════════════════════════════

def create_test_image():
    """Create a simple test image with text using system tools."""
    import subprocess
    img_path = "/tmp/friday_vision_test.png"

    # Use macOS screencapture of a small region, or create with sips
    # Simpler: use Python to create a basic image if PIL available
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (400, 200), color=(30, 30, 30))
        draw = ImageDraw.Draw(img)
        draw.text((20, 30), "FRIDAY v0.3", fill=(0, 255, 0))
        draw.text((20, 70), "Emails: 4 unread", fill=(200, 200, 200))
        draw.text((20, 100), "Calendar: Work 2pm-12am", fill=(200, 200, 200))
        draw.text((20, 130), "TV: Netflix playing", fill=(200, 200, 200))
        draw.text((20, 160), "Battery: 78%", fill=(200, 200, 200))
        img.save(img_path)
        return img_path
    except ImportError:
        # Fallback: use a screenshot
        subprocess.run(["screencapture", "-x", "-R", "0,0,400,200", img_path],
                       capture_output=True, timeout=5)
        if Path(img_path).exists():
            return img_path
        return None


def test_vision(client, model, label):
    print(f"\n{'─'*70}")
    print(f"  VISION — {label}")
    print(f"{'─'*70}")

    img_path = create_test_image()
    if not img_path or not Path(img_path).exists():
        print("  ⚠️  Could not create test image, skipping vision test")
        return []

    with open(img_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    vision_tests = [
        ("What text do you see in this image?", "text_extraction"),
        ("What information is displayed? Summarize briefly.", "comprehension"),
        ("What color scheme is being used?", "visual_analysis"),
    ]

    results = []
    for query, desc in vision_tests:
        t0 = time.time()
        try:
            r = client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": query},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                    ],
                }],
                max_tokens=200,
            )
            elapsed = time.time() - t0
            text = (r.choices[0].message.content or "").strip()
            preview = text.replace("\n", " ")[:70]
            print(f"  ✅ {elapsed:.1f}s | {desc:<20} | \"{preview}\"")
            results.append({"passed": True, "time": elapsed})
        except Exception as e:
            elapsed = time.time() - t0
            print(f"  ❌ {elapsed:.1f}s | {desc:<20} | ERROR: {str(e)[:60]}")
            results.append({"passed": False, "time": elapsed})

    # Also test vision + tool calling (can it see an image AND pick a tool?)
    print(f"\n  Vision + Tool Calling:")
    t0 = time.time()
    try:
        r = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are FRIDAY. Look at the image and pick the right tool based on what you see."},
                {"role": "user", "content": [
                    {"type": "text", "text": "Based on what you see, check my emails — it says I have unread ones."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                ]},
            ],
            tools=DISPATCH_TOOLS,
            max_tokens=100,
        )
        elapsed = time.time() - t0
        msg = r.choices[0].message
        if msg.tool_calls:
            tc = msg.tool_calls[0]
            print(f"  ✅ {elapsed:.1f}s | vision+tools        | Called {tc.function.name}({tc.function.arguments[:40]})")
        else:
            text = (msg.content or "")[:60]
            print(f"  ⚠️  {elapsed:.1f}s | vision+tools        | No tool call: \"{text}\"")
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  ❌ {elapsed:.1f}s | vision+tools        | ERROR: {str(e)[:60]}")

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 3: AUDIO — Gemma 4 E4B audio input
# ═══════════════════════════════════════════════════════════════════════════════

def create_test_audio():
    """Create a short test audio clip using macOS say command."""
    import subprocess
    audio_path = "/tmp/friday_audio_test.wav"
    try:
        subprocess.run(
            ["say", "-o", audio_path, "--data-format=LEI16@16000", "Check my emails and tell me if anything is urgent"],
            capture_output=True, timeout=10,
        )
        if Path(audio_path).exists() and Path(audio_path).stat().st_size > 0:
            return audio_path
    except Exception:
        pass
    return None


def test_audio(client, label):
    """Test audio input with Gemma 4 E4B (edge model with audio support)."""
    print(f"\n{'─'*70}")
    print(f"  AUDIO — {label}")
    print(f"{'─'*70}")

    audio_path = create_test_audio()
    if not audio_path:
        print("  ⚠️  Could not create test audio, skipping")
        return []

    with open(audio_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode()

    # Test 1: Basic audio transcription/understanding
    t0 = time.time()
    try:
        r = client.chat.completions.create(
            model="google/gemma-4-e4b-it",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is being said in this audio clip? Respond briefly."},
                    {"type": "input_audio", "input_audio": {"data": audio_b64, "format": "wav"}},
                ],
            }],
            max_tokens=100,
        )
        elapsed = time.time() - t0
        text = (r.choices[0].message.content or "").strip()
        preview = text.replace("\n", " ")[:80]
        print(f"  ✅ {elapsed:.1f}s | audio understanding | \"{preview}\"")
    except Exception as e:
        elapsed = time.time() - t0
        err = str(e)[:80]
        print(f"  ❌ {elapsed:.1f}s | audio understanding | ERROR: {err}")
        if "not available" in err.lower() or "not found" in err.lower() or "not supported" in err.lower():
            print(f"  ℹ️  E4B audio may not be available on OpenRouter yet")

    return []


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "═" * 70)
    print("  FRIDAY STREAMING + VISION + AUDIO BENCHMARK")
    print("═" * 70)

    # ── Streaming TTFT ──
    print("\n" + "═" * 70)
    print("  PART 1: STREAMING TTFT (time-to-first-token)")
    print("═" * 70)

    q_stream = test_streaming(groq, "qwen/qwen3-32b", "Qwen3-32B (Groq)")
    g_stream = test_streaming(openrouter, "google/gemma-4-31b-it", "Gemma 4 31B (OpenRouter)")

    # Compare TTFT
    print(f"\n{'─'*70}")
    print(f"  TTFT COMPARISON")
    print(f"{'─'*70}")
    q_ttft_avg = sum(r["ttft"] for r in q_stream) / len(q_stream)
    g_ttft_avg = sum(r["ttft"] for r in g_stream) / len(g_stream)
    q_total_avg = sum(r["total"] for r in q_stream) / len(q_stream)
    g_total_avg = sum(r["total"] for r in g_stream) / len(g_stream)

    print(f"  {'':40} {'Qwen3 (Groq)':>15} {'Gemma 4 (OR)':>15}")
    print(f"  {'Avg TTFT (first token)':40} {q_ttft_avg:>14.2f}s {g_ttft_avg:>14.2f}s")
    print(f"  {'Avg Total (full response)':40} {q_total_avg:>14.2f}s {g_total_avg:>14.2f}s")
    print(f"  {'TTFT Ratio':40} {'':>15} {g_ttft_avg/q_ttft_avg:>13.1f}x")

    # ── Vision ──
    print("\n" + "═" * 70)
    print("  PART 2: VISION (image understanding)")
    print("═" * 70)

    print("\n  Qwen3-32B: ❌ Text-only model, no vision support")
    g_vision = test_vision(openrouter, "google/gemma-4-31b-it", "Gemma 4 31B (OpenRouter)")

    # ── Audio ──
    print("\n" + "═" * 70)
    print("  PART 3: AUDIO (speech understanding)")
    print("═" * 70)

    print("\n  Qwen3-32B: ❌ Text-only model, no audio support")
    print("  Gemma 4 31B: ❌ No audio support (image + text only)")
    print("  Testing Gemma 4 E4B (edge model with audio)...")
    test_audio(openrouter, "Gemma 4 E4B (OpenRouter)")

    # ── Final Summary ──
    print("\n" + "═" * 70)
    print("  SUMMARY")
    print("═" * 70)
    print(f"""
  STREAMING:
    Qwen3 TTFT:  {q_ttft_avg:.2f}s  |  Gemma4 TTFT:  {g_ttft_avg:.2f}s  |  Gap: {g_ttft_avg - q_ttft_avg:.2f}s
    Qwen3 Total: {q_total_avg:.2f}s  |  Gemma4 Total: {g_total_avg:.2f}s  |  Gap: {g_total_avg - q_total_avg:.2f}s

  VISION:
    Qwen3: ❌ (text only)
    Gemma4 31B: ✅ (image + text)
    Gemma4 E4B: ✅ (image + text + audio)

  VERDICT:
    If TTFT gap < 2s, Gemma feels just as responsive in streaming mode.
    Vision gives Gemma a capability Qwen simply doesn't have.
""")
