# SMS Integration (Twilio + Tailscale Funnel)

Text FRIDAY from anywhere in the world. Send an SMS to FRIDAY's Twilio number, it processes through FridayCore, and replies via TwiML. No app install, no WhatsApp pairing, no iMessage requirement — works from any phone on any network.

## How It Works

```
Your Phone (SMS)
    │
    │  Twilio receives the SMS
    ▼
Twilio Webhook (HTTP POST)
    │
    │  https://traviss-macbook-air.tail452e49.ts.net/sms
    ▼
Tailscale Funnel
    │
    │  Forwards to localhost:3200
    ▼
FRIDAY SMS Server (Python HTTP)
    │
    │  Extracts From + Body from Twilio form data
    │  Security check: only allowed numbers processed
    ▼
FridayCore.process(message)
    │
    │  Full FRIDAY pipeline: routing → agent dispatch → tools → synthesis
    ▼
TwiML Response
    │
    │  <Response><Message>FRIDAY's reply</Message></Response>
    ▼
Twilio delivers reply SMS to your phone
```

No cloud middleman beyond Twilio itself. The webhook server runs on your machine. Tailscale Funnel provides a stable public HTTPS URL without exposing your IP or opening firewall ports.

## Architecture

Three components work together:

### 1. SMS Webhook Server (`friday/sms/server.py`)

A lightweight HTTP server running on port 3200 (configurable via `SMS_PORT` env var).

- **POST /sms** — receives Twilio webhook payloads, processes through FridayCore, returns TwiML
- **GET /health** — health check endpoint (`{"status":"ok","service":"friday-sms"}`)
- **Security** — only processes SMS from numbers in `SMS_ALLOWED_NUMBERS` or `CONTACT_PHONE`
- **Threading** — runs as a daemon thread inside the main FRIDAY process. When FRIDAY starts, SMS starts. When FRIDAY stops, SMS stops.
- **Response truncation** — SMS replies capped at 1500 chars (Twilio concatenated SMS limit is 1600)
- **Timeout** — FridayCore processing times out at 45 seconds to avoid Twilio's 15s webhook timeout causing retries

### 2. SMS Tools (`friday/tools/sms_tools.py`)

Outbound SMS capability — FRIDAY can send you texts proactively.

- **`send_sms(to, message)`** — send an SMS via Twilio REST API
- **`read_sms(limit)`** — read recent inbound messages from Twilio
- Uses `asyncio.to_thread()` for non-blocking Twilio API calls
- Lazy client initialization — Twilio SDK only loaded when first used
- Integrated into CommsAgent — FRIDAY can send/read SMS alongside email, iMessage, WhatsApp

### 3. Tailscale Funnel (Public URL)

Tailscale Funnel exposes `localhost:3200` to the internet via a stable HTTPS URL. No ngrok, no port forwarding, no dynamic DNS.

- **URL**: `https://traviss-macbook-air.tail452e49.ts.net/sms`
- **Stable** — same URL forever, survives reboots, no random subdomains
- **Secure** — HTTPS with valid TLS cert (Tailscale manages it)
- **Auto-start** — FRIDAY's CLI starts Funnel automatically via `tailscale funnel --bg 3200`
- **No rate limits** — unlike ngrok free tier, no throttling on webhooks

## Setup

### Prerequisites

