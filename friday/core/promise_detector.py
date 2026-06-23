"""Promise detector — catches the "I'll do X" yap-without-action pattern.

When fast_chat (or anything else) replies with words like "I'll fetch the
specs / I'm pulling the prices" but never fires a tool, the user gets a
promise and no action. This module detects those patterns so the
orchestrator can escalate to an agent that actually does the work.

Strict by design — only matches active-action verbs ("fetch", "pull",
"research", etc.), not generic future-tense ("I'll keep that in mind").
"""

import re

# Verbs that imply concrete external action (a tool call should follow).
# Excluded on purpose: think, consider, remember, note, keep, mind — those
# don't promise external action.
_ACTION_VERBS = (
    r"fetch(?:ing)?|"
    r"pull(?:ing)?|"
    r"grab(?:bing)?|"
    r"research(?:ing)?|"
    r"look(?:ing)?\s+up|"
    r"lookup|"
    r"put(?:ting)?\s+together|"
    r"compil(?:e|ing)|"
    r"gather(?:ing)?|"
    r"get(?:ting)?\b|"
    r"find(?:ing)?|"
    r"hit(?:ting)?\b|"
    r"check(?:ing)?|"
    r"search(?:ing)?|"
    r"open(?:ing)?\b|"
    r"send(?:ing)?\b|"
    r"draft(?:ing)?\b|"
    r"book(?:ing)?\b|"
    r"build(?:ing)?\b|"
    r"download(?:ing)?\b|"
    r"compar(?:e|ing)\b|"
    r"summari[sz](?:e|ing)\b"
)

# "I'll fetch / I will pull / I'm gonna grab / I'm fetching / Hold on, I'm pulling"
# Optional intent verb between modal and action ("I'll go pull",
# "I'll just fetch", "I'll quickly gather") — kept short to avoid
# matching unrelated content.
_FILLER = r"(?:go(?:nna)?|just|quickly|first|now)\s+"

_PROMISE_PATTERNS = [
    re.compile(
        rf"\bI(?:'ll|\s+will|\s+am\s+gonna|'m\s+gonna|m\s+gonna)\s+(?:{_FILLER})?(?:{_ACTION_VERBS})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\bI'?m\s+(?:{_ACTION_VERBS})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\bhold\s+(?:on|up|tight)[,\s].{{0,40}}\bI'?m\s+(?:{_ACTION_VERBS})",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        rf"\b(?:hold\s+on|gimme\s+a\s+(?:sec|minute|moment))[,\.\s]+I'?(?:ll|m)\s+(?:{_FILLER})?(?:{_ACTION_VERBS})",
        re.IGNORECASE,
    ),
]


# Background / in-progress claims — the model says work is ALREADY happening
# ("I've queued a fresh run", "running in the background", "this'll take a few
# minutes", "working on it"). These are the sneakiest lies: they imply action
# is underway when nothing fired. This family caught us out on "try again →
# I've queued a fresh run".
_BG_CLAIM_PATTERNS = [
    re.compile(r"\b(?:I'?ve|I have|just)\s+(?:queued|kicked\s+off|started|begun|launched|initiated|fired\s+off|set\s+up|spun\s+up|re-?run|re-?queued)\b", re.I),
    re.compile(r"\b(?:queued|kicked\s+off|launched|started)\s+(?:a\s+|another\s+|the\s+|fresh\s+|new\s+)?(?:run|check|search|task|job|investigation|background)\b", re.I),
    re.compile(r"\b(?:running|processing|working\s+on|pulling\s+up|digging\s+into|looking\s+into)\s+(?:it|this|that|the\b)", re.I),
    re.compile(r"\b(?:in|running\s+in)\s+the\s+background\b", re.I),
    re.compile(r"\bthis(?:'ll| will| might| may| could| should)?\s+take\s+(?:a\s+)?(?:few|couple|several|\d+)\s*(?:more\s+)?(?:second|sec|minute|min|moment|hour)s?\b", re.I),
    re.compile(r"\b(?:on\s+it|already\s+on\s+it|i'?m\s+on\s+it)\b", re.I),
    re.compile(r"\b(?:give|gimme)\s+me?\s+a\s+(?:sec|second|minute|moment|min)\b.{0,30}\b(?:while|as)\s+I\b", re.I),
    re.compile(r"\blet\s+me\s+(?:run|kick\s+off|re-?run|fire\s+off|start|launch|dig|pull)\b", re.I),
    re.compile(r"\bI'?ll\s+(?:hit|ping|let|holler\s+at|message|text|update)\s+you\s+(?:when|once|after|as\s+soon)\b", re.I),
]


