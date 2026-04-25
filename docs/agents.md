# FRIDAY Agents — Full Reference

This is the definitive reference for every specialist agent in FRIDAY. Each agent is a focused, tool-scoped worker that runs inside a ReAct loop. The orchestrator picks one agent per turn based on the user's intent, the agent calls the tools it needs, and then returns a result.

## 1. How dispatch works

A FRIDAY "agent" is a subclass of [`BaseAgent`](../friday/core/base_agent.py) with a `name`, a `system_prompt`, a `tools` dict (name → callable + schema), and a `max_iterations` cap. When a user turn comes in, [`FridayCore`](../friday/core/orchestrator.py) runs it through a three-tier router: first [`fast_path.py`](../friday/core/fast_path.py) for zero-LLM instant commands, then [`router.py`](../friday/core/router.py) which tries regex `match_agent()` followed by an LLM `classify_intent()` call against the slim classification prompt, and finally falls back to CHAT if nothing matches. Once an agent is selected, the orchestrator calls `agent.run(task, context)` and the agent's ReAct loop takes over: the LLM picks tool calls, the base class executes them (in parallel when multiple are emitted), feeds the observations back into the next turn, and repeats until the model emits a final text answer or `max_iterations` is hit. All 10 specialist agents are registered in `FridayCore.__init__` inside [`orchestrator.py`](../friday/core/orchestrator.py).

The ReAct loop itself is ~200 lines in [`base_agent.py`](../friday/core/base_agent.py) and is worth understanding before writing a new agent. Each iteration: (1) the assistant message + any previous tool results are sent to `cloud_chat` with the agent's tool schemas; (2) `extract_tool_calls` inspects the response — if there are none, the final text is returned as an `AgentResponse`; (3) if there is one tool call, it runs in sequence; if there are many, `asyncio.gather` runs them in parallel; (4) tool results are passed through `_compact_data()` which trims large email/calendar payloads to the fields a small model can actually summarise, JSON-encoded, and appended as `role: tool` messages; (5) the loop continues until the model stops calling tools, `max_iterations` fires, or an exception escapes. Along the way, `_extract_paths()` walks every tool result looking for keys like `saved_path`, `path`, `file_path`, `output_path` whose values point at real media extensions (PNG/JPG/PDF/DOCX/MP4/MP3…) and collects them into `AgentResponse.media_paths` for the CLI to preview. Skills from [`friday/skills/`](../friday/skills/) are loaded for each agent by name via `build_skill_context()` and appended to the system prompt at run time.

### 1.1 The dispatch pipeline end-to-end

A single user turn flows through these layers in order. Each layer can short-circuit the rest.

1. **Fast path** — [`friday/core/fast_path.py`](../friday/core/fast_path.py). Pure regex → direct tool call. Greetings, "what time is it", trivial TV commands, and a handful of other zero-LLM shortcuts. No model is invoked. Typical latency: 50–200 ms.
2. **One-shot** — [`friday/core/oneshot.py`](../friday/core/oneshot.py). Regex → single tool → one LLM call to format the result in FRIDAY's voice. Used for things like "screenshot", where the tool is obvious but the response needs personality.
3. **Router** — [`friday/core/router.py`](../friday/core/router.py). The LLM classifier runs first; regex is the offline fallback. `classify_intent()` sends `_CLASSIFY_PROMPT` plus the last two turns of conversation to the configured cloud LLM and returns one of three verdicts: `(agent_name, task)` for a confident agent route, the `CHAT_DECISION` sentinel for "this is casual chat", or `None` for "classifier errored / unsure". If the LLM picks an agent → dispatch. If it returns `CHAT_DECISION` → straight to CHAT (no regex override). If it returns `None` AND cloud is offline → fall back to `match_agent()` regex. If it returns `None` while cloud is up (e.g. unexpected output) → trust uncertainty and route to CHAT. The previous behaviour where regex ran *first* and could hijack queries the LLM had correctly tagged as chat (e.g. "why is the sky blue" landing in `research_agent`) is gone.
4. **Agent.run()** — the selected agent's ReAct loop executes. For most agents this is inherited `BaseAgent.run`; `household_agent` adds a fast path of its own, `research_agent` and `deep_research_agent` override `run()` entirely with bespoke pipelines.
5. **Tool dispatch** — [`friday/core/tool_dispatch.py`](../friday/core/tool_dispatch.py). Each tool call is logged, rate-limited where relevant, and dispatched to the underlying async function. Tool results flow back as `ToolResult` objects (`success`, `data`, `error`).
6. **Response assembly** — the orchestrator turns the `AgentResponse` into a chat message, appends to `self.conversation`, logs the turn via [`log_turn`](../friday/memory/conversation_log.py), and yields any `media_paths` for the CLI to preview.

The upshot: agents never talk to each other directly. The orchestrator is the only hub. If a turn needs two agents (e.g. "research X then email it to me"), the LLM classifier picks the *primary* agent, and that agent's prompt must instruct it to chain tools that cover both halves — or the user runs two turns.

## 2. Summary table

| Agent | Scope | Tools | Max iters | Main tools |
| --- | --- | --- | --- | --- |
| [code_agent](../friday/agents/code_agent.py) | Read/write/debug/run code and shell | ~15 | 10 | `read_file`, `write_file`, `run_command`, `search_web`, GitHub suite |
| [comms_agent](../friday/agents/comms_agent.py) | Email, calendar, iMessage, FaceTime, WhatsApp, SMS | 13–19 | 5 | `read_emails`, `send_email`, `get_calendar`, `send_imessage`, `send_whatsapp` |
| [deep_research_agent](../friday/agents/deep_research_agent.py) | Multi-agent research → long document (docx/pdf/md/txt) | N/A (bespoke pipeline) | N/A | `search_web`, `fetch_page`, `read_file` |
| [household_agent](../friday/agents/household_agent.py) | LG TV and smart-home control | ~20 | 8 | `turn_on_tv`, `tv_volume`, `tv_launch_app`, `tv_remote_button`, `tv_status` |
| [job_agent](../friday/agents/job_agent.py) | Autonomous job applications end-to-end | ~16 | 30 | `tailor_cv`, `generate_pdf`, `browser_discover_form`, `browser_fill_form`, `browser_upload` |
| [memory_agent](../friday/agents/memory_agent.py) | Store / recall long-term memories | ~5 | 10 | `store_memory`, `search_memory` |
| [monitor_agent](../friday/agents/monitor_agent.py) | Create/manage URL, search, and topic watchers | ~7 | 5 | `create_monitor`, `list_monitors`, `pause_monitor`, `delete_monitor`, `force_check` |
| [research_agent](../friday/agents/research_agent.py) | Web research + short write-ups to disk | ~8 | 2 (bespoke 2-call flow) | `search_web`, `fetch_page`, `search_memory` |
| [social_agent](../friday/agents/social_agent.py) | X / Twitter posting, search, mentions, engagement | ~9 | 3 | `post_tweet`, `search_x`, `get_my_mentions`, `like_tweet`, `retweet` |
| [system_agent](../friday/agents/system_agent.py) | Mac control, browser, files, terminal, PDF, screen vision | 15–40 (dynamic) | 5 (10 for forms) | `open_application`, `take_screenshot`, `browser_navigate`, `ocr_screen`, `run_command` |

