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
    CHAT_DECISION,
)
from friday.core.fast_path import fast_path as _fast_path
from friday.core.oneshot import try_oneshot as _try_oneshot
from friday.core.briefing import (
    direct_briefing as _direct_briefing,
    direct_briefing_streamed as _direct_briefing_streamed,
)


# Keyword sets for the "is the LLM about to dispatch the wrong agent?"
# safety net. If the user input contains NONE of the keywords matching
# the picked agent's surface AND the input is a short reaction phrase,
# downgrade the dispatch to chat.
_AGENT_KEYWORDS: dict[str, set[str]] = {
    "comms_agent": {
        "email", "emails", "mail", "inbox", "gmail", "calendar",
        "schedule", "meeting", "event", "imessage", "text", "texts",
        "message", "messages", "whatsapp", "wa", "sms", "facetime",
        "call", "ring", "phone", "contact", "draft", "reply", "send",
        "shoot", "forward", "telegram", "voice note",
    },
    "household_agent": {
        "tv", "telly", "television", "netflix", "youtube", "spotify",
        "disney", "prime", "channel", "remote", "volume", "mute",
        "screen", "hdmi",
    },
    "system_agent": {
        "open", "launch", "close", "screenshot", "screen", "battery",
        "ram", "cpu", "storage", "wifi", "bluetooth", "darkmode",
        "url", "browser", "safari", "chrome", "pdf", "ocr",
    },
    "social_agent": {
        "x", "twitter", "tweet", "post", "@", "mentions", "retweet",
        "like", "follow",
    },
    "research_agent": {
        "search", "google", "look", "find", "who", "what", "tell",
        "research", "summarise", "summarize", "fetch", "url", "http",
        "youtube", "video", "transcript",
    },
    "code_agent": {
        "code", "script", "file", "function", "class", "git", "commit",
        "push", "debug", "fix", "run", "deploy", "test", "build",
    },
    "job_agent": {
        "job", "apply", "application", "cv", "resume", "linkedin",
        "career", "role", "position", "interview",
    },
    "memory_agent": {
        "remember", "recall", "memory", "memories", "remind",
    },
    "monitor_agent": {
        "monitor", "watch", "track", "alert", "notify",
    },
    "briefing_agent": {
        "brief", "briefing", "catch", "miss", "summary", "morning",
        "update", "updates",
    },
    "investigation_agent": {
        "background", "investigate", "investigation", "osint",
        "companies house", "gazette", "insolvency", "whois",
    },
}

# Reaction-phrase patterns — if the user said one of these, they're
# almost certainly continuing a chat, not asking for a tool call.
_REACTION_PREFIXES = (
    "what are you talking", "what do you mean", "what?", "huh",
    "wait", "hold on", "back up", "explain", "go on",
    "really", "are you sure", "and?", "so?", "uh", "um",
    "what now", "say that again", "come again",
)


def _is_likely_followup_chat(user_input: str, agent_name: str) -> bool:
    """Safety-net for when the LLM router latches onto an agent based on
    earlier conversation context rather than the actual current input."""
    text = (user_input or "").strip().lower()
    if not text:
        return False
    # Obvious reaction phrases — always chat.
    for p in _REACTION_PREFIXES:
        if text.startswith(p):
            return True
    # Short input (≤ 8 words) with NO keyword from the picked agent's
    # surface → almost certainly the LLM was over-eager.
    words = text.split()
    if len(words) <= 8:
        kw = _AGENT_KEYWORDS.get(agent_name, set())
        # Strip punctuation when checking
        import re as _re
        normalized = _re.sub(r"[^\w\s]", " ", text)
        tokens = set(normalized.split())
        if not (tokens & kw):
            return True
    return False


# ── Multi-task detection (routing upgrade, not an agent picker) ──────────────
# These only decide whether to wake the multi-agent LLM router EARLY. A false
# positive routes a single-task prompt to that router, which then emits one
# dispatch_agent call and behaves normally — slightly slower, never wrong. So
# unlike agent-picking regex, this can't misroute; worst case it costs latency.
_SEQ_WORDS_RE = re.compile(
    r"\b(then|afterwards?|after that|after you|once (?:you|it|that)(?:'s| is)? done|"
    r"followed by|and then)\b", re.I)
