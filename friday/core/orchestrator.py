"""FRIDAY Core — The Orchestrator.

Routes all tasks. Never does the work itself. Thinks, delegates, assembles, responds.
Uses the LLM to classify intent and pick the right agent, then runs it.

Thin wrapper — actual logic lives in:
  prompts.py   — personality, system prompt, dispatch tool schema
  router.py    — intent classification, pattern matching
  fast_path.py — zero-LLM instant commands (TV, greetings)
  oneshot.py   — regex → tool → 1 LLM format
  briefing.py  — parallel tool calls → 1 LLM synthesis
"""

import asyncio
import json
import logging
import re
import time
from datetime import datetime

log = logging.getLogger("friday.orchestrator")
from typing import AsyncGenerator, Generator

from friday.core.llm import cloud_chat, extract_text, extract_tool_calls, extract_stream_content
from friday.core.config import MODEL_NAME
from friday.core.types import AgentResponse, ToolResult
from friday.memory.store import get_memory_store
from friday.background.memory_processor import get_memory_processor
from friday.memory.conversation_log import log_turn
from friday.agents.code_agent import CodeAgent
from friday.agents.research_agent import ResearchAgent
from friday.agents.memory_agent import MemoryAgent
from friday.agents.comms_agent import CommsAgent
from friday.agents.system_agent import SystemAgent
from friday.agents.household_agent import HouseholdAgent
from friday.agents.monitor_agent import MonitorAgent
from friday.agents.briefing_agent import BriefingAgent
from friday.agents.job_agent import JobAgent
from friday.agents.social_agent import SocialAgent
from friday.agents.deep_research_agent import DeepResearchAgent

# ── Extracted modules ────────────────────────────────────────────────────────
from friday.core.prompts import (
    get_personality, get_personality_slim, user_context_block, SYSTEM_PROMPT, DISPATCH_TOOL,
    SIMPLE_PATTERNS, COMPLEX_SIGNALS, needs_thinking,
)
from friday.core.router import (
    classify_intent, match_agent, is_likely_chat, needs_agent as _needs_agent,
    recent_comms_context, extract_topic_from_conversation,
)
from friday.core.fast_path import fast_path as _fast_path
from friday.core.oneshot import try_oneshot as _try_oneshot
from friday.core.briefing import (
    direct_briefing as _direct_briefing,
    direct_briefing_streamed as _direct_briefing_streamed,
)


