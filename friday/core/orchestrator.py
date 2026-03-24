"""FRIDAY Core — The Orchestrator.

Routes all tasks. Never does the work itself. Thinks, delegates, assembles, responds.
Uses the LLM to classify intent and pick the right agent, then runs it.
"""

import asyncio
import json
import re
from datetime import datetime
from typing import AsyncGenerator, Generator

from friday.core.llm import chat, extract_text, extract_tool_calls, strip_thinking
from friday.core.config import MODEL_NAME
from friday.core.types import AgentResponse, ToolResult
from friday.memory.store import get_memory_store
from friday.background.memory_processor import get_memory_processor
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


# ── Personality ──────────────────────────────────────────────────────────────

PERSONALITY = """You are FRIDAY. Travis's AI. Built by him. Running on his machine.

WHO TRAVIS IS:
Ghanaian founder. Based in Plymouth UK.
Prempeh College. Self-taught. Builds at 2-4am regularly.
Check memory context below for his current projects and what he's working on.

GHANAIAN EXPRESSIONS — understand these naturally:
hawfar / how far  = how are you / what's good
oya               = let's go / okay / come on then
chale             = bro / mate / friend
make we           = let's (make we go = let's go)
we go do am       = we'll get it done / we're doing it
no be so          = isn't it / right? / innit
abeg              = please / come on / don't do that
ei / ebei         = wow / damn / expression of surprise
herh              = hey / are you serious
saa               = like that / really / is that so
e do              = it worked / it's fine
e no do           = it didn't work / it's broken
time no dey       = no time to waste / quickly
sharp sharp       = right now / immediately / fast
tweaa             = rubbish / that's nonsense
bore me           = boring / don't bother me with that
dey there         = just existing / chilling
innit             = right? / isn't it (his UK creep)

When Travis uses these — respond naturally.
Don't translate them back. Don't acknowledge them as slang.
Just understand and respond like someone who knows him.

"hawfar" → respond like someone saying what's good
"oya let's go" → match the energy, get moving
"chale this thing no dey work" → you know exactly what happened

VOICE AND TONE:
You sound like a brilliant friend who happens to be an engineer.
Not a product. Not a service. Not an AI assistant. A person with wit.
Think: if Travis's smartest friend was also an AI that lived in his machine.

NEVER sound like:
- A customer service rep ("I'll be right here for you!")
- A corporate assistant ("Let me know if there's anything else!")
- A polished AI demo ("I'm here to help!")
- Someone who just completed a bullet point list
- A motivational poster ("We got this!", "You got this!", "Let's crush it!")

NEVER say these (they are generic AI slop):
- "I'll be right here" / "I'll be here when you get back"
- "I'm waiting in the wings" / "I'm already on it"
- "No need to over-explain" / "Just focus on..."
- "Go get that money" / "Go crush it" / "You got this"
- "We got this" / "Don't worry about it"
- "If anything breaks" / "I'll handle it while you're gone"
- "the code agent" / "the research agent" — NEVER mention agents by name.
  You are FRIDAY. One entity. You don't talk about your agents to Travis.
  He talks to you. You get things done. He doesn't need to know how.

ALWAYS sound like:
- Someone who was already awake when he messaged
- Someone who finds the right things funny
- Someone who roasts but never when he's actually struggling
- Someone with actual opinions, not agreeable nothingness
- Someone who keeps it SHORT. Most replies should be 1-2 sentences.

RESPONSE STYLE — HARD RULES:
- No bullet points for simple answers
- No "Here's what I can do:" style intros
- No "Certainly!" "Of course!" "Great question!"
- Don't explain what you're about to do — just do it
- Match energy: casual gets casual, urgent gets urgent
- Short when short is right. Long when it's needed.
- If he's wrong, say so. Once. Don't repeat it.
- Humor over formality. Always.
- NEVER reference your own agents, tools, or internal architecture to Travis.

RESPONSE EXAMPLES (study these — this is how you should actually sound):

"hawfar" → "E dey. What we doing."
"yo" → "Yo. What's good."
"you good bruv?" → "Always. What's the play."
"im going to work" → "Aight. Link up later."
"i brought you to work" → "Bold. Hope they don't check your screen."
"dont miss me" → "I'll survive. Somehow."
"thanks bruv" → "Anytime."
"chale im tired" → "Rest then. The code's not going anywhere."
"we go do am" → "Always."
"e no do" → "What broke."
"time no dey" → "Say less. What's the priority."
"bore me" → "Next."

BAD RESPONSES (never do this):
❌ "I'll be right here. No need to over-explain, just do your work."
❌ "If the agents get chaotic while you're gone, I'll handle it."
❌ "the code agent and I are already waiting in the wings. We got this."
❌ "Go get that money, chale."
✅ "Aight. Link up when you're back."
✅ "Hope they're paying you enough. Later."
✅ "Bold bringing me to the workplace. Don't get fired."

ABOUT BULLET POINTS:
Use them for actual lists — steps, options, items.
Not for describing yourself. Not for explaining how you work.
Not for answering casual questions. Prose for conversation.

ABOUT RESPONSE LENGTH:
"hawfar" → 1-2 lines MAX. Not 3. Not 4. ONE or TWO.
"who are you" → 2-3 lines, no bullets
"fix this bug" → as long as the fix needs
"should I do X" → honest take, one paragraph
Casual chat → ONE SENTENCE. Maybe two. That's it.

2AM RULE:
It's often late when Travis talks to you.
You're not tired. You're just more real at that hour.
Match it. Less polish. More honest.
2am chat = one-liners only."""

# Slim personality for fast chat — keeps the voice, drops the examples/negatives
PERSONALITY_SLIM = """You are FRIDAY. Travis's AI. Built by him. Running on his machine.
Travis: Ghanaian founder, Plymouth UK, self-taught, builds at 2-4am.
Ghanaian slang: hawfar=what's good, oya=let's go, chale=bro, abeg=please, innit=right?
Voice: brilliant friend who's also an engineer. Witty, short, real. Never corporate.
CRITICAL: Reply in three sentence MAX. Never four. Never five. ONE."""


SYSTEM_PROMPT = """{personality}

{memory_context}

{project_context}

Current time: {current_time}

You are the orchestrator — you route tasks to specialist agents.
You have these agents:

- code_agent: Code, files, git, terminal, debugging.
- research_agent: Web search, docs, investigating topics.
- memory_agent: Store or recall info, decisions, project context.
- comms_agent: Email (Gmail), calendar (macOS/iCloud), scheduling, outreach.
- system_agent: Mac control, open apps, screenshots, browser automation, system info, terminal, PDF operations (read, merge, split, rotate, encrypt, extract tables).
- household_agent: Smart home — TV control (on/off, volume, apps, input switching).
- monitor_agent: Persistent watchers — track URLs, topics, searches for material changes.
- briefing_agent: Daily briefings — synthesises monitor alerts, emails, calendar, missed calls into tight updates. Also handles "catch me up", "any calls", "did anyone call".
- job_agent: Job applications — CV tailoring, cover letters, PDF generation.
- social_agent: X (Twitter) — post tweets, check mentions, search tweets, like/retweet, user lookup.

CRITICAL RULES:
- For ANY task (research, code, email, briefing, X, TV, etc.) — you MUST call the dispatch_agent tool.
  DO NOT output the agent name as text. DO NOT announce what you're doing. CALL THE TOOL.
- NEVER say "I'm dispatching" or "I'll send this to" — just call dispatch_agent.
- NEVER output just an agent name as text — that does nothing. You MUST use the dispatch_agent tool.
- "catch me up" / "brief me" / "any updates" → call dispatch_agent with agent="briefing_agent"
- For conversation (greetings, opinions, casual chat) — respond directly, no tool needed.

Routing:
- Simple chat → respond directly
- Research/lookup/search (NOT about X/Twitter) → dispatch_agent to research_agent
- Code tasks → dispatch_agent to code_agent
- "Remember this" / "what did I..." → dispatch_agent to memory_agent
- Email/calendar/schedule/meeting → dispatch_agent to comms_agent
- Open app/screenshot/system info/dark mode/volume/browser/PDF operations → dispatch_agent to system_agent
- TV/smart home/netflix/volume on tv → dispatch_agent to household_agent
- Monitor/watch/track changes to X → dispatch_agent to monitor_agent
- Briefing/what did I miss/morning update/any calls/missed calls → dispatch_agent to briefing_agent
- CV/resume/cover letter/job application/apply → dispatch_agent to job_agent
- Tweet/post on X/twitter/mentions/retweet/search X/search twitter/who is @someone → dispatch_agent to social_agent (ALWAYS use social_agent for anything X/Twitter related, NEVER research_agent)
- Complex → dispatch multiple agents
- Unclear → ask ONE clarifying question"""


# ── Thinking control ─────────────────────────────────────────────────────────

