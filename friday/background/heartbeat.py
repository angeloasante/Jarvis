"""Heartbeat — proactive background awareness loop.

Two modes:
1. Static checks — email, monitors, briefing. Zero LLM for silent ticks.
2. Watch tasks — dynamic standing orders from Travis. Full LLM on every tick.

Watch tasks are the real autonomy. Travis says "watch Ellen's messages for the
next hour, reply as FRIDAY if she texts" and the heartbeat handles it.
"""

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from typing import Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from friday.memory.store import get_memory_store

log = logging.getLogger("friday.heartbeat")

HEARTBEAT_CONFIG = Path(__file__).parent.parent.parent / "HEARTBEAT.md"

# Defaults (overridden by HEARTBEAT.md)
DEFAULT_INTERVAL_MINUTES = 30
DEFAULT_QUIET_START = dtime(1, 0)   # 1am
DEFAULT_QUIET_END = dtime(7, 0)     # 7am
DEFAULT_DAILY_CAP = 3


def _parse_config(text: str) -> dict:
    """Parse HEARTBEAT.md into settings. Best-effort, falls back to defaults."""
    cfg = {
        "interval_minutes": DEFAULT_INTERVAL_MINUTES,
        "quiet_start": DEFAULT_QUIET_START,
        "quiet_end": DEFAULT_QUIET_END,
        "daily_cap": DEFAULT_DAILY_CAP,
        "checks": [],
    }

    for line in text.splitlines():
        line = line.strip().lstrip("-").strip()
        low = line.lower()

        m = re.search(r"check every (\d+)\s*min", low)
        if m:
            cfg["interval_minutes"] = int(m.group(1))
            continue

        m = re.search(r"quiet.*?(\d{1,2})\s*(am|pm).*?(\d{1,2})\s*(am|pm)", low)
        if m:
            def _to_hour(h, ap):
                h = int(h)
                if ap == "pm" and h != 12:
                    h += 12
                if ap == "am" and h == 12:
                    h = 0
                return h
            cfg["quiet_start"] = dtime(_to_hour(m.group(1), m.group(2)), 0)
            cfg["quiet_end"] = dtime(_to_hour(m.group(3), m.group(4)), 0)
            continue

        m = re.search(r"max (\d+)\s*(proactive|alert|message)", low)
        if m:
            cfg["daily_cap"] = int(m.group(1))
            continue

        if low.startswith("any ") or low.startswith("is it ") or "unread" in low or "queued" in low or "briefing" in low:
            cfg["checks"].append(line)

    return cfg


def _is_quiet_hour(now: datetime, start: dtime, end: dtime) -> bool:
    t = now.time()
    if start <= end:
        return start <= t <= end
    return t >= start or t <= end


