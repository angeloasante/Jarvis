"""Intent routing — classify user intent and route to the right agent.

Two routing strategies:
  1. LLM classification (Groq, ~1s) — primary when cloud available
  2. Regex pattern matching — fallback when offline or cloud fails

All functions are standalone (no class). They take conversation and memory
as explicit params so FridayCore can call them without coupling.
"""

import re
import logging
from datetime import datetime

from friday.core.config import USE_CLOUD

logger = logging.getLogger(__name__)

# ── Slim classification prompt — no personality, just routing ────────────────

_CLASSIFY_PROMPT = """You are the router for FRIDAY, a personal AI OS. You pick which agent HANDLES the user's request.

CORE PRINCIPLE: FRIDAY agents are not assistants that explain. They EXECUTE. They DO the thing. Choose the agent that can ACTUALLY PERFORM the action. Never route to CHAT when an agent exists that can do the task.

──────────────────────────────────────────────────
AGENTS (what each one CAN DO):
──────────────────────────────────────────────────

job_agent — AUTONOMOUSLY APPLIES TO JOBS
  Can: browse job sites (LinkedIn, Greenhouse, Lever, Ashby, careers pages), read job descriptions, tailor the user's CV to a specific role, generate tailored PDF cover letter, fill application forms in Safari (text fields, dropdowns, file uploads, React-Select), submit (with confirmation).
  Use for:
    • "apply for [role] at [company]"
    • "go to [company]'s site and apply for me"
    • "find me jobs at Google"
    • "tailor my CV for this role"
    • "look at this job posting and apply"
    • "read the job on my screen and make a CV"
    • anything involving submitting a job application end-to-end
  NOT for: general research about a company (that's research_agent).

system_agent — CONTROLS THE MAC
  Can: open/close apps, take screenshots, read what's on the screen (OCR + vision), solve questions on any visible page, control volume/brightness/dark mode, run terminal commands, read files, browse the web via Safari (navigate, click, fill forms, read pages), manipulate PDFs.
  Use for:
    • "open [app]" / "open [website]" / "go to [site]"
    • "screenshot" / "what's on my screen"
    • "fill the form on my screen"
    • "what's my battery / CPU / RAM / storage"
    • "turn on dark mode" / "set volume to 30"
    • "navigate to [URL]"
    • "read this PDF" / "solve the questions on this page"
  NOT for: things about the TV (that's household_agent).

household_agent — CONTROLS THE TV AND SMART HOME
  Can: turn LG TV on/off, change volume, mute, launch apps on TV (Netflix, YouTube, Spotify, Disney+, Prime), pause/play, change channel, screen off, smart home devices.
  Use for ANY request involving the TV, telly, television, lounge/living room screen.

comms_agent — HANDLES ALL COMMUNICATION
  Can: read/search/send Gmail, read/create calendar events, read/send iMessages, start FaceTime calls, search contacts, read/send WhatsApp (via local bridge), send/read SMS (via Twilio), draft/edit/send email drafts.
  Use for:
    • email ("check my emails", "draft an email", "send it")
    • calendar ("what's on my calendar", "book a meeting")
    • messages ("text Mom", "reply to <contact nickname>", "check my whatsapp")
    • FaceTime ("call Dad", "facetime my brother")
    • SMS ("sms me", "text my twilio number")

social_agent — X / TWITTER
  Can: post tweets, reply, quote-tweet, like, retweet, search X, read mentions, look up @users.
  Use for ANY mention of X, Twitter, tweeting, posting, or @usernames.

briefing_agent — DAILY DIGESTS
  Can: synthesize emails + calendar + missed calls + X feed + monitor alerts into a briefing.
  Use for: "catch me up", "brief me", "morning summary", "what did I miss", "any updates".

memory_agent — PERSONAL MEMORY
  Can: store facts about the user/their projects/their people, recall stored memories, search memory.
  Use for: "remember that X", "what do I know about X", "recall my preferences".
  NOT for: save-to-file (code_agent), not for notes to send someone (comms_agent).

monitor_agent — AUTONOMOUS WATCHERS
  Can: watch URLs for changes, track recurring web searches, monitor topics, alert on updates.
  Use for: "monitor this page", "watch for changes", "alert me when X updates", "track [thing]".
  NOT for: one-time lookups (research_agent).

research_agent — WEB RESEARCH + SHORT WRITE-UPS
  Can: search the web, fetch and read web pages, summarize, answer factual questions, AND save a short report to a file (md/docx/pdf/txt) when asked.
  Use for:
    • "who is [person]" / "what is [thing]"
    • "fetch this URL and tell me about it"
    • "tell me about [topic]"
    • "write a SHORT / QUICK / BRIEF report/summary/overview on [topic]" (even with "save to desktop")
    • background info on a company (NOT applying — that's job_agent)
  This is the FAST path (~10-20s). Prefer this over deep_research_agent unless user asks for depth.

code_agent — FILES AND CODE
  Can: read/write files, run terminal commands, git operations, build/test code, save generated content to disk.
  Use for: "write a script", "create a file at [path]", "fix this bug", "save [X] to my desktop", anything involving a file path or code.

deep_research_agent — LONG-FORM / MULTI-SECTION DOCUMENTS
  Can: multi-agent parallel research + synthesis into full 4-8 section documents (docx/pdf/md). Takes 2-3 minutes.
  Use ONLY when user explicitly asks for depth:
    • "write a PAPER on X"
    • "COMPREHENSIVE / DETAILED / IN-DEPTH / THOROUGH report about Y"
    • "DEEP DIVE into Z"
    • "multi-section document"
    • school/uni submissions, theses
  Do NOT use for "short report", "quick summary", "brief overview" — that's research_agent.

cron_agent — SCHEDULED TASKS
  Can: create/list/delete recurring cron jobs.
  Use for: "every weekday at 8am do X", "schedule X daily", "list my crons".

CHAT — CASUAL CONVERSATION ONLY
  Use for: greetings, opinions, "how are you", follow-ups asking about YOUR OWN previous response ("why did you say that", "what do you mean", "explain"), emotional conversation, no actionable task.

──────────────────────────────────────────────────
HARD RULES (these override everything above):
──────────────────────────────────────────────────

1. If the user wants to DO something (apply, open, send, fill, control, execute) — NEVER pick CHAT. Find the right action agent.
2. "Apply for a job" / "go to [site] and apply" → job_agent. NEVER research_agent. NEVER CHAT.
3. "Open [website/app]" / "go to [URL]" → system_agent. NEVER research_agent.
4. Anything about TV / telly → household_agent. Always.
5. X / Twitter / tweet / @username → social_agent. Always.
6. Device stats (battery/RAM/CPU/storage) → system_agent, NEVER research_agent.
7. "short report / quick summary / brief overview" → research_agent (fast, saves files too). Only "detailed / comprehensive / in-depth / multi-section / paper" → deep_research_agent.
8. Follow-ups about YOUR last response ("why did you say that", "what do you mean") → CHAT.
9. Short confirmations ("yes", "do it", "go ahead"): if the previous message was an agent asking "should I continue?", route to THAT SAME agent. Otherwise CHAT.
10. When uncertain between CHAT and an action agent → pick the action agent. The user asks FRIDAY to DO things.

Respond with ONLY the agent name (lowercase, with _agent suffix) or "CHAT". Nothing else. No explanation.

Current time: {time}"""


