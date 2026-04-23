# FRIDAY Telegram

Second messaging channel, alongside SMS. Richer media, no tunnel required, free.

Source: [`friday/telegram/bot.py`](../friday/telegram/bot.py), [`friday/tools/telegram_tools.py`](../friday/tools/telegram_tools.py), [`friday/core/setup_wizard.py`](../friday/core/setup_wizard.py).

---

## Why two channels

SMS (Twilio) and Telegram each cover what the other can't:

| Property | SMS (Twilio) | Telegram |
|---|---|---|
| Works without internet | ✓ (uses cell voice network) | ✗ (needs data) |
| Rich media (photos, audio, docs) | Only in US/CA via MMS; **UK long-codes don't support MMS** | ✓ — up to 50 MB per file |
| Cost | $0.0075 / SMS, $0.02 / MMS | Free (personal use) |
| Public tunnel required | ✓ — ngrok or Tailscale Funnel | ✗ — long polling goes outbound |
| Text length | 1600 chars per message | 4096 chars per message |
| User opt-in | Implicit — any inbound SMS works | Explicit `/start` once |

**Rule of thumb:** SMS when signal is bad or you're off-grid; Telegram when you need a photo, voice note, or a report attached. FRIDAY's LLM picks the right tool based on content — it'll use `send_telegram_document` for a 12 MB investigation report and `send_sms` for a one-line alert.

---

## Setup

```bash
friday setup telegram
```

What the wizard does:

1. **Bot creation.** Prints instructions to message [@BotFather](https://t.me/BotFather) with `/newbot`, pick a name, pick a username ending in `bot`. BotFather hands back a token like `123456:ABC-DEF…`.
2. **Token validation.** Calls `getMe` against the Bot API to confirm the token works. If it doesn't, the wizard aborts — nothing gets saved.
3. **Auto chat-link.** You hit *Start* in your bot's chat window; the wizard polls `getUpdates` for 60 seconds and grabs the first `chat_id` it sees. That ID becomes the allowlist, so nobody else can drive FRIDAY through the bot.
4. **Persists** `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_CHAT_IDS` to `~/Friday/.env`.

If the 60s window times out, the wizard leaves the bot in open mode — any chat can reach it until you set the allowlist manually.

---

## Runtime — how inbound flows

`friday/telegram/bot.py` runs a daemon thread that loops on `getUpdates(timeout=25)`. Each message:

1. **Allowlist check.** `str(chat_id) not in TELEGRAM_ALLOWED_CHAT_IDS` → reply "Unauthorised.", drop.
2. **Slash commands.** `/start` replies with the chat_id (handy if you ever need to re-lock). `/id` prints the chat_id too.
3. **fast_path.** `friday.fast_path(text)` — instant hits (TV play/pause, volume, mute, greetings). Sub-second.
4. **Full pipeline.** `friday.dispatch_background(text)` streams chunks back; we concat and reply when `DONE:` fires.
5. **Chunking.** If the reply exceeds Telegram's 4096-char message limit, we split into multiple `sendMessage` calls.

No webhook server. No public URL. If ngrok is down, Telegram still works.

---

## Runtime — how outbound works

The LLM has six send tools, listed in [`friday/tools/telegram_tools.py`](../friday/tools/telegram_tools.py):

| Tool | Telegram method | Max size | Typical use |
|---|---|---|---|
| `send_telegram_message` | `sendMessage` | 4096 chars/message, auto-chunks longer | Any text reply |
| `send_telegram_photo` | `sendPhoto` | 10 MB | JPG/PNG/WEBP displayed as image |
| `send_telegram_audio` | `sendAudio` | 50 MB | MP3/M4A — shows in audio player |
| `send_telegram_voice` | `sendVoice` | 20 MB (1 MB ideal) | OGG/Opus voice note |
| `send_telegram_document` | `sendDocument` | 50 MB | PDF, DOCX, ZIP — attachment |
| `send_telegram_video` | `sendVideo` | 50 MB | MP4 |

Each tool accepts either a local path or a public URL. If you pass a URL Telegram fetches it server-side; otherwise we multipart-upload the file.

Destination defaults to the first ID in `TELEGRAM_ALLOWED_CHAT_IDS`, falling back to `TELEGRAM_CHAT_ID`. Override per-call by passing `chat_id`.

---

## Environment variables

| Var | Purpose | Required |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather token (e.g. `123456:ABC-…`) | Yes |
| `TELEGRAM_ALLOWED_CHAT_IDS` | Comma-separated chat IDs permitted to talk to the bot | Recommended |
| `TELEGRAM_CHAT_ID` | Legacy default destination if allowlist is empty | Optional |

All written to `~/Friday/.env` by the wizard. Edit by hand if you want to add a second person's chat_id later.

---

## Inside the CLI

- `/telegram` — show live bot status and the current allowlist
- `/sms` — show SMS tunnel status (complementary)

Both appear in `/help` under "Messaging channels". Status row for Telegram also shows up in `friday doctor`.

---

## Diagnostics

```bash
# Bot reachable?
curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getMe" | jq

# What messages are queued for the bot?
curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getUpdates?timeout=0" | jq

# Send a test message — replace CHAT_ID
curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
     -d chat_id=CHAT_ID -d text='hello'
```

If `/telegram` reports `DOWN`, the token is likely revoked — regenerate via `@BotFather` → `/mybots` → your bot → *API Token* → *Revoke*.

---

## Security

- **Allowlist strictly enforced.** A missing `TELEGRAM_ALLOWED_CHAT_IDS` means anyone who finds the bot can reach it. The wizard auto-fills this; if you ever clear it, rerun the wizard or `echo 'TELEGRAM_ALLOWED_CHAT_IDS=<your_id>' >> ~/Friday/.env`.
- **Token lives in `~/Friday/.env`**, `chmod 600`. Rotate via BotFather if you ever paste it into a screenshot or commit it by mistake.
- **Every inbound message** is logged at INFO via `friday.telegram` — audit with `grep 'friday.telegram' ~/Library/Logs/friday.log`.
- **No persistent storage of Telegram content** beyond what the regular FRIDAY memory store picks up. Voice notes / photos you receive are held in memory until the tool handler finishes; nothing is written to disk by the bot itself.

---

## Not implemented (on purpose)

- **Group chats.** The bot is personal. Group-chat support would need per-chat policy (who can command what) which is more scope than warranted today. Message if you want it.
- **Inbound photo OCR / voice-note transcription.** You can send FRIDAY a photo, but it won't auto-OCR the contents yet. Wire it via `screen_vision` once/if needed.
- **Webhook mode.** Polling is simpler and enough for single-user use. Webhook is faster only above ~50 msg/sec which is beyond personal-assistant scale.

---

## See also

- [`docs/notifications.md`](notifications.md) — iMessage vs SMS notification routing.
- [Twilio SMS setup](install.md#twilio-sms) — pairing Telegram with the voice-fallback SMS channel.
- [`friday/core/tool_dispatch.py`](../friday/core/tool_dispatch.py) — how the six send tools become callable by the LLM.
