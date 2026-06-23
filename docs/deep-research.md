# Deep Research — Multi-Agent Parallel Research & Long-Form Document Pipeline

The `deep_research_agent` is FRIDAY's heavyweight document producer. Unlike the fast `research_agent` (2 LLM calls, ~10-20s), this one orchestrates a planner, parallel gatherers, parallel section writers, and a synthesiser into a single 1,500-2,500 word document saved to disk as `.docx`, `.pdf`, `.md`, or `.txt`. It is the multi-agent pipeline for any task that needs gathering → processing → producing a deliverable.

File: [`friday/agents/deep_research_agent.py`](../friday/agents/deep_research_agent.py)

## 1. Overview — when does this fire vs `research_agent`?

The [router](../friday/core/router.py) picks between the two using wording alone. Both agents can save files; the distinction is **depth**, not output.

**Shallow → `research_agent`** (~10-20s, 2 LLM calls):
- "brief overview of X"
- "quick summary on Y"
- "short report about Z"
- Any factual lookup: "who is", "what is", "tell me about"

**Deep → `deep_research_agent`** (2-3 minutes, 10-15 LLM calls):
- "write a **paper** on X"
- "**comprehensive** report on Y"
- "**detailed** analysis of Z"
- "**in-depth** / **thorough** / **deep dive** into..."
- "write me a **submission-ready** document"
- "research X **and save** a paper to my desktop"

The regex lives in `match_agent()` as `deep_research_patterns` in [`friday/core/router.py`](../friday/core/router.py):

```python
deep_research_patterns = [
    r"\bdeep (research|dive|analysis)\b",
    r"\b(research|write)\s+(a |the )?(paper|report|document|analysis|thesis)\b",
    r"\bdetailed (research|report|analysis|paper)\b",
    r"\bcomprehensive (research|report|analysis|overview)\b",
    r"\b(research|investigate|analyze)\s+.{5,}\s+and\s+(save|write|create|make|build)\b",
    r"\bwrite (me |)(a |the )?(research |)(paper|report|document|submission)\s+(about|on|for)\b",
    r"\b(create|make|build)\s+(a |the )?(detailed|submission|research)[\s-]*(ready )?(paper|report|document|file)\b",
    r"\bdo\s+(a |)(research|deep dive)\s+(about|on|into)\b",
    r"\b(read|open)\s+.{3,}\s+(and |then )(research|improve|rewrite|upgrade)\b",
    r"\bimprove\s+.{3,}\s+(to |)(research|paper|academic|submission)[\s-]*(paper |grade|ready|level)?\b",
]
```

If the LLM classifier is reached instead, the same distinction is baked into the classify prompt: "short report / quick summary / brief overview → research_agent. Only detailed / comprehensive / in-depth / multi-section / paper → deep_research_agent."

## 2. Architecture — fan-out and synthesis

Unlike every other FRIDAY agent, deep_research does **not** use the ReAct loop in `BaseAgent`. It overrides `run()` with a bespoke six-phase pipeline:

```
┌─────────────┐    ┌────────────────┐    ┌───────────────────┐
│  Planner    │───▶│  Gatherers     │───▶│  Section writers  │
│  (1 LLM)    │    │  (N parallel)  │    │  (M parallel)     │
└─────────────┘    └────────────────┘    └───────────────────┘
                                                   │
                                                   ▼
                                         ┌───────────────────┐
                                         │  Synthesiser      │
                                         │  (1 LLM — abs +   │
                                         │   conclusion)     │
                                         └───────────────────┘
                                                   │
                                                   ▼
                                         ┌───────────────────┐
                                         │  Assembler + save │
                                         └───────────────────┘
```

Each phase is awaited before the next starts. Steps **within** a phase run via `asyncio.gather`. Search queries inside a SEARCH step fan out again — 2-3 queries × `search_web` in parallel, plus `fetch_page` on the top 2 URLs for deeper content.

## 3. LLM call budget

For a typical "write a detailed report on X" request:

| Phase        | LLM calls                | Duration       |
|--------------|--------------------------|----------------|
| Planner      | 1                        | ~2-3s          |
| Gatherers    | 0 (tool calls only)      | ~20-40s        |
| Writers      | N sections (4-8)         | ~40-80s        |
| Synthesiser  | 1 (abstract + conclusion)| ~5-10s         |
| **Total**    | **6-10 LLM calls**       | **~2-3 min**   |

Tool budget: roughly 4-8 `search_web` calls × 2-3 queries each (so ~12-24 Tavily hits) plus up to 2 `fetch_page` calls per SEARCH step. Writers are batched 3-at-a-time with a 1s sleep between batches to stay under Groq's 6K TPM cap:

```python
batch_size = 3
for batch_start in range(0, len(section_names), batch_size):
    batch = section_names[batch_start:batch_start + batch_size]
    batch_results = await asyncio.gather(
        *[_write_section(name, batch_start + i) for i, name in enumerate(batch)],
        return_exceptions=True,
    )
    section_results.extend(batch_results)
    if batch_start + batch_size < len(section_names):
        await asyncio.sleep(1)  # Brief pause between batches
```