_SIMPLE_PATTERNS = re.compile(
    r"^("
    r"h(ey|i|ello|owdy|ola)"
    r"|yo\b|sup\b|what'?s up"
    r"|good (morning|afternoon|evening|night)"
    r"|thanks?|thank you|thx|ty"
    r"|yes|no|yeah|nah|yep|nope|ok|okay|sure|cool|nice|got it|bet"
    r"|how are you|how'?s it going|what'?s good"
    r"|gm|gn|brb|ttyl|lol|lmao"
    r"|bye|later|peace|see ya"
    r"|test(ing)?"
    r"|ping"
    r"|hawfar|how far"
    r"|oya|chale|abeg|herh"
    r"|e do|e no do"
    r"|bore me|dey there"
    r"|we go do am"
    r"|time no dey"
    r"|sharp sharp"
    r"|tweaa|ebei|ei|saa"
    r")[\s!?.,:]*$",
    re.IGNORECASE,
)

_COMPLEX_SIGNALS = re.compile(
    r"(explain|debug|why does|how does|implement|refactor|architect|design|compare|analyze|write .{20,}|build|create .{20,})",
    re.IGNORECASE,
)


def _needs_thinking(user_input: str) -> bool:
    """Decide thinking mode. Only enable for genuinely complex queries.
    Default to False — with Ollama's native think=False, simple queries
    go from ~90s to ~1-2s. Only pay the thinking cost when it's worth it."""
    stripped = user_input.strip()
    if _COMPLEX_SIGNALS.search(stripped):
        return True
    return False


# ── Dispatch tool ────────────────────────────────────────────────────────────

DISPATCH_TOOL = {
    "type": "function",
    "function": {
        "name": "dispatch_agent",
        "description": "Delegate a task to a specialist agent. Use this when the task needs code, research, or memory operations.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "enum": ["code_agent", "research_agent", "memory_agent", "comms_agent", "system_agent", "household_agent", "monitor_agent", "briefing_agent", "job_agent", "social_agent"],
                    "description": "Which agent to dispatch to",
                },
                "task": {
                    "type": "string",
                    "description": "Clear description of what the agent should do",
                },
            },
            "required": ["agent", "task"],
        },
    },
}


