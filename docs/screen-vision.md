# Screen Vision

FRIDAY's screen-understanding stack: take screenshots, OCR them with Apple Vision, ask a VLM what's on screen, scroll-and-stitch a full page, and solve every question on a worksheet straight into a `.docx`.

On-command only. FRIDAY never watches the screen passively — every tool checks `FRIDAY_SCREEN_ACCESS=true` in `.env` before running.

Source: [friday/tools/screen_tools.py](../friday/tools/screen_tools.py)
Wired into: [friday/agents/system_agent.py](../friday/agents/system_agent.py), [friday/core/tool_dispatch.py](../friday/core/tool_dispatch.py)

---

## The 6 tools

| Tool | Backend | Latency | Output |
|---|---|---|---|
| `capture_screen` | `screencapture` (native) | ~100 ms | PNG + base64 |
| `ocr_screen` | Apple Vision (local) | ~300–800 ms | plain text |
| `ask_about_screen` | Qwen2.5-VL via Ollama, cloud LLM fallback | 1–5 s | answer text |
| `read_screen` | Apple Vision (wraps OCR + cleaning) | ~1 s viewport / N×1s full-page | clean text |
| `capture_full_page` | scroll + OCR loop | ~1 s × pages | concatenated text |
| `solve_screen_questions` | full-page OCR + cloud LLM + python-docx | 10–30 s | `.docx` saved |

All screenshots land in `~/Downloads/friday_screenshots/` (48h TTL, auto-cleaned on every capture). `.docx` answers land in `~/Documents/friday_files/`.

---

### 1. `capture_screen`

```python
async def capture_screen(region: dict = None) -> ToolResult
```

Shells out to macOS `screencapture -x`. Optional `region={"x", "y", "w", "h"}` clips to a rectangle.

**Returns:** `{saved_path, image_b64, media_type, size_bytes, timestamp}`.

The base64 is inline so downstream tools (VLM calls) don't re-read the file. Used as the first step inside `ocr_screen`, `ask_about_screen`, and the full-page loop.

**Use:** "take a screenshot", "screenshot this area".

---

### 2. `ocr_screen`

```python
async def ocr_screen(image_path: str = None) -> ToolResult
```

Local OCR via Apple's **Vision framework** (`VNRecognizeTextRequest`). Invoked by writing a tiny Swift script and executing it with `swift -e`:

```swift
let handler = VNImageRequestHandler(data: tiffData, options: [:])
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
try handler.perform([request])
```

Each `VNRecognizedTextObservation`'s top candidate is printed line by line. No network, no API key, no model download — Vision ships with macOS.

If `image_path` is omitted, it takes a fresh screenshot first. Times out at 30 s.

**Returns:** `{text, image_path, char_count, line_count}`.

**Use:** "read the text on screen", "OCR this screenshot".

---

### 3. `ask_about_screen`

```python
async def ask_about_screen(query: str, image_path: str = None) -> ToolResult
```

The VLM path. Captures (or loads) an image, base64-encodes it, and asks Qwen2.5-VL via Ollama:

```python
response = ollama.chat(
    model="qwen2.5vl:7b",
    messages=[{"role": "user", "content": prompt, "images": [image_b64]}],
)
```

**Graceful degradation ladder** — if the vision model isn't pulled:

1. Run `ocr_screen` to get text.
2. Feed the text plus the user's query into `cloud_chat` (Groq / OpenAI / Anthropic — whichever backend is configured in `friday/core/llm.py`).
3. Last resort: return the raw OCR text wrapped in a "here's what I can read" prefix.

Means `ask_about_screen` always returns *something* useful, even on a fresh install without Ollama.

**Returns:** `{answer, image_path, model}`. `model` is `"qwen2.5vl:7b"` | `"ocr_fallback"` | `"ocr_raw"`.

**Use:** "what's on my screen", "what error is this", "what language is this code", "what app is open".

---

### 4. `read_screen`

```python
async def read_screen(app: str = None, full_page: bool = False) -> ToolResult
```

General-purpose clean-text reader. Wraps `ocr_screen` (viewport) or `capture_full_page` (full), then strips UI chrome — menu bars (`File | Edit | View | Insert | Format | Tools | Window | Help`), bare URLs, tab titles with repeated `...` / `…`, and lines under 3 chars.

If `app` is given, activates it first via AppleScript so the target window is frontmost.

**Returns:** `{text, pages_captured, char_count, line_count}`.

**Use:** "read the article", "read the job posting on screen", "what does this page say" — general-purpose, not just Q&A.

---

### 5. `capture_full_page`

