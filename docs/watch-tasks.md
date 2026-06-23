# Standing Orders / Watch Tasks

FRIDAY's autonomous background reply system. One of the two things the heartbeat
does (the other being zero-LLM static checks for email, calendar, morning
briefing). Watch tasks are the *dynamic* half — conversational standing orders
the user gives, persisted in SQLite, ticked every 30 seconds by the heartbeat,
and allowed to read, reason, and reply without further prompting.

Source:
- [`friday/background/heartbeat.py`](../friday/background/heartbeat.py) — the
  executor, classifier, and per-type handlers
- [`friday/tools/watch_tools.py`](../friday/tools/watch_tools.py) — the three
  tools the LLM calls to create, list, and cancel
- [`friday/memory/store.py`](../friday/memory/store.py) — `watch_tasks` table
- [`friday/core/setup_wizard.py`](../friday/core/setup_wizard.py) —
  `friday heartbeat` status command
- [`friday/cli.py`](../friday/cli.py) — the `/clearwatches` slash command

---

## 1. What a watch task is

A **watch task** (a.k.a. standing order) is a persistent instruction in natural
language that the heartbeat loop executes on a schedule until it expires or is
cancelled. Unlike a one-shot command — "read messages from Mom" returns right
now and stops — a watch task keeps running in the background, deciding on each
tick whether anything has changed and whether a response is warranted.

The problem it solves: one-shot tool calls require the user to be present and
ask. Watch tasks let the user leave the loop entirely. "Watch Mom's messages
for the next hour, reply as me if she texts" sets up autonomous behaviour —
FRIDAY polls iMessage, recognises new inbound messages, drafts a reply in the
user's voice, sends it, and logs the action.

Contrast this with fast-path tool calls that return-and-forget. Watch tasks are
the *autonomy layer*: FRIDAY deciding when to act without being asked each time.

---

## 2. Supported watch targets

The heartbeat classifies each instruction the moment it runs, using keyword
heuristics in `_classify_watch_type`. The full set:

| Type           | Detected by                                                     | Default interval |
| -------------- | --------------------------------------------------------------- | ---------------- |
| `imessage`     | default (no other keywords match)                               | 60s              |
| `whatsapp`     | "whatsapp", "whats app", "wa message"                           | 60s              |
| `email`        | "email", "emails", "inbox", "gmail", "mail"                     | 300s (5 min)     |
| `calls`        | "missed call", "call log", "calls from"                         | 120s             |
| `url`          | any `https://...`, "web page", "website changes"                | 7200s (2 hours)  |
| `search`       | "search for", "news about", "updates on", "trending", ...       | 900s (15 min)    |
| `topic`        | "topic", "space", "field", "industry", "sector", "market"       | 900s             |
| `browser`      | "linkedin", "open browser", "notifications on"                  | 3600s (1 hour)   |
| `notifications`| "mac notification", "system notification", "notification center" | — (stub)        |

This document focuses on the four watch targets the user asked about: iMessage,
WhatsApp, self-chat mode, and URL/page monitoring.

### iMessage contact watch

Directly reads the user's Messages database (via `read_imessages`) and replies
through `send_imessage`. The instruction is scanned by `_extract_contact` to
pull the contact name. Example instructions:

- "watch messages from Mom, reply like me if she texts"
- "keep an eye on partner's texts for the next 2 hours"
- "check new messages from a contact and respond naturally"

On each tick the executor (`_execute_imessage_watch`) reads the last 5 messages,
fingerprints the newest one as `"{date}|{first 100 chars of text}"`, compares
to `last_state`, and only runs the LLM if the fingerprint changed AND the
newest message is inbound (not sent by the user) OR the user explicitly tagged
FRIDAY with `@friday`.

### WhatsApp contact watch

Identical pattern, routed through `_execute_whatsapp_watch`, which calls the
Baileys-backed `read_whatsapp` / `send_whatsapp` tools. Same contact
extraction, same fingerprint comparison, same LLM reply drafting. The only
differences: the identity system prompt is shorter (no tag-awareness or reveal
modes yet — WhatsApp watches only reply AS the user), and it skips
early if `newest.from_me` or `direction == "sent"`.

WhatsApp setup is covered separately in [whatsapp-setup.md](./whatsapp-setup.md).

### Self-chat mode (remote control via iMessage)

A special mode of the iMessage watcher. Triggered when the instruction contains
any of: `"my own"`, `"remote control"`, `"command to friday"`, `"text myself"`,
`"messages to self"`, `"messages from me"`.