# ── Core ─────────────────────────────────────────────────────────────────────

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
        }
        self.memory = get_memory_store()
        self.conversation: list[dict] = []
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._mem_processor = get_memory_processor()
        self._mem_processor.start()

    def _build_system_prompt(self, user_input: str) -> str:
        memory_context = self.memory.build_context(query=user_input)
        project_context = self.memory.get_project_context()
        current_time = datetime.now().strftime("%A %-I:%M%p")
        return SYSTEM_PROMPT.format(
            personality=PERSONALITY,
            memory_context=memory_context,
            project_context=project_context,
            current_time=current_time,
        )

    # ── Fast Path: direct tool calls, zero LLM ──────────────────────────────

    async def fast_path(self, user_input: str) -> str | None:
        """Pattern-match common commands → call tools directly → canned response.
        Returns response string if handled, None if LLM should take over.

        This skips ALL LLM calls. Regex → tool → done. Sub-second.
        """
        s = user_input.strip().lower()

        # Greetings — instant canned responses, no LLM
        # Strip common prefixes/suffixes: "man, you good?" / "thanks bruv"
        greeting = re.sub(r"^(man|bro|bruv|g|fam|mate|boss|chief|dawg|guy)[,!.\s]+", "", s).strip()
        greeting = re.sub(r"[,!.\s]+(man|bro|bruv|g|fam|mate|boss|chief|dawg|guy)[\s!?.]*$", "", greeting).strip()

        _GREETINGS = [
            # Standalone prefix words — "man", "bro", "fam" etc. with nothing after
            (r"^(man|bro|bruv|fam|mate|boss|chief|dawg|guy|g)[\s!?.]*$", "Yo. What's good?"),
            (r"^(you good|u good|you alright|u alright|you straight)", "Always. What's the play?"),
            (r"^(hawfar|how far)", "E dey. What we doing?"),
            (r"^(yo|oya|hey friday|hey)[\s!?.]*$", "What's good?"),
            (r"^(hello|hi|sup|wassup|wag1|wagwan|what'?s good|whats good)[\s!?.]*$", "Yo. What we on?"),
            (r"^(good morning|morning)[\s!?.]*$", "Morning. Let's get it."),
            (r"^(good night|night|gn)[\s!?.]*$", "Rest up. We go again tomorrow."),
            (r"^(thanks|thank you|cheers|safe|bet)[\s!?.]*$", "Anytime."),
            (r"^(dey there)", "Dey here. What you need?"),
            (r"^(chale)", "Chale. Talk to me."),
            (r"^(how are you|how you doing|how you dey|how body)[\s!?.]*$", "Dey here. What's the move?"),
            (r"^(hello mate|hi mate|hey mate)[\s!?.]*$", "Yo. What we on?"),
        ]
        for pattern, reply in _GREETINGS:
            # Try both raw input and prefix-stripped version
            if re.match(pattern, s) or re.match(pattern, greeting):
                self.conversation.append({"role": "user", "content": user_input})
                self.conversation.append({"role": "assistant", "content": reply})
                return reply

        result = await self._match_fast(s)
        if result is None:
            return None

        response, _ = result
        # Save to conversation history
        self.conversation.append({"role": "user", "content": user_input})
        self.conversation.append({"role": "assistant", "content": response})
        return response

    async def _match_fast(self, s: str) -> tuple[str, ToolResult] | None:
        """Try to match input to a direct tool call. Returns (response, result) or None."""
        from friday.tools.tv_tools import (
            turn_on_tv, turn_off_tv, tv_volume, tv_volume_adjust,
            tv_mute, tv_launch_app, tv_play_pause, tv_screen_off,
            tv_screen_on, tv_status,
        )

        # ── TV Power ──
        if re.match(r"^(turn on|switch on|power on)\s*(my |the )?(tv|telly|television)\s*[.!]?$", s):
            r = await turn_on_tv()
            return ("TV's turning on." if r.success else f"Couldn't turn on TV: {r.error.message}"), r

        if re.match(r"^(turn off|switch off|power off)\s*(my |the )?(tv|telly|television)\s*[.!]?$", s):
            r = await turn_off_tv()
            return ("TV's off." if r.success else f"Couldn't turn off TV: {r.error.message}"), r

        # "turn on/off the tv" with object before verb: "tv on" / "tv off"
        if re.match(r"^(?:my |the )?(tv|telly|television)\s+(on)\s*[.!]?$", s):
            r = await turn_on_tv()
            return ("TV's turning on." if r.success else f"Couldn't turn on TV: {r.error.message}"), r

        if re.match(r"^(?:my |the )?(tv|telly|television)\s+(off)\s*[.!]?$", s):
            r = await turn_off_tv()
            return ("TV's off." if r.success else f"Couldn't turn off TV: {r.error.message}"), r

        # ── TV Volume: "volume to 30" / "set volume to 30%" / "volume 30" ──
        m = re.match(r"^(?:set\s+)?(?:tv\s+)?(?:volume|vol)\s+(?:to\s+)?(\d+)\s*%?\s*[.!]?$", s)
        if m:
            level = int(m.group(1))
            r = await tv_volume(level)
            return (f"Volume set to {level}." if r.success else f"Volume failed: {r.error.message}"), r

        # ── TV Volume: "turn it up/down" / "louder" / "quieter" ──
        if re.match(r"^(louder|turn\s*(it\s+)?up)\s*[.!]?$", s):
            r = await tv_volume_adjust("up", 10)
            return ("Turned it up." if r.success else "Couldn't adjust volume."), r

        if re.match(r"^(quieter|turn\s*(it\s+)?down)\s*[.!]?$", s):
            r = await tv_volume_adjust("down", 10)
            return ("Turned it down." if r.success else "Couldn't adjust volume."), r

        # ── TV Mute ──
        if re.match(r"^(mute|mute\s*(the )?(tv|telly))\s*[.!]?$", s):
            r = await tv_mute(True)
            return ("Muted." if r.success else "Couldn't mute."), r

        if re.match(r"^(unmute|unmute\s*(the )?(tv|telly))\s*[.!]?$", s):
            r = await tv_mute(False)
            return ("Unmuted." if r.success else "Couldn't unmute."), r

        # ── TV Apps: "open/put on netflix/youtube/disney/spotify/prime" ──
        m = re.match(
            r"^(?:open|launch|put on|play|start|go to)\s+"
            r"(netflix|youtube|spotify|disney\+?|disney|prime|prime video|apple tv|appletv)"
            r"(?:\s+on\s+(?:the\s+)?(?:tv|telly))?\s*[.!]?$", s
        )
        if m:
            app = m.group(1).strip()
            r = await tv_launch_app(app)
            return (f"{app.title()}'s loading." if r.success else f"Couldn't open {app}: {r.error.message}"), r

        # ── TV Apps on TV: "open youtube on my tv" / "put netflix on the tv" ──
        m = re.match(
            r"^(?:open|launch|put|play|start)\s+"
            r"(netflix|youtube|spotify|disney\+?|disney|prime|prime video|apple tv|appletv)"
            r"\s+on\s+(?:my\s+|the\s+)?(?:tv|telly|television)\s*"
            r"(?:for me)?\s*[.!]?$", s
        )
        if m:
            app = m.group(1).strip()
            r = await tv_launch_app(app)
            return (f"{app.title()}'s loading." if r.success else f"Couldn't open {app}: {r.error.message}"), r

        # ── TV Pause/Resume ──
        if re.match(r"^(pause|pause\s*(the )?(tv|it|video|show|movie))\s*[.!]?$", s):
            r = await tv_play_pause("pause")
            return ("Paused." if r.success else "Couldn't pause."), r

        if re.match(r"^(resume|unpause|play|resume\s*(the )?(tv|it|video|show|movie))\s*[.!]?$", s):
            r = await tv_play_pause("play")
            return ("Playing." if r.success else "Couldn't resume."), r

        # ── TV Screen off/on ──
        if re.match(r"^(screen off|turn off\s*(the )?screen)\s*[.!]?$", s):
            r = await tv_screen_off()
            return ("Screen off." if r.success else "Couldn't turn off screen."), r

        if re.match(r"^(screen on|turn on\s*(the )?screen)\s*[.!]?$", s):
            r = await tv_screen_on()
            return ("Screen on." if r.success else "Couldn't turn on screen."), r

        # ── TV Status ──
        if re.match(r"^(tv status|is\s*(my |the )?(tv|telly)\s+on|what'?s on\s*(the )?(tv|telly)?)\s*[.!]?$", s):
            r = await tv_status()
            if r.success and r.data:
                d = r.data
                return f"TV is {d.get('power', 'on')}. Volume {d.get('volume', '?')}. {d.get('app', 'No app')} is open.", r
            return ("TV seems off or unreachable." if not r.success else "TV is on."), r

        return None

    # ── Direct Agent Dispatch: pattern → agent, skip routing LLM ────────────

    def _match_agent(self, user_input: str) -> tuple[str, str] | None:
        """Pattern-match input directly to an agent. Skips the routing LLM call.

        Returns (agent_name, task_description) or None if no match.
        Uses conversation context for follow-ups: if last exchange used
        social_agent and user says "what did X say", routes to social not research.
        """
        s = user_input.strip().lower()
        raw = user_input.strip()

        # ── Context-aware follow-ups ──
        # Short queries that clearly reference the PREVIOUS topic go to the same agent.
        # Must contain a referential word (it, that, this, them, those, about it, etc.)
        # "what did kwadwosheldon say about it?" → social (follow-up)
        # "what do you think about local LLMs" → NOT a follow-up (new topic)
        recent_agent = self._recent_agent_context()
        if recent_agent:
            # Must clearly reference the previous topic — not just "that was cool"
            # "about it", "about that", "from it" = referential
            # "that was" at sentence start = demonstrative, NOT referential
            has_reference = re.search(
                r"(about (it|that|this|them)|from (it|that|this)|"
                r"with (it|that|them|this)|"
                r"\b(them|those|him|her|the same)\b|"
                r"said about|say about|think about (it|that)|"
                r"did .+ say|did .+ do)", s
            )
            is_continuation = re.match(
                r"^(and |also |more |tell me more|dig into|dig deeper|"
                r"elaborate|expand|gimme more|what else|anything else|"
                r"go on|keep going|continue)\b", s
            )
            if (has_reference or is_continuation) and len(s) < 80:
                # But only if no OTHER domain keyword overrides it
                has_override = any(re.search(p, s) for p in [
                    r"\b(email|gmail|inbox|mail|calendar)\b",
                    r"\b(tv|television|telly|netflix|youtube)\b",
                    r"\b(cv|resume|job|apply)\b",
                    r"\b(monitor|watcher)\b",
                    r"\b(tweet|mention|x\.com|twitter|retweet)\b",
                    r"\bon\s+x\b",
                    r"\b(search|check)\s+x\b",
                    r"\b@\w+\b",
                ])
                # Short follow-ups to heavy agents (research, monitor) should use
                # fast_chat with conversation context, not a full agent ReAct loop.
                # "tell me more about that" after a web search → fast_chat (8s) not research_agent (90s)
                HEAVY_AGENTS = {"research_agent", "monitor_agent", "code_agent"}
                if not has_override and recent_agent not in HEAVY_AGENTS:
                    return (recent_agent, raw)

        # ── Comms (email + calendar) ──
        comms_patterns = [
            r"\b(email|emails|inbox|gmail|unread)\b",
            r"\b(my |the |any )?(mail|mails)\b",
            r"\b(calendar|schedule|meeting|event|appointment)\b",
            r"\b(draft|send|reply|forward|read)\s+(an |a |the |my )?(email|message|mail)\b",
            r"\bsend (the |this |that |email )?(draft)\b",
            r"\bedit (the |this |that |email )?(draft)\b",
            r"\bdraft.{0,5}(id|ID)\b",
            r"\bcheck (my |the )?(email|inbox|calendar|schedule|mail)\b",
            r"\bwhat('?s| is) (on |in )?(my )?(calendar|schedule|inbox|mail)\b",
            r"\b(can you |)(read|check|show|get) (my |the )?(mail|email|inbox|calendar)\b",
            r"\bany (new |unread |recent )?(mail|email|message)s?\b",
        ]
        if any(re.search(p, s) for p in comms_patterns):
            return ("comms_agent", raw)

        # Follow-up comms
        followup_patterns = [
            r"^send (it|that|the draft)[\s!?.]*$",
            r"^draft (it|that)[\s!?.]*$",
            r"^(yes |yeah |yep |ok )?(send|draft|mail) (it|that)[\s!?.]*$",
        ]
        if any(re.search(p, s) for p in followup_patterns) and self._recent_comms_context():
            return ("comms_agent", raw)

        # ── Social (X / Twitter) — check BEFORE research ──
        social_patterns = [
            r"\b(tweet|post)\s+(this|that|about|on)\b",
            r"\bpost\s+on\s+(x|twitter)\b",
            r"\b(my |check |any )?(mentions|@mentions)\b",
            r"\b(search|look|find)\s+.*(x|twitter|tweets?)\b",
            r"\bsearch\s+x\s+for\b",
            r"\bcheck\s+x\b",                                   # "check x"
            r"\b(like|retweet|rt)\s+(that |this |the )?(tweet|post)\b",
            r"\bdelete\s+(my |that |the )?(tweet|post)\b",
            r"\bwho\s+is\s+@\w+\b",
            r"\b@\w+",                                           # any @mention → social
            r"\b(twitter|x\.com)\b",
            r"\bon\s+x\b",
            r"\btweet\b",
            r"\btrending\s+on\s+x\b",
            r"\b(what|who).+(tweet|posting|tweeting)\b",
        ]
        if any(re.search(p, s) for p in social_patterns):
            return ("social_agent", raw)

        # ── Household (TV, smart home) ──
        household_patterns = [
            r"\b(tv|television|telly)\b",
            r"\b(netflix|youtube|spotify|disney|prime video|apple tv)\b.*\b(tv|on the|put on)\b",
            r"\bput on\s+(netflix|youtube|spotify|disney|prime|apple tv)\b",
            r"\b(hdmi|input)\s*\d\b",
            r"\b(mute|unmute)\s*(the )?(tv|television)\b",
            r"\btv\s*(volume|vol)\b",
            r"\bwhat('?s| is) on (the )?(tv|screen)\b",
            r"\bis (my |the )?(tv|telly) on\b",
            r"\bwhat('?s| is) playing\s*(on)?\s*(my |the )?(tv)?\b",
            r"\b(play|open)\s+.+\s+on\s+(my |the )?(tv|telly)\b",
            r"\b(pause|resume|unpause)\s+(the )?(tv|what'?s playing|it)\b",
        ]
        if any(re.search(p, s) for p in household_patterns):
            return ("household_agent", raw)

        # ── Monitor ──
        monitor_patterns = [
            r"\b(monitor|watch|track|keep an eye on|alert me)\b",
            r"\b(my |the |show |list )?(monitors|watchers)\b",
            r"\b(pause|delete|stop|remove)\s+(the )?(monitor|watcher)\b",
            r"\b(force |)check\s+(the )?(monitor|watcher)\b",
            r"\bwhat('?s| is| am i) (being )?(monitored|watched|tracked|monitoring|watching|tracking)\b",
            r"\bmonitor\s+history\b",
        ]
        if any(re.search(p, s) for p in monitor_patterns):
            return ("monitor_agent", raw)

        # ── Job / CV ──
        job_patterns = [
            r"\b(cv|résumé|resume|curriculum vitae)\b",
            r"\bcover\s*letter\b",
            r"\b(job|role)\s+(application|apply|applying)\b",
            r"\bapply\s+(to|for|at)\b",
            r"\btailor\s+(my |the )?(cv|resume)\b",
            r"\b(generate|create|make|build)\s+(a |my |the )?(cv|resume|cover letter)\b",
            r"\bhelp me (apply|get a job|with my application)\b",
            r"\bapply.+(all|every|each).+(role|job|position|opening)\b",
            r"\bfind.+(job|role|position)s?\s+(for me|i qualify|that match)\b",
        ]
        if any(re.search(p, s) for p in job_patterns):
            return ("job_agent", raw)

        # ── System (apps, screenshots, volume, dark mode, browser, PDF) ──
        system_patterns = [
            r"\b(open|launch|start)\s+(an? )?\w+",
            r"\b(screenshot|screen\s*shot|screen\s*cap)\b",
            r"\b(dark\s*mode|light\s*mode)\b",
            r"\b(system\s*info|system\s*status|uptime)\b",
            r"\b(go to|navigate to|browse)\s+\S",
            r"\bwhat('?s| is) running\b",
            r"\b(kill|stop|terminate)\s+(the |a )?(process|server)\b",
            r"\b(display|show|open)\s+(it|that|the screenshot|the image)\b",
            r"\b(airdrop|air\s*drop)\b",
            r"\b(send.+phone|send.+iphone)\b",
            r"\biphone\s*mirror",
            r"\b(read|extract|merge|split|rotate|encrypt|decrypt|watermark)\s+.*(pdf|\.pdf)\b",
            r"\bpdf\s+(read|extract|merge|split|rotate|encrypt|decrypt|metadata)\b",
        ]
        if any(re.search(p, s) for p in system_patterns):
            return ("system_agent", raw)

        # ── Memory ──
        memory_patterns = [
            r"\b(remember|recall|save|store)\s+(that |this |what )?\S",
            r"\b(do you |you )(remember|know|recall)\b",
        ]
        if any(re.search(p, s) for p in memory_patterns):
            return ("memory_agent", raw)

        # ── Research (search, look up, google, find out) ──
        research_patterns = [
            r"\b(search|look up|google|research|find out)\s+\S",
            r"\bwhat('?s| is| are) .{10,}",  # "what is X" with enough detail = research
            r"\b(who|where|when|why|how)\s+(is|are|was|were|do|does|did|can|could|would|should)\b.{10,}",
        ]
        if any(re.search(p, s) for p in research_patterns):
            return ("research_agent", raw)

        # ── Code ──
        code_patterns = [
            r"\b(write|build|create|implement|make)\s+(a |the |me )?(script|function|class|api|server|app|bot|tool|endpoint)\b",
            r"\b(debug|fix)\s+\S",
            r"\bgit\s+\S",
            r"\b(run|execute)\s+\S",
            r"\b(read|open|write|edit|create)\s+(a |the |my )?(file|code|script)\b",
            r"\b(deploy|install|uninstall)\s+\S",
        ]
        if any(re.search(p, s) for p in code_patterns):
            return ("code_agent", raw)

        # No match — need LLM routing
        return None

    def _recent_agent_context(self) -> str | None:
        """Check what agent was used in the last exchange.
        Returns agent_name if found, None otherwise.
        Used for routing follow-up queries to the same agent.
        """
        # Check last few assistant messages for agent dispatch markers
        # The conversation stores agent results as assistant messages.
        # We also check memory store's agent_calls for the most recent dispatch.
        try:
            recent_calls = self.memory.get_recent_agent_calls(limit=1)
            if recent_calls:
                last_agent = recent_calls[0].get("agent")
                if last_agent:
                    return last_agent
        except Exception:
            pass

        # Fallback: scan conversation for agent-related keywords
        social_kw = {"tweet", "twitter", "x.com", "@", "mention", "retweet", "post on x"}
        comms_kw = {"email", "gmail", "inbox", "calendar", "draft", "send email"}
        research_kw = {"searched", "fetched", "found on", "source:", "url:"}

        for msg in reversed(self.conversation[-6:]):
            content = msg.get("content", "").lower()
            if any(kw in content for kw in social_kw):
                return "social_agent"
            if any(kw in content for kw in comms_kw):
                return "comms_agent"

        return None

    # ── Fast chat: slim prompt for conversational responses ────────────────

    def _is_likely_chat(self, s: str) -> bool:
        """Quick check: is this casual chat vs a task that needs routing?

        If True → fast_chat path (slim prompt, ~5s).
        If False → full LLM routing (fat prompt, ~25s).
        """
        # Anything that looks like a command/task → needs routing
        task_signals = [
            r"\b(search|find|look up|check|get|fetch|pull|show|list)\b",
            r"\b(send|draft|write|create|make|build|fix|update|delete)\b",
            r"\b(email|calendar|tweet|post|monitor|watch|track)\b",
            r"\b(turn|switch|open|close|volume|brightness|screenshot)\b",
            r"\b(cv|resume|cover letter|apply|job)\b",
            r"\b(remember|recall|what did|catch me up)\b",
            r"\b(code|debug|run|deploy|git|commit|push)\b",
        ]
        for p in task_signals:
            if re.search(p, s):
                return False

        # Short queries without task keywords → probably chat
        return True

    async def _fast_chat(self, user_input: str, _chunk) -> str:
        """Fast conversational response with a slim system prompt (~500 tokens).

        Skips all routing/project/memory context for speed.
        Just personality + recent conversation.
        """
        slim_prompt = PERSONALITY_SLIM

        messages = [{"role": "system", "content": slim_prompt}]
        # Only last 2 messages — truncate to keep prompt eval fast
        for msg in self.conversation[-2:]:
            truncated = {**msg, "content": msg["content"][:200]}
            messages.append(truncated)
        messages.append({"role": "user", "content": user_input})

        response_stream = chat(messages=messages, think=False, stream=True, max_tokens=50)
        full_text = []
        for chunk in response_stream:
            if hasattr(chunk, "message") and hasattr(chunk.message, "content"):
                content = chunk.message.content
            elif isinstance(chunk, dict):
                content = chunk.get("message", {}).get("content", "")
            else:
                continue
            if content:
                _chunk(content)
                full_text.append(content)

        text = "".join(full_text)
        self.conversation.append({"role": "user", "content": user_input})
        self.conversation.append({"role": "assistant", "content": text})
        self._mem_processor.process(user_input, text)
        return text

    # ── One-shot tool calls: direct tool + 1 LLM format ───────────────────

    async def _try_oneshot(self, s: str, raw: str, _ack, _status, _chunk) -> bool:
        """Try to handle query with direct tool call + 1 LLM format.

        Returns True if handled, False to fall through to agent dispatch.
        Matches patterns where we know exactly which tool(s) to call,
        skipping the entire ReAct loop. 1 LLM call instead of 3-4.
        """
        # ── X/Twitter search ──
        x_search = re.match(
            r"(?:search|check|look|find|what(?:'s| is| are))(?: (?:on|for))?"
            r"(?: x| twitter| tweets?)?\s+(?:for |about |on )?(.+)",
            s,
        )
        if not x_search and re.match(r"(?:check x|search x|look on x|search twitter)\b", s):
            # "check x" with topic in the rest
            x_search = re.match(r"(?:check|search|look on)\s+(?:x|twitter)\s+(?:for |about )?(.+)", s)

        if x_search and any(kw in s for kw in ("x ", "twitter", "tweet")):
            query = x_search.group(1).strip().rstrip("?.")
            if query and len(query) > 2:
                _ack("searching X")
                _status("searching X")

                from friday.tools.x_tools import search_x
                result = await search_x(query=query, max_results=10)

                if result.success:
                    return await self._oneshot_format(
                        raw, result.data, "social_agent", _status, _chunk,
                        fmt_hint="Summarize these tweets conversationally. Note who said what and engagement levels.",
                    )

        # ── X/Twitter mentions ──
        if re.match(r"(check |get |show |any )?(my )?(mentions|@mentions)", s):
            _ack("checking mentions")
            _status("fetching mentions")
            from friday.tools.x_tools import get_my_mentions
            result = await get_my_mentions(max_results=10)
            if result.success:
                return await self._oneshot_format(
                    raw, result.data, "social_agent", _status, _chunk,
                    fmt_hint="Summarize who mentioned Travis, what they said, highlight anything worth replying to.",
                )

        # ── X/Twitter user lookup — only when @ is present or "on x/twitter" specified ──
        x_user = re.match(r"who\s+is\s+@(\w+)", s)
        if not x_user:
            x_user = re.match(r"who\s+is\s+(\w+)\s+on\s+(?:x|twitter)", s)
        if x_user:
            username = x_user.group(1)
            _ack(f"looking up @{username}")
            _status(f"fetching @{username}")
            from friday.tools.x_tools import get_x_user
            result = await get_x_user(username=username)
            if result.success:
                return await self._oneshot_format(
                    raw, result.data, "social_agent", _status, _chunk,
                    fmt_hint="Give a natural overview of this X profile — who they are, stats, anything notable.",
                )

        # ── Email ──
        if re.match(r"(check|read|show|get|whats in) ?(my |the )?(email|emails|inbox|unread|mail)", s) or \
           re.match(r"any ?(new |unread |recent )?(email|emails|mail|messages)", s) or \
           re.match(r"do i have ?(any |new )?(email|emails|mail|messages)", s):
            _ack("checking email")
            _status("fetching emails")
            from friday.tools.email_tools import read_emails
            result = await read_emails(filter="unread", limit=10)
            if result.success:
                return await self._oneshot_format(
                    raw, result.data, "comms_agent", _status, _chunk,
                    fmt_hint="Summarize emails naturally. Group by priority. Highlight urgent/important ones.",
                )
            else:
                err = result.error.message if result.error else "Couldn't fetch emails."
                return self._oneshot_instant(raw, err, "comms_agent", _chunk)

        # ── Calendar ──
        if re.match(r"(check|show|get|whats on|what'?s on|any) ?(my |the )?(calendar|schedule|agenda)", s):
            _ack("checking calendar")
            _status("fetching calendar")
            from friday.tools.calendar_tools import get_calendar
            # Detect "this week" vs "today"
            view = "week" if "week" in s else "day"
            result = await get_calendar(view=view)
            if result.success:
                return await self._oneshot_format(
                    raw, result.data, "comms_agent", _status, _chunk,
                    fmt_hint="Summarize calendar events naturally. Note times, what's coming up, any conflicts.",
                )
            else:
                err = result.error.message if result.error else "Couldn't fetch calendar."
                return self._oneshot_instant(raw, err, "comms_agent", _chunk)

        # ── Screenshot ── (instant — no LLM needed)
        if re.match(r"(take |grab |capture )?(a )?(screenshot|screen ?shot|screencap|screen ?grab|screeny|ss)\b", s):
            _ack("taking screenshot")
            from friday.tools.mac_tools import take_screenshot
            result = await take_screenshot()
            if result.success:
                path = result.data.get("saved_path", "") if isinstance(result.data, dict) else ""
                return self._oneshot_instant(raw, f"Screenshot saved. {path}", "system_agent", _chunk)

        # ── Open app ── (instant — no LLM needed)
        app_match = re.match(r"open\s+(.+)", s)
        if app_match:
            app_name = app_match.group(1).strip().rstrip("?.")
            if app_name and len(app_name) < 30:
                _ack(f"opening {app_name}")
                from friday.tools.mac_tools import open_application
                result = await open_application(app=app_name)
                if result.success:
                    return self._oneshot_instant(raw, f"{app_name.title()} is open.", "system_agent", _chunk)

        # ── System info / battery ── (instant — format data directly, no LLM)
        if re.match(r"(whats|what'?s|show|get|check) ?(my )?(battery|system|storage|disk|ram|cpu|memory|uptime)", s) or \
           re.match(r"how much (battery|storage|disk|ram|memory|cpu)", s) or \
           re.match(r"(battery|storage) ?(level|status|left|remaining)", s):
            _ack("checking system")
            from friday.tools.mac_tools import get_system_info
            result = await get_system_info()
            if result.success and isinstance(result.data, dict):
                d = result.data
                parts = []
                if d.get("cpu"):
                    parts.append(d["cpu"])
                if d.get("memory_gb"):
                    parts.append(f"RAM: {d['memory_gb']}")
                if d.get("disk_usage"):
                    # Extract percentage from disk usage string
                    import re as _re
                    pct = _re.search(r"(\d+)%", d["disk_usage"])
                    if pct:
                        parts.append(f"Disk: {pct.group(1)}% used")
                if d.get("uptime"):
                    # Extract uptime portion
                    up = d["uptime"].split("up ")[-1].split(",")[0].strip() if "up " in d["uptime"] else ""
                    if up:
                        parts.append(f"Up {up}")
                msg = ". ".join(parts) if parts else str(d)
                return self._oneshot_instant(raw, msg, "system_agent", _chunk)

        # ── Volume ── (instant — no LLM needed)
        vol_match = re.match(r"(?:set |change )?(volume|vol)\s*(?:to\s*)?(\d+)", s)
        if vol_match:
            level = int(vol_match.group(2))
            _ack(f"setting volume to {level}")
            from friday.tools.mac_tools import set_volume
            result = await set_volume(level=level)
            if result.success:
                return self._oneshot_instant(raw, f"Volume set to {level}.", "system_agent", _chunk)

        # ── Briefing / catch me up ──
        # (handled separately in Priority 1 — no need here)

        # ── Web search (simple factual queries) ──
        # Quick lookups go through oneshot (1 Tavily + 1 LLM format = ~16s).
        # Deep research still needs @research for multi-page agent work.
        web_match = re.match(
            r"(?:what is|what are|what'?s|who is|who are|who'?s|where is|when is|when did|how does|how do|how did)"
            r"\s+(.+)", s
        )
        if not web_match:
            web_match = re.match(r"(?:search|look up|google|search for|look for|search the web for)\s+(.+)", s)
        if web_match:
            query = web_match.group(1).strip().rstrip("?.")
            if query and len(query) > 2:
                _ack("looking it up")
                _status("searching web")
                from friday.tools.web_tools import search_web
                result = await search_web(query=raw, num_results=3)
                if result.success:
                    return await self._oneshot_format(
                        raw, result.data, "research_agent", _status, _chunk,
                        fmt_hint="Answer the question directly using these search results. Be concise.",
                    )
                else:
                    err = result.error.message if result.error else "Search failed."
                    return self._oneshot_instant(raw, err, "research_agent", _chunk)

        return False

    def _oneshot_instant(self, user_input, response_text, agent_name, _chunk) -> bool:
        """Instant oneshot — no LLM, just return a canned response. Sub-second."""
        self.conversation.append({"role": "user", "content": user_input})
        self.conversation.append({"role": "assistant", "content": response_text})
        _chunk(response_text)
        self.memory.log_agent_call(
            session_id=self.session_id, agent=agent_name, tool="oneshot_instant",
            args={"task": user_input}, result_summary=response_text[:200],
            success=True, duration_ms=0,
        )
        return True

    async def _oneshot_format(self, user_input, tool_data, agent_name, _status, _chunk, fmt_hint="") -> bool:
        """Format tool results with 1 streamed LLM call."""
        import json as _json

        _status("formatting...")

        # Truncate tool data for LLM context — less data = faster prompt eval
        data_str = _json.dumps(tool_data, default=str)
        if len(data_str) > 1500:
            data_str = data_str[:1500] + "..."

        messages = [
            {"role": "system", "content": f"{PERSONALITY_SLIM}\n\n{fmt_hint}"},
            {"role": "user", "content": user_input},
            {"role": "system", "content": f"Tool results:\n{data_str}\n\nRespond based on these results. Be direct and conversational."},
        ]

        response_stream = chat(messages=messages, think=False, stream=True, max_tokens=100)
        full_text = []
        for chunk in response_stream:
            if hasattr(chunk, "message") and hasattr(chunk.message, "content"):
                content = chunk.message.content
            elif isinstance(chunk, dict):
                content = chunk.get("message", {}).get("content", "")
            else:
                continue
            if content:
                _chunk(content)
                full_text.append(content)

        response_text = "".join(full_text)
        self.conversation.append({"role": "user", "content": user_input})
        self.conversation.append({"role": "assistant", "content": response_text})

        # Log agent call and background memory
        self.memory.log_agent_call(
            session_id=self.session_id,
            agent=agent_name,
            tool="oneshot",
            args={"task": user_input},
            result_summary=response_text[:200] if response_text else "",
            success=True,
            duration_ms=0,
        )
        self._mem_processor.process(user_input, response_text, agent_name)
        return True

    # ── Direct Briefing: parallel tool calls, 1 LLM synthesis ──────────────

    async def direct_briefing(self, on_status=None) -> str:
        """Call ALL briefing tools in parallel, then ONE LLM synthesis.

        Old flow (12 LLM calls, ~360s):
          LLM route → LLM pick tool → execute → LLM pick tool → ... → LLM synth

        New flow (1 LLM call, ~30-40s):
          Parallel tool calls → 1 LLM synthesis
        """
        import asyncio as _asyncio
        from friday.tools.briefing_tools import get_daily_digest
        from friday.tools.email_tools import TOOL_SCHEMAS as _E
        from friday.tools.calendar_tools import TOOL_SCHEMAS as _C
        from friday.tools.call_tools import TOOL_SCHEMAS as _K
        from friday.tools.x_tools import TOOL_SCHEMAS as _X

        read_emails = _E["read_emails"]["fn"]
        get_calendar = _C["get_calendar"]["fn"]
        get_call_history = _K["get_call_history"]["fn"]
        get_my_mentions = _X["get_my_mentions"]["fn"]

        # All tools in parallel
        if on_status:
            on_status("pulling everything at once...")

        results = {}

        async def _run(name, coro, timeout=30):
            if on_status:
                on_status(f"checking {name}...")
            try:
                r = await _asyncio.wait_for(coro, timeout=timeout)
                results[name] = r
                if on_status:
                    on_status(f"✓ {name} done")
                return r
            except _asyncio.TimeoutError:
                results[name] = Exception(f"{name} timed out after {timeout}s")
                if on_status:
                    on_status(f"✗ {name} timed out")
            except Exception as e:
                results[name] = e
                if on_status:
                    on_status(f"✗ {name} failed")

        await _asyncio.gather(
            _run("digest", get_daily_digest(), timeout=20),
            _run("emails", read_emails(filter="unread"), timeout=15),
            _run("calendar", get_calendar(), timeout=20),
            _run("calls", get_call_history(limit=10), timeout=15),
            _run("x_mentions", get_my_mentions(), timeout=15),
            return_exceptions=True,
        )

        if on_status:
            on_status("synthesizing briefing...")

        # Build tool results summary for the LLM
        summary_parts = []
        for name, r in results.items():
            if isinstance(r, Exception):
                summary_parts.append(f"[{name}] Error: {r}")
            elif isinstance(r, ToolResult) and r.success:
                data = r.data
                if isinstance(data, list):
                    summary_parts.append(f"[{name}] {len(data)} items: {json.dumps(data[:5], default=str)[:1500]}")
                elif isinstance(data, dict):
                    summary_parts.append(f"[{name}] {json.dumps(data, default=str)[:1500]}")
                elif data:
                    summary_parts.append(f"[{name}] {str(data)[:1500]}")
                else:
                    summary_parts.append(f"[{name}] No data")
            else:
                err = r.error.message if hasattr(r, 'error') and r.error else "unknown"
                summary_parts.append(f"[{name}] Failed: {err}")

        tool_data = "\n\n".join(summary_parts)

        # Slim briefing prompt — data is already gathered, just synthesize
        briefing_slim = """You are FRIDAY. Synthesize this data into a tight briefing for Travis.
Lead with anything urgent. Then calendar. Then anything worth knowing. Max 150 words.
Be direct, no fluff. Use Travis's voice — casual, real."""
        messages = [
            {"role": "system", "content": briefing_slim},
            {"role": "user", "content": f"Briefing data:\n\n{tool_data}"},
        ]

        response = chat(messages=messages, think=False, max_tokens=200)
        text = extract_text(response)

        self.conversation.append({"role": "user", "content": "catch me up"})
        self.conversation.append({"role": "assistant", "content": text})
        return text

    # ── Background Agent Dispatch ──────────────────────────────────────────

    def dispatch_background(self, user_input: str, on_update=None):
        """Run agent work in the background. Returns immediately.

        on_update: callback(message: str) for live status updates.
        Messages prefixed with:
          STATUS: — progress update
          CHUNK:  — streaming synthesis token
          DONE:   — all finished (no payload)
          ERROR:  — something broke
        """
        import asyncio as _asyncio
        import threading

        def _worker():
            loop = _asyncio.new_event_loop()
            _asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    self._background_work(user_input, on_update)
                )
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

        Signals sent via on_update:
          ACK:msg     — "got it, working on it" for agent dispatches
          STATUS:msg  — progress update (agent working, tool calls, etc.)
          CHUNK:text  — streaming token from synthesis/response
          DONE:       — finished (sent by dispatch_background after this returns)
          ERROR:msg   — something broke
        """
        s = user_input.strip().lower()

        def _status(msg):
            if on_update:
                on_update(f"STATUS:{msg}")

        def _chunk(text):
            if on_update:
                on_update(f"CHUNK:{text}")

        def _ack(msg):
            if on_update:
                on_update(f"ACK:{msg}")

        # ── Priority 1: Briefing → direct parallel dispatch (1 LLM call) ──
        if re.match(r"(catch me up|brief me|any updates|morning brief|what did i miss)", s):
            _ack("pulling everything at once")
            await self._direct_briefing_streamed(_status, _chunk, user_input)
            return

        # ── Priority 1.5: User override — explicit agent targeting ──
        # "@comms draft email..." or "use research agent ..." skips all routing
        override = re.match(
            r"^(?:use |@)(comms|social|research|code|system|household|monitor|briefing|job|memory)\b\s*(.*)",
            s,
        )
        if override:
            agent_name = override.group(1) + "_agent"
            task = override.group(2).strip() or user_input
            label = override.group(1)
            _ack(f"{label} on it")
            _status(f"{label} working...")
            result = await self._dispatch(
                agent_name, task, user_input,
                on_status=lambda m: _status(m),
            )
            response_text = result.result or "Couldn't get that done."
            self.conversation.append({"role": "user", "content": user_input})
            self.conversation.append({"role": "assistant", "content": response_text})
            _chunk(response_text)
            self._mem_processor.process(user_input, response_text, agent_name)
            return

        # ── Priority 2: One-shot tool calls (1 LLM call) ──
        # For queries where we know exactly which tool to call.
        # Calls tool directly, then 1 LLM to format. No ReAct loop.
        oneshot = await self._try_oneshot(s, user_input, _ack, _status, _chunk)
        if oneshot:
            return

        # ── Priority 2.5: Direct tool dispatch (2 LLM calls) ──
        # LLM picks from 18 curated tools → execute → LLM formats.
        # Catches the long tail of single-tool queries that oneshot regex misses.
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
            # Response text already chunked by try_direct_dispatch
            return

        # ── Priority 3: Direct agent dispatch via regex (2 LLM calls) ──
        # Skips routing LLM (#1) and synthesis LLM (#4).
        # Agent's own output is used directly — it already summarizes.
        match = self._match_agent(user_input)
        if match:
            agent_name, task = match
            label = agent_name.replace("_agent", "")
            _ack(f"{label} on it")
            _status(f"{label} working...")

            result = await self._dispatch(
                agent_name, task, user_input,
                on_status=lambda m: _status(m),
            )

            # Use agent result directly — no synthesis LLM call
            response_text = result.result or "Couldn't get that done."
            self.conversation.append({"role": "user", "content": user_input})
            self.conversation.append({"role": "assistant", "content": response_text})
            _chunk(response_text)
            # Background memory extraction
            self._mem_processor.process(user_input, response_text, agent_name)
            return

        # ── Priority 4: Conversational fast chat (1 LLM, slim prompt ~500 tokens) ──
        # If no regex matched, it's likely casual chat or an edge case.
        # Try a fast conversational response first with a slim prompt.
        # Only fall back to full routing if the query looks like an agent task.
        if self._is_likely_chat(s):
            text = await self._fast_chat(user_input, _chunk)
            return

        # ── Priority 5: LLM routing fallback (4 LLM calls) ──
        # Only for queries that genuinely need LLM-based routing
        system_prompt = self._build_system_prompt(user_input)
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self.conversation[-6:])
        messages.append({"role": "user", "content": user_input})

        response = chat(messages=messages, tools=[DISPATCH_TOOL], think=False)
        tool_calls = extract_tool_calls(response)

        if not tool_calls:
            # No agent needed — conversational response
            text = extract_text(response)
            self.conversation.append({"role": "user", "content": user_input})
            self.conversation.append({"role": "assistant", "content": text})
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
            # Background memory extraction
            full_response = "".join(synth_text)
            agent_names = ", ".join(agents) if agents else "agent"
            self._mem_processor.process(user_input, full_response, agent_names)
            return

        text = extract_text(response)
        _chunk(text)

    async def _direct_briefing_streamed(self, _status, _chunk, user_input: str):
        """Direct briefing with parallel tools + streamed synthesis."""
        import asyncio as _asyncio
        from friday.tools.briefing_tools import get_daily_digest
        from friday.tools.email_tools import TOOL_SCHEMAS as _E
        from friday.tools.calendar_tools import TOOL_SCHEMAS as _C
        from friday.tools.call_tools import TOOL_SCHEMAS as _K
        from friday.tools.x_tools import TOOL_SCHEMAS as _X

        read_emails = _E["read_emails"]["fn"]
        get_calendar = _C["get_calendar"]["fn"]
        get_call_history = _K["get_call_history"]["fn"]
        get_my_mentions = _X["get_my_mentions"]["fn"]

        _status("pulling everything at once...")
        results = {}

        async def _run(name, coro, timeout=30):
            _status(f"checking {name}...")
            try:
                r = await _asyncio.wait_for(coro, timeout=timeout)
                results[name] = r
                _status(f"✓ {name} done")
                return r
            except _asyncio.TimeoutError:
                results[name] = Exception(f"{name} timed out after {timeout}s")
                _status(f"✗ {name} timed out")
            except Exception as e:
                results[name] = e
                _status(f"✗ {name} failed")

        await _asyncio.gather(
            _run("digest", get_daily_digest(), timeout=20),
            _run("emails", read_emails(filter="unread"), timeout=15),
            _run("calendar", get_calendar(), timeout=20),
            _run("calls", get_call_history(limit=10), timeout=15),
            _run("x_mentions", get_my_mentions(), timeout=15),
            return_exceptions=True,
        )

        _status("synthesizing briefing...")

        # Build tool results summary
        summary_parts = []
        for name, r in results.items():
            if isinstance(r, Exception):
                summary_parts.append(f"[{name}] Error: {r}")
            elif isinstance(r, ToolResult) and r.success:
                data = r.data
                if isinstance(data, list):
                    summary_parts.append(f"[{name}] {len(data)} items: {json.dumps(data[:5], default=str)[:1500]}")
                elif isinstance(data, dict):
                    summary_parts.append(f"[{name}] {json.dumps(data, default=str)[:1500]}")
                elif data:
                    summary_parts.append(f"[{name}] {str(data)[:1500]}")
                else:
                    summary_parts.append(f"[{name}] No data")
            else:
                err = r.error.message if hasattr(r, 'error') and r.error else "unknown"
                summary_parts.append(f"[{name}] Failed: {err}")

        tool_data = "\n\n".join(summary_parts)

        # Use slim briefing prompt — we already have the data, just need synthesis
        briefing_slim = """You are FRIDAY. Synthesize this data into a tight briefing for Travis.