Tool counts are approximate because several agents dynamically inject or skip tools depending on available integrations (WhatsApp, SMS, Playwright, screencast, CV) or task keywords (system_agent's browser/PDF/screen injection).

## 3. Deep dives

### code_agent

Source: [`code_agent.py`](../friday/agents/code_agent.py).

- **Scope.** Reading, writing, debugging, and running code. The "hands" of FRIDAY. Touches the filesystem and shell, uses web search for docs, and talks to GitHub. Does not send mail, control the Mac UI, or browse the web for general research.
- **Tools (from `self.tools = {...}`):** merges all of [`file_tools`](../friday/tools/file_tools.py) (`read_file`, `write_file`, `list_directory`, `search_files`), all of [`terminal_tools`](../friday/tools/terminal_tools.py) (`run_command`, `run_background`), `search_web` from [`web_tools`](../friday/tools/web_tools.py), `search_memory` from [`memory_tools`](../friday/tools/memory_tools.py), and the full [`github_tools`](../friday/tools/github_tools.py) suite.
- **Max iterations.** Inherits the `BaseAgent` default of **10**.
- **Model override.** Uses `moonshotai/kimi-k2-instruct` instead of the cluster default — the agent sets `model = "moonshotai/kimi-k2-instruct"` because it is stronger on code.
- **System prompt.** Describes the agent as FRIDAY's coding specialist, lays out style rules (match existing style, handle errors explicitly, no silent failures, no hardcoded secrets, prefer async/await, only comment the "why"), and tells it to understand full context before editing and to fix the real problem rather than the symptom. Full text in the source file.
- **Routing signals (from [`router.py`](../friday/core/router.py)).** The regex `code_patterns` block matches `debug|fix <bug|error|issue|code|script|crash>`, `git <anything>`, `run|execute <script|code|command|server|test|file>`, `read|open|write|edit|create <file|code|script>`, and `deploy|install|uninstall <anything>`. The LLM classifier calls it out for "write a script", "create a file at [path]", "fix this bug", "save [X] to my desktop", anything involving a file path or code.
- **Example commands.**
  - "fix the bug in `friday/cli.py`"
  - "run the test suite"
  - "git status then commit the staged files"
  - "write a Python script that reads CSV from stdin and emits JSON"
  - "deploy the Modal app"
- **Gotchas.** This agent deliberately does *not* have browser, email, or Mac-UI tools — those live on other agents. If a request mixes code with, say, "and open the result in Safari", the router will often favour `system_agent` or hand it to `code_agent` and rely on `run_command` + `open` to bridge.

### comms_agent

Source: [`comms_agent.py`](../friday/agents/comms_agent.py).

- **Scope.** All human-to-human channels: Gmail, Google Calendar, iMessage, FaceTime, WhatsApp (optional), and Twilio SMS (optional). Handles reading, searching, drafting, and sending. Cannot touch files, code, or the shell.
- **Tools:** `read_emails`, `search_emails`, `read_email_thread`, `send_email`, `draft_email`, `send_draft`, `edit_draft` from [`email_tools`](../friday/tools/email_tools.py); `get_calendar`, `create_event` from [`calendar_tools`](../friday/tools/calendar_tools.py); `read_imessages`, `send_imessage`, `start_facetime`, `search_contacts` from [`imessage_tools`](../friday/tools/imessage_tools.py). If [`whatsapp_tools`](../friday/tools/whatsapp_tools.py) imports, it also gets `send_whatsapp`, `read_whatsapp`, `search_whatsapp`, `whatsapp_status`. If [`sms_tools`](../friday/tools/sms_tools.py) imports, it also gets `send_sms`, `read_sms`.
- **Max iterations.** `max_iterations = 5`.
- **System prompt.** Long, explicit prompt built by `get_system_prompt()` which re-reads `USER` config on every construction so Settings UI edits are picked up without a restart. Covers: the "you" vs FRIDAY pronoun trap, channel detection (iMessage vs email vs WhatsApp vs SMS are NEVER mixed), a full tool-call mapping table for common phrasings ("check my emails", "reply to X", "text me on sms", etc.), contact-nickname handling (pass the user's exact words, the tool resolves), drafting style (match the tone of the thread, short and casual), FaceTime calling, and post-tool-result behaviour. Optionally appends a `CONTACT FACTS` block from `USER.contact_aliases`.
- **Routing signals.** The `comms_patterns` block in `match_agent` is the largest in the router — it matches `email|emails|inbox|gmail|unread`, `calendar|schedule|meeting|event|appointment`, `draft|send|reply|forward|read <email|message|mail>`, iMessage phrasings (`text X`, `send a text`, `check my messages`, `reply to X`, `what did X say`), WhatsApp (`whatsapp`, `send X on whatsapp`), FaceTime (`facetime X`, `call X on facetime`), and contact lookups (`find X's number`). A secondary `followup_patterns` block catches confirmations like "send it", "draft it", "yes send" when the recent conversation has comms context.
- **Example commands.**
  - "check my emails"
  - "draft an email to Jess about the Friday demo and send it"
  - "what's on my calendar today"
  - "reply to Mama saying I'll call her tonight"
  - "text me on sms with the summary"
  - "facetime Dad audio only"
- **Gotchas.** (a) The channel-detection rules in the system prompt are load-bearing. The #1 real-world failure is the model reaching for `draft_email` right after reading an iMessage thread. The prompt's "if you called `read_imessages` at ANY point, ALL follow-up sends go through `send_imessage`" line is there specifically to prevent this. (b) `send_sms` needs an E.164 phone number, never a name — if the user says "sms Mom", the agent has to `search_contacts` first. (c) WhatsApp is only available if the local bridge is running; see [`docs/whatsapp-setup.md`](whatsapp-setup.md). (d) SMS requires Twilio creds; see [`docs/sms-setup.md`](sms-setup.md).

### deep_research_agent

Source: [`deep_research_agent.py`](../friday/agents/deep_research_agent.py).

- **Scope.** Long-form, multi-section deliverables — research papers, comprehensive reports, thesis-grade documents. Runs a bespoke four-stage pipeline (plan → parallel execute → parallel section writers → synthesis + assemble) and saves the output to disk as `.docx`, `.pdf`, `.md`, or `.txt`.
- **Tools.** Does **not** inherit from `BaseAgent` and does not register an Ollama-schema tool dict. Directly imports `search_web` and `fetch_page` from [`web_tools`](../friday/tools/web_tools.py), and lazy-imports `read_file` from [`file_tools`](../friday/tools/file_tools.py) when the plan includes a `READ_FILE` step. Output writers live in the same file: `_save_docx`, `_save_pdf` (via WeasyPrint), `_save_md`, `_save_txt`, plus `convert_file` for format conversion of existing documents.
- **Max iterations.** N/A. The pipeline has fixed phases rather than a ReAct loop: 1 planner LLM call, N parallel tool executions per phase, M parallel section writers (batched in groups of 3 with a 1-second delay to dodge Groq TPM limits), 1 synthesis call, then assembly and save.
- **System prompt.** Multiple specialised prompts: `PLANNER_PROMPT` returns a typed JSON plan (`READ_FILE | SEARCH | FETCH | WRITE` steps grouped by phase); `SECTION_WRITER_PROMPT` writes 400–600-word sections with inline `[Source: URL]` citations; `SYNTHESIS_PROMPT` produces the abstract and conclusion; `IMPROVE_PROMPT` rewrites existing documents at research-paper grade when a `READ_FILE` step is present. Full text in the source file.
- **Routing signals.** The `deep_research_patterns` block matches `deep research|dive|analysis`, `research|write <a/the> paper|report|document|analysis|thesis`, `detailed <research|report|analysis|paper>`, `comprehensive <research|report|analysis|overview>`, `research X and save/write/create Y`, `create/make/build <detailed|submission|research> paper|report|document|file`, and `read X and research|improve|rewrite|upgrade`. The LLM classifier prompt explicitly reserves this agent for "PAPER", "COMPREHENSIVE / DETAILED / IN-DEPTH / THOROUGH", "DEEP DIVE", "multi-section document", and academic submissions.
- **Example commands.**
  - "write a comprehensive paper on the UK Global Talent visa and save it to my desktop"
  - "deep dive into the economics of open-source LLMs"
  - "read my thesis at `~/Documents/draft.docx`, research its topics, and improve it to research-paper grade"
  - "build a submission-ready report on AI safety in 2026"
- **Output location.** `_determine_save_path()` picks `~/Desktop` if the task mentions "desktop", `~/Downloads` if it mentions "download", otherwise `~/Documents/friday_files/`. Filenames are `<slugified_title>_<YYYYMMDD>.<fmt>` with a 60-char cap on the title slug.
- **Gotchas.** (a) PDF output requires WeasyPrint — if it's not installed the agent saves an HTML fallback and raises a runtime error. (b) The planner is instructed to *never* include `Introduction`, `Conclusion`, `Summary`, or `Abstract` in the sections list — those are handled by the synthesis step. If a section writer slips one in, the assembler drops it. (c) Total runtime is typically 2–3 minutes; use `research_agent` for anything faster.

### household_agent

Source: [`household_agent.py`](../friday/agents/household_agent.py).

- **Scope.** Smart-home control. Currently: LG WebOS TV over local Wi-Fi (with Wake-on-LAN), plus `play_music` for Mac Music when phrasing is ambiguous between TV playback and music app. Future: LG ThinQ appliances, smart lights.
- **Tools.** Full [`tv_tools`](../friday/tools/tv_tools.py) set: `turn_on_tv`, `turn_off_tv`, `tv_screen_off`, `tv_screen_on`, `tv_volume`, `tv_volume_adjust`, `tv_mute`, `tv_launch_app`, `tv_close_app`, `tv_list_apps`, `tv_list_sources`, `tv_set_source`, `tv_play_pause`, `tv_remote_button`, `tv_type_text`, `tv_notify`, `tv_get_audio_output`, `tv_set_audio_output`, `tv_system_info`, `tv_status`. Also `play_music` from [`mac_tools`](../friday/tools/mac_tools.py).
- **Max iterations.** `max_iterations = 8`.
- **Fast path.** This is the headline optimisation. `_fast_match(task)` pattern-matches simple commands (power on/off, set volume to 40, mute, launch Netflix, "netflix on tv", multi-step "turn on the tv and put on youtube") directly to tool calls and executes them **without any LLM turn**. Result: ~1–2 s instead of ~30 s. When the previous step is `turn_on_tv`, the loop sleeps 6 s before running the next tool so the TV has time to boot. Only ambiguous or complex commands fall through to the LLM.
- **System prompt.** Only used when the fast path misses. Lists every TV tool with its args, defines the remote-button navigation sequences for Disney+, Netflix, and YouTube search flows (`up, up, right, ok` then `tv_type_text` then `down, ok`), and forbids faking results.
- **Routing signals.** The `household_patterns` block matches anything containing `tv|television|telly`, `netflix|youtube|spotify|disney|prime video|apple tv` alongside `tv|on the|put on`, HDMI inputs, `mute the tv`, `tv volume`, `what's on the tv`, "is my tv on", pause/resume on "the tv|what's playing|it". A follow-up block catches "search for X on youtube" and remote-style words (`next|back|select`) when the last agent was household.
- **Example commands.**
  - "turn on the tv"
  - "volume to 30"
  - "put on Netflix"
  - "turn on the tv and put on youtube"
  - "play Black Widow on Disney"
  - "mute" / "unmute" / "louder"
- **Response formatting.** `_format_result()` hand-crafts short, FRIDAY-voice replies for each tool — "TV's turning on. Give it a few seconds." / "Volume set to 42." / "Netflix is on." — rather than letting the LLM paraphrase. This makes the fast path feel instant and consistent.
- **Gotchas.** (a) The TV must be awake enough to accept a Wake-on-LAN packet; a fully cold set can miss the first packet. (b) `tv_launch_app` exposes a `verified` flag — if the TV's current-app reports back a different app, the reply says so rather than lying. (c) "pause" is intentionally handled by the LLM, not fast path, because "pause the music" can mean Mac Music or the TV depending on context.

### job_agent

Source: [`job_agent.py`](../friday/agents/job_agent.py).

- **Scope.** Autonomously applying to jobs end-to-end. Finds postings (LinkedIn, Greenhouse, Lever, Ashby, company career pages), reads the JD, tailors the CV to the role, generates a PDF, fills the application form (including React-Select and file uploads), verifies, and asks before final submit. Can also scan the inbox for job openings.
- **Tools.** Full [`cv_tools`](../friday/tools/cv_tools.py) (notably `tailor_cv` and `generate_pdf`); `search_web` from [`web_tools`](../friday/tools/web_tools.py); and an opinionated browser set from [`browser_tools`](../friday/tools/browser_tools.py): `browser_navigate`, `browser_discover_form`, `browser_fill_form`, `browser_screenshot`, `browser_click`, `browser_type`, `browser_scroll`, `browser_upload`, `browser_get_text`, `browser_execute_js`, `browser_elements`, `browser_wait_for_login`.
- **Max iterations.** `max_iterations = 30` — by far the highest, because real applications need many discover/fill/verify cycles.
- **System prompt.** Built by `get_system_prompt()` which injects an applicant identity block from `USER` config (name, email, phone, location, GitHub, portfolio, bio). Defines a strict three-phase playbook — Phase 1: find the job (search, navigate, inspect elements, re-search if the page is a React SPA with no links); Phase 2: tailor CV and generate PDF; Phase 3: fill (batch `browser_fill_form` once with every field using exact selectors from `browser_discover_form`), upload, then **verify** with another `browser_discover_form` call until `unfilled_required_count == 0`. Defines default answers for common fields (right to work, visa sponsorship, how did you hear, salary, demographics → decline). Forbids guessing selectors, forbids reporting done while required fields are unfilled.
- **Routing signals.** The `job_patterns` block matches `cv|résumé|resume|curriculum vitae`, `cover letter`, `job|role application|apply|applying`, `apply to|for|at`, `tailor my cv|resume`, `generate|create|make|build <a/my/the> cv|resume|cover letter`, `apply to all/every role`, `find jobs that match`, `look at / read the screen for a cv|apply`, and `open the career page`.
- **Example commands.**
  - "apply for the backend role at Anthropic"
  - "go to Stripe's careers site and apply for a software engineer role"
  - "tailor my CV for this job posting"
  - "look at the job on my screen and apply"
  - "find me jobs at YC startups I qualify for"
- **Gotchas.** (a) LinkedIn's Jobs tab is a React SPA; the prompt tells the agent to search for a Greenhouse or Lever URL instead of scrolling forever. (b) `browser_fill_form` should be called **once with every field**, not field-by-field — the prompt hammers this because small models sometimes serialise calls and blow through the iteration budget. (c) The verify step is mandatory — the agent is not allowed to report done until `unfilled_required_count == 0`. (d) Default demographic answers all decline to self-identify; change this in the system prompt if you want different behaviour.

### memory_agent

Source: [`memory_agent.py`](../friday/agents/memory_agent.py).

- **Scope.** Long-term personal memory. Stores decisions, lessons, preferences, project notes, and people; retrieves them by semantic search. Also runs at the start and end of complex orchestrator tasks to pre-load and persist context.
- **Tools.** All of [`memory_tools`](../friday/tools/memory_tools.py): `store_memory`, `search_memory`, `list_memories`, `delete_memory`, `update_memory_importance` (whatever is exported by that module).
- **Max iterations.** Inherits `BaseAgent` default of **10**.
- **System prompt.** Short. Defines six categories (`project | decision | lesson | preference | person | general`) and an importance scale 1–10. Tells the agent to be selective: "Store decisions, not descriptions. Store lessons, not logs. Store what changes future behaviour."
- **Routing signals.** The `memory_patterns` block matches `remember that|this|what`, `do you remember|know|recall`, `recall my preferences`. The classifier prompt adds "remember that X", "what do I know about X".
- **Example commands.**
  - "remember that my partner prefers flat whites over cappuccinos"
  - "recall my preferences for FRIDAY's tone"
  - "what do you know about the Modal deployment"
  - "remember — we decided to skip Postgres for now and stick with SQLite"
- **Gotchas.** Memories are stored in the conversation/memory store backed by [`friday/memory/store.py`](../friday/memory/store.py). Importance scores bias retrieval; prefer higher importance for things that change future behaviour, not for "this was interesting." The background memory processor in [`friday/background/memory_processor.py`](../friday/background/memory_processor.py) may also auto-store turn-level insights, so this agent is usually only invoked for explicit recall or deliberate stores.

### monitor_agent

Source: [`monitor_agent.py`](../friday/agents/monitor_agent.py).

- **Scope.** Persistent watchers. Creates and manages background monitors for URLs, recurring web searches, and broad topics. Material changes are queued for the briefing agent. This is "set it and walk away" — not one-time lookups (that's research_agent).
- **Tools.** All of [`monitor_tools`](../friday/tools/monitor_tools.py): `create_monitor`, `list_monitors`, `pause_monitor`, `resume_monitor`, `delete_monitor`, `force_check`, `get_monitor_history`.
- **Max iterations.** `max_iterations = 5`.
- **System prompt.** Defines three `monitor_type`s — `url` (watch a specific page), `search` (watch a recurring query), `topic` (watch a broad subject). Gives frequency guidelines (legal/visa daily, competitor weekly), importance guidelines (visa = critical, funding deadlines = high, general news = normal), and keyword guidelines that define "material" — e.g. visa keywords are `eligibility, requirement, criteria, deadline, fee, endorsement`. Tells the agent to confirm in one or two sentences after creating a monitor, not to be verbose.
- **Routing signals.** The `monitor_patterns` block matches `monitor|watch for|watch this page|url|site|link|track changes|keep an eye on|alert me when`, `my/the monitors|watchers`, `pause|delete|stop|remove <the monitor|watcher>`, `force check the monitor`, `what am I monitoring`, `monitor history`. URLs are stripped before matching so `youtube.com/watch` does not trigger it.
- **Example commands.**
  - "monitor gov.uk/global-talent for changes"
  - "keep an eye on YC's W26 batch announcement"
  - "track AI visa policy in the UK"
  - "what am I monitoring?"
  - "pause the YC monitor"
- **Gotchas.** (a) Do not confuse with `research_agent`: monitor is "set up a long-running watcher", research is "find out right now". (b) Keywords are the knob that controls noise — overly broad keywords flood the briefing; overly narrow ones miss the change. Error on the side of specific. (c) "stop monitoring X" is `delete_monitor`, not `pause_monitor` — pause suspends, delete removes.

### research_agent

Source: [`research_agent.py`](../friday/agents/research_agent.py).

- **Scope.** Fast web research and short write-ups. Answers factual questions in ~10–20 s. Can also save a short report (`.md`, `.pdf`, `.docx`, `.txt`) to disk when the user asks. Prefer this over `deep_research_agent` unless the user explicitly wants depth.
- **Tools.** All of [`web_tools`](../friday/tools/web_tools.py) (`search_web`, `fetch_page`, etc.), `store_memory` and `search_memory` from [`memory_tools`](../friday/tools/memory_tools.py), and the full [`github_tools`](../friday/tools/github_tools.py) set.
- **Max iterations.** `max_iterations = 2`, but the class overrides `run()` entirely with a bespoke two-LLM-call flow: (1) pick and run all tools in parallel with `TOOL_PICK_PROMPT`; (2) generate the answer. When the user asks for a file, a third call writes the full document via `DOCUMENT_PROMPT` and a fourth short call writes a chat summary via `SUMMARY_PROMPT`.
- **System prompt.** Four prompts in one file. `TOOL_PICK_PROMPT` tells the model to never respond with text, only make tool calls. `ANSWER_PROMPT` (built by `get_answer_prompt()` using the `USER` config so the voice matches "your usual friend-who's-an-engineer energy") answers using only the research data. `DOCUMENT_PROMPT` writes 1,500–2,500-word structured documents with inline `[Source: URL]` citations, a Key Takeaways section, and a Sources section. `SUMMARY_PROMPT` writes a 2–4 sentence chat message confirming the save.
- **Known sources.** The module ships a `KNOWN_SOURCES` dict that pre-injects authoritative URLs (gov.uk for UK visas, vendor docs for Stripe/Paystack/Supabase/Modal/Railway/Vercel/Ollama) when the task mentions those topics, so the agent fetches directly instead of searching.
- **Routing signals.** The `research_patterns` block matches `search|look up|google|research|find out|find info <X>`, `search for`, `what is|are <10+ chars>` (excluding vibe phrases like "what's the move"), and `who|where|when|why|how <10+ chars>`. The LLM classifier prompt adds "who is [person]", "tell me about [topic]", and "write a SHORT / QUICK / BRIEF report/summary/overview on [topic]" (even with "save to desktop").
- **Example commands.**
  - "who is Geoffrey Hinton"
  - "search for the latest on the UK Global Talent visa"
  - "tell me about Modal Labs"
  - "write a short brief on vector databases and save it to my desktop"
  - "quick summary of the YC W26 batch"
- **File-save heuristic.** `_wants_file(task)` returns `True` only when the task contains a save verb (`save|write|create|make|store|export|draft|generate|produce`) **and** a file noun (`file|pdf|docx|markdown|report|document|paper|summary|note|brief`) or a known folder (`desktop|downloads|documents|~/|/users/`). This keeps "what's X?" fast and chat-only.
- **Gotchas.** (a) The agent explicitly sets `max_iterations = 2` but then bypasses `BaseAgent.run()` entirely — the two-call flow is in its own `run()` override. Don't try to tune behaviour via `max_iterations`. (b) `KNOWN_SOURCES` is a manual allow-list of authoritative URLs; add entries here when you notice the agent repeatedly search-churning for a topic that has one canonical source.

### social_agent

Source: [`social_agent.py`](../friday/agents/social_agent.py).

- **Scope.** X / Twitter only. Posting, replying, quote-tweeting, liking, retweeting, searching, mentions, user lookups.
- **Tools.** Full [`x_tools`](../friday/tools/x_tools.py) set: `post_tweet`, `delete_tweet`, `like_tweet`, `retweet`, `search_x`, `get_my_mentions`, `get_x_user`, plus any others exported.
- **Max iterations.** `max_iterations = 3` — tight, because each X action is a single well-scoped call.
- **System prompt.** Short and strict. Forbids posting without confirmation, forbids liking/retweeting unless explicitly told to, requires the first response to be a tool call, and warns about credits (`search_x` and `get_x_user` cost credits; posting/mentions are cheap). Caps tweets at 280 chars and tells the agent never to change the user's voice — post exactly what the user says.
- **Routing signals.** The `social_patterns` block is checked **before** research so `@username` queries do not get misrouted. It matches `tweet|post this|that|about|on`, `post on x|twitter`, `my mentions|@mentions`, `search x for`, `like|retweet|rt that tweet`, `delete my tweet`, `who is @user`, bare `@username`, `twitter|x.com`, `on x`, bare `tweet`, `trending on x`.
- **Example commands.**
  - "post this on X: shipped FRIDAY's agent router today"
  - "check my mentions"
  - "search X for 'claude code hooks'"
  - "who is @karpathy"
  - "retweet that last post"
- **Gotchas.** (a) The X API has low free-tier limits; the prompt calls out credit-expensive tools so the agent does not burn monthly allowance on exploratory searches. (b) Never lets the model re-run `search_x` in a loop — one query per turn. (c) All writes go through confirmation — posting requires the user to approve the exact text first.

### system_agent

Source: [`system_agent.py`](../friday/agents/system_agent.py).

- **Scope.** Everything that involves controlling the Mac: apps, windows, volume, dark mode, AirDrop, iPhone Mirroring, AppleScript, terminal commands, files, browser automation (Playwright), PDF operations, OCR, and screen vision. Also handles generic form filling and standing-order "watch tasks" routed from the router.
- **Tools (core, always loaded):** `run_command`, `run_background` from [`terminal_tools`](../friday/tools/terminal_tools.py); `open_application`, `close_application`, `type_text`, `take_screenshot`, `get_system_info`, `run_applescript`, `set_volume`, `toggle_dark_mode`, `play_music`, `open_url` from [`mac_tools`](../friday/tools/mac_tools.py); `read_file`, `list_directory` from [`file_tools`](../friday/tools/file_tools.py). If [`screencast_tools`](../friday/tools/screencast_tools.py) imports: `cast_screen_to`, `stop_screencast`, `open_on_extended_display`, `list_displays`.
- **Dynamic tool injection.** `run()` inspects the task text and injects extra tool packs on demand: **browser** tools ([`browser_tools`](../friday/tools/browser_tools.py): navigate, screenshot, click, fill, type, check, select, scroll, elements, upload, get_text, execute_js, back, wait_for_login, close, plus batch `discover_form` and `fill_form`) when keywords like `browser|navigate|webpage|linkedin|netflix|.com` appear; **CV** tools (`generate_pdf`, `tailor_cv` from [`cv_tools`](../friday/tools/cv_tools.py)) when the task is a form-fill; **PDF** tools ([`pdf_tools`](../friday/tools/pdf_tools.py)) on any `pdf` keyword; **screen** tools ([`screen_tools`](../friday/tools/screen_tools.py): `ocr_screen`, `ask_about_screen`, `capture_full_page`, `solve_screen_questions`) on `screen|see what|look at|ocr|solve|question|quiz|exam`.
- **Max iterations.** `max_iterations = 5` by default, bumped to **10** for form-fill tasks (which need discover → fill → verify loops). Both are reset after each `run()`.
- **System prompt.** Built by `get_system_prompt()` which re-reads `USER` config and inserts a `{form_identity_block}` with the user's name/email/phone/GitHub/website/location for form filling. The prompt hammers on (a) chaining — multi-verb tasks MUST call a tool for every step before returning text; (b) honesty — if no tool can do it, say so; (c) a full five-step form-filling playbook (discover → text fields → checkboxes/dropdowns/radios → upload → verify, with a two-cycle bail-out rule); (d) the login flow (when `browser_navigate` returns `login_required: true`, call `browser_wait_for_login` and continue — never screenshot a login page and call it done); and (e) AirDrop AppleScript for "send to phone" requests.
- **Routing signals.** Multiple blocks in the router feed into system_agent. `screen_patterns` (`can you see`, `look at my screen`, `what's on screen`, `ocr`, `solve the questions`). `form_patterns` (`fill the form`, `complete the form`, `submit the form`). `system_patterns` (`open|launch|start <app>`, `screenshot`, `dark mode|light mode`, `battery|ram|cpu|storage`, `go to|navigate to <url>`, `what's running`, `kill the process`, `airdrop`, `iphone mirroring`, `pdf read|extract|merge|split|rotate|encrypt|decrypt`). `watch_patterns` for standing orders (`for the next 2 hours check my messages every 5 minutes`). `cron_patterns` for scheduled jobs (`every weekday at 8am…`, `list my crons`) — the system agent hosts cron management too.
- **Example commands.**
  - "open Cursor"
  - "take a screenshot and describe it"
  - "what's on my screen"
  - "solve the questions on my screen"
  - "fill the form on my screen"
  - "how much battery do I have"
  - "turn on dark mode"
  - "merge the PDFs in my Downloads folder"
  - "every weekday at 8am give me a briefing" (cron)
  - "airdrop that screenshot to my phone"
- **Gotchas.** (a) The dynamic injection is keyed off `task` text only, not the actual tool schemas the LLM sees — so if you rename a keyword (`navigate` → `browse`) and forget to update the trigger list, tools silently won't be injected. (b) After every `run()`, the agent calls `self.__init__()` to reset its tool dict and max iterations; any stateful tool must live in the tool module, not on the agent. (c) `system_agent` hosts cron management for historical reasons, but the LLM classifier still mentions a `cron_agent` — routing usually ends up here.

## 4. How to write a new agent

The pattern is small by design. If a new capability cluster appears (e.g. a `finance_agent` for banking or a `travel_agent` for bookings), here is the recipe.

### 4.1 Minimum required attributes

A new agent is a subclass of [`BaseAgent`](../friday/core/base_agent.py) with four class-level attributes plus an `__init__` that wires up tools.

```python
from friday.core.base_agent import BaseAgent
from friday.tools.my_tools import TOOL_SCHEMAS as MY_TOOLS


SYSTEM_PROMPT = """You are FRIDAY's <area> specialist.
... task rules, tool mapping, tone ..."""


class MyAgent(BaseAgent):
    name = "my_agent"               # must end in _agent; matches router keys
    system_prompt = SYSTEM_PROMPT   # see prompt-writing rules below
    max_iterations = 5              # tight for single-step, higher for form loops
    model = None                    # keep default; override only if measurably better

    def __init__(self):
        self.tools = {**MY_TOOLS}   # name -> {"fn": <async callable>, "schema": <Ollama schema dict>}
        super().__init__()          # builds self.tool_definitions from self.tools
```

The contract `BaseAgent` expects from every tool entry:

- `fn`: an **async** callable that returns a `ToolResult` (see [`friday/core/types.py`](../friday/core/types.py)).
- `schema`: a dict matching the Ollama / OpenAI tool-schema format (`type: "function"`, `function.name`, `function.description`, `function.parameters`).

`BaseAgent._build_tool_definitions()` gathers those schemas and hands them to `cloud_chat(..., tools=...)` on every turn. Nothing else is required — the ReAct loop, parallel tool execution, file-path capture from tool results (screenshots, PDFs, CVs, etc. are auto-discovered for the CLI preview), skill loading from [`friday/skills/`](../friday/skills/), and conversation logging all come for free.

### 4.1.1 Worked example — `finance_agent`

Hypothetical: you want to add banking. The end-to-end delta would be:

```python
# 1. friday/tools/banking_tools.py
from friday.core.types import ToolResult

async def get_balance(account: str = "main") -> ToolResult:
    ...
async def list_transactions(account: str = "main", limit: int = 20) -> ToolResult:
    ...

TOOL_SCHEMAS = {
    "get_balance": {
        "fn": get_balance,
        "schema": {
            "type": "function",
            "function": {
                "name": "get_balance",
                "description": "Read the current balance of a bank account.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "account": {"type": "string", "description": "Account nickname (default 'main')"},
                    },
                },
            },
        },
    },
    # ... list_transactions schema here
}
```

```python
# 2. friday/agents/finance_agent.py
from friday.core.base_agent import BaseAgent
from friday.tools.banking_tools import TOOL_SCHEMAS as BANK_TOOLS

SYSTEM_PROMPT = """You manage the user's personal finances.

ALWAYS respond in English.

RULES:
1. You MUST call tools. NEVER invent balances or transactions.
2. Your first response MUST be a tool call.
3. NEVER move money without confirm=True.

TOOL MAPPING:
- "what's my balance" → get_balance()
- "show my transactions" → list_transactions(limit=20)
- "last 50 transactions on savings" → list_transactions(account="savings", limit=50)
"""


class FinanceAgent(BaseAgent):
    name = "finance_agent"
    system_prompt = SYSTEM_PROMPT
    max_iterations = 5

    def __init__(self):
        self.tools = {**BANK_TOOLS}
        super().__init__()
```

```python
# 3. friday/core/orchestrator.py — add the import and registry line
from friday.agents.finance_agent import FinanceAgent
# ... inside FridayCore.__init__:
self.agents = {
    ...,
    "finance_agent": FinanceAgent(),
}
```

```python
# 4. friday/core/router.py — match_agent(): add BEFORE research_patterns
finance_patterns = [
    r"\b(balance|balances)\b",
    r"\b(transactions?|transfers?)\b",
    r"\b(bank|banking|account)\b",
    r"\bhow much (money|cash) do i have\b",
]
if any(re.search(p, s) for p in finance_patterns):
    return ("finance_agent", raw)
```

And in `_CLASSIFY_PROMPT` add a one-paragraph description and append `finance_agent` to `valid_agents`. That's the whole surface area.

### 4.2 Prompt-writing rules

Look at the existing agents before writing yours. The ones that work well share a shape:

- **Rule 1 — first response must be a tool call.** All action agents (comms, system, job, monitor, social) state this explicitly. It prevents the model from making up results.
- **Rule 2 — no fabrication.** Every agent that touches real data says "you know NOTHING about X, you MUST call tools."
- **Rule 3 — explicit tool mapping.** For each common user phrasing, spell out exactly which tool to call with which args. `comms_agent` is the gold standard here.
- **Rule 4 — `confirm=True` for destructive calls.** Sending email, texting, posting tweets, submitting applications — require confirmation. Let the user say "send it" as a second turn.
- **Rule 5 — always respond in English.** Every agent pins this in case the model drifts.
- **Rule 6 — describe the tone, not the persona.** FRIDAY's voice lives in [`friday/core/prompts.py`](../friday/core/prompts.py); agent prompts focus on task mechanics.

### 4.3 Tool layout

Add a new file to [`friday/tools/`](../friday/tools/) that exports a `TOOL_SCHEMAS` dict. Keep one module per capability cluster (email, calendar, browser, etc.). The module's async functions are the `fn` values; the hand-written schemas alongside them are the `schema` values. Guard optional integrations with a `try: import …` so missing deps do not break startup — `comms_agent` does this for WhatsApp and SMS, `system_agent` does it for screencast, browser, and CV.

### 4.4 Registering the agent

Two edits register a new agent with the orchestrator:

1. **Import and instantiate in [`friday/core/orchestrator.py`](../friday/core/orchestrator.py)** — add your agent to the `self.agents = {...}` dict in `FridayCore.__init__` alongside the existing ten.
2. **Add routing rules in [`friday/core/router.py`](../friday/core/router.py)** — two places to edit:
   - `match_agent()` — add a `<name>_patterns` regex block returning `(your_agent_name, raw)`. Order matters; place it before broader agents (e.g. research) that might swallow your phrasing.
   - `classify_intent()`'s `_CLASSIFY_PROMPT` — add a short description of your agent so the Groq classifier knows when to pick it, add your agent name to `valid_agents`, and if relevant add a hard rule to the `HARD RULES` block.

Optional third touchpoint: if any input should bypass the LLM entirely, add a pattern to [`friday/core/fast_path.py`](../friday/core/fast_path.py) (see `household_agent`'s fast path for the pattern — direct tool execution, no model call).

### 4.5 Iteration budget

Pick `max_iterations` based on how many tool turns the agent genuinely needs:

- **2–3** when there is a fixed workflow (research: pick tools → answer; social: one call per action).
- **5** for most tool-using agents (comms, monitor, system default).
- **8–10** when there are verify loops (household, code, system in form-fill mode).
- **30** only for truly multi-phase autonomous flows (job_agent: browse → read → tailor → generate → fill → verify → submit can easily hit 15+ turns).

Too low and the agent bails mid-task with `max_iterations_exceeded`; too high and a confused model can burn tokens in a loop. The `BaseAgent` loop logs the full ReAct trace via `log_react_trace` to the conversation-log store, so you can review real runs and tune the cap.

### 4.6 Testing

The fastest loop: run [`friday/cli.py`](../friday/cli.py) with `FRIDAY_DEBUG=1` in the environment, issue a representative command, and watch the route decision, tool calls, and iteration count print. For unit-level testing, call `agent.run(task)` directly in an async test — `BaseAgent.run` returns an `AgentResponse` you can assert on (`success`, `tools_called`, `result`, `media_paths`).

### 4.7 Checklist before merging a new agent

- [ ] Subclass of `BaseAgent` with `name`, `system_prompt`, `tools`, `max_iterations`.
- [ ] Tool modules under [`friday/tools/`](../friday/tools/) expose `TOOL_SCHEMAS`.
- [ ] Optional integrations wrapped in `try: import …` so missing deps don't break boot.
- [ ] System prompt states "first response must be a tool call" for any action agent.
- [ ] System prompt has an explicit tool-mapping table for common phrasings.
- [ ] Destructive operations require `confirm=True`.
- [ ] Agent instantiated in `FridayCore.__init__` in [`orchestrator.py`](../friday/core/orchestrator.py).
- [ ] Regex block added to `match_agent()` in [`router.py`](../friday/core/router.py), ordered correctly.
- [ ] Agent described in `_CLASSIFY_PROMPT` and added to `valid_agents` in `classify_intent()`.
- [ ] Optional: fast-path pattern added to [`fast_path.py`](../friday/core/fast_path.py) for instant commands.
- [ ] Optional: `AGENT_SKILLS` entry added if the agent should auto-load skills.
- [ ] At least one real example tested through the CLI with `FRIDAY_DEBUG=1`.
- [ ] Row added to the summary table in this document.
- [ ] Deep-dive section added to this document (scope / tools / max iters / prompt / routing / examples / gotchas).

### 4.8 Routing decisions: trust the LLM, default to chat on uncertainty

Two rules now govern routing, both encoded in [`friday/core/orchestrator.py`](../friday/core/orchestrator.py):

1. **Trust the LLM's `CHAT_DECISION` verdict.** When `classify_intent()` returns the `CHAT_DECISION` sentinel, the orchestrator goes straight to `_fast_chat`. No regex override, no second-guessing. This was the fix for "why is the sky blue" landing in `research_agent` — the LLM had correctly classified it as chat, but the regex layer overrode that decision.
2. **Default to chat when uncertain (cloud up).** When the LLM returns `None` (= unexpected output), the orchestrator only falls back to regex if the cloud is *offline*. When the cloud is up but the classifier was unsure, the safe default is chat — not regex. The reasoning: regex over-routes ("what is photosynthesis" matches a regex looking for "what is X" and is sent to research). Chat is the cheapest, lowest-risk path.

What this means when writing a new agent: focus the entries you add to `_CLASSIFY_PROMPT` on what the agent *can do*, with concrete example phrasings. Don't lean on the regex layer to catch your agent — it's a fallback, not a primary path. If your agent needs a particular phrasing to route correctly, it goes in the classify prompt's section for that agent.

### 4.9 Provider pin (`FRIDAY_PRIMARY_PROVIDER`)

When you're testing routing logic, latency, or response quality, it's useful to pin which LLM the classifier *and* every agent calls. [`friday/core/config.py`](../friday/core/config.py) reads `FRIDAY_PRIMARY_PROVIDER` from `~/Friday/.env`:

| Value | Effect |
|---|---|
| `groq` | Pin Groq (Qwen3-32B) as primary regardless of OpenRouter being configured. Useful when OpenRouter's daily free-tier cap kicks in. |
| `openrouter` | Pin OpenRouter (Gemma 4 :free) as primary even when Groq is configured. |
| `auto` (or unset) | Default behaviour — uses key-priority order (explicit override → OpenRouter → Google AI Studio (if opted in) → Groq → Ollama). |

Other configured providers still appear in the runtime fallback chain underneath the pin, so you keep automatic recovery when the pinned primary 429s or 5xxs. The pin intentionally ignores the env `CLOUD_MODEL` override so an OpenRouter-flavoured model name doesn't leak into a Groq pin.

## 5. Patterns seen across every agent

After reading ten agents, the patterns that actually matter are surprisingly few.

### 5.1 Tool wiring

Every agent ends up with the same shape in `__init__`:

```python
def __init__(self):
    self.tools = {
        **MODULE_A_SCHEMAS,
        **{k: v for k, v in MODULE_B_SCHEMAS.items() if k in ("one", "two")},
    }
    super().__init__()
```

The `dict(...)` or `{**A, **B}` merge pattern lets you pick whole modules or subset them. Subsetting is used when a module exports twenty tools but the agent only needs three — `code_agent` does this with `WEB_TOOLS` (only `search_web`) and `MEMORY_TOOLS` (only `search_memory`). Merging the whole module is the default — `memory_agent`, `social_agent`, `monitor_agent`, `household_agent` all use `{**X_TOOLS}` unchanged.

### 5.2 Optional integrations

Whenever a tool module depends on something that might not be installed (Playwright, Twilio, WhatsApp bridge, WeasyPrint, screencast utilities), the pattern is:

```python
try:
    from friday.tools.whatsapp_tools import TOOL_SCHEMAS as WHATSAPP_TOOLS
    _HAS_WHATSAPP = True
except Exception:
    WHATSAPP_TOOLS = {}
    _HAS_WHATSAPP = False
```

Then inside `__init__`, guard the tool registration with the flag. This is what lets FRIDAY boot on a fresh machine that hasn't set up every integration yet.

### 5.3 Settings-reactive prompts

`comms_agent`, `system_agent`, and `job_agent` all define a `get_system_prompt()` function that reads `USER` config at agent-construction time and inlines the relevant block (contact aliases, applicant identity, form-fill identity). Calling `self.system_prompt = get_system_prompt()` in `__init__` means the Settings UI can edit the config and the next agent run picks it up without a restart.

### 5.4 First-response-is-a-tool-call rule

Every action agent (comms, system, monitor, job, social, household's LLM path) states this explicitly. The reason: small models love to open with "Sure! Let me check your emails…" and then end the turn without actually calling `read_emails`. The rule exists to kill that failure mode at the system-prompt level.

### 5.5 Confirmation for destructive writes

The pattern is `confirm=True` as an explicit tool argument, not a prompt-level "are you sure". `send_email`, `send_imessage`, `send_sms`, `send_whatsapp`, `post_tweet`, `like_tweet`, `retweet`, `delete_tweet`, job-application submit — all gate on this flag. The agent's job is to collect the user's verbal confirmation ("yes, send it") and then re-issue the tool with `confirm=True`.

### 5.6 Model overrides

Most agents run on the cluster default (see [`friday/core/config.py`](../friday/core/config.py) and [`friday/core/llm.py`](../friday/core/llm.py)). `code_agent` sets `model = "moonshotai/kimi-k2-instruct"` because it tested better on code. If you fork an agent for a domain where the default underperforms, override here rather than editing the global config.

## 6. Voice and tone

Agent prompts focus on task mechanics; FRIDAY's voice lives in [`friday/core/prompts.py`](../friday/core/prompts.py) and is injected by the orchestrator when it wraps the agent's result for the user. Agents mostly say "always respond in English" and leave personality to the wrapper. Two exceptions: `research_agent`'s answer prompt pulls `USER.assistant_name` so the preamble matches the user's configured persona, and `household_agent`'s `_format_result` hand-writes short, punchy replies ("TV's off." / "Volume set to 42.") so the fast path feels instant.

Rule of thumb: if the agent's reply is going to be read verbatim by the user (e.g. household's fast path, monitor's confirmation), own the phrasing in the agent. If the orchestrator is going to synthesise the final reply from tool results, let the agent return structured data and keep the voice out of it.

## 7. Debugging an agent

- **Enable debug logging.** Set `FRIDAY_DEBUG=1` before running the CLI. You'll see the route decision, each tool call with args, each tool result summary, and iteration count.
- **Inspect the ReAct trace.** Every run writes to the conversation log via `log_react_trace` in [`friday/memory/conversation_log.py`](../friday/memory/conversation_log.py). The schema is `session_id | agent_name | task | messages | tools_called | final_answer | success | duration_ms | iterations`. Query this when you see intermittent failures.
- **Test the router in isolation.** `router.match_agent("your input here", [])` returns `(agent_name, task)` or `None`. Use this from a Python REPL to diagnose why a phrasing isn't landing on your agent.
- **Reduce `max_iterations` during dev.** If you're debugging why the agent spirals, lower the cap to 2 or 3 — it fails fast with `max_iterations_exceeded` and you can read the last few messages to see what it was trying to do.
- **Watch for `_compact_data` over-trimming.** If your agent's tool returns a shape `_compact_data` doesn't recognise, it just passes through with 200-char string truncation. For a new shape (e.g. bank-account objects), consider adding a branch to `_compact_data` so the model gets the fields it cares about without the bloat.

## 8. Routing cheat sheet

When a user phrasing lands on the "wrong" agent, this is the usual cause — the router's precedence order. Blocks earlier in `match_agent()` win. Current order (abbreviated):

1. Context-aware follow-ups (inherits `recent_agent` if the input has pronouns like "about it" / "tell me more" and no override keywords).
2. `comms_patterns` — email, calendar, iMessage, WhatsApp, FaceTime, contacts.
3. Comms follow-ups ("send it", "draft it" when the recent conversation is comms-flavoured).
4. `social_patterns` — anything about X / Twitter / @username.
5. `household_patterns` — TV, smart home.
6. Household follow-ups (when the last agent was household).
7. `monitor_patterns` — watchers, tracking.
8. `job_patterns` — CV, cover letter, apply.
9. `watch_patterns` — standing orders ("for the next hour, watch my messages"). → `system_agent`.
10. `cron_patterns` — recurring schedules. → `system_agent`.
11. `deep_research_patterns` — paper, comprehensive report, deep dive.
12. `screen_patterns` — vision / OCR. → `system_agent`.
13. `research_patterns` — general search / look-up / who is X.
14. `form_patterns` — "fill the form". → `system_agent`.
15. `system_patterns` — apps, screenshots, volume, dark mode, PDFs, navigate.
16. `code_patterns` — debug, git, run, file edits.
17. `memory_patterns` — remember / recall.

Three hard-rule overrides in the LLM classifier prompt:

- **"Apply for a job"** always lands on `job_agent`, never `research_agent`.
- **"Open [site]"** always lands on `system_agent`, never `research_agent`.
- **Device stats** (battery/RAM/CPU/storage) always `system_agent`.

If you add a new agent and its trigger phrases collide with an earlier block, insert your regex block *above* the conflicting one — or add a keyword override at the top of `match_agent()` like the social patterns do for `@username`.

## 9. Cross-references

- Base loop: [`friday/core/base_agent.py`](../friday/core/base_agent.py)
- Router: [`friday/core/router.py`](../friday/core/router.py)
- Orchestrator + agent registry: [`friday/core/orchestrator.py`](../friday/core/orchestrator.py)
- Zero-LLM fast path: [`friday/core/fast_path.py`](../friday/core/fast_path.py)
- One-shot regex → tool path: [`friday/core/oneshot.py`](../friday/core/oneshot.py)
- Personality / top-level prompts: [`friday/core/prompts.py`](../friday/core/prompts.py)
- Conversation & ReAct trace logs: [`friday/memory/conversation_log.py`](../friday/memory/conversation_log.py)
- Skills (auto-loaded per agent): [`friday/skills/`](../friday/skills/)
- Response / tool types: [`friday/core/types.py`](../friday/core/types.py)