```python
async def capture_full_page(max_scrolls: int = 20, app: str = None) -> ToolResult
```

The scroll-and-stitch trick. Needed because a screen is a viewport; a page is usually longer.

**Flow:**

1. If `app` given, activate via `osascript`. Click the window centre so the content area has keyboard focus.
2. `Cmd+Up` to scroll to top (works in Safari, Chrome, Preview, Word, Pages, Notion, PDFs).
3. Loop up to `max_scrolls`:
   - Find the frontmost window's bounds via System Events AppleScript (picks the *largest* window by area so toolbar mini-windows don't steal the capture).
   - `screencapture -x -R x,y,w,h` just that window.
   - OCR it with Apple Vision (via the internal `_ocr_image` helper).
   - Delete the PNG (cleanup as we go — full pages can be 20+ screenshots).
   - Compare against the previous viewport's text via `_text_overlap` (set-based overlap ratio on content lines, filtering UI chrome first).
   - If overlap > 0.85 for **two frames in a row**, we've hit the bottom — stop. One frame isn't enough; long pages often have repeated headers.
   - Otherwise `_dedupe_text` strips the overlapping prefix from the new viewport and appends.
   - 15 × Down-arrow (AppleScript `key code 125`) to scroll. More reliable than Page Down across apps.
4. Return the concatenated deduplicated text.

**Returns:** `{text, pages_captured, char_count, line_count}`.

The overlap detection lives in [`_filter_content_lines`](../friday/tools/screen_tools.py) and [`_text_overlap`](../friday/tools/screen_tools.py). The dedup join is in [`_dedupe_text`](../friday/tools/screen_tools.py) — it walks the new viewport's lines, treats everything under 5 chars as noise, and finds the first genuinely-new content line.

**Use:** "read the whole page", "capture everything in this document".

---

### 6. `solve_screen_questions`

```python
async def solve_screen_questions(save_path: str = None, app: str = None, full_page: bool = True) -> ToolResult
```

The headline workflow — capture a worksheet / quiz / problem set and get answers in a formatted Word doc.

**Flow:**

1. Capture: `capture_full_page` if `full_page=True` (default), else single-viewport `ocr_screen`.
2. Clean OCR: strip menus, bare URLs, tab-title noise.
3. Truncate if > 8000 chars — keep first 5000 and last 3000 with a `[...middle content...]` marker. Lets the free-tier Groq limit absorb long worksheets without losing the questions at either end.
4. Send to `cloud_chat` with an expert-tutor system prompt: identify every question, solve completely, show working, cite multiple-choice answers, use markdown headings / numbered lists / bold for final answers. `max_tokens=8000`.
5. Parse the markdown into a proper `.docx` via [`_markdown_to_docx`](../friday/tools/screen_tools.py) and [`_add_rich_text`](../friday/tools/screen_tools.py). Handles `#`/`##`/`###` headings, `**bold**`, `*italic*`, `- bullets`, `1.` numbered lists, and inline formatting within paragraphs. Uses `python-docx` (`Document`, `Pt`, `RGBColor`, `WD_ALIGN_PARAGRAPH`).
6. Title page centred: "Screen Questions — Solved by FRIDAY", date, page count.
7. Save to `save_path` or default `~/Documents/friday_files/Screen_Answers_<timestamp>.docx`. Falls back to `.txt` if `python-docx` not installed.

**Returns:** `{answers, save_path, pages_captured, questions_text_length, answers_length}`.

**Use:** "solve the questions on this page and save answers to my desktop", "answer every question in this worksheet".

---

## Permissions

macOS gates screenshot APIs behind **Screen Recording** permission, granted per-app to whatever terminal is running FRIDAY.

**System Settings → Privacy & Security → Screen Recording → enable** your terminal (Terminal.app, iTerm, Warp, Ghostty, VS Code). Restart the terminal after granting — macOS caches permissions at process start.

Without it, `screencapture` returns a black or desktop-only PNG with no window contents.

Separately, FRIDAY itself requires `FRIDAY_SCREEN_ACCESS=true` in `.env`. Every tool checks it via `_screen_access_enabled()` and returns `PERMISSION_DENIED` otherwise. This is intentional — screen access is opt-in per-install, not default-on.

AppleScript automation (used for window bounds, scrolling, app activation) triggers a one-time Automation permission prompt for System Events. Allow it once and you're set.

---

## Performance