Lead with anything urgent. Then calendar. Then anything worth knowing. Max 150 words.
Be direct, no fluff. Use Travis's voice — casual, real."""
        messages = [
            {"role": "system", "content": briefing_slim},
            {"role": "user", "content": f"Briefing data:\n\n{tool_data}"},
        ]

        # Stream synthesis — cap at 200 tokens for speed
        response_stream = chat(messages=messages, think=False, stream=True, max_tokens=200)
        full_text = ""
        for chunk in response_stream:
            if hasattr(chunk, "message"):
                content = chunk.message.content or ""
            elif isinstance(chunk, dict):
                content = chunk.get("message", {}).get("content", "") or ""
            else:
                continue
            if content:
                full_text += content
                _chunk(content)

        self.conversation.append({"role": "user", "content": user_input})
        self.conversation.append({"role": "assistant", "content": full_text.strip()})

    async def process(self, user_input: str) -> str:
        """Process user input — non-streaming. Used when tool calls may be needed."""
        system_prompt = self._build_system_prompt(user_input)
        think = _needs_thinking(user_input)

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self.conversation[-20:])
        messages.append({"role": "user", "content": user_input})

        response = chat(messages=messages, tools=[DISPATCH_TOOL], think=think)
        tool_calls = extract_tool_calls(response)

        if not tool_calls:
            text = extract_text(response)
            self.conversation.append({"role": "user", "content": user_input})
            self.conversation.append({"role": "assistant", "content": text})
            return text

        # Process agent dispatches
        agent_results = []
        for tc in tool_calls:
            if tc["name"] == "dispatch_agent":
                agent_name = tc["arguments"]["agent"]
                task = tc["arguments"]["task"]
                agent_result = await self._dispatch(agent_name, task, user_input)
                agent_results.append(agent_result)

        if agent_results:
            synthesis = await self._synthesize(user_input, agent_results)
            self.conversation.append({"role": "user", "content": user_input})
            self.conversation.append({"role": "assistant", "content": synthesis})
            return synthesis

        text = extract_text(response)
        self.conversation.append({"role": "user", "content": user_input})
        self.conversation.append({"role": "assistant", "content": text})
        return text

    def stream(self, user_input: str) -> Generator[str, None, None]:
        """Stream a direct response. For simple queries that won't need tool calls.
        With think=False, Ollama disables thinking at engine level so we get
        pure content tokens — no filtering needed."""
        system_prompt = self._build_system_prompt(user_input)
        think = _needs_thinking(user_input)

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self.conversation[-20:])
        messages.append({"role": "user", "content": user_input})

        response_stream = chat(messages=messages, think=think, stream=True)

        full_text = ""

        for chunk in response_stream:
            # Handle both object and dict responses
            if hasattr(chunk, "message"):
                content = chunk.message.content or ""
            elif isinstance(chunk, dict):
                content = chunk.get("message", {}).get("content", "") or ""
            else:
                continue

            if content:
                full_text += content
                yield content

        # Save to conversation
        self.conversation.append({"role": "user", "content": user_input})
        self.conversation.append({"role": "assistant", "content": full_text.strip()})

    async def process_and_stream(self, user_input: str, on_status=None) -> AsyncGenerator[str, None]:
        """Process with agents, streaming the final synthesis.
        on_status is an optional callback for progress updates like 'searching...'"""
        system_prompt = self._build_system_prompt(user_input)

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self.conversation[-20:])
        messages.append({"role": "user", "content": user_input})

        if on_status:
            on_status("routing...")

        response = chat(messages=messages, tools=[DISPATCH_TOOL], think=False)
        tool_calls = extract_tool_calls(response)

        if not tool_calls:
            # No agent needed — yield text directly
            text = extract_text(response)
            self.conversation.append({"role": "user", "content": user_input})
            self.conversation.append({"role": "assistant", "content": text})
            yield text
            return

        # Dispatch agents
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
            # Stream the synthesis
            for chunk in self.stream_synthesis(user_input, agent_results):
                yield chunk
        else:
            text = extract_text(response)
            self.conversation.append({"role": "user", "content": user_input})
            self.conversation.append({"role": "assistant", "content": text})
            yield text

    def needs_agent(self, user_input: str) -> bool:
        """Quick check: does this input likely need agent dispatch?
        If not, we can stream directly for speed.
        Be conservative — only trigger on clear task intent, not conversational uses."""
        stripped = user_input.strip().lower()

        import re

        # Email/calendar always dispatch — no ambiguity
        comms_patterns = [
            r"\b(email|emails|inbox|gmail|unread)\b",
            r"\b(my |the |any )?(mail|mails)\b",
            r"\b(calendar|schedule|meeting|event|appointment)\b",
            r"\b(draft|send|reply|forward|read)\s+(an |a |the |my )?(email|message|mail)\b",
            r"\bsend (the |this |that |email )?(draft)\b",
            r"\bedit (the |this |that |email )?(draft)\b",
            r"\bdraft.{0,5}(id|ID)\b",
            r"\bcheck (my |the )?(email|inbox|calendar|schedule|mail)\b",
            r"\bwhat('?s| is) (on |in )?(my )?(calendar|schedule|inbox|mail)\b",
            r"\b(can you |)(read|check|show|get) (my |the )?(mail|email|inbox|calendar)\b",
            r"\bany (new |unread |recent )?(mail|email|message)s?\b",
        ]
        if any(re.search(p, stripped) for p in comms_patterns):
            return True

        # Follow-up comms commands — check if recent conversation was about email/calendar
        followup_patterns = [
            r"^send (it|that|the draft)[\s!?.]*$",
            r"^draft (it|that)[\s!?.]*$",
            r"^(yes |yeah |yep |ok )?(send|draft|mail) (it|that)[\s!?.]*$",
            r"^(check|did) (it|that) (send|go|get sent)[\s!?.]*$",
        ]
        if any(re.search(p, stripped) for p in followup_patterns):
            # Only dispatch if we were recently talking about email/calendar
            if self._recent_comms_context():
                return True

        # TV / smart home — always dispatch to household agent
        household_patterns = [
            r"\b(tv|television|telly)\b",
            r"\b(turn on|turn off|switch on|switch off)\s+(the )?(tv|television|telly)\b",
            r"\b(netflix|youtube|spotify|disney|prime video|apple tv)\b.*\b(tv|on the|put on)\b",
            r"\bput on\s+(netflix|youtube|spotify|disney|prime|apple tv)\b",
            r"\b(hdmi|input)\s*\d\b",
            r"\b(mute|unmute)\s*(the )?(tv|television)\b",
            r"\btv\s*(volume|vol)\b",
            r"\bwhat('?s| is) on (the )?(tv|screen)\b",
            r"\bis (my |the )?(tv|telly) on\b",
            r"\bwhat('?s| is) playing\s*(on)?\s*(my |the )?(tv)?\b",
            r"\b(play|open)\s+.+\s+on\s+(my |the )?(tv|telly)\b",
            r"\b(pause|resume|unpause)\s+(the )?(tv|what'?s playing|it)\b",
            r"\b(pause|resume|stop)\s+(the )?(show|movie|video|stream)\b",
            r"\b(louder|quieter|turn (it |the volume )?(up|down))\b.*\b(tv)?\b",
            r"\b(increase|decrease|raise|lower)\s+(the )?(tv )?(volume|vol)\b",
        ]
        if any(re.search(p, stripped) for p in household_patterns):
            return True

        # Monitor/briefing patterns — always dispatch
        monitor_patterns = [
            r"\b(monitor|watch|track|keep an eye on|alert me)\b",
            r"\b(my |the |show |list )?(monitors|watchers)\b",
            r"\b(pause|delete|stop|remove)\s+(the )?(monitor|watcher)\b",
            r"\b(force |)check\s+(the )?(monitor|watcher)\b",
            r"\bwhat('?s| is| am i) (being )?(monitored|watched|tracked|monitoring|watching|tracking)\b",
            r"\bmonitor\s+history\b",
        ]
        if any(re.search(p, stripped) for p in monitor_patterns):
            return True

        # Job/CV patterns — always dispatch to job agent
        job_patterns = [
            r"\b(cv|résumé|resume|curriculum vitae)\b",
            r"\bcover\s*letter\b",
            r"\b(job|role)\s+(application|apply|applying)\b",
            r"\bapply\s+(to|for|at)\b",
            r"\btailor\s+(my |the )?(cv|resume)\b",
            r"\b(generate|create|make|build)\s+(a |my |the )?(cv|resume|cover letter)\b",
            r"\bhelp me (apply|get a job|with my application)\b",
            r"\b(check|scan|look).+(email|mail|inbox).+(job|role|opening|position|application)\b",
            r"\b(job|role|opening|position).+(email|mail|inbox)\b",
            r"\bapply.+(all|every|each).+(role|job|position|opening)\b",
            r"\bgo on .+ and apply\b",
            r"\bfind.+(job|role|position)s?\s+(for me|i qualify|that match)\b",
        ]
        if any(re.search(p, stripped) for p in job_patterns):
            return True

        # X / Twitter / social patterns — always dispatch (check BEFORE task patterns)
        social_patterns = [
            r"\b(tweet|post)\s+(this|that|about|on)\b",
            r"\bpost\s+on\s+(x|twitter)\b",
            r"\b(my |check |any )?(mentions|@mentions)\b",
            r"\b(search|look|find)\s+.*(x|twitter|tweets?)\b",
            r"\bsearch\s+x\s+for\b",                                # "search x for ..."
            r"\b(like|retweet|rt)\s+(that |this |the )?(tweet|post)\b",
            r"\bdelete\s+(my |that |the )?(tweet|post)\b",
            r"\bwho\s+is\s+@\w+\b",                                 # "who is @someone"
            r"\b@\w+.*(twitter|x|tweet|post|profile)\b",            # "@user on twitter"
            r"\b(twitter|x\.com)\b",
            r"\bon\s+x\b",                                          # "on x" (the platform)
            r"\btweet\b",
            r"\btrending\s+on\s+x\b",
            r"\b(what|who).+(tweet|posting|tweeting)\b",
        ]
        if any(re.search(p, stripped) for p in social_patterns):
            return True

        briefing_patterns = [
            r"\b(brief|briefing|debrief)\b",
            r"\bwhat did (i|we) miss\b",
            r"\b(morning|evening|daily)\s+(update|brief|summary|digest|report)\b",
            r"\bcatch me up\b",
            r"\bwhat('?s| is) new\b",
            r"\bgive me (a |the )?(update|rundown|summary)\b",
            r"\bany (alerts?|updates?|changes?)\b",
            r"\b(any |did .+ |who )?(call|calls|called|ring|rang)\b",
            r"\bmissed\s+(call|calls)\b",
            r"\b(voicemail|voice\s*mail)\b",
            r"\b(phone|facetime)\s+(log|history|calls?)\b",
        ]
        if any(re.search(p, stripped) for p in briefing_patterns):
            return True

        # System control patterns — always dispatch
        system_patterns = [
            r"\b(open|launch|start)\s+(an? )?\w+",                    # open Cursor, launch Chrome
            r"\b(screenshot|screen\s*shot|screen\s*cap)\b",            # take a screenshot
            r"\b(dark\s*mode|light\s*mode)\b",                         # toggle dark mode
            r"\b(volume|mute|unmute)\b",                               # volume control
            r"\b(system\s*info|system\s*status|uptime)\b",             # system info
            r"\b(go to|navigate to|browse)\s+\S",                      # browser navigation
            r"\bwhat('?s| is) running\b",                              # process check
            r"\b(kill|stop|terminate)\s+(the |a )?(process|server)\b", # process management
            r"\b(display|show|open)\s+(it|that|the screenshot|the image)\b",  # display file
            r"\b(airdrop|air\s*drop)\b",                             # airdrop to phone
            r"\b(send.+phone|send.+iphone)\b",                      # send to phone
            r"\biphone\s*mirror",                                    # iphone mirroring
            r"\b(read|extract|merge|split|rotate|encrypt|decrypt|watermark)\s+.*(pdf|\.pdf)\b",  # PDF ops
            r"\bpdf\s+(read|extract|merge|split|rotate|encrypt|decrypt|metadata)\b",              # PDF ops
            r"\b(extract\s+tables?|extract\s+text)\s+from\b",                                     # PDF extraction
        ]
        if any(re.search(p, stripped) for p in system_patterns):
            return True

        # Task verbs followed by something — means "do this for me"
        task_patterns = [
            r"\b(search|look up|google|research)\s+\S",       # search/research anything
            r"\b(remember|recall|save)\s+\S",                  # memory ops
            r"\bwhat did (i|we)\b",                            # memory recall
            r"\b(run|execute)\s+\S",                           # run commands
            r"\b(read|open|write|edit|create)\s+\S",           # file ops
            r"\bgit\s+\S",                                     # any git command
            r"\b(deploy|install|uninstall)\s+\S",              # deploy/install
            r"\b(debug|fix)\s+\S",                             # debug/fix anything
            r"\b(write|build|create|implement|make)\s+\S",     # build anything
            r"\b(find|check|test|scan|analyze|explain)\s+\S",  # investigation tasks
        ]
        has_task_verb = any(re.search(p, stripped) for p in task_patterns)
        if not has_task_verb:
            return False

        # Vague requests — verb is there but no real context to act on.
        # These should go to chat so FRIDAY can ask what's needed (~2s vs ~18s).
        vague_patterns = [
            r"^(fix|debug|help with|check|test|find|run)\s+(my |the |a |this |that )?(bug|issue|error|problem|thing|stuff|code|it)s?[.!?\s]*$",
            r"^(build|create|make|write|implement)\s+(me |a |the )?(something|thing|stuff|it)[.!?\s]*$",
        ]
        if any(re.search(p, stripped) for p in vague_patterns):
            return False

        return True

    def _recent_comms_context(self) -> bool:
        """Check if recent conversation involved email/calendar (last 6 messages)."""
        comms_keywords = {"email", "mail", "draft", "send", "calendar", "schedule", "inbox", "gmail"}
        for msg in self.conversation[-6:]:
            content = msg.get("content", "").lower()
            if any(kw in content for kw in comms_keywords):
                return True
        return False

    async def _dispatch(self, agent_name: str, task: str, original_input: str, on_status=None) -> AgentResponse:
        """Dispatch to a specialist agent."""
        agent = self.agents.get(agent_name)
        if not agent:
            return AgentResponse(
                agent_name=agent_name,
                success=False,
                result=f"Unknown agent: {agent_name}",
                error="agent_not_found",
            )

        # Pass tool call progress to CLI
        def on_tool_call(tool_name, tool_args):
            if on_status:
                # Show friendly tool names
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
                # Add query/url context when available
                if tool_name == "search_web":
                    q = tool_args.get("query", "")
                    label = f'searching: "{q[:40]}"'
                elif tool_name == "fetch_page":
                    u = tool_args.get("url", "")
                    # Show just the domain
                    domain = u.split("//")[-1].split("/")[0] if "//" in u else u[:40]
                    label = f"reading {domain}"
                on_status(label)

        # Build context: memory + recent conversation so agents know what was discussed
        memory_context = self.memory.build_context(query=original_input)
        conv_context = ""
        if self.conversation:
            recent = self.conversation[-6:]  # Last 3 exchanges
            conv_lines = []
            for msg in recent:
                role = "Travis" if msg["role"] == "user" else "FRIDAY"
                conv_lines.append(f"{role}: {msg['content'][:300]}")
            conv_context = "Recent conversation:\n" + "\n".join(conv_lines)

        context = f"{memory_context}\n\n{conv_context}".strip()
        result = await agent.run(task=task, context=context, on_tool_call=on_tool_call)

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

    async def _synthesize(self, user_input: str, agent_results: list[AgentResponse]) -> str:
        """Take agent results and produce a final FRIDAY response (non-streaming)."""
        messages = self._build_synthesis_messages(user_input, agent_results)
        response = chat(messages=messages, think=False)
        return extract_text(response)

    def stream_synthesis(self, user_input: str, agent_results: list[AgentResponse]) -> Generator[str, None, None]:
        """Stream the synthesis step token by token."""
        messages = self._build_synthesis_messages(user_input, agent_results)
        response_stream = chat(messages=messages, think=False, stream=True)

        full_text = ""
        for chunk in response_stream:
            if hasattr(chunk, "message"):
                content = chunk.message.content or ""
            elif isinstance(chunk, dict):
                content = chunk.get("message", {}).get("content", "") or ""
            else:
                continue
            if content:
                full_text += content
                yield content

        self.conversation.append({"role": "user", "content": user_input})
        self.conversation.append({"role": "assistant", "content": full_text.strip()})

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