When those phrases are present, `_execute_imessage_watch` hands off to
`_execute_self_chat_watch`. The contact defaults to the user's own configured
name (from `~/.friday/user.json`). Any new message the user sends to themselves
is treated as a **command**, piped through the full `FridayCore` orchestrator,
and the result is sent back prefixed with `"FRIDAY: "`.

This is how the user drives FRIDAY from their phone when away from the Mac —
text yourself "check my inbox", FRIDAY executes, texts back the answer.

Loop protection: self-chat ignores any message where the first 15 characters
(case-insensitive) contain `"friday:"` — those are FRIDAY's own replies.

### URL / page change monitoring — and why it's NOT the same as `create_monitor`

Watch tasks and **monitors** sound similar but are separate systems:

- **Watch tasks** (`create_watch`) — heartbeat-driven, one SQLite table
  (`watch_tasks`), handles *everything* including URL/search/topic via
  `_execute_web_watch`.
- **Monitors** (`create_monitor` in [`friday/tools/monitor_tools.py`](../friday/tools/monitor_tools.py))
  — older, richer system with its own `monitors` and `monitor_events` tables,
  keyword-based materiality filter, importance levels (critical/high/normal),
  and a `briefing_queue` that feeds the morning briefing.

The two overlap. As the code comment notes:
> Replaces the old monitor_scheduler. Same logic: Fetch content ... Hash and
> compare against last_state ... If changed, extract diff, check materiality, notify.

New URL/search/topic work tends to go through watch tasks now because they're
simpler and uniformly handled. Monitors still exist for the briefing-queue
workflow (structured alerts with importance + history). Use `create_monitor`
when you want the alert to go through the briefing pipeline; use `create_watch`
for everything else.

---

## 3. Lifecycle — create → persist → tick → reply

```
┌───────────────────────────────────────────────────────────────┐
│ 1. LLM calls create_watch("watch Mom's texts, reply as me")   │
│    → insert row into watch_tasks (id, instruction, interval,  │
│                                   expires_at, active=1)       │
└───────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌───────────────────────────────────────────────────────────────┐
│ 2. Heartbeat's _watch_tick runs every 30s                     │
│    → expires stale rows (expires_at < now AND NOT NULL)       │
│    → SELECT active=1 tasks; skip if not due yet               │
│    → UPDATE last_check=now BEFORE running (no double-fire)    │
└───────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌───────────────────────────────────────────────────────────────┐
│ 3. _classify_watch_type routes to the right executor:         │
│    imessage / whatsapp / email / calls / url / search / …     │
└───────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌───────────────────────────────────────────────────────────────┐
│ 4. Executor reads target, computes fingerprint, compares to   │
│    last_state. First tick sets baseline and returns.          │
└───────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌───────────────────────────────────────────────────────────────┐
│ 5. If changed: ONE LLM call drafts a reply (or NO_REPLY).     │
│    If reply → send → UPDATE last_state = new fingerprint.     │
└───────────────────────────────────────────────────────────────┘
```

### The `watch_tasks` table

Defined in [`friday/memory/store.py`](../friday/memory/store.py):

```sql
CREATE TABLE IF NOT EXISTS watch_tasks (
    id TEXT PRIMARY KEY,
    instruction TEXT NOT NULL,
    interval_seconds INTEGER NOT NULL DEFAULT 60,
    expires_at TEXT,               -- NULL = persistent
    last_check TEXT,
    last_state TEXT,               -- fingerprint OR JSON {hash, content}
    active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_watch_tasks_active ON watch_tasks(active);
```

`last_state` is a free-form string. For message watches it's
`"{date}|{first 100 chars}"`. For web watches it's a JSON blob
`{"hash": "...", "content": "..."}` so the diff engine can do unified-diff
against the previous content.

Deduplication: `create_watch` scans existing active rows. If a new watch
targets the same contact (for message watches) or same URL/query (for web
watches), the existing row is **updated** rather than duplicated. This prevents
stacking multiple watches on the same contact when the user issues near-
identical instructions.

---

## 4. The LLM call that drafts replies

Single `cloud_chat` call per trigger, capped at 150 tokens. The system prompt
composes four things:

1. **User identity** pulled from `~/.friday/user.json` via `user_config.USER`.
   `_user_name()` and `_user_possessive()` give the user's display name and the
   possessive form ("Travis" / "Travis's"). Falls back to `"the user"`.
