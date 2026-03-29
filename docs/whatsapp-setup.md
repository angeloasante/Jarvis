# WhatsApp Integration (Baileys Bridge)

FRIDAY can read and send WhatsApp messages through a local Node.js bridge server. The bridge uses [Baileys](https://github.com/WhiskeySockets/Baileys) — an unofficial WhatsApp Web API that connects as a linked device (like WhatsApp Desktop), running entirely on your machine.

No third-party servers. No message forwarding. Your WhatsApp session lives locally in `~/.friday/whatsapp/auth_state/`.

## How It Works

```
FRIDAY (Python)
    │
    │  HTTP requests (localhost:3100)
    ▼
Express Bridge (Node.js)
    │
    │  Baileys (Noise Protocol + Protobuf over WebSocket)
    ▼
WhatsApp Servers
```

The bridge runs as a persistent Node.js process alongside FRIDAY. It:
- Maintains a WhatsApp Web multi-device session (same as WhatsApp Desktop)
- Stores messages in memory as they arrive (+ full history sync on connect)
- Exposes REST endpoints that FRIDAY's Python tools call

## Prerequisites

- **Node.js 18+** (tested on v22)
- **npm** (comes with Node.js)
- **A WhatsApp account** with phone number verified

Check your Node version:
```bash
node --version  # Should be v18 or higher
```

If you don't have Node.js:
```bash
brew install node
```

## Setup

### 1. Install bridge dependencies

```bash
cd friday/whatsapp
npm install
```

This installs:
- `@whiskeysockets/baileys` — WhatsApp Web protocol
- `express` — HTTP server for FRIDAY to talk to
- `pino` — logging
- `qrcode-terminal` — QR code display for pairing

### 2. Start the bridge and pair

```bash
node server.js
```

On first run, you'll see a QR code in the terminal:

```
[WA Bridge] HTTP server listening on port 3100

[WA Bridge] Scan this QR code with WhatsApp > Linked Devices > Link a Device:

  ██████████████████
  █ QR CODE HERE   █
  ██████████████████
```

**To scan:**
1. Open WhatsApp on your phone
2. Go to **Settings** (or the three dots menu) > **Linked Devices**
3. Tap **Link a Device**
4. Point your phone camera at the QR code in the terminal

Once scanned, the bridge connects and syncs your chat history:

```
[WA Bridge] Connected to WhatsApp
[WA Bridge] History sync: 1847 messages, 42 chats
```

The auth state is saved to `~/.friday/whatsapp/auth_state/`. Next time you start the bridge, it reconnects automatically — no QR scan needed.

### 3. Verify the connection

In another terminal:
```bash
curl http://localhost:3100/status
```

You should see:
```json
{
  "status": "connected",
  "qr": null,
  "user": {
    "id": "44XXXXXXXXXX:1@s.whatsapp.net",
    "name": "Your Name"
  }
}
```

### 4. Run FRIDAY

```bash
uv run friday
```

FRIDAY automatically detects the WhatsApp bridge. Try:
```
You: "check my whatsapp"
You: "read whatsapp messages from Mom"
You: "send a whatsapp to +44XXXXXXXXXX saying hey"
You: "search whatsapp for meeting tomorrow"
```

## Bridge Endpoints

The bridge exposes these REST endpoints on `localhost:3100`:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/status` | Connection status, QR code if pending, logged-in user |
| `POST` | `/send` | Send a text message (`to`, `message`, optional `quote_id`) |
| `GET` | `/chats` | List recent chats (sorted by last message) |
| `GET` | `/messages/:jid` | Read messages by WhatsApp JID |
| `GET` | `/messages?contact=Name` | Read messages by contact name |
| `GET` | `/messages?phone=+44...` | Read messages by phone number |
| `GET` | `/search?query=text` | Search messages across all chats |
| `POST` | `/read` | Mark messages as read (`jid`, `ids`) |
| `GET` | `/check/:phone` | Check if a number is on WhatsApp |
| `POST` | `/logout` | Disconnect and clear auth state |

## Running the Bridge in Background

You probably don't want a terminal tab dedicated to the bridge. A few options:

### Option A: Background with nohup
```bash
cd friday/whatsapp
nohup node server.js > ~/.friday/whatsapp/bridge.log 2>&1 &
echo $! > ~/.friday/whatsapp/bridge.pid
```

To stop it:
```bash
kill $(cat ~/.friday/whatsapp/bridge.pid)
```

### Option B: launchd (auto-start on login)

Create `~/Library/LaunchAgents/com.friday.whatsapp-bridge.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.friday.whatsapp-bridge</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/node</string>
        <string>/path/to/JARVIS/friday/whatsapp/server.js</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/YOU/.friday/whatsapp/bridge.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/YOU/.friday/whatsapp/bridge.log</string>
</dict>
</plist>
```

Replace `/path/to/JARVIS` and `/Users/YOU` with your actual paths, then:
```bash
launchctl load ~/Library/LaunchAgents/com.friday.whatsapp-bridge.plist
```

### Option C: tmux / screen
```bash
tmux new -d -s wa-bridge 'cd friday/whatsapp && node server.js'
```

## Changing the Port

By default the bridge runs on port `3100`. To change it:

```bash
WA_BRIDGE_PORT=3200 node server.js
```

Then update the Python tools to match — set `WA_BRIDGE_PORT` in your `.env` or edit `BRIDGE_URL` in `friday/tools/whatsapp_tools.py`.

## Troubleshooting

### QR code expired / won't scan
The QR refreshes every ~20 seconds. If you miss it, the bridge generates a new one automatically. Just wait for the next one.

### "stream errored out" (code 515)
Normal. WhatsApp servers periodically reset the connection. The bridge auto-reconnects within 2-15 seconds. You'll see:
```
[WA Bridge] Disconnected (code=515), reconnect=true
[WA Bridge] Reconnecting in 2s (attempt 1/5)
[WA Bridge] Connected to WhatsApp
```

### Bridge shows "connected" but no chats
History sync can take a minute on first connect, especially with lots of chats. The bridge logs progress:
```
[WA Bridge] History sync: 1847 messages, 42 chats
```

If it stays empty after 2 minutes, restart the bridge — WhatsApp sometimes doesn't push history on the first session.

### "WhatsApp not connected" from FRIDAY
The bridge isn't running or hasn't connected yet. Check:
1. Is the bridge process running? `curl http://localhost:3100/status`
2. If status is `qr_pending` — scan the QR code
3. If status is `disconnected` — restart with `node server.js`

### Logged out unexpectedly
If you unlink the device from your phone (Settings > Linked Devices), the bridge detects it and clears auth. You'll need to re-pair:
```bash
cd friday/whatsapp
rm -rf ~/.friday/whatsapp/auth_state
node server.js  # Generates new QR
```

### Contact not found when sending
The bridge resolves contacts by matching names against pushNames in your chat history. If you've never chatted with someone, use their phone number with country code:
```
"send a whatsapp to +447555834656 saying hello"
```

## What FRIDAY Can Do with WhatsApp

| Command | What happens |
|---------|-------------|
| "check my whatsapp" | Lists recent chats with last message preview |
| "read whatsapp from Mom" | Shows messages from that contact |
| "send X a whatsapp saying Y" | Previews message, sends on confirm |
| "search whatsapp for flight details" | Searches all chats for matching text |
| "whatsapp status" | Shows connection state |

WhatsApp tools follow the same safety pattern as iMessage — `send_whatsapp` requires `confirm=True` to actually send. FRIDAY always previews first.

## Privacy

- The bridge runs entirely on your machine. No FRIDAY server, no cloud relay.
- Messages are held in memory only (lost on bridge restart). Auth state is on disk at `~/.friday/whatsapp/auth_state/`.
- Auth state is gitignored — never committed to the repo.
- WhatsApp's end-to-end encryption still applies. The bridge acts as a linked device, same as WhatsApp Desktop.
- To fully disconnect: unlink the device from your phone, then `rm -rf ~/.friday/whatsapp/auth_state`.
