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

## Cross-channel delivery: SMS → Telegram

The common real-world flow: you text FRIDAY on SMS ("send me the latest Richard Asante investigation on Telegram") and the result lands on Telegram. That chain is now end-to-end wired:

```
SMS inbound                           (friday/sms/server.py)
  ↓
dispatch_background                   (friday/core/orchestrator.py)
  ↓
router.match_agent → comms_agent      (friday/core/router.py)
  ↓
comms_agent.run:                      (friday/agents/comms_agent.py)
  1. search_files(query, ~/Friday/investigations/)
  2. send_telegram_document(path_or_url=...)
  ↓
SMS reply: "Sent the Richard Asante report to your Telegram."
```

Key enablers (already merged):

- **Router**: the comms-pattern block matches `(send|shoot|forward|drop|text|push) … (on|to|via) telegram`, `telegram me (it|that|this)`, and bare `telegram`. Misc phrasings all land on comms_agent.
- **comms_agent tools**: imports every `send_telegram_*` tool plus `search_files` and `read_file` from file_tools, so it can find a file by fuzzy name before sending.
- **`search_files` normalisation**: spaces, underscores, and dashes are treated as equivalent in filenames — so `"Richard Asante"` matches `richard_asante_20260422_205436.docx` on disk.
- **Agent prompt**: explicit decision tree for rich-media ("document → `send_telegram_document`; photo → `send_telegram_photo`; voice note → `tts_to_file` → `send_telegram_voice`") plus a hard rule — **never reply "sent" unless the tool actually returned success**.

### Voice notes via ElevenLabs v3

The LLM renders voice notes by chaining **two tools** in one ReAct round:

1. `tts_to_file(text, format="ogg")` — POSTs to ElevenLabs' `/v1/text-to-speech/{voice_id}` with `model_id=eleven_v3`. Saves the MP3, converts to OGG/Opus via ffmpeg (48 kbps, speech-tuned). Returns the path.
2. `send_telegram_voice(path_or_url=...)` — uploads as a Telegram voice-note bubble.

**Emotion via audio tags.** Eleven v3 accepts inline tags right in the text:

```
"Alright Travis [sighs] OpenRouter is still rate-limited [laughs]
but Groq's carrying the load. [excited] Oh, and the voice pipeline
finally works end to end."
```

Supported tags include `[laughs]`, `[laughs harder]`, `[starts laughing]`, `[wheezing]`, `[whispers]`, `[excited]`, `[sad]`, `[curious]`, `[sighs]`, `[sarcastic]`. They're voice-dependent — some voices carry laughter well, others sound forced. Test short samples.

**Tuned voice_settings** (in [`friday/tools/voice_tools.py`](../friday/tools/voice_tools.py)):

```python
"voice_settings": {
    "stability": 0.35,       # lets tone swing with audio tags
    "similarity_boost": 0.75,
    "style": 0.65,           # surfaces emotional inflection
    "use_speaker_boost": True,
}
```

Lower `stability` + higher `style` = more expressive. Too low stability = unstable pacing; too high style = hammy. 0.35 / 0.65 is the current sweet spot.

**Format comparison:**

| Format | Telegram UI | File size (typical) | ffmpeg required |
|---|---|---|---|
| `ogg` | Voice-note bubble with waveform | ~100 KB for 15 s | ✓ (MP3 → Opus conversion) |
| `mp3` | Audio-player row | ~250 KB for 15 s | — |

Pick `ogg` for personal voice messages; `mp3` for longer clips that should look like music/podcasts.

**Cost note.** Eleven v3 is billed the same per-char as the other tiers, but the expressive model burns ~30–50% more characters than flash for the same input (audio tags count, and the model sometimes emphasises syllables you didn't ask for). A typical 200-char voice note is ~$0.01 on v3 vs ~$0.006 on flash v2.5. Negligible for personal use.

## Environment variables

| Var | Purpose | Required |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather token (e.g. `123456:ABC-…`) | Yes |
| `TELEGRAM_ALLOWED_CHAT_IDS` | Comma-separated chat IDs permitted to talk to the bot | Recommended |
| `TELEGRAM_CHAT_ID` | Legacy default destination if allowlist is empty | Optional |
| `ELEVENLABS_API_KEY` | ElevenLabs key — needed for voice notes via `tts_to_file` | Optional (voice notes only) |
| `ELEVENLABS_VOICE_ID` | Default voice for generated clips | Optional (has sensible default) |
| `ELEVENLABS_EXPRESSIVE_MODEL` | TTS model for rendered files. Default `eleven_v3` (supports audio tags). Set to `eleven_flash_v2_5` for cheapest/fastest if you don't need emotion. | Optional |

All live in `~/Friday/.env` — the single source of truth for user-specific values. The repo's dev `.env` is no longer used for secrets.

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
- **Inbound voice-note ASR.** Outbound voice notes work (`tts_to_file` → `send_telegram_voice`). Inbound — where the USER records a voice note in Telegram and FRIDAY transcribes + acts — isn't wired. Would slot into `friday/telegram/bot.py` alongside the text handler using the existing STT pipeline.
- **Webhook mode.** Polling is simpler and enough for single-user use. Webhook is faster only above ~50 msg/sec which is beyond personal-assistant scale.

---

## See also

- [`docs/notifications.md`](notifications.md) — iMessage vs SMS notification routing.
- [Twilio SMS setup](install.md#twilio-sms) — pairing Telegram with the voice-fallback SMS channel.
- [`friday/core/tool_dispatch.py`](../friday/core/tool_dispatch.py) — how the six send tools become callable by the LLM.