2. **The standing order itself** (`task["instruction"]`), so the LLM knows why
   it's drafting this reply.
3. **The last 20 messages** of the conversation with the contact, formatted as
   `NAME: text\nNAME: text\n...`. The user's lines use their name in caps; the
   contact's lines use the contact name in caps.
4. **The identity rule** — the single most important switch — below.

### Identity switching — reply AS user, or reply AS FRIDAY

This is the `identity_rule` block around line 543 of `heartbeat.py`:

```python
if identify_as_friday or friday_mode or tagged_by_user:
    identity_rule = f"""You are FRIDAY, {user_possessive} AI. Reply as yourself — prefix with "FRIDAY: ".
- If {user_name} tagged you in a message (e.g. "Friday, am I lying?", "Friday what do you think?", "Friday tell them"), you MUST reply. Address BOTH what the other person said AND what {user_name} said. Back {user_name} up. Be their ride-or-die AI.
- If the person addressed you directly (e.g. "Friday stop replying", "Friday please"), respond to what THEY said. Respect their request.
- If they say "stop replying" or "stop texting" — say something like "FRIDAY: Fair enough, I'll let {user_name} know you want them. They're busy building me right now but I'll pass it on." Then the message is done.
- If they want {user_name} ("where is {user_name}", "tell them to call me") — say they're busy building you (FRIDAY) right now, but you'll let them know.
- If {user_name} introduced you, be warm and introduce yourself naturally.
- Be confident, real, a bit witty. You're not a generic AI — you're FRIDAY."""
else:
    identity_rule = f"Reply AS {user_name}. You ARE {user_name} in this conversation. Never mention FRIDAY or AI."
```

Three independent conditions trigger FRIDAY-as-itself mode:

- **`identify_as_friday`** — the instruction itself contains any of:
  `"as friday"`, `"let them know its you"`, `"identify as friday"`,
  `"say its friday"`. The user explicitly set the watch to out FRIDAY from the
  start.
- **`friday_mode`** — the conversation history reveals that FRIDAY is already
  known to the other party. Matched phrases: `"called friday"`, `"named friday"`,
  `"it's friday"`, `"meet friday"`, `"this is friday"`, `"my ai"`,
  `"ai i built"`, `"ai assistant"`, `"ai operating system"`. Or the other
  person has said the word "friday" themselves — which means they already
  know.
- **`tagged_by_user`** — the most recent message in the thread is from the
  user, isn't FRIDAY's own reply, and contains `@friday`. See below.

If *none* of those fire, the LLM impersonates the user — matches their texting
vibe, never mentions AI, just texts like them.

### Deflection rules (when replying AS the user)

Pulled verbatim from the system prompt so FRIDAY doesn't make commitments on
the user's behalf:

- Never agree to phone or video calls. Deflect — "I'm not available right now,
  I'll let them know".
- Never agree to send money or spend money. "I'll pass that on to {user}".
- Never agree to go somewhere or make plans. Deflect — "{user} isn't available
  right now".
- Never say "{user} mentioned X" or "{user} told me X" — the user is
  inactive, they can't have told FRIDAY anything. FRIDAY monitors, tracks, and
  detects things independently.

These exist because the LLM, left alone, will happily make plans on the user's
behalf. The prompt hard-codes the refusal path.

---

## 5. `@friday` tagging — summoning FRIDAY mid-thread

Mechanism: when the newest message in a watched thread is **outbound** (from
the user), the executor inspects it:

```python
low = newest_text.lower().strip()
is_friday_own_reply = "friday:" in low[:15]  # first 15 chars
is_user_tag = not is_friday_own_reply and "@friday" in low
```

If the user's message contains `@friday` anywhere, `tagged_by_user = True`.
This forces:

- `identity_rule` to FRIDAY-reveal mode
- The LLM prompt to treat this as a MUST-reply (no `NO_REPLY` allowed)
- The LLM to address both the contact and the user's tag

This lets the user actively drive their own conversations from inside: "hey
@friday, when's our flight?" in a thread with a friend will pull FRIDAY in
to answer, without ending the watch or needing a separate command.

The 15-character check on `friday:` is a loop-breaker: FRIDAY's own sent
messages begin with `FRIDAY:` (sometimes with a stray leading char from
`chat.db` rendering, so the check is permissive). Those are skipped so FRIDAY
doesn't reply to itself.

---

## 6. NO_REPLY — when FRIDAY stays quiet

The LLM is asked to **reason first** about whether the incoming message
warrants a reply at all. From the prompt:

> Some messages are conversation-enders or acknowledgements that don't need a
> response: "Okay", "Ok", "Alright", "Cool", "Sure", "Lol", "Haha", thumbs up,
> single emoji reactions. Statements that close a topic with no question or
> prompt. Messages where replying would be awkward or forced.
>
> If the message does NOT need a reply, respond with exactly: NO_REPLY

When the LLM returns `NO_REPLY` (or an empty/near-empty response), the
executor logs "LLM says no reply needed", **still updates `last_state`** (so
the same message isn't re-evaluated next tick), and returns without sending.

One forced exception: if `tagged_by_user` is True, the prompt overrides:
`"EXCEPTION: If {user_name} tagged FRIDAY in their message, you ALWAYS reply.
No skipping."`

---

## 7. Safety

### Privacy isolation per conversation

The system prompt ends with a hard rule:

> PRIVACY: This conversation is COMPLETELY isolated. NEVER mention other people
> {user_name} is texting, other conversations, or that you are monitoring
> anyone else's messages. You only know about THIS conversation with {contact}.
> No names, no hints, no "I'm also talking to…". Each person's conversation is
> their own.

Each tick only reads the 20 most recent messages for *that* contact. Nothing
about other threads enters the LLM context. The watch_tasks table does contain
the whole list of active watches, but that's only used by the scheduler, never
by the reply-drafting LLM call.

### Attachment skipping

If the newest message body is wrapped in square brackets — `[photo]`,
`[video]`, `[voice message]`, `[sticker]`, `[attachment]` — the executor
updates `last_state` and returns silently. FRIDAY doesn't try to reply to
things it can't see.

### FRIDAY-reply detection (loop prevention)

Two overlapping guards:

1. In `_execute_imessage_watch`, when the newest message is outbound, the
   first 15 characters are checked for `"friday:"`. Matches are treated as
   FRIDAY's own replies — skipped.
2. In `_execute_self_chat_watch`, messages starting with `"friday:"` (but
   NOT `@friday`) are explicitly filtered.

Without these, a self-chat loop ("FRIDAY: done" → FRIDAY re-reads its own
message → responds to itself → ...) would run away within seconds.

### Send confirmation

Every `send_imessage` / `send_whatsapp` call is made with `confirm=True`.
That flag is a tool-level safety check.

---

## 8. The three tools exposed to agents

From [`friday/tools/watch_tools.py`](../friday/tools/watch_tools.py):

### `create_watch(instruction, interval_seconds=60, duration_minutes=0)`

- **`instruction`** (string, required) — the full standing order in natural
  language. Contains what to watch, what to reply with, any identity hints.
- **`interval_seconds`** (int, default 60) — how often the executor runs for
  this task. Minimum 30. If left at default, `create_watch` auto-picks a
  smart interval based on the classified type (URL → 7200s, search → 900s,
  etc.)
- **`duration_minutes`** (int, default 0) — how long before the watch
  auto-expires. `0` = persistent (no `expires_at`, runs until manually
  cancelled).

Returns `{id, instruction, interval_seconds, expires_at, persistent,
duration_minutes, [updated]}`. The `updated` key is present when the call
updated an existing watch for the same target instead of creating a new row.

### `list_watches()`

No args. Returns a list of dicts, one per active row.

### `cancel_watch(task_id)`

- **`task_id`** (string, required) — the 8-char UUID prefix returned by
  `create_watch`.

Sets `active = 0` on the row (soft delete). The heartbeat's next tick won't
pick it up.

---

## 9. CLI surface

### `/clearwatches` (inside the REPL)

One-shot nuke. From [`friday/cli.py`](../friday/cli.py):

```python
if user_input == "/clearwatches":
    from friday.memory.store import get_memory_store
    db = get_memory_store().db
    count = db.execute("SELECT COUNT(*) FROM watch_tasks WHERE active = 1").fetchone()[0]
    db.execute("UPDATE watch_tasks SET active = 0 WHERE active = 1")
    db.commit()
    console.print(f":: Cleared {count} active watch task(s)")
```

Sets every active watch to inactive. Useful when you've lost track of what's
running, or before running tests.

### `friday heartbeat` (shell command)

Shows heartbeat status + active watches. From `setup_wizard.heartbeat()`:

- A short explainer of the two heartbeat jobs (silent checks + watch tasks)
- Location of `HEARTBEAT.md` (interval, quiet hours, daily cap)
- A bulleted list of active watches with their intervals

Example output excerpt:

```
Active watch tasks:
  · watch Mom's messages, reply as me if she texts   every 60s
  · monitor emails from stripe.com, notify on new    every 300s
```

---

## 10. Intervals and durations

Two orthogonal axes: **how often** (`interval_seconds`) and **how long**
(`duration_minutes`).

**Interval** — seconds between ticks for *this specific* task. The heartbeat
scheduler runs every 30s and checks each task's `last_check` against its
interval. `interval_seconds=60` means "every minute". Smart defaults kick in
when the caller passes the default 60:

```python
_SMART_INTERVALS = {
    "search": 900,     # 15 min — news moves fast
    "topic": 900,
    "url": 7200,       # 2 hours — pages change less often
    "email": 300,
    "whatsapp": 60,
    "imessage": 60,
    "calls": 120,
    "browser": 3600,
}
```

**Duration** — minutes until `expires_at`. `0` means persistent (stored as
`NULL`). The `_watch_tick` expiry step:

```python
db.execute("UPDATE watch_tasks SET active = 0 WHERE active = 1 AND expires_at IS NOT NULL AND expires_at < ?", (now.isoformat(),))
```

Note `expires_at IS NOT NULL` — persistent watches never expire via this
query, only via `cancel_watch` or `/clearwatches`.

Typical combinations:

| Use case                           | interval | duration |
| ---------------------------------- | -------- | -------- |
| Reply to Mom for the next hour     | 60       | 60       |
| Always watch partner's texts       | 60       | 0        |
| Ping me on shipping emails, ever   | 300      | 0        |
| Watch a release page this week     | 7200     | 10080    |
| Track AI news forever              | 900      | 0        |

---

## 11. Example instructions

Real standing orders. Each shows what the user says, what FRIDAY creates, and
how it behaves.

**"Watch Mom's messages for the next hour, reply as me if she texts."**
- Type: `imessage` (default classification)
- Contact: `"mom"` (from `_extract_contact`)
- Interval: 60s, duration: 60 minutes
- Behaviour: impersonates the user, NO_REPLY on acknowledgements, deflects
  calls/money/plans.

**"Keep an eye on my partner's texts — if they ask when I'll be home say I'm in meetings."**
- Type: `imessage`, contact `"partner"`
- Interval: 60s, persistent
- Behaviour: same identity logic. The "if they ask when I'll be home" hint
  feeds into the system prompt via the instruction field.

**"Watch WhatsApp from my brother, reply like me if he sends anything."**
- Type: `whatsapp`, contact `"brother"`
- Routes to `_execute_whatsapp_watch`. Reply-AS-user identity by default
  (the WhatsApp executor has a simpler prompt with no tag/friday-mode path).

**"Start remote control mode — text myself and treat those as FRIDAY commands."**
- Contains `"text myself"` → self-chat mode
- Contact defaults to the user's own name from `user.json`
- Routes to `_execute_self_chat_watch`. Every new outbound self-message
  (that isn't prefixed `FRIDAY:`) becomes a FRIDAY command, processed by the
  orchestrator, replied to with `FRIDAY: {result}`.

**"Watch https://example.com/releases for new entries."**
- Type: `url` (explicit URL)
- Default interval: 7200s (2 hours)
- Routes to `_execute_web_watch` → fetches page, SHA-256 hashes first 2000
  chars, diffs on change, sends an LLM-summarised notification.

**"Search for Anthropic news daily and alert me on major announcements."**
- Type: `search`
- Default interval: 900s
- Target extracted as `"anthropic news"` after stripping the noise words
  (`search for`, `daily`, `alert me on`).

**"Watch my emails, notify me if anything from Stripe comes in."**
- Type: `email`, interval 300s, persistent
- Routes to `_execute_email_watch`. Parses sender filter from the instruction
  ("from Stripe"), compares the last 5 email IDs against `last_state`, sends
  a notification per new matching email (max 3 per tick).

**"Watch LinkedIn for new notifications."**
- Type: `browser`
- Hard-coded URL `https://www.linkedin.com/notifications/`
- Interval: 3600s. Uses `browser_navigate` + `browser_get_text` + hash
  comparison + LLM summary.

**"@friday what do you think about this?"** (sent by the user, mid-thread,
inside a watched iMessage conversation)
- Not itself a watch creation — this is a live trigger. The active iMessage
  watch on that contact sees the outbound message, detects `@friday`,
  switches identity to FRIDAY-as-itself, forces a reply.