- **Twilio account** (free trial or paid) — [twilio.com](https://twilio.com)
- **Twilio phone number** — buy one in the Twilio console (£1/month for UK numbers)
- **Tailscale** — [tailscale.com](https://tailscale.com) (free for personal use, up to 100 devices)

### Step 1: Twilio Credentials

Add to your `.env`:

```bash
# Twilio SMS
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_PHONE_NUMBER=+447367000489          # Your Twilio number
TWILIO_PHONE_NUMBER_US=+17405588099        # Optional: US number for US recipients
```

Get these from [console.twilio.com](https://console.twilio.com) → Account Info.

### Step 2: Set Allowed Numbers

Your phone number should be in `.env` so FRIDAY only processes SMS from you:

```bash
CONTACT_PHONE=+447555834656
```

Or for multiple numbers:

```bash
SMS_ALLOWED_NUMBERS=+447555834656,+447000000000
```

### Step 3: Install & Enable Tailscale

```bash
# macOS — install from App Store or:
brew install --cask tailscale

# Log in (opens browser)
tailscale login

# Enable Funnel (first time — opens browser for approval)
tailscale funnel 3200
```

When you visit the Funnel approval page, click "Enable" — this is a one-time step.

### Step 4: Configure Twilio Webhook

1. Go to [console.twilio.com](https://console.twilio.com) → Phone Numbers → Manage → Active Numbers
2. Click your Twilio number
3. Under **Messaging** → "A message comes in":
   - **Webhook URL**: `https://your-machine.tailnet.ts.net/sms`
   - **Method**: `HTTP POST`
4. Save

### Step 5: Start FRIDAY

```bash
uv run friday
```

You'll see in the console:
```
:: SMS server ACTIVE on port 3200
:: Tailscale Funnel ACTIVE — SMS reachable from anywhere
```

That's it. Text your Twilio number and FRIDAY answers.

## Testing

### Quick Health Check

```bash
curl https://your-machine.tailnet.ts.net/health
# {"status":"ok","service":"friday-sms"}
```

### Simulate a Twilio Webhook

```bash
curl -X POST https://your-machine.tailnet.ts.net/sms \
  -d "From=%2B447555834656&To=%2B447367000489&Body=what+time+is+it" \
  -H "Content-Type: application/x-www-form-urlencoded"
```

Expected response:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>It's 10:04 AM, Wednesday.</Message>
</Response>
```

### Send an SMS from FRIDAY

```python
from friday.tools.sms_tools import send_sms
await send_sms(to="+447555834656", message="Yo — FRIDAY here. SMS is live.")
```

Or just tell FRIDAY: *"text me on SMS saying hey"*

## How It Integrates with FRIDAY

### CLI Boot Sequence

When you run `uv run friday`, the CLI (`friday/cli.py`) does this automatically:

1. Checks if `TWILIO_ACCOUNT_SID` is set and auth token isn't the placeholder
2. Starts the SMS webhook server on port 3200 (daemon thread)
3. Checks if Tailscale is running, starts Funnel in background (`tailscale funnel --bg 3200`)

No manual steps. No separate terminal windows. Everything starts and stops with FRIDAY.

### Comms Agent

The SMS tools (`send_sms`, `read_sms`) are loaded into the CommsAgent alongside email, iMessage, WhatsApp, and calendar tools. FRIDAY can:

- Send you SMS proactively (alerts, watch notifications)
- Read inbound SMS from Twilio logs
- Route SMS queries: *"send an SMS to +447..."* → `send_sms`

### Inbound Processing

Every inbound SMS goes through the full FRIDAY pipeline:

```
SMS text → FridayCore.process()
  ├─ Fast path (greetings, TV commands) → instant reply
  ├─ Oneshot (check email, calendar) → tool + format
  ├─ Agent dispatch (research, apply to job) → full ReAct loop
  └─ Chat (casual conversation) → personality response
```

FRIDAY doesn't know or care that the input came via SMS. It processes it the same as CLI or voice input.

## UK vs US Numbers

If you have both a UK and US Twilio number:

| Number | Best for |
|--------|----------|
| UK (+44) | Texting UK numbers (cheaper, faster delivery) |
| US (+1) | Texting US numbers |

The US number may need **Geo Permissions** enabled for international SMS:
- Twilio Console → Messaging → Settings → Geo permissions → tick target countries

`TWILIO_PHONE_NUMBER` in `.env` sets the default outbound number. Set it to whichever matches your primary location.

## Troubleshooting

### SMS not arriving at FRIDAY

1. **Check Funnel is running**: `tailscale funnel status`
2. **Check SMS server is up**: `curl http://localhost:3200/health`
3. **Check webhook URL in Twilio**: must be `https://...ts.net/sms`, method POST
4. **Check allowed numbers**: your phone must be in `CONTACT_PHONE` or `SMS_ALLOWED_NUMBERS`

### FRIDAY replies "Unauthorized"

Your phone number isn't in the allowed list. Add it to `CONTACT_PHONE` or `SMS_ALLOWED_NUMBERS` in `.env` and restart FRIDAY.

### "HTTP 400: Message cannot be sent"

Cross-region issue — US numbers can't always reach UK numbers without Geo Permissions. Use a number that matches the recipient's country, or enable Geo Permissions in Twilio console.

### Tailscale Funnel not starting

1. Make sure Tailscale is connected: `tailscale status`
2. Enable Funnel on your tailnet (one-time): visit the URL shown when you first run `tailscale funnel 3200`
3. Check if something else is using port 3200: `lsof -i :3200`

### SMS replies timing out

FridayCore has a 45-second timeout for processing. If the query triggers a slow agent (deep research, multi-step job application), the response may exceed Twilio's expectations. Simple queries (time, weather, email check) reply in 2-10 seconds.

## Standalone Mode

You can run the SMS server without the full FRIDAY CLI for testing:

```bash
python -m friday.sms.server
```

This starts FridayCore + SMS server on port 3200. Useful for debugging webhook issues.

## Security Notes

- **Allowed numbers only** — SMS from unknown numbers get "Unauthorized." response
- **No authentication header** — Twilio's request validation (X-Twilio-Signature) is not implemented yet. For production, add [Twilio request validation](https://www.twilio.com/docs/usage/security#validating-requests) to verify webhooks are genuinely from Twilio.
- **Response truncation** — replies capped at 1500 chars to stay within SMS limits
- **No PII logging** — message bodies are logged at first 50 chars only (`log.info(f"SMS from {from_number}: {message_body[:50]}")`)

## Cost

| Item | Cost |
|------|------|
| Twilio UK number | ~£1/month |
| Inbound SMS | Free (Twilio doesn't charge for receiving) |
| Outbound SMS (UK→UK) | ~£0.04/message |
| Tailscale | Free (personal, up to 100 devices) |
| **Total** | **~£1/month + per-message** |

## Files

| File | Purpose |
|------|---------|
| `friday/sms/__init__.py` | Package init |
| `friday/sms/server.py` | HTTP webhook server (port 3200), TwiML responses |
| `friday/tools/sms_tools.py` | `send_sms`, `read_sms` tool functions + schemas |
| `friday/agents/comms_agent.py` | SMS tools loaded into agent toolset |
| `friday/cli.py` | Auto-starts SMS server + Tailscale Funnel on boot |
