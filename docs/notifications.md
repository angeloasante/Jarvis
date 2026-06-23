# FRIDAY Notifications

How FRIDAY gets alerts onto the user's phone. Two channels, different trade-offs, both wired into the same phone number.

Source: [`friday/tools/notify.py`](../friday/tools/notify.py), [`friday/tools/sms_tools.py`](../friday/tools/sms_tools.py), [`friday/background/heartbeat.py`](../friday/background/heartbeat.py).

## 1. Overview — two channels

FRIDAY pushes alerts to your phone via one of two paths:

**iMessage-to-self** (default for heartbeat / watch-task alerts)
- Uses AppleScript to drive `Messages.app` on the Mac.
- Sends an iMessage from your Apple ID to your own number — it lands on your phone like any other text.
- Instant. Free. No external dependencies.
- Requires: Mac is running, signed into iMessage, and your number is a registered participant.

**Twilio SMS** (for delivering actual content / "text me the results")
- Real SMS from FRIDAY's Twilio number.
- Works even if the Mac is offline (server-side).
- Requires paid Twilio setup — see [`docs/sms-setup.md`](./sms-setup.md).
- Used for result delivery, not silent background pings.

**Rule of thumb:** heartbeat notices use iMessage. User says "text me the summary" — SMS.

## 2. Priority / emoji mapping

`send_phone_notification` prefixes every iMessage with an emoji based on priority:

```python
prefix = {
    "critical": "🚨",
    "high":     "⚠️",
    "normal":   "🔔",
    "low":      "💬",
}.get(priority, "🔔")
```

`notify_phone_async` auto-picks priority from the alert text:

| Keywords in alert                              | Priority   | Emoji |
|------------------------------------------------|------------|-------|
| urgent, critical, emergency, asap              | `critical` | 🚨    |
| important, action required                     | `high`     | ⚠️    |
| (anything else — default)                      | `normal`   | 🔔    |
| (explicitly passed `low`)                      | `low`      | 💬    |

Messages are formatted as `{emoji} FRIDAY — {title}\n{body}`.

## 3. How `send_phone_notification` works

Located at [`friday/tools/notify.py:30`](../friday/tools/notify.py).

1. Builds `{emoji} FRIDAY — {title}` + optional body.
2. Escapes backslashes and double quotes for AppleScript.
3. Resolves the target phone via `_user_phone()`:

```python
def _user_phone() -> str:
    """Resolve the user's own phone number. Env var wins, then user.json."""
    env = os.getenv("CONTACT_PHONE", "").strip()
    if env:
        return env
    try:
        from friday.core.user_config import USER
        return (USER.phone or "").strip()
    except Exception:
        return ""
```

4. Shells out to `osascript` with a 15s timeout, telling `Messages.app` to send the message to `participant "{target_number}" of targetService` (where `targetService` is the first iMessage account).