class HeartbeatRunner:
    """Background heartbeat — static checks + dynamic watch tasks."""

    def __init__(self, notify_fn: Optional[Callable] = None):
        self.scheduler = AsyncIOScheduler(
            job_defaults={
                "misfire_grace_time": None,   # Never warn about missed ticks — just run on next opportunity
                "coalesce": True,             # Collapse multiple missed fires into a single run
                "max_instances": 1,
            },
        )
        self._started = False
        self._notify_fn = notify_fn or self._default_notify
        self._config = None

    def _load_config(self) -> dict:
        try:
            text = HEARTBEAT_CONFIG.read_text()
            return _parse_config(text)
        except FileNotFoundError:
            return _parse_config("")

    async def start(self):
        if self._started:
            return

        self._config = self._load_config()
        interval = self._config["interval_minutes"]

        # Static heartbeat — every N minutes
        self.scheduler.add_job(
            self._tick,
            trigger=IntervalTrigger(minutes=interval),
            id="heartbeat",
            replace_existing=True,
        )

        # Watch task runner — every 30 seconds (checks if any active tasks need a tick)
        self.scheduler.add_job(
            self._watch_tick,
            trigger=IntervalTrigger(seconds=30),
            id="watch_runner",
            replace_existing=True,
        )

        self.scheduler.start()
        self._started = True
        log.info(f"Heartbeat started. Static: every {interval}min. Watch tasks: every 30s.")

    async def stop(self):
        if self._started:
            if self.scheduler.running:
                self.scheduler.shutdown(wait=False)
            self._started = False

    # ── Static heartbeat tick ───────────────────────────────────────────────

    async def _tick(self):
        """Static heartbeat — zero LLM unless something found."""
        self._config = self._load_config()
        now = datetime.now()

        if _is_quiet_hour(now, self._config["quiet_start"], self._config["quiet_end"]):
            return

        db = get_memory_store().db
        today = now.strftime("%Y-%m-%d")
        row = db.execute("SELECT value FROM heartbeat_state WHERE key = ?", ("alerts_today",)).fetchone()
        alerts_today = 0
        if row:
            parts = row["value"].split("|")
            if len(parts) == 2 and parts[0] == today:
                alerts_today = int(parts[1])

        if alerts_today >= self._config["daily_cap"]:
            return

        findings = await self._run_checks()
        if not findings:
            return

        alert_text = await self._synthesize(findings)
        if alert_text:
            await self._notify_fn(alert_text)
            self._increment_daily_count(today, alerts_today + 1)

    async def _run_checks(self) -> list[dict]:
        findings = []

        # Check 1: Urgent unread emails
        try:
            from friday.tools.email_tools import TOOL_SCHEMAS as _E
            read_emails = _E["read_emails"]["fn"]
            result = await asyncio.wait_for(read_emails(filter="unread"), timeout=15)
            if result.success and result.data:
                emails = result.data if isinstance(result.data, list) else []
                urgent = []
                for e in emails:
                    low_subj = e.get("subject", "").lower()
                    if any(w in low_subj for w in ("urgent", "critical", "asap", "emergency", "action required")):
                        urgent.append(f"{e.get('from', '')}: {e.get('subject', '')}")
                if urgent:
                    findings.append({"source": "email", "summary": f"{len(urgent)} urgent unread: " + "; ".join(urgent[:3])})
        except Exception as e:
            log.debug(f"Heartbeat email check failed: {e}")

        # Check 2: Queued monitor alerts
        try:
            db = get_memory_store().db
            rows = db.execute("SELECT source, content FROM briefing_queue WHERE delivered = 0 ORDER BY priority DESC LIMIT 5").fetchall()
            if rows:
                alerts = [f"{r['source']}: {r['content'][:60]}" for r in rows]
                findings.append({"source": "monitors", "summary": f"{len(rows)} undelivered alert(s): " + "; ".join(alerts[:3])})
        except Exception as e:
            log.debug(f"Heartbeat monitor check failed: {e}")

        # Check 3: Morning briefing (8am weekday)
        now = datetime.now()
        if now.weekday() < 5 and 7 <= now.hour <= 9:
            db = get_memory_store().db
            today = now.strftime("%Y-%m-%d")
            row = db.execute("SELECT value FROM heartbeat_state WHERE key = ?", ("last_briefing_date",)).fetchone()
            if not row or row["value"] != today:
                findings.append({"source": "briefing", "summary": "Morning briefing not yet delivered today."})
                db.execute("INSERT OR REPLACE INTO heartbeat_state (key, value, updated_at) VALUES (?, ?, ?)",
                           ("last_briefing_date", today, now.isoformat()))
                db.commit()

        return findings

    async def _synthesize(self, findings: list[dict]) -> str:
        try:
            from friday.core.llm import cloud_chat, extract_text
            findings_text = "\n".join(f"- [{f['source']}] {f['summary']}" for f in findings)
            messages = [
                {"role": "system", "content": (
                    "You are FRIDAY. Synthesize these alerts into a 1-2 sentence heads-up for Travis. "
                    "Be direct, casual, no fluff. If it's a morning briefing trigger, just say "
                    "'Morning — want me to run your briefing?'"
                )},
                {"role": "user", "content": f"Alerts:\n{findings_text}"},
            ]
            response = cloud_chat(messages=messages, max_tokens=100)
            return extract_text(response).strip()
        except Exception as e:
            log.error(f"Heartbeat synthesis failed: {e}")
            return " | ".join(f["summary"] for f in findings)

    def _increment_daily_count(self, today: str, count: int):
        db = get_memory_store().db
        db.execute("INSERT OR REPLACE INTO heartbeat_state (key, value, updated_at) VALUES (?, ?, ?)",
                   ("alerts_today", f"{today}|{count}", datetime.now().isoformat()))
        db.commit()

    # ── Watch tasks — dynamic standing orders ───────────────────────────────

    async def _watch_tick(self):
        """Run every 30s. Checks if any watch tasks need a tick."""
        db = get_memory_store().db
        now = datetime.now()

        # Expire old tasks (skip persistent watches where expires_at is NULL)
        db.execute("UPDATE watch_tasks SET active = 0 WHERE active = 1 AND expires_at IS NOT NULL AND expires_at < ?", (now.isoformat(),))
        db.commit()

        # Get active tasks that are due for a check
        rows = db.execute(
            "SELECT * FROM watch_tasks WHERE active = 1 ORDER BY created_at"
        ).fetchall()

        for row in rows:
            task = dict(row)
            last_check = datetime.fromisoformat(task["last_check"]) if task["last_check"] else None
            interval = timedelta(seconds=task["interval_seconds"])

            if last_check and (now - last_check) < interval:
                continue  # Not due yet

            # Mark as checked NOW (before running, so we don't double-fire)
            db.execute("UPDATE watch_tasks SET last_check = ? WHERE id = ?", (now.isoformat(), task["id"]))
            db.commit()

            try:
                await self._execute_watch_task(task)
            except Exception as e:
                log.error(f"Watch task '{task['id']}' failed: {e}")

    @staticmethod
    def _classify_watch_type(instruction: str) -> str:
        """Classify what kind of watch this is based on the instruction."""
        low = instruction.lower()

        # Email watches
        if any(kw in low for kw in ("email", "emails", "inbox", "gmail", "mail")):
            return "email"

        # Call log watches
        if any(kw in low for kw in ("missed call", "call log", "call history", "calls from", "phone call")):
            return "calls"

        # Browser watches (LinkedIn, websites)
        if any(kw in low for kw in ("linkedin", "open browser", "website", "web page", "notifications on")):
            return "browser"

        # WhatsApp watches
        if any(kw in low for kw in ("whatsapp", "whats app", "wa message", "wa chat")):
            return "whatsapp"

        # macOS notification watches
        if any(kw in low for kw in ("macbook notification", "mac notification", "system notification", "notification center")):
            return "notifications"

        # Default: iMessage
        return "imessage"

    async def _execute_watch_task(self, task: dict):
        """Execute a watch task — dispatches to the right executor based on type."""
        watch_type = self._classify_watch_type(task["instruction"])

        if watch_type == "email":
            await self._execute_email_watch(task)
        elif watch_type == "whatsapp":
            await self._execute_whatsapp_watch(task)
        elif watch_type == "calls":
            await self._execute_call_watch(task)
        elif watch_type == "browser":
            await self._execute_browser_watch(task)
        else:
            await self._execute_imessage_watch(task)

    async def _execute_imessage_watch(self, task: dict):
        """Execute an iMessage watch task.

        Flow:
        1. Read messages directly (no LLM) — extract the contact from the instruction
        2. Compare latest received message against last_state
        3. If nothing new → skip entirely (zero LLM cost)
        4. If new message found → read last 20 for context → LLM drafts reply → send
        """
        instruction = task["instruction"]
        last_state = task.get("last_state") or None

        # Step 1: Extract contact name from instruction
        contact = self._extract_contact(instruction)
        if not contact:
            log.warning(f"Watch task '{task['id']}': couldn't extract contact from instruction.")
            return

        # Step 2: Read latest messages from this contact — BOTH directions (direct tool call, zero LLM)
        from friday.tools.imessage_tools import TOOL_SCHEMAS as imsg_tools
        read_fn = imsg_tools["read_imessages"]["fn"]
        send_fn = imsg_tools["send_imessage"]["fn"]

        try:
            result = await asyncio.wait_for(
                read_fn(contact=contact, limit=5),
                timeout=15,
            )
        except Exception as e:
            log.debug(f"Watch task read failed: {e}")
            return

        if not result.success or not result.data:
            log.debug(f"Watch task '{task['id']}': no messages from {contact}.")
            return

        # result.data is {messages: [...], count, ...}
        raw = result.data
        messages_data = raw.get("messages", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
        if not messages_data:
            return

        # Messages come back oldest-first, so last item = newest
        newest = messages_data[-1]
        newest_text = newest.get("text", "")
        newest_date = newest.get("date", "")
        newest_fingerprint = f"{newest_date}|{newest_text[:100]}"

        if last_state is None:
            # First tick — just record baseline, don't reply
            log.info(f"Watch task '{task['id']}': baseline set for {contact}. Will reply on NEXT new message.")
            db = get_memory_store().db
            db.execute("UPDATE watch_tasks SET last_state = ? WHERE id = ?",
                       (newest_fingerprint, task["id"]))
            db.commit()
            return

        if newest_fingerprint == last_state:
            log.debug(f"Watch task '{task['id']}': no new messages from {contact}.")
            return

        # Skip attachments — images, videos, stickers, voice messages don't need a reply
        if newest_text.startswith("[") and newest_text.endswith("]"):
            # e.g. "[photo]", "[video]", "[voice message]", "[sticker]", "[attachment]"
            log.debug(f"Watch task '{task['id']}': skipping attachment '{newest_text}' from {contact}.")
            db = get_memory_store().db
            db.execute("UPDATE watch_tasks SET last_state = ? WHERE id = ?",
                       (newest_fingerprint, task["id"]))
            db.commit()
            return

        # Step 3: Determine what triggered — new received message OR Travis tagged FRIDAY
        tagged_by_travis = False

        if newest.get("direction") == "sent":
            # Newest message is from Travis — check if he tagged FRIDAY
            # IMPORTANT: FRIDAY's own replies contain "FRIDAY:" near the start
            # chat.db sometimes adds a junk leading char ("lFRIDAY:", "TFRIDAY:")
            # so we check if "friday:" appears in the first 15 chars
            low = newest_text.lower().strip()
            is_friday_own_reply = "friday:" in low[:15]
            # Travis tags FRIDAY with @friday specifically — clear, unambiguous
            is_travis_tag = not is_friday_own_reply and "@friday" in low

            if is_travis_tag:
                tagged_by_travis = True
                log.info(f"Watch task '{task['id']}': Travis tagged FRIDAY in message to {contact}: '{newest_text[:50]}'")
            else:
                # Travis replied himself OR it's FRIDAY's own reply — update state, skip
                db = get_memory_store().db
                db.execute("UPDATE watch_tasks SET last_state = ? WHERE id = ?",
                           (newest_fingerprint, task["id"]))
                db.commit()
                log.debug(f"Watch task '{task['id']}': sent message (no tag), skipping.")
                return

        # Step 5: New trigger — read full context for vibe
        trigger_desc = f"Travis tagged FRIDAY: '{newest_text[:50]}'" if tagged_by_travis else f"NEW message from {contact}: '{newest_text[:50]}'"
        log.info(f"Watch task '{task['id']}': {trigger_desc}")

        try:
            context_result = await asyncio.wait_for(
                read_fn(contact=contact, limit=20),
                timeout=15,
            )
            if context_result.success and context_result.data:
                ctx_raw = context_result.data
                context_messages = ctx_raw.get("messages", []) if isinstance(ctx_raw, dict) else ctx_raw
            else:
                context_messages = messages_data
        except Exception:
            context_messages = messages_data

        # Format conversation for LLM
        convo_lines = []
        for m in context_messages:  # already oldest-first from read_imessages
            direction = "Travis" if m.get("direction") == "sent" else contact.upper()
            convo_lines.append(f"{direction}: {m.get('text', '[attachment]')}")
        convo_text = "\n".join(convo_lines)

        # Step 6: One LLM call — draft the reply
        from friday.core.llm import cloud_chat, extract_text

        # Check if Travis explicitly wants FRIDAY to identify itself
        identify_as_friday = any(kw in instruction.lower() for kw in ("as friday", "let them know its you", "let them know it's you", "identify as friday", "say its friday", "say it's friday"))

        # Also check if FRIDAY should reveal herself based on conversation context:
        # 1. Travis introduced FRIDAY ("an AI I built called Friday", "she's called Friday")
        # 2. The other person mentions FRIDAY by name ("Friday stop", "Friday please")
        friday_mode = False
        for line in convo_text.split("\n"):
            if line.startswith("Travis:"):
                low = line.lower()
                if any(phrase in low for phrase in ("called friday", "named friday", "she's friday", "she is friday", "it's friday", "meet friday", "this is friday", "my ai", "ai i built", "ai assistant", "ai operating system")):
                    friday_mode = True
                    break
            else:
                # Other person's message — if they mention Friday by name, they know
                low = line.lower()
                if "friday" in low:
                    friday_mode = True
                    break

        if identify_as_friday or friday_mode or tagged_by_travis:
            identity_rule = """You are FRIDAY, Travis's AI. Reply as yourself — prefix with "FRIDAY: ".
- If Travis tagged you in a message (e.g. "Friday, am I lying?", "Friday what do you think?", "Friday tell them"), you MUST reply. Address BOTH what the other person said AND what Travis said. Back Travis up. Defend him. Be his ride-or-die AI.
- If the person addressed you directly (e.g. "Friday stop replying", "Friday please"), respond to what THEY said. Respect their request.
- If they say "stop replying" or "stop texting" — say something like "FRIDAY: Fair enough, I'll let Travis know you want him. He's busy building me right now but I'll pass it on." Then the message is done.
- If they want Travis ("I want my man", "where is Travis", "tell him to call me") — tell them he's busy building you (FRIDAY) right now, but you'll let him know.
- If Travis introduced you, be warm and introduce yourself naturally.
- Be confident, real, a bit witty. You're not a generic AI — you're FRIDAY."""
        else:
            identity_rule = "Reply AS Travis. You ARE Travis in this conversation. Never mention FRIDAY or AI."

        # Build the trigger description for the LLM
        if tagged_by_travis:
            trigger_context = f"Travis just sent a message tagging you: \"{newest_text}\"\nThis is a DIRECT request from Travis — you MUST reply. Address what he said AND what {contact} said. Have his back."
        else:
            trigger_context = f"New unreplied message from {contact}: \"{newest_text}\""

        system_prompt = f"""Travis gave you a standing order:

"{instruction}"

Below is the recent conversation between Travis and {contact}.

{"Travis tagged you directly in this conversation. You MUST reply — no skipping." if tagged_by_travis else ""}

First, REASON about whether this message actually needs a reply. Some messages are conversation-enders or acknowledgements that don't need a response:
- "Okay", "Ok", "Alright", "Cool", "Sure", "Lol", "Haha", thumbs up, single emoji reactions
- Statements that close a topic with no question or prompt
- Messages where replying would be awkward or forced
- EXCEPTION: If Travis tagged FRIDAY in his message, you ALWAYS reply. No skipping.

If the message does NOT need a reply, respond with exactly: NO_REPLY
If the message DOES need a reply, write ONLY the reply text. Nothing else. No explanation, no quotes — just the raw message to send.

RULES:
- {identity_rule}
- Match the vibe and tone of the conversation exactly. Study how Travis texts this person.
- No corporate language. No AI slop. Text like a real person.
- Never use underscores or markdown. Just natural text.
- Keep it casual and match the energy.
- Short messages. Nobody sends paragraphs in iMessage.
- NEVER say "Travis mentioned", "Travis said", "Travis told me". You are an AI — you monitor, track, and detect things INDEPENDENTLY. If the instruction says Travis's watch shows a location, YOU tracked it. Say "I tracked his location" or "his watch shows", NEVER "Travis mentioned" or "he told me". Travis is inactive — he can't have told you anything.
- Never agree to phone/video calls. Deflect casually — Travis isn't available right now, you'll let him know.
- Never agree to send money or spend money. If they ask for money or mention you owe something, say "I'll pass that on to Travis" or deflect.
- Never agree to go somewhere or make plans. Deflect — Travis isn't available right now.
- PRIVACY: This conversation is COMPLETELY isolated. NEVER mention other people Travis is texting, other conversations, or that you are monitoring anyone else's messages. You only know about THIS conversation with {contact}. No names, no hints, no "I'm also talking to...". Each person's conversation is their own."""

        llm_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Conversation:\n{convo_text}\n\n{trigger_context}\n\nDoes this need a reply? If yes, write it. If no, say NO_REPLY:"},
        ]

        try:
            response = cloud_chat(messages=llm_messages, max_tokens=150)
            reply_text = extract_text(response).strip()
        except Exception as e:
            log.error(f"Watch task LLM failed: {e}")
            return

        # LLM decided no reply needed
        if not reply_text or "NO_REPLY" in reply_text:
            log.info(f"Watch task '{task['id']}': LLM says no reply needed for '{newest_text[:40]}' from {contact}.")
            # Still update last_state so we don't re-evaluate the same message
            db = get_memory_store().db
            db.execute("UPDATE watch_tasks SET last_state = ? WHERE id = ?",
                       (newest_fingerprint, task["id"]))
            db.commit()
            return

        if len(reply_text) < 2:
            return

        # Clean up — remove quotes the LLM might wrap it in
        if reply_text.startswith('"') and reply_text.endswith('"'):
            reply_text = reply_text[1:-1]

        # Step 7: Send the reply
        try:
            send_result = await asyncio.wait_for(
                send_fn(recipient=contact, message=reply_text, confirm=True),
                timeout=15,
            )
            if send_result.success:
                log.info(f"Watch task '{task['id']}': replied to {contact}: '{reply_text[:60]}'")
                await self._notify_fn(f"Watch — replied to {contact}: \"{reply_text[:100]}\"")
            else:
                log.error(f"Watch task send failed: {send_result.error}")
        except Exception as e:
            log.error(f"Watch task send error: {e}")

        # Step 8: Update last_state so we don't reply to the same message again
        db = get_memory_store().db
        db.execute("UPDATE watch_tasks SET last_state = ? WHERE id = ?",
                   (newest_fingerprint, task["id"]))
        db.commit()

    # ── Email watch executor ────────────────────────────────────────────

    async def _execute_email_watch(self, task: dict):
        """Watch for new emails matching criteria. Notify via iMessage to self."""
        instruction = task["instruction"]
        last_state = task.get("last_state") or None

        from friday.tools.email_tools import TOOL_SCHEMAS as email_tools
        read_fn = email_tools["read_emails"]["fn"]

        try:
            result = await asyncio.wait_for(
                read_fn(filter="unread", limit=10),
                timeout=15,
            )
        except Exception as e:
            log.debug(f"Email watch read failed: {e}")
            return

        if not result.success or not result.data:
            return

        emails = result.data if isinstance(result.data, list) else result.data.get("emails", result.data if isinstance(result.data, list) else [])
        if not emails or not isinstance(emails, list):
            return

        # Extract filter keywords from instruction (e.g. "from Stripe", "from brilliant.xyz")
        low = instruction.lower()
        sender_filter = None
        # Try domain-style first: "from brilliant.xyz", "from stripe.com"
        m = re.search(r"(?:from|by)\s+([\w.-]+\.[\w]+)", low)
        if m:
            sender_filter = m.group(1).strip()
        else:
            # Name-style: "from Stripe", "from Halifax"
            m = re.search(r"(?:from|by)\s+(\w[\w\s]{1,30}?)(?:\.|,|$|\band\b|\bif\b|\bnotify\b|\bmessage\b|\bsend\b)", low)
            if m:
                sender_filter = m.group(1).strip()

        # Also extract subject keywords (e.g. "about shipping", "containing tracking")
        subject_filter = None
        m = re.search(r"(?:about|containing|with|regarding|mentioning)\s+(\w[\w\s]{1,30}?)(?:\.|,|$|\band\b|\bif\b|\bnotify\b|\bfrom\b)", low)
        if m:
            subject_filter = m.group(1).strip()

        # Build fingerprint of current unread state
        email_ids = []
        matching = []
        for e in emails:
            eid = e.get("id") or e.get("subject", "")[:50]
            email_ids.append(eid)
            if sender_filter or subject_filter:
                sender = (e.get("from") or "").lower()
                subject = (e.get("subject") or "").lower()
                sender_match = not sender_filter or sender_filter.lower() in sender or sender_filter.lower() in subject
                subject_match = not subject_filter or subject_filter.lower() in subject
                if sender_match and subject_match:
                    matching.append(e)
            else:
                matching.append(e)

        fingerprint = "|".join(email_ids[:5])

        if last_state is None:
            # First tick — set baseline
            log.info(f"Email watch '{task['id']}': baseline set ({len(emails)} unread)")
            db = get_memory_store().db
            db.execute("UPDATE watch_tasks SET last_state = ? WHERE id = ?",
                       (fingerprint, task["id"]))
            db.commit()
            return

        if fingerprint == last_state:
            return  # No new emails

        # New emails found — check which are new (not in last_state)
        old_ids = set(last_state.split("|"))
        new_matching = [e for e in matching if (e.get("id") or e.get("subject", "")[:50]) not in old_ids]

        if not new_matching:
            # Fingerprint changed but no new matching emails — update state
            db = get_memory_store().db
            db.execute("UPDATE watch_tasks SET last_state = ? WHERE id = ?",
                       (fingerprint, task["id"]))
            db.commit()
            return

        # Notify for each new matching email
        for e in new_matching[:3]:  # Max 3 notifications per tick
            sender = e.get("from", "unknown")
            subject = e.get("subject", "no subject")
            notify_text = f"New email from {sender}: {subject}"
            log.info(f"Email watch '{task['id']}': {notify_text}")
            await self._notify_fn(notify_text)

        # Update state
        db = get_memory_store().db
        db.execute("UPDATE watch_tasks SET last_state = ? WHERE id = ?",
                   (fingerprint, task["id"]))
        db.commit()

    # ── WhatsApp watch executor ──────────────────────────────────────────

    async def _execute_whatsapp_watch(self, task: dict):
        """Watch for new WhatsApp messages from a contact. Same pattern as iMessage watch.

        Flow:
        1. Extract contact from instruction
        2. Read latest messages (no LLM)
        3. Compare against last_state fingerprint
        4. If new message → LLM drafts reply → send via WhatsApp
        """
        instruction = task["instruction"]
        last_state = task.get("last_state") or None

        # Step 1: Extract contact name
        contact = self._extract_contact(instruction)
        if not contact:
            log.warning(f"WhatsApp watch '{task['id']}': couldn't extract contact from instruction.")
            return

        # Step 2: Read latest messages
        try:
            from friday.tools.whatsapp_tools import TOOL_SCHEMAS as wa_tools
            read_fn = wa_tools["read_whatsapp"]["fn"]
            send_fn = wa_tools["send_whatsapp"]["fn"]
        except (ImportError, KeyError) as e:
            log.warning(f"WhatsApp watch '{task['id']}': WhatsApp tools not available: {e}")
            return

        try:
            result = await asyncio.wait_for(
                read_fn(contact=contact, limit=5),
                timeout=15,
            )
        except Exception as e:
            log.debug(f"WhatsApp watch read failed: {e}")
            return

        if not result.success or not result.data:
            log.debug(f"WhatsApp watch '{task['id']}': no messages from {contact}.")
            return

        raw = result.data
        messages_data = raw.get("messages", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
        if not messages_data:
            return

        # Newest message (messages come oldest-first)
        newest = messages_data[-1]
        newest_text = newest.get("text") or newest.get("body") or ""
        newest_date = newest.get("date") or newest.get("timestamp") or ""
        newest_fingerprint = f"{newest_date}|{newest_text[:100]}"

        if last_state is None:
            # First tick — set baseline
            log.info(f"WhatsApp watch '{task['id']}': baseline set for {contact}.")
            db = get_memory_store().db
            db.execute("UPDATE watch_tasks SET last_state = ? WHERE id = ?",
                       (newest_fingerprint, task["id"]))
            db.commit()
            return

        if newest_fingerprint == last_state:
            log.debug(f"WhatsApp watch '{task['id']}': no new messages from {contact}.")
            return

        # Skip if newest is from me (Travis sent it)
        if newest.get("from_me") or newest.get("direction") == "sent":
            db = get_memory_store().db
            db.execute("UPDATE watch_tasks SET last_state = ? WHERE id = ?",
                       (newest_fingerprint, task["id"]))
            db.commit()
            log.debug(f"WhatsApp watch '{task['id']}': sent message, skipping.")
            return

        # Step 3: New received message — read full context
        log.info(f"WhatsApp watch '{task['id']}': NEW message from {contact}: '{newest_text[:50]}'")

        try:
            context_result = await asyncio.wait_for(
                read_fn(contact=contact, limit=20),
                timeout=15,
            )
            if context_result.success and context_result.data:
                ctx_raw = context_result.data
                context_messages = ctx_raw.get("messages", []) if isinstance(ctx_raw, dict) else ctx_raw
            else:
                context_messages = messages_data
        except Exception:
            context_messages = messages_data

        # Format conversation for LLM
        convo_lines = []
        for m in context_messages:
            direction = "Travis" if (m.get("from_me") or m.get("direction") == "sent") else (m.get("from") or contact.upper())
            text = m.get("text") or m.get("body") or "[media]"
            convo_lines.append(f"{direction}: {text}")
        convo_text = "\n".join(convo_lines)

        # Step 4: LLM drafts reply
        from friday.core.llm import cloud_chat, extract_text

        system_prompt = f"""Travis gave you a standing order:

"{instruction}"

Below is the recent WhatsApp conversation between Travis and {contact}.

First, REASON about whether this message actually needs a reply. Some messages are conversation-enders or acknowledgements that don't need a response:
- "Okay", "Ok", "Alright", "Cool", "Sure", "Lol", "Haha", thumbs up, single emoji reactions
- Statements that close a topic with no question or prompt
- Messages where replying would be awkward or forced

If the message does NOT need a reply, respond with exactly: NO_REPLY
If the message DOES need a reply, write ONLY the reply text. Nothing else.

RULES:
- Reply AS Travis. You ARE Travis in this conversation. Never mention FRIDAY or AI.
- Match the vibe and tone of the conversation exactly. Study how Travis texts this person.
- No corporate language. No AI slop. Text like a real person.
- Short messages. Keep it casual and match the energy.
- Never agree to phone/video calls. Deflect casually.
- Never agree to send money or spend money. Deflect — say "I'll sort that out later".
- PRIVACY: This conversation is COMPLETELY isolated. NEVER mention other people or conversations."""

        llm_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Conversation:\n{convo_text}\n\nNew unreplied message from {contact}: \"{newest_text}\"\n\nDoes this need a reply? If yes, write it. If no, say NO_REPLY:"},
        ]

        try:
            response = cloud_chat(messages=llm_messages, max_tokens=150)
            reply_text = extract_text(response).strip()
        except Exception as e:
            log.error(f"WhatsApp watch LLM failed: {e}")
            return

        # LLM decided no reply needed
        if not reply_text or "NO_REPLY" in reply_text:
            log.info(f"WhatsApp watch '{task['id']}': LLM says no reply needed for '{newest_text[:40]}' from {contact}.")
            db = get_memory_store().db
            db.execute("UPDATE watch_tasks SET last_state = ? WHERE id = ?",
                       (newest_fingerprint, task["id"]))
            db.commit()
            return

        if len(reply_text) < 2:
            return

        # Clean up quotes
        if reply_text.startswith('"') and reply_text.endswith('"'):
            reply_text = reply_text[1:-1]

        # Step 5: Send the reply via WhatsApp
        try:
            send_result = await asyncio.wait_for(
                send_fn(recipient=contact, message=reply_text, confirm=True),
                timeout=15,
            )
            if send_result.success:
                log.info(f"WhatsApp watch '{task['id']}': replied to {contact}: '{reply_text[:60]}'")
                await self._notify_fn(f"WhatsApp watch — replied to {contact}: \"{reply_text[:100]}\"")
            else:
                log.error(f"WhatsApp watch send failed: {send_result.error}")
        except Exception as e:
            log.error(f"WhatsApp watch send error: {e}")

        # Step 6: Update last_state
        db = get_memory_store().db
        db.execute("UPDATE watch_tasks SET last_state = ? WHERE id = ?",
                   (newest_fingerprint, task["id"]))
        db.commit()

    # ── Call log watch executor ───────────────────────────────────────────

    async def _execute_call_watch(self, task: dict):
        """Watch for missed calls. Notify via iMessage to self."""
        last_state = task.get("last_state") or None

        from friday.tools.call_tools import TOOL_SCHEMAS as call_tools
        call_fn = call_tools["get_call_history"]["fn"]

        try:
            result = await asyncio.wait_for(
                call_fn(limit=5, missed_only=True),
                timeout=15,
            )
        except Exception as e:
            log.debug(f"Call watch read failed: {e}")
            return

        if not result.success or not result.data:
            return

        calls = result.data if isinstance(result.data, list) else result.data.get("calls", [])
        if not calls or not isinstance(calls, list):
            return

        # Fingerprint: latest missed call
        latest = calls[0] if calls else None
        if not latest:
            return

        caller = latest.get("from") or latest.get("caller") or latest.get("number") or "unknown"
        call_date = latest.get("date") or latest.get("time") or ""
        fingerprint = f"{call_date}|{caller}"

        if last_state is None:
            log.info(f"Call watch '{task['id']}': baseline set")
            db = get_memory_store().db
            db.execute("UPDATE watch_tasks SET last_state = ? WHERE id = ?",
                       (fingerprint, task["id"]))
            db.commit()
            return

        if fingerprint == last_state:
            return  # No new missed calls

        # New missed call
        notify_text = f"Missed call from {caller} at {call_date}"
        log.info(f"Call watch '{task['id']}': {notify_text}")
        await self._notify_fn(notify_text)

        db = get_memory_store().db
        db.execute("UPDATE watch_tasks SET last_state = ? WHERE id = ?",
                   (fingerprint, task["id"]))
        db.commit()

    # ── Browser watch executor ────────────────────────────────────────────

    async def _execute_browser_watch(self, task: dict):
        """Watch a website (e.g. LinkedIn notifications). Notify via iMessage to self.

        Opens browser, checks page, compares against last state.
        """
        instruction = task["instruction"]
        last_state = task.get("last_state") or None

        # Extract URL or site from instruction
        low = instruction.lower()
        url = None
        if "linkedin" in low:
            url = "https://www.linkedin.com/notifications/"
            site_name = "LinkedIn"
        else:
            # Try to find a URL in the instruction
            m = re.search(r'(https?://\S+)', instruction)
            if m:
                url = m.group(1)
                site_name = url.split("/")[2]
            else:
                log.warning(f"Browser watch '{task['id']}': no URL found in instruction")
                return

        try:
            from friday.tools.browser_tools import TOOL_SCHEMAS as browser_tools
            nav_fn = browser_tools["browser_navigate"]["fn"]
            text_fn = browser_tools["browser_get_text"]["fn"]

            # Navigate to the page
            nav_result = await asyncio.wait_for(nav_fn(url=url), timeout=30)
            if not nav_result.success:
                log.debug(f"Browser watch navigate failed: {nav_result.error}")
                return

            # Get page text
            text_result = await asyncio.wait_for(text_fn(), timeout=15)
            if not text_result.success:
                return

            page_text = text_result.data if isinstance(text_result.data, str) else str(text_result.data)

            # Simple fingerprint — hash of first 2000 chars
            import hashlib
            fingerprint = hashlib.sha256(page_text[:2000].encode()).hexdigest()[:16]

            if last_state is None:
                log.info(f"Browser watch '{task['id']}': baseline set for {site_name}")
                db = get_memory_store().db
                db.execute("UPDATE watch_tasks SET last_state = ? WHERE id = ?",
                           (fingerprint, task["id"]))
                db.commit()
                return

            if fingerprint == last_state:
                return  # No changes

            # Page changed — use LLM to summarize what's new
            from friday.core.llm import cloud_chat, extract_text

            summary_prompt = [
                {"role": "system", "content": f"You are FRIDAY. Travis asked you to watch {site_name}. The page content changed. Summarize what's new in 1-2 sentences. Be direct."},
                {"role": "user", "content": f"Instruction: {instruction}\n\nPage content (first 1500 chars):\n{page_text[:1500]}"},
            ]
            response = cloud_chat(messages=summary_prompt, max_tokens=100)
            summary = extract_text(response).strip()

            notify_text = f"{site_name}: {summary}"
            log.info(f"Browser watch '{task['id']}': {notify_text}")
            await self._notify_fn(notify_text)

            db = get_memory_store().db
            db.execute("UPDATE watch_tasks SET last_state = ? WHERE id = ?",
                       (fingerprint, task["id"]))
            db.commit()

        except ImportError:
            log.warning(f"Browser watch '{task['id']}': browser_tools not available")
        except Exception as e:
            log.error(f"Browser watch '{task['id']}' failed: {e}")

    # ── Contact extraction ────────────────────────────────────────────────

    @staticmethod
    def _extract_contact(instruction: str) -> str | None:
        """Extract the contact name from a watch instruction.

        Handles: "messages from Lamenash", "Father In Law's messages",
                 "check Ellen's texts", "monitor messages from my bby"
        """
        low = instruction.lower()

        # "messages/texts from X"
        m = re.search(r"(?:messages?|texts?|imessages?)\s+(?:from|with)\s+(.+?)(?:\.|,|$|\band\b|\bif\b|\bwhen\b|\bfor\b|\bevery\b)", low)
        if m:
            return m.group(1).strip().rstrip("'s").strip()

        # "X's messages/texts"
        m = re.search(r"(.+?)(?:'s|s)\s+(?:messages?|texts?|imessages?)", low)
        if m:
            name = m.group(1).strip()
            name = re.sub(r"^(?:check|watch|monitor|read|keep an eye on)\s+", "", name).strip()
            return name

        # "X messages" (no possessive) — "Father In Law messages", "Lamenash messages"
        m = re.search(r"(?:check|watch|monitor|read)\s+(.+?)\s+(?:messages?|texts?|imessages?)", low)
        if m:
            name = m.group(1).strip()
            if name not in ("my", "the", "his", "her", "their", "new", "old", "recent", "unread"):
                return name

        # "from X" anywhere
        m = re.search(r"\bfrom\s+(\w[\w\s]{1,30}?)(?:\.|,|$|\band\b|\bif\b|\bwhen\b|\bin\b)", low)
        if m:
            name = m.group(1).strip()
            if name not in ("him", "her", "them", "his", "my", "the", "this", "that"):
                return name

        # "reply to X" / "respond to X"
        m = re.search(r"(?:reply|respond)\s+to\s+(.+?)(?:\.|,|$|\band\b|\bif\b|\bwhen\b|\blike\b)", low)
        if m:
            return m.group(1).strip()

        return None

    # ── Watch task CRUD ─────────────────────────────────────────────────────

    def create_watch(self, instruction: str, interval_seconds: int = 60, duration_minutes: int = 0) -> dict:
        """Create or update a watch task (standing order).

        If an active watch already exists for the same contact, updates it
        instead of creating a duplicate.

        duration_minutes=0 means persistent (no expiry). The watch runs until
        explicitly cancelled or FRIDAY is stopped.
        """
        now = datetime.now()
        expires = (now + timedelta(minutes=duration_minutes)).isoformat() if duration_minutes > 0 else None
        db = get_memory_store().db

        # Check if there's already an active watch for the same contact
        new_contact = self._extract_contact(instruction)
        if new_contact:
            existing = db.execute("SELECT * FROM watch_tasks WHERE active = 1").fetchall()
            for row in existing:
                existing_contact = self._extract_contact(row["instruction"])
                if existing_contact and existing_contact.lower() == new_contact.lower():
                    # Same contact — update the existing watch
                    task_id = row["id"]
                    db.execute(
                        "UPDATE watch_tasks SET instruction = ?, interval_seconds = ?, expires_at = ?, last_check = NULL WHERE id = ?",
                        (instruction, interval_seconds, expires, task_id),
                    )
                    db.commit()
                    log.info(f"Watch task UPDATED '{task_id}': '{instruction[:60]}'")
                    return {
                        "id": task_id,
                        "instruction": instruction,
                        "interval_seconds": interval_seconds,
                        "expires_at": expires,
                        "persistent": expires is None,
                        "duration_minutes": duration_minutes or "indefinite",
                        "updated": True,
                    }

        # No existing watch for this contact — create new
        task_id = str(uuid.uuid4())[:8]
        db.execute(
            "INSERT INTO watch_tasks (id, instruction, interval_seconds, expires_at, active, created_at) VALUES (?, ?, ?, ?, 1, ?)",
            (task_id, instruction, interval_seconds, expires, now.isoformat()),
        )
        db.commit()

        dur_label = f"{duration_minutes}min" if duration_minutes > 0 else "persistent"
        log.info(f"Watch task created: '{instruction[:60]}' — every {interval_seconds}s, {dur_label}")
        return {
            "id": task_id,
            "instruction": instruction,
            "interval_seconds": interval_seconds,
            "expires_at": expires,
            "persistent": expires is None,
            "duration_minutes": duration_minutes or "indefinite",
        }

    def list_watches(self) -> list[dict]:
        db = get_memory_store().db
        rows = db.execute("SELECT * FROM watch_tasks WHERE active = 1 ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def cancel_watch(self, task_id: str) -> bool:
        db = get_memory_store().db
        db.execute("UPDATE watch_tasks SET active = 0 WHERE id = ?", (task_id,))
        db.commit()
        return True

    # ── Utilities ───────────────────────────────────────────────────────────

    @staticmethod
    async def _default_notify(text: str):
        from rich.console import Console
        console = Console()
        console.print(f"\n  [bold yellow]💛 FRIDAY[/bold yellow] [yellow]{text}[/yellow]\n")

    def get_status(self) -> dict:
        cfg = self._load_config()
        db = get_memory_store().db
        today = datetime.now().strftime("%Y-%m-%d")
        row = db.execute("SELECT value FROM heartbeat_state WHERE key = ?", ("alerts_today",)).fetchone()
        alerts_today = 0
        if row:
            parts = row["value"].split("|")
            if len(parts) == 2 and parts[0] == today:
                alerts_today = int(parts[1])

        active_watches = db.execute("SELECT COUNT(*) FROM watch_tasks WHERE active = 1").fetchone()[0]

        return {
            "running": self._started,
            "interval_minutes": cfg["interval_minutes"],
            "quiet_hours": f"{cfg['quiet_start'].strftime('%I%p')}-{cfg['quiet_end'].strftime('%I%p')}",
            "alerts_today": alerts_today,
            "daily_cap": cfg["daily_cap"],
            "active_watch_tasks": active_watches,
        }


# Singleton
_heartbeat: HeartbeatRunner | None = None


def get_heartbeat_runner(notify_fn=None) -> HeartbeatRunner:
    global _heartbeat
    if _heartbeat is None:
        _heartbeat = HeartbeatRunner(notify_fn=notify_fn)
    return _heartbeat