- **Apple Vision OCR** — ~300–800 ms per screenshot on M-series. Real-time on modern Macs because Vision uses the Neural Engine.
- **Full-page capture** — roughly 1 s per viewport (OCR + scroll + settle). A 10-page PDF scroll-captures in ~10 s.
- **Qwen2.5-VL local** — 3–5 s per query on M-series. Pull once with `ollama pull qwen2.5vl:7b` (~5 GB).
- **Cloud VLM fallback** — 1–2 s per query (OCR + `cloud_chat`). Faster than local VLM but sends the OCR text (not the raw image) to the LLM provider.
- **`solve_screen_questions`** — dominated by LLM latency; 10–30 s end-to-end for a full worksheet.

---

## Why this matters

Phone-camera solvers (Photomath et al.) need you to point a camera at a screen, which is clumsy and introduces OCR errors from angle and glare. Screen-vision runs against the pixel buffer directly:

- Solve on-screen assignments without switching devices or photographing a laptop.
- Read PDFs and long articles end-to-end, including scroll content a camera can't reach.
- Debug UIs — "what does this error say", "which button is greyed out", "why is this form invalid".
- Accessibility — narrate any text-heavy view, even if the app doesn't expose accessibility labels.

---

## Privacy

- **OCR stays local.** Apple Vision runs in-process, no network. The Swift script is spawned as a subprocess and output is read via stdout.
- **Qwen2.5-VL local.** Stays on-device if you pull it.
- **Cloud VLM fallback** — when Qwen isn't available, `ask_about_screen` sends OCR *text* (not the image) to whatever `cloud_chat` is configured against (Groq / OpenAI / Anthropic / Gemini). See [friday/core/llm.py](../friday/core/llm.py).
- **`solve_screen_questions`** always uses `cloud_chat` for the solving step — OCR text is sent out. Disable by setting `FRIDAY_SCREEN_ACCESS=false`.
- Screenshots auto-delete after 48 h (`_SCREENSHOT_TTL_HOURS`); full-page intermediate PNGs are deleted immediately after OCR.

---

## Example workflows

**"What's on my screen?"**

```
user: what's on my screen
FRIDAY → ask_about_screen(query="describe what's on screen")
        → capture_screen → Qwen2.5-VL
        → "Safari, Hacker News front page. Top story is..."
```

**"Solve the questions on this page and save answers to my desktop"**

```
user: solve every question on this page, save to my desktop
FRIDAY → solve_screen_questions(save_path="~/Desktop/answers.docx", full_page=True)
        → capture_full_page (12 viewports, dedup)
        → clean OCR text
        → cloud_chat (tutor prompt, max_tokens=8000)
        → python-docx with markdown rendering
        → "Solved 14 questions. Saved to ~/Desktop/answers.docx."
```

**"Read the full article in Safari"**

```
user: read the full article
FRIDAY → read_screen(app="Safari", full_page=True)
        → capture_full_page → strip UI chrome → return clean text
```

---

## Install

Screen tools are always available — no `friday setup` step. You need:

1. `FRIDAY_SCREEN_ACCESS=true` in `.env`.
2. macOS Screen Recording permission for your terminal.
3. *(Optional)* `ollama pull qwen2.5vl:7b` for local VLM instead of OCR-fallback.
4. `python-docx` (already in `requirements.txt`) for `.docx` export.

No other wiring — the tools auto-register via `TOOL_SCHEMAS` in [friday/tools/screen_tools.py](../friday/tools/screen_tools.py) and get injected into the system agent on any screen-keyword query.

---

## Extending

To add a new screen tool:

1. Write an `async def my_tool(...) -> ToolResult` in [screen_tools.py](../friday/tools/screen_tools.py). Start with the `_screen_access_enabled()` gate. Reuse helpers: `capture_screen`, `_ocr_image`, `_get_frontmost_window_bounds`, `_activate_app`, `_scroll_page_down`, `_dedupe_text`, `_markdown_to_docx`.
2. Append to `TOOL_SCHEMAS` with an OpenAI-style JSON schema (name, description, parameters).
3. Add a keyword to `screen_keywords` in [system_agent.py](../friday/agents/system_agent.py) so the agent loads it when the user's query mentions it.
4. Add a direct-dispatch entry in [tool_dispatch.py](../friday/core/tool_dispatch.py) if it should be callable via the fast single-tool path.
5. Add a pattern line to the `PATTERNS:` section of `_BASE_PROMPT` so the model learns the trigger phrasing.

The Swift-via-`swift -e` approach scales — any `Vision`, `AppKit`, or `CoreImage` API is one subprocess away. For heavier pipelines (streaming, live OCR), consider a small compiled Swift helper in `friday/native/` instead of spawning `swift -e` per call.