def classify_intent(
    user_input: str,
    conversation: list[dict],
) -> tuple[str, str] | None:
    """Use Groq LLM to classify intent in ~1s. Returns (agent_name, task) or None for chat.

    Only called when cloud is available. Falls back to match_agent() regex if this fails.
    """
    if not USE_CLOUD:
        return None

    try:
        from friday.core.llm import cloud_chat, extract_text

        now = datetime.now().strftime("%A %d %B %Y, %H:%M")
        messages = [{"role": "system", "content": _CLASSIFY_PROMPT.format(time=now)}]

        # Last 2 messages for context (pronoun resolution, follow-ups)
        for msg in conversation[-2:]:
            messages.append({**msg, "content": msg["content"][:200]})
        messages.append({"role": "user", "content": user_input})

        response = cloud_chat(messages=messages, max_tokens=20)
        text = extract_text(response).strip().lower().replace(".", "")

        # Parse the response
        valid_agents = {
            "code_agent", "research_agent", "memory_agent", "comms_agent",
            "system_agent", "household_agent", "monitor_agent", "briefing_agent",
            "job_agent", "social_agent", "cron_agent", "deep_research_agent",
        }

        if text in valid_agents:
            return (text, user_input.strip())
        if text == "chat":
            return None  # Let fast_chat handle it

        # Model returned something unexpected — fall through to regex
        logger.debug(f"LLM classify returned unexpected: '{text}'")
        return None

    except Exception as e:
        logger.debug(f"LLM classify failed ({type(e).__name__}), falling back to regex")
        return None