# Completion claims — the model says work is ALREADY DONE ("Message sent via
# Telegram", "I've sent it", "done, emailed it", "it's on its way"). The
# sneakiest lie of all: it claims success. Paired with the ground-truth check
# (0 agents ran this turn) this is a dead giveaway. This is the family that
# slipped through on "E do. Message sent via Telegram."
_DONE_CLAIM_PATTERNS = [
    re.compile(r"\b(?:message|text|doc|document|report|file|note)\s+(?:has\s+been\s+|is\s+)?sent\b", re.I),
    re.compile(r"\b(?:I'?ve|I\s+have|just)\s+(?:sent|texted|emailed|messaged|posted|shared|delivered|forwarded|dropped|fired\s+off)\b", re.I),
    re.compile(r"\b(?:sent|delivered|posted|shared|emailed|texted|forwarded)\s+(?:it|that|the|them|to\s+you|via|on\s+telegram|to\s+your)\b", re.I),
    re.compile(r"\b(?:done|all\s+set|all\s+done)[,.\s]+(?:sent|texted|emailed|messaged|posted|shared|delivered)\b", re.I),
    re.compile(r"\bit'?s\s+(?:on\s+its\s+way|been\s+sent|done|delivered)\b", re.I),
    re.compile(r"\b(?:message|doc|report|file|note)\s+sent\s+(?:via|on|through|to)\b", re.I),
    re.compile(r"\bsent\s+(?:it\s+)?(?:via|on|through)\s+(?:telegram|whatsapp|sms|email|imessage)\b", re.I),
]


def detect_promise(text: str) -> str | None:
    """Return the matched action-claim span, or None.

    Three families count as a claim of action that should be backed by a real
    tool/agent run:
      1. Immediate intent — "I'll fetch the specs", "I'm pulling the prices".
      2. Background/in-progress — "I've queued a fresh run", "running in the
         background", "this'll take a few minutes", "working on it".
      3. Completion — "Message sent via Telegram", "I've emailed it", "done,
         sent it", "it's on its way".
    If a turn contains any but fired no tools, the system has lied and should
    escalate to actually do the work.
    """
    if not text or len(text) < 8:
        return None
    for family in (_PROMISE_PATTERNS, _BG_CLAIM_PATTERNS, _DONE_CLAIM_PATTERNS):
        for pat in family:
            m = pat.search(text)
            if m:
                return m.group(0)
    return None


# Confirmation phrases — broader than "yes/yeah/ok". Used for re-dispatching
# to last_agent (or pending promise) when the user gives a green light.
_CONFIRMATION_RE = re.compile(
    r"^(?:"
    r"yes|yeah|yep|yh|ye|yea|"
    r"go\s+ahead(?:\s+and\s+(?:do|fetch|pull|get|run|build|find)\s+it)?|"
    r"do\s+(?:that|it|so)|"
    r"yh\s+do\s+(?:that|it)|"
    r"yeah?\s+do\s+(?:that|it)|"
    r"sure(?:\s+(?:do|go|thing))?|"
    r"ok|okay|kk|"
    r"please(?:\s+do)?|"
    r"proceed|"
    r"bet|say\s+less|aight|ight|"
    r"fetch\s+it|pull\s+it|get\s+it|find\s+it|"
    r"go\s+for\s+it|run\s+it|"
    r"try\s+again|retry|run\s+it\s+again|do\s+it\s+again|"
    r"(?:go|run|try)\s+(?:it\s+)?again|once\s+more|"
    r"can\s+you\s+(?:do|fetch|pull|get|run|find)\s+(?:it|that)|"
    r"can\s+you|"
    r"plz|pls"
    r")\s*[.!?]*$"
)


def is_confirmation(text: str) -> bool:
    """Broad confirmation matcher. Used to re-dispatch on green-light replies."""
    if not text:
        return False
    return bool(_CONFIRMATION_RE.match(text.strip().lower()))