## 4. Document format

The planner emits a `sections` list of 4-8 section titles. Conclusion/intro/abstract are stripped if the planner emits them — the synthesiser handles those separately to avoid duplication:

```python
_skip = {"introduction", "conclusion", "summary", "abstract",
         "conclusion and summary", "references", "table of contents"}
section_names = [s for s in section_names if s.lower().strip() not in _skip]
```

Each section writer follows `SECTION_WRITER_PROMPT`: 400-600 words, specific facts/numbers/names, inline citations as `[Source: https://example.com/page]`, professional tone, no repetition across sections. Final document structure:

1. Title (H1) + "Compiled by FRIDAY — {date}" subtitle
2. Abstract (150-250 words, from synthesiser)
3. Table of Contents (numbered section list)
4. Sections (400-600 words each × 4-8 sections)
5. Conclusion (200-300 words, from synthesiser)
6. References (deduplicated URLs extracted from research + inline `[Source:]` tags)

Target length: **1,500-2,500 words**. Sources are harvested two ways in the assembler:

```python
all_sources = set()
for data in gathered_data.values():
    urls = re.findall(r'https?://[^\s\])<>"]+', data)
    all_sources.update(urls[:10])
for s in sections:
    source_refs = re.findall(r'\[Source:\s*([^\]]+)\]', s.get("content", ""))
    for ref in source_refs:
        ref = ref.strip()
        if not ref.startswith("http"):
            ref = f"https://{ref}"
        all_sources.add(ref)
```

## 5. Output formats

Format detection runs first via `detect_format(task)`. Default is **docx**.

| Format | Library                  | Function          | Notes                                    |
|--------|--------------------------|-------------------|------------------------------------------|
| `.docx`| `python-docx` (`docx`)   | `_save_docx`      | Calibri 11pt, H1 title, Heading styles, page break after TOC |
| `.pdf` | `weasyprint`             | `_save_pdf`       | HTML → PDF; falls back to saving `.html` + raising `RuntimeError` if WeasyPrint missing |
| `.md`  | stdlib                   | `_save_md`        | Markdown with `---` separators           |
| `.txt` | stdlib                   | `_save_txt`       | Plain text, UPPERCASE headings + underline |

The PDF path uses the **same WeasyPrint library** as [`friday/tools/cv_tools.py`](../friday/tools/cv_tools.py), but with a different template — `cv_tools.py` uses a Jinja2-rendered dark-sidebar resume template; `deep_research_agent._save_pdf` builds a simple document-style HTML with Calibri, H1 centred, H2 bottom-bordered. The `research_agent`'s file saver actually **reuses** `_save_pdf` from this module for its quick-report PDFs.

## 6. Where files go

Filename is derived from the document title (planner-chosen), sanitized, and suffixed with today's date:

```python
@staticmethod
def _determine_save_path(task: str, title: str, fmt: str = "docx") -> Path:
    task_lower = task.lower()
    if "desktop" in task_lower:
        save_dir = Path.home() / "Desktop"
    elif "download" in task_lower:
        save_dir = Path.home() / "Downloads"
    else:
        save_dir = Path.home() / "Documents" / "friday_files"
        save_dir.mkdir(parents=True, exist_ok=True)

    safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in title)
    safe_title = safe_title.strip().replace(" ", "_")[:60]
    if not safe_title:
        safe_title = "research_paper"

    filename = f"{safe_title}_{datetime.now().strftime('%Y%m%d')}.{fmt}"
    return save_dir / filename
```

So "Halo Hardware Overview" becomes `Halo_Hardware_Overview_20260420.docx` on the Desktop.

## 7. Real example — "write a detailed report on Brilliant Labs' Halo hardware and save it to my desktop"

1. **Router** — `match_agent()` hits `r"\bdetailed (research|report|analysis|paper)\b"` → returns `("deep_research_agent", raw)`.
2. **Planner** (1 LLM call, ~2s) — produces JSON like:
   ```json
   {
     "title": "Brilliant Labs Halo — Hardware Overview",
     "output_format": "docx",
     "steps": [
       {"phase": 1, "type": "SEARCH", "params": {"queries": ["Brilliant Labs Halo specs", "Halo AR glasses hardware", "Halo display microLED"]}},
       {"phase": 1, "type": "SEARCH", "params": {"queries": ["Halo battery life", "Halo chipset", "Halo comparison Frame"]}},
       {"phase": 2, "type": "WRITE", "params": {"section_title": "Optics and Display"}},
       ...
     ],
     "sections": ["Overview", "Optics and Display", "Compute and Sensors", "Battery and Connectivity", "Comparison with Competitors"]
   }
   ```