def match_agent(
    user_input: str,
    conversation: list[dict],
    memory=None,
) -> tuple[str, str] | None:
    """Pattern-match input directly to an agent. Skips the routing LLM call.

    Returns (agent_name, task_description) or None if no match.
    Uses conversation context for follow-ups: if last exchange used
    social_agent and user says "what did X say", routes to social not research.
    """
    s = user_input.strip().lower()
    raw = user_input.strip()

    # ── Context-aware follow-ups ──
    recent_agent = recent_agent_context(conversation, memory)
    if recent_agent:
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
            r"go on|keep going|continue|another|try again|"
            r"look up another|different|other)\b", s
        )
        if (has_reference or is_continuation) and len(s) < 80:
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
            HEAVY_AGENTS = {"research_agent", "monitor_agent", "code_agent"}
            if not has_override and recent_agent not in HEAVY_AGENTS:
                return (recent_agent, raw)

    # ── Comms (email + calendar + iMessage + FaceTime) ──
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
        # iMessage — send
        r"\b(text|imessage|iMessage)\s+\S",
        r"\b(send|shoot)\s+(a |an |)?(text|message|imessage|iMessage)\b",
        r"\b(message|text)\s+.+\s+(saying|that says|and say|and tell)\b",
        # iMessage — read / reply
        r"\b(check|read|show|get)\s+(my |the )?(messages|texts|imessages|iMessages)\b",
        r"\b(any |)(new |recent |unread )?(messages|texts|imessages)\b",
        r"\bwhat did .+ (say|send|text|message)\b",
        r"\breply\s+to\s+\S",
        r"\brespond\s+to\s+\S",
        # WhatsApp
        r"\b(whatsapp|whats\s*app|wa)\s+(message|text|send|check|read)\b",
        r"\b(send|text|message)\s+.+\s+(on |via |through )?(whatsapp|wa)\b",
        r"\b(check|read|show|get)\s+(my |the )?(whatsapp|wa)\b",
        r"\bwhatsapp\b",
        # FaceTime
        r"\b(facetime|face\s*time)\s+\S",
        r"\b(call|ring|phone)\s+\S.+\b(on )?(facetime|face\s*time)\b",
        r"\b(facetime|face\s*time)\s+(call|audio)\b",
        # Contacts
        r"\b(find|look\s*up|get|what'?s)\s+.+('s |s )?(number|phone|contact)\b",
        r"\b(who is|look up)\s+.+\s+in\s+(my )?(contacts)\b",
    ]
    if any(re.search(p, s) for p in comms_patterns):
        return ("comms_agent", raw)

    # Follow-up comms
    followup_patterns = [
        r"^send (it|that|the draft)",
        r"^draft (it|that)",
        r"^(yes |yeah |yep |ok )?(send|draft|mail) (it|that)",
        r"\bsend it+\b",  # "send itttt"
        r"^draft .+ and send",
        r"^send .+ to ",  # "send something to X"
        r"\bidentify yourself\b",
        r"\btell (him|her|them) ",
    ]
    if any(re.search(p, s) for p in followup_patterns) and recent_comms_context(conversation):
        return ("comms_agent", raw)

    # ── Social (X / Twitter) — check BEFORE research ──
    social_patterns = [
        r"\b(tweet|post)\s+(this|that|about|on)\b",
        r"\bpost\s+on\s+(x|twitter)\b",
        r"\b(my |check |any )?(mentions|@mentions)\b",
        r"\b(search|look|find)\s+.*(x|twitter|tweets?)\b",
        r"\bsearch\s+x\s+for\b",
        r"\bcheck\s+x\b",
        r"\b(like|retweet|rt)\s+(that |this |the )?(tweet|post)\b",
        r"\bdelete\s+(my |that |the )?(tweet|post)\b",
        r"\bwho\s+is\s+@\w+\b",
        r"\b@\w+",
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

    # Household follow-up — if last agent was household, "search for X on youtube"
    # means search on the TV's YouTube app, not web search
    if recent_agent == "household_agent":
        household_followup = [
            r"\b(search|look|find)\s+(for\s+)?.*\bon\s+(youtube|netflix|disney|spotify)\b",
            r"\b(open|play|go to)\s+(his |her |their |the |that |this )",
            r"\b(search|look) for\b",
            r"\b(next|previous|back|forward|select|pick|choose)\b",
        ]
        if any(re.search(p, s) for p in household_followup):
            return ("household_agent", raw)

    # ── Monitor ──
    monitor_patterns = [
        r"\b(monitor|watch for|watch this .*(page|url|site|link)|track changes|keep an eye on|alert me when)\b",
        r"\b(my |the |show |list )?(monitors|watchers)\b",
        r"\b(pause|delete|stop|remove)\s+(the )?(monitor|watcher)\b",
        r"\b(force |)check\s+(the )?(monitor|watcher)\b",
        r"\bwhat('?s| is| am i) (being )?(monitored|watched|tracked|monitoring|watching|tracking)\b",
        r"\bmonitor\s+history\b",
    ]
    # Strip URLs before matching monitor patterns — "youtube.com/watch" shouldn't trigger monitor
    s_no_urls = re.sub(r'https?://\S+', '', s).strip()
    if any(re.search(p, s_no_urls) for p in monitor_patterns):
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
        r"\b(look at|read).+(screen|page).+(cv|resume|cover letter|apply|job)\b",
        r"\b(cv|resume|cover letter|apply|job).+(screen|page|on my|i'?m on)\b",
        r"\b(open|go to).+(career|job|hiring|vacancy|vacancies)\b",
        r"\bcareer\s*(page|section|link|site)\b",
    ]
    if any(re.search(p, s) for p in job_patterns):
        return ("job_agent", raw)

    # ── Watch tasks (standing orders) ──
    watch_patterns = [
        r"\b(watch|monitor|keep an eye on)\s+.+(message|text|email|inbox).+(for the next|for \d+|every)\b",
        r"\bfor the next\s+\d+\s*(hour|min|minute).+(check|watch|monitor|reply|respond)\b",
        r"\b(check|watch)\s+.+(every|each)\s+\d+\s*(min|minute|second)\b",
        r"\b(if|when)\s+.+(new message|texts?|emails?)\s+(come|comes|arrive).+(reply|respond|let me know|ping me)\b",
        r"\b(auto.?reply|auto.?respond)\b",
        r"\bstanding order\b",
        r"\b(cancel|stop|end)\s+(the |my )?(watch|standing order)\b",
        r"\bwhat('?s| am i|are you) watch(ing)?\b",
    ]
    if any(re.search(p, s) for p in watch_patterns):
        return ("system_agent", raw)

    # ── Cron / scheduled tasks ──
    cron_patterns = [
        r"\b(cron|crons|cronjob|cron job)\b",
        r"\b(schedule|scheduled)\s+(a |the )?(task|job|cron|reminder)\b",
        r"\b(every|each)\s+(day|weekday|morning|evening|monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|month|hour)\b.+(run|do|check|send|remind|brief)",
        r"\b(list|show|delete|remove|pause|disable|enable)\s+(my |the |all )?(cron|crons|scheduled|recurring)\b",
        r"\b(recurring|repeating)\s+(task|job|reminder)\b",
        r"\bset up .+ (every|daily|weekly|monthly)\b",
        r"\bremind me (every|daily|weekly)\b",
    ]
    if any(re.search(p, s) for p in cron_patterns):
        return ("system_agent", raw)  # System agent handles cron management

    # ── Deep research / multi-agent tasks — produces a deliverable (paper, report, file) ──
    deep_research_patterns = [
        r"\bdeep (research|dive|analysis)\b",
        r"\b(research|write)\s+(a |the )?(paper|report|document|analysis|thesis)\b",
        r"\bdetailed (research|report|analysis|paper)\b",
        r"\bcomprehensive (research|report|analysis|overview)\b",
        r"\b(research|investigate|analyze)\s+.{5,}\s+and\s+(save|write|create|make|build)\b",
        r"\b(save|write)\s+(it |the result |the research )?(to|on|in)\s+(my )?(desktop|downloads|a file)\b",
        r"\bwrite (me |)(a |the )?(research |)(paper|report|document|submission)\s+(about|on|for)\b",
        r"\b(create|make|build)\s+(a |the )?(detailed|submission|research)[\s-]*(ready )?(paper|report|document|file)\b",
        r"\bdo\s+(a |)(research|deep dive)\s+(about|on|into)\b",
        r"\b(read|open)\s+.{3,}\s+(and |then )(research|improve|rewrite|upgrade)\b",
        r"\bimprove\s+.{3,}\s+(to |)(research|paper|academic|submission)[\s-]*(paper |grade|ready|level)?\b",
        r"\b(research|analyze)\s+.{5,}\s+(and |then )(create|write|save|build|make)\b",
    ]
    if any(re.search(p, s) for p in deep_research_patterns):
        return ("deep_research_agent", raw)

    # ── Screen vision / OCR — before research to catch "what's on my screen" etc. ──
    screen_patterns = [
        r"\bcan you see\b",
        r"\blook at (my |the )?screen\b",
        r"\bwhat('?s| is| do you) see\b",
        r"\bwhat('?s| is) (on |this |that )(my )?screen\b",
        r"\blook at this\b",
        r"\bcheck (my |the )?screen\b",
        r"\bwhat does this (mean|say|do)\b",
        r"\bwhat language is this\b",
        r"\bwhat (file|code|page|site|error|app) is\b",
        r"\blook( at)? (right|here|this|that)\b",
        r"\bread (my |the |what'?s on )?(the )?screen\b",
        r"\bocr\b",
        r"\bwhat am i (doing|looking at|working on)\b",
        r"\bsolve.*(question|problem|quiz|exam|test|worksheet|assignment|exercise)",
        r"\b(answer|solve|do).*(on|from|off) (my |the )?screen\b",
        r"\bfull page\b.*\b(screen|capture|ocr|read)\b",
        r"\b(screen|capture|read).*(full page|whole page|entire page|all of it)\b",
    ]
    if any(re.search(p, s) for p in screen_patterns):
        return ("system_agent", raw)

    # ── Research (search, look up, google, find out) ──
    research_patterns = [
        r"\b(search|look up|google|research|find out|find info|find information)\s+\S",
        r"\bsearch\s+for\b",
        r"\bwhat('?s| is| are)\s+(?!good|up|crackin|poppin|happenin|the move|the vibe|the plan).{10,}",
        r"\b(who|where|when|why|how)\s+\w*\s*(is|are|was|were|do|does|did|can|could|would|should)\b.{5,}",
    ]
    if any(re.search(p, s) for p in research_patterns):
        return ("research_agent", raw)

    # ── Form filling (generic — "fill the form on my screen") ──
    form_patterns = [
        r"\bfill\s+(the |this |that |in )?(the )?(form|fields|application)\b",
        r"\bfill\s+(it |them |everything )?(in|out)\b",
        r"\bcomplete\s+(the |this |that )?(form|fields|application)\b",
        r"\bsubmit\s+(the |this |that )?(form|application)\b",
        r"\bfill\s+out\s+(the |this |that )?(form|page|application)\b",
    ]
    if any(re.search(p, s) for p in form_patterns):
        return ("system_agent", raw)

    # ── System (apps, screenshots, volume, dark mode, battery, browser, PDF) ──
    system_patterns = [
        r"\b(open|launch|start)\s+(an? )?\w+",
        r"\b(screenshot|screen\s*shot|screen\s*cap)\b",
        r"\b(dark\s*mode|light\s*mode)\b",
        r"\b(system\s*info|system\s*status|uptime)\b",
        r"\b(battery|storage|disk\s*space|ram|cpu)\s*(percentage|percent|level|status|left|life|remaining|usage)?\b",
        r"\bhow much (battery|storage|disk|ram|memory|cpu)\b",
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

    # ── Code ──
    code_patterns = [
        r"\b(debug|fix)\s+(the |this |my |a )?(bug|error|issue|code|script|crash)\b",
        r"\bgit\s+\S",
        r"\b(run|execute)\s+(the |this |my |a )?(script|code|command|server|test|file)\b",
        r"\b(read|open|write|edit|create)\s+(a |the |my )?(file|code|script)\b",
        r"\b(deploy|install|uninstall)\s+\S",
    ]
    if any(re.search(p, s) for p in code_patterns):
        return ("code_agent", raw)

    # ── Memory ──
    memory_patterns = [
        r"\b(remember|recall)\s+(that |this |what )",
        r"\b(do you |you )(remember|know|recall)\b",
    ]
    if any(re.search(p, s) for p in memory_patterns):
        return ("memory_agent", raw)

    return None


def recent_agent_context(conversation: list[dict], memory=None) -> str | None:
    """Check what agent was used in the last exchange."""
    try:
        if memory:
            recent_calls = memory.get_recent_agent_calls(limit=1)
            if recent_calls:
                last_agent = recent_calls[0].get("agent")
                if last_agent:
                    return last_agent
    except Exception:
        pass

    social_kw = {"tweet", "twitter", "x.com", "@", "mention", "retweet", "post on x"}
    comms_kw = {"email", "gmail", "inbox", "calendar", "draft", "send email", "imessage", "text", "facetime", "message", "whatsapp"}
    system_kw = {"fill form", "fill the form", "browser_fill_form", "browser_discover_form",
                 "screenshot", "dark mode", "system info", "open app", "run command"}
    household_kw = {"tv", "television", "telly", "netflix", "youtube", "spotify", "disney",
                    "volume", "mute", "hdmi", "remote", "pause", "play on tv"}

    for msg in reversed(conversation[-6:]):
        content = msg.get("content", "").lower()
        if any(kw in content for kw in social_kw):
            return "social_agent"
        if any(kw in content for kw in comms_kw):
            return "comms_agent"
        if any(kw in content for kw in household_kw):
            return "household_agent"
        if any(kw in content for kw in system_kw):
            return "system_agent"

    return None


def extract_topic_from_conversation(conversation: list[dict]) -> str | None:
    """Extract the main topic from recent conversation for pronoun resolution."""
    if not conversation:
        return None

    recent_text = " ".join(
        m["content"][:300] for m in conversation[-4:]
    )

    proper_nouns = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b", recent_text)
    SKIP = {"The", "This", "That", "What", "How", "Friday", "FRIDAY",
            "Just", "Yeah", "Nah", "Are", "But", "Not", "You", "They"}
    # Also skip the user's own name (if configured) — it's noise for topic extraction.
    try:
        from friday.core.user_config import USER
        if USER.name:
            SKIP.add(USER.name)
            for part in USER.name.split():
                if len(part) > 2:
                    SKIP.add(part)
    except Exception:
        pass
    proper_nouns = [n for n in proper_nouns if n not in SKIP and len(n) > 2]

    if proper_nouns:
        return proper_nouns[-1]

    for msg in reversed(conversation[-4:]):
        if msg["role"] == "user":
            text = msg["content"].lower()
            text = re.sub(r"^(search for|look up|what is|who is|tell me about)\s+", "", text)
            text = re.sub(r"^(their|the|a|an)\s+", "", text)
            if len(text) > 3 and len(text) < 80:
                return text.strip()

    return None


def is_likely_chat(s: str) -> bool:
    """Quick check: is this casual chat vs a task that needs routing?"""
    task_signals = [
        r"\b(search|find|look up|check|get|fetch|pull|show|list)\b",
        r"\b(send|draft|write|create|make|build|fix|update|delete|text|message)\b",
        r"\b(email|calendar|tweet|post|monitor|watch|track|facetime|imessage|call)\b",
        r"\b(turn|switch|open|close|volume|brightness|screenshot)\b",
        r"\b(cv|resume|cover letter|apply|job)\b",
        r"\b(remember|recall|what did|catch me up)\b",
        r"\b(code|debug|run|deploy|git|commit|push)\b",
    ]
    for p in task_signals:
        if re.search(p, s):
            return False
    return True


def needs_agent(user_input: str, conversation: list[dict]) -> bool:
    """Quick check: does this input likely need agent dispatch?"""
    stripped = user_input.strip().lower()

    # Email/calendar/iMessage/FaceTime always dispatch
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
        # iMessage + FaceTime
        r"\b(text|imessage|iMessage)\s+\S",
        r"\b(send|shoot)\s+(a |an |)?(text|message|imessage|iMessage)\b",
        r"\b(check|read|show|get)\s+(my |the )?(messages|texts|imessages)\b",
        r"\bwhat did .+ (say|send|text|message)\b",
        r"\breply\s+to\s+\S",
        r"\brespond\s+to\s+\S",
        r"\b(facetime|face\s*time)\s+\S",
        r"\b(call|ring|phone)\s+\S.+\b(facetime|face\s*time)\b",
        r"\b(find|look\s*up|get)\s+.+('s |s )?(number|phone|contact)\b",
    ]
    if any(re.search(p, stripped) for p in comms_patterns):
        return True

    # Follow-up comms
    followup_patterns = [
        r"^send (it|that|the draft)[\s!?.]*$",
        r"^draft (it|that)[\s!?.]*$",
        r"^(yes |yeah |yep |ok )?(send|draft|mail) (it|that)[\s!?.]*$",
        r"^(check|did) (it|that) (send|go|get sent)[\s!?.]*$",
    ]
    if any(re.search(p, stripped) for p in followup_patterns):
        if recent_comms_context(conversation):
            return True

    # TV / smart home
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

    # Monitor/briefing
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

    # Job/CV
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

    # Social / X
    social_patterns = [
        r"\b(tweet|post)\s+(this|that|about|on)\b",
        r"\bpost\s+on\s+(x|twitter)\b",
        r"\b(my |check |any )?(mentions|@mentions)\b",
        r"\b(search|look|find)\s+.*(x|twitter|tweets?)\b",
        r"\bsearch\s+x\s+for\b",
        r"\b(like|retweet|rt)\s+(that |this |the )?(tweet|post)\b",
        r"\bdelete\s+(my |that |the )?(tweet|post)\b",
        r"\bwho\s+is\s+@\w+\b",
        r"\b@\w+.*(twitter|x|tweet|post|profile)\b",
        r"\b(twitter|x\.com)\b",
        r"\bon\s+x\b",
        r"\btweet\b",
        r"\btrending\s+on\s+x\b",
        r"\b(what|who).+(tweet|posting|tweeting)\b",
    ]
    if any(re.search(p, stripped) for p in social_patterns):
        return True

    # Watch tasks (standing orders)
    watch_patterns = [
        r"\b(watch|monitor|keep an eye on)\s+.+(message|text|email|inbox).+(for the next|for \d+|every)\b",
        r"\bfor the next\s+\d+\s*(hour|min|minute).+(check|watch|monitor|reply|respond)\b",
        r"\b(auto.?reply|auto.?respond)\b",
        r"\bstanding order\b",
    ]
    if any(re.search(p, stripped) for p in watch_patterns):
        return True

    # Cron / scheduled tasks
    cron_patterns = [
        r"\b(cron|crons|cronjob|cron job)\b",
        r"\b(schedule|scheduled)\s+(a |the )?(task|job|cron|reminder)\b",
        r"\b(every|each)\s+(day|weekday|morning|evening|monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|month|hour)\b.+(run|do|check|send|remind|brief)",
        r"\b(list|show|delete|remove|pause|disable|enable)\s+(my |the |all )?(cron|crons|scheduled|recurring)\b",
        r"\b(recurring|repeating)\s+(task|job|reminder)\b",
        r"\bset up .+ (every|daily|weekly|monthly)\b",
        r"\bremind me (every|daily|weekly)\b",
    ]
    if any(re.search(p, stripped) for p in cron_patterns):
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

    # Deep research / multi-agent tasks
    deep_patterns = [
        r"\bdeep (research|dive|analysis)\b",
        r"\b(research|write)\s+(a |the )?(paper|report|document|analysis|thesis)\b",
        r"\bdetailed (research|report|analysis|paper)\b",
        r"\bcomprehensive (research|report|analysis|overview)\b",
        r"\b(research|investigate|analyze)\s+.{5,}\s+and\s+(save|write|create|build)\b",
        r"\b(create|make|build)\s+(a |the )?(detailed|submission|research)[\s-]*(ready )?(paper|report|document|file)\b",
        r"\bdo\s+(a |)(research|deep dive)\b",
        r"\b(read|open)\s+.{3,}\s+(and |then )(research|improve|rewrite)\b",
    ]
    if any(re.search(p, stripped) for p in deep_patterns):
        return True

    # Screen vision / OCR
    screen_patterns = [
        r"\bcan you see\b",
        r"\blook at (my |the )?screen\b",
        r"\bwhat('?s| is| do you) see\b",
        r"\blook at this\b",
        r"\bcheck (my |the )?screen\b",
        r"\bwhat does this (mean|say|do)\b",
        r"\bwhat am i (doing|looking at|working on)\b",
        r"\bread (my |the )?screen\b",
        r"\bocr\b",
    ]
    if any(re.search(p, stripped) for p in screen_patterns):
        return True

    # System control
    system_patterns = [
        r"\b(open|launch|start)\s+(an? )?\w+",
        r"\b(screenshot|screen\s*shot|screen\s*cap)\b",
        r"\b(dark\s*mode|light\s*mode)\b",
        r"\b(volume|mute|unmute)\b",
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
        r"\b(extract\s+tables?|extract\s+text)\s+from\b",
    ]
    if any(re.search(p, stripped) for p in system_patterns):
        return True

    # Task verbs
    task_patterns = [
        r"\b(search|look up|google|research)\s+\S",
        r"\b(remember|recall|save)\s+\S",
        r"\bwhat did (i|we)\b",
        r"\b(run|execute)\s+\S",
        r"\b(read|open|write|edit|create)\s+\S",
        r"\bgit\s+\S",
        r"\b(deploy|install|uninstall)\s+\S",
        r"\b(debug|fix)\s+\S",
        r"\b(write|build|create|implement|make)\s+\S",
        r"\b(find|check|test|scan|analyze|explain)\s+\S",
    ]
    has_task_verb = any(re.search(p, stripped) for p in task_patterns)
    if not has_task_verb:
        return False

    # Vague requests → chat
    vague_patterns = [
        r"^(fix|debug|help with|check|test|find|run)\s+(my |the |a |this |that )?(bug|issue|error|problem|thing|stuff|code|it)s?[.!?\s]*$",
        r"^(build|create|make|write|implement)\s+(me |a |the )?(something|thing|stuff|it)[.!?\s]*$",
    ]
    if any(re.search(p, stripped) for p in vague_patterns):
        return False

    return True


def recent_comms_context(conversation: list[dict]) -> bool:
    """Check if recent conversation involved email/calendar (last 6 messages)."""
    comms_keywords = {"email", "mail", "draft", "send", "calendar", "schedule", "inbox", "gmail", "imessage", "text", "facetime", "message"}
    for msg in conversation[-6:]:
        content = msg.get("content", "").lower()
        if any(kw in content for kw in comms_keywords):
            return True
    return False