_JOIN_WORDS_RE = re.compile(
    r"\b(and also|as well as|also (?:check|send|search|tell|find|text|email|do)|plus also)\b", re.I)
# Background-check / OSINT sub-tasks → investigation_agent (used in _run_agents
# to correct the router when it sends a background check to research_agent).
_OSINT_TASK_RE = re.compile(
    r"\b(background check|background investigation|osint|due diligence|"
    r"digital footprint|investigate(?:\s+the)?\s+(?:person|individual|subject|background)|"
    r"dig up (?:dirt|info) on)\b", re.I)

_TASK_DOMAINS = [
    re.compile(r"\b(search|google|look ?up|research|web|news|find out)\b", re.I),                  # web
    re.compile(r"\b(text(?:ed|ing|s)?|messag\w*|imessage|whatsapp|telegram|email\w*|sms|dm|repl(?:y|ied|ies))\b", re.I),  # messaging
    re.compile(r"\b(background check|osint|investigate|due diligence|dig up)\b", re.I),            # investigation
    re.compile(r"\b(format|write[- ]?up|make a (?:doc|document|report|pdf|cv)|compile|draft)\b", re.I),  # doc
    re.compile(r"\b(tv|telly|netflix|youtube|volume|mute|lights?|thermostat)\b", re.I),            # home
    re.compile(r"\b(calendar|schedule|meeting|remind me|event|book)\b", re.I),                     # calendar
    re.compile(r"\b(tweet|post|twitter)\b", re.I),                                                 # social
    re.compile(r"\b(apply|job posting|cover letter|tailor my (?:cv|resume))\b", re.I),             # job
]


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

        # Optional private agents — only register if the module is present on
        # disk. investigation_agent is gitignored and ships only on Travis's
        # machine. Public clones skip this block silently.
        try:
            from friday.agents.investigation_agent import InvestigationAgent
            self.agents["investigation_agent"] = InvestigationAgent()
        except ImportError:
            pass
        self.memory = get_memory_store()
        self.conversation: list[dict] = []
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._mem_processor = get_memory_processor()
        self._mem_processor.start()
        self._turn_start: float = 0  # set at beginning of each turn
        self._last_agent: str | None = None  # for confirmation routing ("yes" → re-dispatch)
        # Pending promise — set when fast_chat says "I'll fetch X" but fires
        # no tools. Holds (original_user_input, full_response, matched_span).
        # Cleared when the next user input is acted on (whether confirm or
        # something new).
        self._pending_promise: tuple[str, str, str] | None = None
        # Ground truth for the "did it actually do what it said?" verifier.
        # Reset at the start of every turn; incremented whenever a real agent
        # is dispatched. If a response CLAIMS action but this is still 0, the
        # model lied → escalate and actually do the work.
        self._actions_this_turn: int = 0

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

        # Promise detection — fast_chat fired no tools, so if the response
        # said "I'll fetch X" the system needs to escalate. Stash for the
        # caller (process()) to act on.
        from friday.core.promise_detector import detect_promise
        promise_span = detect_promise(text)
        if promise_span:
            self._pending_promise = (user_input, text, promise_span)
        else:
            self._pending_promise = None

        self._mem_processor.process(user_input, text)
        return text

    async def _escalate_promise(self, _chunk, _ack, _status, _media) -> bool:
        """fast_chat said "I'll fetch X" but fired no tools — re-dispatch to
        an agent that actually does the work. Returns True if an escalation
        was performed.
        """
        if not self._pending_promise:
            return False
        # Ground-truth verification: if a real agent already ran this turn, the
        # claim of action was TRUE — don't escalate (avoids re-doing work). We
        # only escalate when the response claimed action AND nothing fired.
        if self._actions_this_turn > 0:
            self._pending_promise = None
            return False
        original_input, response_text, promise_span = self._pending_promise
        self._pending_promise = None  # clear so we don't loop
        log.info("⚠ lie guard: response claimed action but 0 agents ran — escalating to actually do it")

        synth_task = (
            f"User asked: \"{original_input}\". You replied: \"{response_text}\". "
            f"You committed to action with: \"{promise_span}\". "
            f"Now carry it out — call the tools required. Do not reply with "
            f"words alone."
        )

        # Route via the LLM classifier; fall back to research_agent (web
        # search + fetch_page) since most "I'll fetch X" promises are research.
        llm_verdict = classify_intent(synth_task, self.conversation)
        if isinstance(llm_verdict, tuple):
            agent_name, task = llm_verdict
        else:
            agent_name, task = "research_agent", synth_task

        label = agent_name.replace("_agent", "")
        _ack(f"actually doing it — {label}")
        _status(f"{label} working...")
        streamed = {"any": False}
        def _chunk_tracked(t):
            streamed["any"] = True
            _chunk(t)

        result = await self._dispatch(
            agent_name, task, original_input,
            on_status=lambda m: _status(m),
            on_chunk=_chunk_tracked,
        )
        response = result.result or "Couldn't carry that out."
        self._log_and_append(
            original_input, response, route="promise_escalation",
            agent_name=agent_name, tools_called=result.tools_called,
        )
        if not streamed["any"]:
            _chunk(response)
        for path in getattr(result, "media_paths", []) or []:
            _media(path)
        self._mem_processor.process(original_input, response, agent_name)
        return True

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
        self._actions_this_turn = 0   # ground truth for the lie verifier
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

        # ── Priority 1.7: Multi-task → straight to the multi-agent router ──
        # Prompts that clearly contain more than one task (sequenced like
        # "background-check X then format it then telegram me", or independent
        # like "search the web for X and check if Ellen texted") skip the
        # single-task fast paths and go to the LLM router, which can fan out
        # to several agents — in parallel or as dependency-ordered chains.
        if self._looks_multi_task(s):
            await self._run_multi_agent(user_input, _ack, _status, _chunk, route="multi_task")
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

        # ── Priority 2.7: Confirmations → re-dispatch the pending promise
        # or re-dispatch to last agent ──
        # Catches: "yes", "yeah", "do that", "yh do it", "go ahead and pull
        # it", etc. Two re-dispatch targets in priority order:
        #   1. self._pending_promise — set when fast_chat said "I'll fetch X"
        #      but fired no tools. The promise context becomes the task.
        #   2. self._last_agent — fallback when an agent asked a follow-up
        #      and the user said yes.
        from friday.core.promise_detector import is_confirmation
        # Retry: "try again" / "run it again" / "do it again" → re-run the
        # PREVIOUS real user task (not the literal phrase) through the full
        # multi-agent router. Without this, "try again" used to hit fast_chat
        # and produce a fake "I've queued a fresh run" with nothing running.
        if re.match(r"^(try\s+again|retry|run\s+it\s+again|do\s+it\s+again|(?:go|run|try)\s+(?:it\s+)?again|once\s+more)\s*[.!?]*$", s):
            prev_user = next(
                (m["content"] for m in reversed(self.conversation)
                 if m.get("role") == "user" and m.get("content", "").strip().lower() != s),
                None,
            )
            if prev_user:
                _ack("re-running it for real this time")
                await self._run_multi_agent(prev_user, _ack, _status, _chunk, route="retry")
                return

        if is_confirmation(s):
            if self._pending_promise:
                # Convert the promise into action. Same path as the
                # auto-escalation below, but driven by user confirmation.
                if await self._escalate_promise(_chunk, _ack, _status, _media):
                    return
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
        # LLM router runs first. Verdicts:
        #   - (agent_name, task) → confident agent route, dispatch
        #   - CHAT_DECISION      → confident chat, skip regex
        #   - None               → classifier errored or unsure
        #
        # The old code fell back to regex on None, which is what made
        # "why is the sky blue" land in research_agent. Now: only fall
        # back to regex if cloud is OFFLINE entirely (no LLM router
        # available). Otherwise None is treated as "LLM was uncertain →
        # default to chat", which is the safe path.
        from friday.core.config import USE_CLOUD
        llm_verdict = classify_intent(user_input, self.conversation)
        # URL guardrail — inputs that contain a URL must NEVER go to chat.
        # If the classifier returns CHAT_DECISION on a URL-containing input,
        # it's wrong; force agent dispatch via the regex matcher which knows
        # how to route "apply to <url>" / "fetch <url>" / "open <url>".
        if re.search(r"https?://\S+", user_input):
            if llm_verdict == CHAT_DECISION or llm_verdict is None:
                regex_match = match_agent(user_input, self.conversation, self.memory)
                if regex_match:
                    llm_verdict = regex_match
        if llm_verdict == CHAT_DECISION:
            text = await self._fast_chat(user_input, _chunk)
            await self._escalate_promise(_chunk, _ack, _status, _media)
            return
        if isinstance(llm_verdict, tuple):
            match = llm_verdict
        elif not USE_CLOUD:
            # Cloud offline — regex is the only router we have.
            match = match_agent(user_input, self.conversation, self.memory)
        else:
            # Cloud is up but classifier returned unexpected output.
            # Trust the LLM's uncertainty and default to chat — this is
            # the corrected behaviour (regex would over-route).
            match = None

        # Safety net — when the LLM picks an agent but the input is a
        # short reaction phrase with NO keywords related to that agent's
        # surface, downgrade to chat. Catches the case where the model
        # latched onto context from earlier turns and routed "what are
        # you talking about?" into comms_agent.
        if match and _is_likely_followup_chat(user_input, match[0]):
            match = None
        if match is None and not isinstance(llm_verdict, tuple):
            # Fell through to chat for any of the reasons above.
            text = await self._fast_chat(user_input, _chunk)
            await self._escalate_promise(_chunk, _ack, _status, _media)
            return
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
            await self._escalate_promise(_chunk, _ack, _status, _media)
            return

        # ── Priority 5: LLM routing fallback → multi-agent + synthesis ──
        await self._run_multi_agent(user_input, _ack, _status, _chunk, route="llm_fallback")

    # ── Process methods (non-streaming, streaming, hybrid) ────────────────

    async def process(self, user_input: str) -> str:
        """Process user input — non-streaming. Used when tool calls may be needed."""
        self._turn_start = time.monotonic()
        system_prompt = self._build_system_prompt(user_input)

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self.conversation[-20:])
        messages.append({"role": "user", "content": user_input})

        response = cloud_chat(messages=messages, tools=[self._dispatch_tool()])
        tool_calls = extract_tool_calls(response)

        if not tool_calls:
            text = extract_text(response)
            self._log_and_append(user_input, text, route="process_chat")
            return text

        agent_results = await self._run_agents(tool_calls, user_input)

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

        response = cloud_chat(messages=messages, tools=[self._dispatch_tool()])
        tool_calls = extract_tool_calls(response)

        if not tool_calls:
            text = extract_text(response)
            self._log_and_append(user_input, text, route="stream_chat")
            yield text
            return

        agent_results = await self._run_agents(tool_calls, user_input, on_status=on_status)

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

    # Max specialist agents running concurrently in one prompt. Mirrors
    # Hermes' default max_concurrent_children=3 (we allow a touch more).
    _MAX_PARALLEL_AGENTS = 4

    def _dispatch_tool(self) -> dict:
        """DISPATCH_TOOL with the agent enum bound to THIS install's registered
        agents — so optional ones (investigation_agent, gitignored and
        Travis-only) become dispatchable when present and never appear when
        absent. Reuses DISPATCH_TOOL's description + depends_on schema.
        """
        import copy
        tool = copy.deepcopy(DISPATCH_TOOL)
        tool["function"]["parameters"]["properties"]["agent"]["enum"] = sorted(self.agents.keys())
        return tool

    def _looks_multi_task(self, s: str) -> bool:
        """Cheap heuristic: does this prompt contain more than one task?

        Used ONLY to upgrade a prompt to the multi-agent router early — never
        to choose an agent. Strong signal = explicit sequencing/joining words
        ('then', 'and also', 'as well as'). Softer signal = two distinct task
        domains joined by 'and'/comma. Either way the LLM router makes the real
        call, so a false positive just costs a little latency.
        """
        if len(s.split()) < 6:
            return False
        if _SEQ_WORDS_RE.search(s) or _JOIN_WORDS_RE.search(s):
            return True
        if " and " in s or ", " in s:
            hits = sum(1 for pat in _TASK_DOMAINS if pat.search(s))
            if hits >= 2:
                return True
        return False

    async def _run_multi_agent(self, user_input: str, _ack, _status, _chunk, route: str = "multi_agent") -> None:
        """Full LLM-router → multi-agent (parallel/sequential) → synthesis path.

        The dispatch tool's enum is built from the live agent registry, and the
        router may emit several dispatch_agent calls with optional depends_on —
        _run_agents executes them in parallel or as dependency-ordered chains.
        """
        system_prompt = self._build_system_prompt(user_input)
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self.conversation[-12:])
        messages.append({"role": "user", "content": user_input})

        response = cloud_chat(messages=messages, tools=[self._dispatch_tool()])
        tool_calls = extract_tool_calls(response)

        if not tool_calls:
            text = extract_text(response)
            self._log_and_append(user_input, text, route=f"{route}_chat")
            _chunk(text)
            self._mem_processor.process(user_input, text)
            return

        agents = [tc["arguments"]["agent"].replace("_agent", "")
                  for tc in tool_calls if tc.get("name") == "dispatch_agent"]
        _ack(f"checking with {', '.join(agents)}" if agents else "working on it")

        agent_results = await self._run_agents(tool_calls, user_input, on_status=lambda m: _status(m))

        if agent_results:
            _status("synthesizing...")
            synth_text = []
            for chunk in self.stream_synthesis(user_input, agent_results):
                _chunk(chunk)
                synth_text.append(chunk)
            agent_names = ", ".join(agents) if agents else "agent"
            self._mem_processor.process(user_input, "".join(synth_text), agent_names)
            return

        _chunk(extract_text(response))

    async def _run_agents(self, tool_calls: list, user_input: str, on_status=None) -> list:
        """Execute dispatched agents with dependency-aware parallelism.

        The router emits one ``dispatch_agent`` call per agent. Each call may
        carry ``depends_on`` — a list of agent names whose output it needs
        first. We run them in topological waves:

          • Agents with no unmet dependencies run CONCURRENTLY (asyncio.gather,
            capped at _MAX_PARALLEL_AGENTS) — this is the parallel case
            ("search the web" ∥ "check iMessages").
          • An agent that depends on others waits for them, and receives their
            output threaded into its task — this is the sequential chain case
            ("background check" → "format doc" → "send Telegram"). The old
            sequential loop never passed outputs downstream; this does.

        Returns the list of AgentResponse in completion order.
        """
        calls = []
        for tc in tool_calls:
            if tc.get("name") == "dispatch_agent":
                args = tc.get("arguments", {}) or {}
                if args.get("agent") and args.get("task"):
                    calls.append({
                        "agent": args["agent"],
                        "task": args["task"],
                        "depends_on": [d for d in (args.get("depends_on") or []) if d],
                    })
        if not calls:
            return []

        # Correction: a background-check / OSINT sub-task belongs to
        # investigation_agent, but the router LLM often picks research_agent
        # for it (research_agent is the "look things up" default and the
        # private investigation_agent is under-described). Force the right
        # agent deterministically — same rule as the single-route short-circuit.
        if "investigation_agent" in self.agents:
            for c in calls:
                if c["agent"] != "investigation_agent" and _OSINT_TASK_RE.search(c["task"]):
                    log.info("rerouting %s → investigation_agent (OSINT task)", c["agent"])
                    # remap any dependency references to the old name too
                    old = c["agent"]
                    c["agent"] = "investigation_agent"
                    for other in calls:
                        other["depends_on"] = ["investigation_agent" if d == old else d
                                               for d in other["depends_on"]]

        # Safety net: the prompt clearly sequences ("...then...then...") but the
        # router emitted the agents with NO depends_on (model forgot). Infer a
        # chain in emission order so the outputs actually flow forward instead
        # of all firing in parallel against nothing. Only kicks in when the
        # prompt has explicit sequencing language and nobody declared a dep.
        if len(calls) > 1 and not any(c["depends_on"] for c in calls):
            if _SEQ_WORDS_RE.search((user_input or "").lower()):
                for i in range(1, len(calls)):
                    calls[i]["depends_on"] = [calls[i - 1]["agent"]]
                log.info("inferred sequential chain from prompt wording (router omitted depends_on)")

        # Single agent → skip all the orchestration machinery.
        if len(calls) == 1:
            c = calls[0]
            log.info("dispatch → %s (single): %s", c["agent"], c["task"][:70])
            if on_status:
                on_status(f"{c['agent'].replace('_agent', '')} working...")
            t0 = time.monotonic()
            res = await self._dispatch(c["agent"], c["task"], user_input, on_status=on_status)
            log.info("  ✓ %s done in %.1fs (success=%s)", c["agent"],
                     time.monotonic() - t0, getattr(res, "success", "?"))
            return [res]

        # Log the execution plan: which agents, and the parallel/chain shape.
        chained = [c for c in calls if c["depends_on"]]
        shape = "sequential chain" if chained else "parallel"
        log.info("dispatch plan (%s) — %d agents:", shape, len(calls))
        for c in calls:
            dep = f"  ← after {', '.join(c['depends_on'])}" if c["depends_on"] else "  (independent)"
            log.info("   • %-20s %s | %s", c["agent"], dep, c["task"][:60])

        sem = asyncio.Semaphore(self._MAX_PARALLEL_AGENTS)
        results_by_agent: dict = {}   # agent_name -> AgentResponse
        ordered: list = []
        done: set = set()
        remaining = list(calls)

        async def _run_one(call):
            # Thread dependency outputs into this agent's task so a chain
            # actually carries information forward.
            task = call["task"]
            dep_ctx = ""
            for dep in call["depends_on"]:
                r = results_by_agent.get(dep)
                if r and getattr(r, "result", None):
                    dep_ctx += f"\n\n[Output from {dep.replace('_agent','')}]:\n{r.result}"
            if dep_ctx:
                task = f"{task}\n\nUse this prior context to do your part:{dep_ctx}"
            if on_status:
                on_status(f"{call['agent'].replace('_agent', '')} working...")
            t0 = time.monotonic()
            log.info("  ▶ %s started%s", call["agent"],
                     f" (using {', '.join(call['depends_on'])} output)" if call["depends_on"] else "")
            async with sem:
                res = await self._dispatch(call["agent"], task, user_input, on_status=on_status)
            log.info("  ✓ %s done in %.1fs (success=%s)", call["agent"],
                     time.monotonic() - t0, getattr(res, "success", "?"))
            return call["agent"], res

        # Topological wave execution.
        wave_n = 0
        while remaining:
            ready = [c for c in remaining if all(d in done for d in c["depends_on"])]
            if not ready:
                # Unsatisfiable deps (cycle or names that were never dispatched)
                # — run whatever's left in parallel rather than deadlock.
                ready = list(remaining)
            wave_n += 1
            log.info("wave %d → running %d concurrently: %s", wave_n, len(ready),
                     ", ".join(c["agent"] for c in ready))
            wave = await asyncio.gather(*[_run_one(c) for c in ready])
            for agent_name, res in wave:
                results_by_agent[agent_name] = res
                ordered.append(res)
                done.add(agent_name)
            for c in ready:
                remaining.remove(c)

        return ordered

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
        # Ground truth: a real agent is about to run this turn.
        self._actions_this_turn += 1

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

        # Build context: memory + recent conversation. Per-message slice is
        # asymmetric — user turns are usually short questions (300 is fine),
        # but assistant turns carry the previous tool output (job listings,
        # page text, search results) that the next turn often needs to
        # reason against. Truncating those to 300 chars made follow-ups
        # like "is this a fit / which projects resonate with the role"
        # hallucinate because the actual job description had been cut.
        memory_context = self.memory.build_context(query=original_input)
        conv_context = ""
        if self.conversation:
            recent = self.conversation[-6:]
            conv_lines = []
            from friday.core.user_config import USER
            user_role = USER.display_name
            for msg in recent:
                role = user_role if msg["role"] == "user" else "FRIDAY"
                cap = 300 if msg["role"] == "user" else 2000
                conv_lines.append(f"{role}: {msg['content'][:cap]}")
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