Failure modes, all logged, none raised:
- No phone configured — logs a warning and returns `False`.
- `osascript` non-zero exit — logs `stderr`, returns `False` (common when Messages isn't signed in or Automation permission is denied).
- Timeout / other exception — logged, returns `False`.

The async wrapper `notify_phone_async(text)` splits on `" — "` or `". "` to derive `title` / `body`, runs the priority classifier, sends, and also echoes to the CLI so the terminal user sees the alert too.

## 4. How `send_result_sms` works

Located at [`friday/tools/notify.py:132`](../friday/tools/notify.py). Used when FRIDAY needs to deliver actual content to the phone — research summaries, briefings, "text me what you found".

1. Resolves target number via the same `_user_phone()` above.
2. `_strip_markdown()` flattens the text: `**bold**`, `*italic*`, `` `code` ``, `### heading`, `[link](url)`, and `![img](url)` all become plain text. SMS has no formatting — markdown would arrive as literal asterisks.
3. Truncates to 1500 chars (`text[:1497] + "..."`) to stay under Twilio's 1600-char concatenated SMS ceiling.
4. Calls `friday.tools.sms_tools.send_sms(to, message)` which hits the Twilio REST API.
5. Logs success / failure; returns `bool`.

## 5. When notifications fire automatically

All routed through the heartbeat's `_notify_fn` — which defaults to `notify_phone_async` when FRIDAY starts with a phone configured.

- **Heartbeat static checks** ([`friday/background/heartbeat.py:183`](../friday/background/heartbeat.py)) — every N minutes (default 30). Checks urgent unread email, queued monitor alerts, and the weekday morning briefing trigger. Findings get synthesised into a 1–2 sentence alert and pushed via `_notify_fn`.
- **Monitor alerts** — anything dropped into the `briefing_queue` table with `delivered=0` is picked up on the next tick and announced.
- **Watch-task replies** — when a watch task sends an auto-reply on the user's behalf (iMessage or WhatsApp), the heartbeat calls `_notify_fn(f"Watch — replied to {contact}: ...")` so the user knows what FRIDAY said in their name.
- **Remote-command results** — the self-chat watch executor texts "Remote command: ... → replied" after processing a command sent from the user's phone.
- **Email / call / browser / web watches** — each watch executor fires `_notify_fn` on a material change (new matching email, missed call, page diff, search result shift).

## 6. Quiet hours

Configured in [`HEARTBEAT.md`](../HEARTBEAT.md) at the repo root:

```markdown
- Quiet hours: 1am — 7am (no alerts)
```

Parsed by `_parse_config()` in [`friday/background/heartbeat.py:76`](../friday/background/heartbeat.py) via a regex looking for `quiet ... Nam ... Mpm`. Defaults to 1am–7am if the line is missing or unparseable.

On every static tick, `_is_quiet_hour(now, start, end)` short-circuits the entire tick — no checks run, no alerts fire. Watch tasks (`_watch_tick`) do not honour quiet hours by design: if the user set a watch, they want the reply to happen.

## 7. Daily cap

Also in `HEARTBEAT.md`:

```markdown
- Max 3 proactive messages per day
```

Stored in SQLite (`heartbeat_state` table, key `alerts_today`, value `YYYY-MM-DD|N`). On each static tick, the runner reads the count — if it's already at the cap, the tick exits before running any checks. Incremented only when an alert actually fires.

Default is 3/day. Bump it by editing `HEARTBEAT.md` (`Max 10 proactive messages per day`). Watch-task notifications are not counted against this cap.

## 8. Configuring your own phone

FRIDAY needs to know which number is yours. Two sources, env var wins:

```bash
# option A — env var (overrides user.json)
export CONTACT_PHONE="+447555834656"

# option B — user config
friday config edit    # opens ~/.friday/user.json in $EDITOR
# set "phone": "+447555834656"
```

Must be **E.164 format**: leading `+`, country code, no spaces, no dashes. `+447555834656`, not `07555 834656` or `(555) 834-656`.

Interactive setup: `friday setup twilio` walks you through `.env` entries (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`, `CONTACT_PHONE`).

## 9. Testing

```bash
friday test twilio
```

Implemented at [`friday/core/setup_wizard.py:900`](../friday/core/setup_wizard.py). Resolves `CONTACT_PHONE` → `USER.phone` → env, then calls `send_sms(to, "FRIDAY test SMS — reply if you got this.")`. Exits green if the Twilio API accepts the message.

For iMessage-to-self, the quickest check is to trigger a heartbeat alert manually (drop a row into `briefing_queue`, wait for the next tick) or invoke `send_phone_notification("test", "hello", "normal")` from a Python REPL.

## 10. Roadmap — native push

Both current channels have edge cases. iMessage needs the Mac awake and signed in. Twilio costs money and looks like a text from a random number. Planned:

- **Native APNs via the FRIDAY Mac companion app** — proper iOS push notifications to a dedicated FRIDAY app, no SMS charges, rich notification actions (reply inline, dismiss, snooze).
- **FRIDAY Cloud** — server-side push routing, so alerts fire even when the Mac is off.

Roadmap only — not shipping yet. The iMessage + Twilio pair covers 95% of what a solo user needs today.