3. **Phase 1: Gatherers** — `asyncio.gather` runs both SEARCH steps in parallel. Each fans out again: `search_web` × 3 queries + `fetch_page` on top 2 URLs. Snippets get tagged with `[Source: URL]` so writers can cite them. Results are concatenated into `gathered_data[description] = text`.
4. **Filter synthesis-handled sections** — none of the 5 section titles match the skip set, so all 5 are kept.
5. **Phase 2: Writers** — 5 sections, batch size 3 → two batches (3 + 2). Each writer gets the full merged research (`all_research[:6000]`) plus `task` and its section title:
   ```python
   messages = [
       {"role": "system", "content": SECTION_WRITER_PROMPT},
       {"role": "user", "content": (
           f"Section title: {section_title}\n"
           f"This is section {section_idx + 1} of {len(section_names)} "
           f"in a document titled \"{title}\".\n"
           f"Original task: {task}\n\n"
           f"Research data:\n{all_research[:6000]}\n\n"
           f"Write a detailed, well-structured section focused specifically on "
           f"'{section_title}'. Do not cover topics from other sections."
       )},
   ]
   ```
6. **Phase 3: Synthesiser** (1 LLM call) — sees all 5 written sections, emits `## Abstract\n...\n\n## Conclusion\n...`.
7. **Assembler** — builds markdown doc_lines, collects URLs from gathered_data AND from `[Source:]` tags in sections.
8. **Save** — `detect_format(task)` sees no pdf/md/txt cue → `docx`. `_determine_save_path` sees "desktop" → `~/Desktop/Brilliant_Labs_Halo__Hardware_Overview_20260420.docx`. `_save_docx` writes the file.
9. **Response** — `AgentResponse.media_paths = [str(save_path)]`, CLI streams a 2000-char preview plus a "Saved to ..." line.

## 8. Two-phase flow: gather → synthesise

Phase A (gather): SEARCH + FETCH + optional READ_FILE. Populates `gathered_data: dict[str, str]`. If a READ_FILE step fires, its output is also tracked as `original_content` — this flips the agent into **improvement mode**, using `IMPROVE_PROMPT` instead of `SECTION_WRITER_PROMPT` so the writers preserve the original author's voice while strengthening arguments:

```python
is_improvement = original_content is not None
```

Phase B (synthesise): parallel writers emit sections, then a single synthesis call produces abstract + conclusion. Assembly is deterministic (no LLM) — just string concatenation and WeasyPrint/python-docx rendering.

## 9. Use cases

- **Uni submissions / theses** — "research X and build me a submission-ready paper". Improvement mode lets the user drop a draft path and have FRIDAY upgrade it to research-paper grade.
- **Business competitive analysis** — "comprehensive report on the AR glasses market in 2026".
- **Technical evaluations** — "detailed analysis of Modal vs Railway for AI workloads".
- **Research-to-file hybrid** — "read my thesis at ~/Documents/thesis.md, research its topics, improve to research-paper grade" → planner emits a READ_FILE step plus SEARCH steps, writers flip to IMPROVE mode.

## 10. Limits

- **Timeout** — no hard timeout; relies on Groq API timeouts (~60s per call). A full run takes 2-3 minutes.
- **Parallelism** — writers are throttled to batches of 3 + 1s delay to respect Groq's 6K TPM rate limit. Gatherers run unthrottled since tool calls aren't LLM-rate-limited.
- **Section cap** — the planner is told "4-8 SEARCH steps with 2-3 queries each"; no hard ceiling in code but the synthesiser truncates `sections_text` to 8000 chars, so very long documents start to lose context in the abstract/conclusion call.
- **Research budget** — `all_research` is truncated to `[:6000]` per writer, `gathered_data` values to `[:4000]` in the merge, so ~24KB of gathered context is the practical ceiling.
- **Empty search** — if Tavily returns nothing (missing API key, network error), `gathered_data` is empty, writers get a blank research_data string, and the SECTION_WRITER_PROMPT explicitly forbids invented content. Expected output: thin sections honestly flagging missing data. If `tool_calls` from the planner fails to parse as JSON, the agent returns `success=False` early with the raw planner output in `result`.
- **WeasyPrint missing** — PDF generation falls back to saving the raw HTML with a `.html` suffix and raises `RuntimeError` with an install hint (`uv add weasyprint`).
- **Rate limit bursts** — a 3-section batch of writers fires 3 concurrent Groq calls. If Groq 429s, that section returns as an exception and is silently skipped; the doc will be missing that section but otherwise completes.

## Related files

- Main pipeline: [`friday/agents/deep_research_agent.py`](../friday/agents/deep_research_agent.py)
- Shallow counterpart: [`friday/agents/research_agent.py`](../friday/agents/research_agent.py)
- Web tools: [`friday/tools/web_tools.py`](../friday/tools/web_tools.py) (`search_web`, `fetch_page`, `youtube_transcript`)
- Router: [`friday/core/router.py`](../friday/core/router.py) (`deep_research_patterns`, `_CLASSIFY_PROMPT`)
- CV PDF path (shared WeasyPrint dependency, different template): [`friday/tools/cv_tools.py`](../friday/tools/cv_tools.py)
- File tool used by READ_FILE steps: [`friday/tools/file_tools.py`](../friday/tools/file_tools.py)