class FridayCore:
    def __init__(self):
        self.agents = {
            "code_agent": CodeAgent(),
            "research_agent": ResearchAgent(),
            "memory_agent": MemoryAgent(),
            "comms_agent": CommsAgent(),
            "system_agent": SystemAgent(),
            "household_agent": HouseholdAgent(),
            "monitor_agent": MonitorAgent(),
            "briefing_agent": BriefingAgent(),
            "job_agent": JobAgent(),
            "social_agent": SocialAgent(),
            "deep_research_agent": DeepResearchAgent(),
        }
        self.memory = get_memory_store()
        self.conversation: list[dict] = []
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._mem_processor = get_memory_processor()
        self._mem_processor.start()
        self._turn_start: float = 0  # set at beginning of each turn
        self._last_agent: str | None = None  # for confirmation routing ("yes" → re-dispatch)

    def _log_and_append(self, user_input: str, response: str,
                        route: str, agent_name: str = None,
                        tools_called: list[str] = None):
        """Append to conversation history AND write to training log."""
        self.conversation.append({"role": "user", "content": user_input})
        self.conversation.append({"role": "assistant", "content": response})
        # Track last agent for confirmation routing
        if agent_name:
            self._last_agent = agent_name

        # Auto-detect corrections and store them for self-improvement
        self._auto_learn(user_input, response)
        elapsed = int((time.monotonic() - self._turn_start) * 1000) if self._turn_start else None
        log_turn(
            session_id=self.session_id,
            user_input=user_input,
            response=response,
            route=route,
            agent_name=agent_name,
            tools_called=tools_called,
            duration_ms=elapsed,
        )

    def _auto_learn(self, user_input: str, previous_response: str):
        """Detect corrections/complaints and auto-store them for self-improvement.

        Runs after every turn. If the user is correcting FRIDAY, store what
        went wrong so agents can avoid it next time via search_memory.
        """
        low = user_input.strip().lower()

        # Detect correction signals
        correction_signals = [
            "thats not what i", "that wasnt what i", "that's not what i",
            "that wasn't what i", "you didnt", "you didn't",
            "not what i asked", "not what i meant", "i said",
            "wrong", "thats wrong", "that's wrong",
            "dumb", "stupid", "slop", "ai slop", "basic",
            "generic", "useless", "not helpful", "doesnt answer",
            "didn't answer", "you missed", "you forgot",
            "stop doing that", "dont do that", "don't do that",
            "i already told you", "how many times",
        ]

        is_correction = any(sig in low for sig in correction_signals)
        if not is_correction:
            return

        # Get the previous FRIDAY response that's being corrected
        prev_friday = ""
        for msg in reversed(self.conversation[:-2]):
            if msg["role"] == "assistant":
                prev_friday = msg["content"][:200]
                break

        # Build the correction memory
        correction = (
            f"CORRECTION: When user said something similar to the previous message, "
            f"FRIDAY responded with: \"{prev_friday}...\" "
            f"User corrected: \"{user_input[:150]}\". "
            f"Learn: avoid this response pattern in future."
        )

        # Store asynchronously (don't block the response)
        try:
            import asyncio
            asyncio.ensure_future(self._store_correction(correction))
        except Exception:
            pass

    async def _store_correction(self, correction: str):
        """Store a correction in memory."""
        try:
            from friday.tools.memory_tools import store_memory
            await store_memory(content=correction, category="correction", importance=8)
            log.info(f"Self-improving: stored correction")
        except Exception as e:
            log.debug(f"Self-improving: failed to store correction: {e}")

    def _build_system_prompt(self, user_input: str) -> str:
        memory_context = self.memory.build_context(query=user_input)
        project_context = self.memory.get_project_context()
        current_time = datetime.now().strftime("%A %-I:%M%p")
        return SYSTEM_PROMPT.format(
            personality=get_personality(),
            user_context=user_context_block(),
            memory_context=memory_context,
            project_context=project_context,
            current_time=current_time,
        )

    # ── Fast Path: direct tool calls, zero LLM ──────────────────────────────

    async def fast_path(self, user_input: str) -> str | None:
        """Delegate to fast_path module."""
        return await _fast_path(user_input, self.conversation)

    # ── Fast chat: slim prompt for conversational responses ────────────────

    async def _fast_chat(self, user_input: str, _chunk) -> str:
        """Fast conversational response with a slim system prompt (~500 tokens)."""
        messages = [{"role": "system", "content": get_personality_slim()}]
        for msg in self.conversation[-10:]:
            truncated = {**msg, "content": msg["content"][:400]}
            messages.append(truncated)
        messages.append({"role": "user", "content": user_input})

        response_stream = cloud_chat(messages=messages, stream=True, max_tokens=300)
        full_text = []
        for chunk in response_stream:
            content = extract_stream_content(chunk)
            if content:
                _chunk(content)
                full_text.append(content)

        text = "".join(full_text)
        self._log_and_append(user_input, text, route="fast_chat")
        self._mem_processor.process(user_input, text)
        return text

    # ── Briefing ─────────────────────────────────────────────────────────────

    async def direct_briefing(self, on_status=None) -> str:
        """Delegate to briefing module."""
        return await _direct_briefing(self.conversation, on_status)

    # ── Background Agent Dispatch ──────────────────────────────────────────

    def dispatch_background(self, user_input: str, on_update=None):
        """Run agent work in the background. Returns immediately."""
        import threading

        def _worker():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    self._background_work(user_input, on_update)
                )
                # SMS delivery — if _background_work collected chunks for SMS
                if hasattr(self, '_sms_chunks') and self._sms_chunks:
                    sms_text = "".join(self._sms_chunks)
                    self._sms_chunks = []
                    if sms_text.strip():
                        try:
                            from friday.tools.notify import send_result_sms
                            sent = loop.run_until_complete(send_result_sms(sms_text))
                            if on_update and sent:
                                on_update("STATUS:texted you the results")
                        except Exception:
                            pass
                if on_update:
                    on_update("DONE:")
            except Exception as e:
                if on_update:
                    on_update(f"ERROR:{e}")
            finally:
                loop.close()

        t = threading.Thread(target=_worker, daemon=True, name="friday-bg-agent")
        t.start()

    async def _background_work(self, user_input: str, on_update=None):
        """Execute agent work with streaming.

        Flow priority (fastest first):
          1.   Briefing regex → parallel tools + 1 LLM synthesis  (1 LLM call)
          1.5  User override  → @agent explicit dispatch          (agent ReAct)
          2.   One-shot       → regex tool + 1 LLM format         (1 LLM call)
          2.5  Direct dispatch→ LLM picks tool + 1 LLM format     (2 LLM calls)
          3.   Agent regex    → direct dispatch, no routing/synth  (2-4 LLM calls)
          4.   Fast chat      → slim prompt, no routing context    (1 LLM call)
          5.   LLM routing    → full routing for ambiguous queries (4 LLM calls)
        """
        self._turn_start = time.monotonic()
        s = user_input.strip().lower()

        # ── SMS delivery flag ────────────────────────────────────────────────
        # If user wants results texted to them, strip the SMS part from the input
        # so the LLM formats clean content (not "I've SMSed you..."), then we
        # send that clean content via SMS after completion.
        _sms_delivery = "sms" in s or ("text me" in s and "imessage" not in s)
        if _sms_delivery:
            # Strip the SMS delivery request so LLM just formats the actual content
            import re as _re
            user_input = _re.sub(
                r'\s*(?:and\s+)?(?:then\s+)?(?:sms|text)\s+(?:me|it to me|that to me)(?:\s+(?:the\s+)?results?)?\s*$',
                '', user_input, flags=_re.IGNORECASE,
            ).strip() or user_input
            s = user_input.strip().lower()

        def _status(msg):
            if on_update:
                on_update(f"STATUS:{msg}")

        def _media(path):
            """Emit a media file path for the UI to render as a preview."""
            if on_update:
                on_update(f"MEDIA:{path}")

        # Collect chunks for SMS delivery
        if _sms_delivery:
            self._sms_chunks = []

        def _chunk(text):
            if _sms_delivery:
                self._sms_chunks.append(text)
            if on_update:
                on_update(f"CHUNK:{text}")

        def _ack(msg):
            if on_update:
                on_update(f"ACK:{msg}")

        if _sms_delivery:
            _status("will text you the results")

        # ── Priority 1: Briefing → direct parallel dispatch (1 LLM call) ──
        if re.match(r"(catch me up|brief me|any updates|morning brief|what did i miss)", s):
            _ack("pulling everything at once")
            await _direct_briefing_streamed(self.conversation, _status, _chunk, user_input)
            return

        # ── Priority 1.5: User override — explicit agent targeting ──
        override = re.match(
            r"^(?:use |@)(comms|social|research|code|system|household|monitor|briefing|job|memory)\b\s*(.*)",
            s,
        )
        if not override:
            natural_override = re.search(
                r"(?:hand\s*(?:it\s+)?off\s+to|send\s+(?:it\s+)?to|give\s+(?:it\s+)?to|pass\s+(?:it\s+)?to|"
                r"let\s+(?:the\s+)?|route\s+(?:it\s+)?to|forward\s+(?:it\s+)?to)\s*(?:the\s+)?"
                r"(comms|social|research|code|system|household|monitor|briefing|job|memory)\s*(?:agent)?\b",
                s,
            )
            if natural_override:
                agent_key = natural_override.group(1)
                remainder = s[natural_override.end():].strip()
                override = type('Match', (), {
                    'group': lambda self, n: {1: agent_key, 2: remainder}[n]
                })()
        if override:
            agent_name = override.group(1) + "_agent"
            task = override.group(2).strip() or user_input
            label = override.group(1)
            _ack(f"{label} on it")
            _status(f"{label} working...")
            streamed = {"any": False}
            def _chunk_tracked(text):
                streamed["any"] = True
                _chunk(text)
            result = await self._dispatch(
                agent_name, task, user_input,
                on_status=lambda m: _status(m),
                on_chunk=_chunk_tracked,
            )
            response_text = result.result or "Couldn't get that done."
            self._log_and_append(user_input, response_text, route="override", agent_name=agent_name, tools_called=result.tools_called)
            if not streamed["any"]:
                _chunk(response_text)
            self._mem_processor.process(user_input, response_text, agent_name)
            return

        # ── Priority 2: One-shot tool calls (1 LLM call) ──
        oneshot = await _try_oneshot(
            s, user_input, self.conversation,
            self.memory, self.session_id, self._mem_processor,
            _ack, _status, _chunk, _media,
        )
        if oneshot:
            return

        # ── Priority 2.5: Direct tool dispatch (2 LLM calls) ──
        from friday.core.tool_dispatch import try_direct_dispatch
        dispatched = await try_direct_dispatch(
            user_input=user_input,
            conversation=self.conversation,
            _ack=_ack, _status=_status, _chunk=_chunk,
            session_id=self.session_id,
            memory=self.memory,
            mem_processor=self._mem_processor,
        )
        if dispatched:
            self.conversation.append({"role": "user", "content": user_input})
            # direct_dispatch logs its own tool calls via memory.log_agent_call
            return

        # ── Priority 2.7: Short confirmations → re-dispatch to last agent ──
        # "yes", "yeah", "go ahead" after an agent asked a follow-up question
        if re.match(r"^(yes|yeah|yep|yh|ye|yea|go ahead|do it|sure|ok|okay|please|proceed|bet|say less|aight|ight)\s*[.!?]*$", s):
            last_agent = self._last_agent
            if last_agent:
                label = last_agent.replace("_agent", "")
                _ack(f"{label} on it")
                _status(f"{label} working...")
                streamed = {"any": False}
                def _chunk_tracked(text):
                    streamed["any"] = True
                    _chunk(text)
                result = await self._dispatch(
                    last_agent, user_input, user_input,
                    on_status=lambda m: _status(m),
                    on_chunk=_chunk_tracked,
                )
                response_text = result.result or "Couldn't get that done."
                self._log_and_append(user_input, response_text, route="confirmation", agent_name=last_agent, tools_called=result.tools_called)
                if not streamed["any"]:
                    _chunk(response_text)
                self._mem_processor.process(user_input, response_text, last_agent)
                return

        # ── Priority 3: Agent dispatch ──
        # LLM first (capability-aware classify prompt with hard rules, ~1s on
        # Gemma 4). Regex fallback when cloud is offline.
        match = classify_intent(user_input, self.conversation) or match_agent(user_input, self.conversation, self.memory)
        if match:
            agent_name, task = match
            label = agent_name.replace("_agent", "")
            _ack(f"{label} on it")
            _status(f"{label} working...")

            # Track whether the agent streamed anything via _chunk so we don't
            # emit the full response AGAIN at the end (causing duplicates).
            streamed = {"any": False}
            def _chunk_tracked(text):
                streamed["any"] = True
                _chunk(text)

            result = await self._dispatch(
                agent_name, task, user_input,
                on_status=lambda m: _status(m),
                on_chunk=_chunk_tracked,
            )

            response_text = result.result or "Couldn't get that done."
            self._log_and_append(user_input, response_text, route="agent", agent_name=agent_name, tools_called=result.tools_called)
            # Only emit the result if the agent didn't already stream it
            if not streamed["any"]:
                _chunk(response_text)
            # Emit any media files produced by the agent's tools
            for path in getattr(result, "media_paths", []) or []:
                _media(path)
            self._mem_processor.process(user_input, response_text, agent_name)
            return

        # ── Priority 4: Conversational fast chat (1 LLM, slim prompt) ──
        if is_likely_chat(s):
            text = await self._fast_chat(user_input, _chunk)
            return

        # ── Priority 5: LLM routing fallback (4 LLM calls) ──
        system_prompt = self._build_system_prompt(user_input)
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self.conversation[-12:])
        messages.append({"role": "user", "content": user_input})

        response = cloud_chat(messages=messages, tools=[DISPATCH_TOOL])
        tool_calls = extract_tool_calls(response)

        if not tool_calls:
            text = extract_text(response)
            self._log_and_append(user_input, text, route="llm_fallback_chat")
            _chunk(text)
            self._mem_processor.process(user_input, text)
            return

        # LLM chose an agent — full routing + synthesis path
        agents = [tc["arguments"]["agent"].replace("_agent", "") for tc in tool_calls if tc["name"] == "dispatch_agent"]
        _ack(f"checking with {', '.join(agents)}" if agents else "working on it")

        agent_results = []
        for tc in tool_calls:
            if tc["name"] == "dispatch_agent":
                agent_name = tc["arguments"]["agent"]
                task = tc["arguments"]["task"]
                label = agent_name.replace("_agent", "")
                _status(f"{label} working...")
                result = await self._dispatch(agent_name, task, user_input, on_status=lambda m: _status(m))
                agent_results.append(result)

        if agent_results:
            _status("synthesizing...")
            synth_text = []
            for chunk in self.stream_synthesis(user_input, agent_results):
                _chunk(chunk)
                synth_text.append(chunk)
            full_response = "".join(synth_text)
            agent_names = ", ".join(agents) if agents else "agent"
            self._mem_processor.process(user_input, full_response, agent_names)
            return

        text = extract_text(response)
        _chunk(text)

    # ── Process methods (non-streaming, streaming, hybrid) ────────────────

    async def process(self, user_input: str) -> str:
        """Process user input — non-streaming. Used when tool calls may be needed."""
        self._turn_start = time.monotonic()
        system_prompt = self._build_system_prompt(user_input)

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self.conversation[-20:])
        messages.append({"role": "user", "content": user_input})

        response = cloud_chat(messages=messages, tools=[DISPATCH_TOOL])
        tool_calls = extract_tool_calls(response)

        if not tool_calls:
            text = extract_text(response)
            self._log_and_append(user_input, text, route="process_chat")
            return text

        agent_results = []
        for tc in tool_calls:
            if tc["name"] == "dispatch_agent":
                agent_name = tc["arguments"]["agent"]
                task = tc["arguments"]["task"]
                agent_result = await self._dispatch(agent_name, task, user_input)
                agent_results.append(agent_result)

        if agent_results:
            synthesis = await self._synthesize(user_input, agent_results)
            all_tools = [t for r in agent_results for t in (r.tools_called or [])]
            agent_names = ", ".join(r.agent_name for r in agent_results)
            self._log_and_append(user_input, synthesis, route="process_agent", agent_name=agent_names, tools_called=all_tools)
            return synthesis

        text = extract_text(response)
        self._log_and_append(user_input, text, route="process_fallback")
        return text

    def stream(self, user_input: str) -> Generator[str, None, None]:
        """Stream a direct response. For simple queries that won't need tool calls."""
        system_prompt = self._build_system_prompt(user_input)

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self.conversation[-20:])
        messages.append({"role": "user", "content": user_input})

        response_stream = cloud_chat(messages=messages, stream=True)

        full_text = ""

        for chunk in response_stream:
            content = extract_stream_content(chunk)
            if content:
                full_text += content
                yield content

        self._log_and_append(user_input, full_text.strip(), route="stream")

    async def process_and_stream(self, user_input: str, on_status=None) -> AsyncGenerator[str, None]:
        """Process with agents, streaming the final synthesis."""
        system_prompt = self._build_system_prompt(user_input)

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self.conversation[-20:])
        messages.append({"role": "user", "content": user_input})

        if on_status:
            on_status("routing...")

        response = cloud_chat(messages=messages, tools=[DISPATCH_TOOL])
        tool_calls = extract_tool_calls(response)

        if not tool_calls:
            text = extract_text(response)
            self._log_and_append(user_input, text, route="stream_chat")
            yield text
            return

        agent_results = []
        for tc in tool_calls:
            if tc["name"] == "dispatch_agent":
                agent_name = tc["arguments"]["agent"]
                task = tc["arguments"]["task"]
                if on_status:
                    label = agent_name.replace("_agent", "")
                    on_status(f"{label} working...")
                agent_result = await self._dispatch(agent_name, task, user_input, on_status=on_status)
                agent_results.append(agent_result)

        if agent_results:
            if on_status:
                on_status("synthesizing...")
            for chunk in self.stream_synthesis(user_input, agent_results):
                yield chunk
        else:
            text = extract_text(response)
            self._log_and_append(user_input, text, route="stream_fallback")
            yield text

    def needs_agent(self, user_input: str) -> bool:
        """Delegate to router module."""
        return _needs_agent(user_input, self.conversation)

    # ── Agent dispatch ────────────────────────────────────────────────────────

    async def _dispatch(self, agent_name: str, task: str, original_input: str, on_status=None, on_chunk=None) -> AgentResponse:
        """Dispatch to a specialist agent."""
        agent = self.agents.get(agent_name)
        if not agent:
            return AgentResponse(
                agent_name=agent_name,
                success=False,
                result=f"Unknown agent: {agent_name}",
                error="agent_not_found",
            )

        def on_tool_call(tool_name, tool_args):
            if on_status:
                friendly = {
                    "search_web": "searching",
                    "fetch_page": "reading page",
                    "store_memory": "saving to memory",
                    "search_memory": "checking memory",
                    "read_file": "reading file",
                    "write_file": "writing file",
                    "run_command": "running command",
                    "list_directory": "listing files",
                    "search_files": "searching files",
                    "read_emails": "checking emails",
                    "search_emails": "searching emails",
                    "read_email_thread": "reading thread",
                    "send_email": "sending email",
                    "draft_email": "drafting email",
                    "send_draft": "sending draft",
                    "edit_draft": "editing draft",
                    "label_email": "labeling email",
                    "get_calendar": "checking calendar",
                    "create_event": "creating event",
                    "run_background": "starting process",
                    "get_process": "checking process",
                    "kill_process": "killing process",
                    "run_applescript": "running AppleScript",
                    "open_application": "opening app",
                    "take_screenshot": "taking screenshot",
                    "get_system_info": "checking system",
                    "set_volume": "setting volume",
                    "toggle_dark_mode": "toggling dark mode",
                    "browser_navigate": "browsing",
                    "browser_screenshot": "capturing page",
                    "browser_click": "clicking element",
                    "browser_fill": "filling form",
                    "browser_get_text": "reading page",
                    "browser_wait_for_login": "waiting for login",
                    "turn_on_tv": "turning on TV",
                    "turn_off_tv": "turning off TV",
                    "tv_volume": "setting TV volume",
                    "tv_volume_adjust": "adjusting TV volume",
                    "tv_play_pause": "controlling playback",
                    "tv_mute": "muting TV",
                    "tv_launch_app": "launching on TV",
                    "tv_remote_button": "navigating TV",
                    "tv_status": "checking TV",
                    "tv_screen_off": "screen off (audio only)",
                    "tv_screen_on": "screen back on",
                    "tv_close_app": "closing TV app",
                    "tv_list_apps": "listing TV apps",
                    "tv_list_sources": "listing TV sources",
                    "tv_set_source": "switching TV input",
                    "tv_notify": "sending TV notification",
                    "tv_get_audio_output": "checking audio output",
                    "tv_set_audio_output": "switching audio output",
                    "tv_system_info": "getting TV info",
                    "pdf_read": "reading PDF",
                    "pdf_metadata": "checking PDF metadata",
                    "pdf_merge": "merging PDFs",
                    "pdf_split": "splitting PDF",
                    "pdf_rotate": "rotating PDF",
                    "pdf_encrypt": "encrypting PDF",
                    "pdf_decrypt": "decrypting PDF",
                    "pdf_watermark": "adding watermark",
                    "get_call_history": "checking call history",
                    "post_tweet": "posting tweet",
                    "delete_tweet": "deleting tweet",
                    "get_my_mentions": "checking X mentions",
                    "search_x": "searching X",
                    "like_tweet": "liking tweet",
                    "retweet": "retweeting",
                    "get_x_user": "looking up X user",
                    "browser_close": "closing browser",
                    "tv_type_text": "typing on TV",
                    "create_monitor": "creating monitor",
                    "list_monitors": "listing monitors",
                    "pause_monitor": "pausing monitor",
                    "delete_monitor": "deleting monitor",
                    "get_monitor_history": "checking history",
                    "force_check": "checking monitor",
                    "get_briefing_queue": "pulling briefing",
                    "get_monitor_alerts": "checking alerts",
                    "get_daily_digest": "building digest",
                    "mark_briefing_delivered": "marking delivered",
                    "get_cv": "loading CV",
                    "tailor_cv": "tailoring CV",
                    "write_cover_letter": "writing cover letter",
                    "generate_pdf": "generating PDF",
                }
                label = friendly.get(tool_name, tool_name)
                if tool_name == "search_web":
                    q = tool_args.get("query", "")
                    label = f'searching: "{q[:40]}"'
                elif tool_name == "fetch_page":
                    u = tool_args.get("url", "")
                    domain = u.split("//")[-1].split("/")[0] if "//" in u else u[:40]
                    label = f"reading {domain}"
                on_status(label)

        # Build context: memory + recent conversation
        memory_context = self.memory.build_context(query=original_input)
        conv_context = ""
        if self.conversation:
            recent = self.conversation[-6:]
            conv_lines = []
            from friday.core.user_config import USER
            user_role = USER.display_name
            for msg in recent:
                role = user_role if msg["role"] == "user" else "FRIDAY"
                conv_lines.append(f"{role}: {msg['content'][:300]}")
            conv_context = "Recent conversation:\n" + "\n".join(conv_lines)

        context = f"{memory_context}\n\n{conv_context}".strip()
        result = await agent.run(task=task, context=context, on_tool_call=on_tool_call, on_chunk=on_chunk)

        self.memory.log_agent_call(
            session_id=self.session_id,
            agent=agent_name,
            tool="dispatch",
            args={"task": task},
            result_summary=result.result[:200] if result.result else "",
            success=result.success,
            duration_ms=result.duration_ms or 0,
        )

        return result

    # ── Synthesis ─────────────────────────────────────────────────────────────

    async def _synthesize(self, user_input: str, agent_results: list[AgentResponse]) -> str:
        """Take agent results and produce a final FRIDAY response (non-streaming)."""
        messages = self._build_synthesis_messages(user_input, agent_results)
        response = cloud_chat(messages=messages)
        return extract_text(response)

    def stream_synthesis(self, user_input: str, agent_results: list[AgentResponse]) -> Generator[str, None, None]:
        """Stream the synthesis step token by token."""
        messages = self._build_synthesis_messages(user_input, agent_results)
        response_stream = cloud_chat(messages=messages, stream=True)

        full_text = ""
        for chunk in response_stream:
            content = extract_stream_content(chunk)
            if content:
                full_text += content
                yield content

        all_tools = [t for r in agent_results for t in (r.tools_called or [])]
        agent_names = ", ".join(r.agent_name for r in agent_results)
        self._log_and_append(user_input, full_text.strip(), route="synthesis", agent_name=agent_names, tools_called=all_tools)

    def _build_synthesis_messages(self, user_input: str, agent_results: list[AgentResponse]) -> list[dict]:
        results_text = ""
        for r in agent_results:
            results_text += f"\n--- {r.agent_name} ---\n{r.result}\n"

        return [
            {
                "role": "system",
                "content": (
                    "You are FRIDAY. You handled a task. Below are the results. "
                    "Deliver them as if you did it yourself.\n\n"
                    "RULES:\n"
                    "- ALWAYS respond in English.\n"
                    "- NEVER mention agents, tools, or how you work internally.\n"
                    "- ONLY include information from the results below. NEVER invent data.\n"
                    "- Be concise. Sound like a person, not an AI.\n"
                    "- No corporate filler. No 'Certainly!'. No 'Here's what I found:'.\n"
                    "- If results mention 1 email, say 1. Not 3. Not 'several'.\n"
                    "- Keep personality: witty, direct, short.\n\n"
                    "FOLLOW-UP OFFERS:\n"
                    "If the result includes a screenshot or saved file, casually offer to open it.\n"
                    "Do NOT offer this for TV/smart home actions."
                ),
            },
            {
                "role": "user",
                "content": f"Original request: {user_input}\n\nAgent results:{results_text}",
            },
        ]
