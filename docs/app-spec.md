# FRIDAY App — Product Specification

Detailed UX, architecture, and feature spec for the FRIDAY macOS and iOS apps. This document is the source of truth for app product decisions.

---

## FRIDAY macOS App

### First Principles

The CLI is for developers. The app is for everyone else. But "everyone else" doesn't mean dumbed down — it means **zero setup, same power.** A senior engineer and their mum should both be able to use the same app. The engineer just also has the terminal.

The app is NOT a chatbot window. It's a **presence** — FRIDAY lives in your menu bar, always there, always aware. You interact with it like you interact with a person who sits next to you: sometimes you talk, sometimes you glance, sometimes it taps your shoulder.

### Architecture

```
macOS App (SwiftUI)
├── Menu Bar Icon (always present)
│   ├── Click → quick command bar (Spotlight-style)
│   ├── Right-click → settings, quit
│   └── Status indicator (green dot = connected, orange = processing)
│
├── Command Bar (Cmd+Shift+F global hotkey)
│   ├── Type anything → FRIDAY processes it
│   ├── Same as CLI but with autocomplete + suggestions
│   ├── Shows live status: "checking emails..." "TV muted."
│   └── Dismiss with Esc — doesn't interrupt your work
│
├── Notification Center Integration
│   ├── FRIDAY alerts appear as native macOS notifications
│   ├── Watch task replies: "💛 FRIDAY replied to Ellen's Pap"
│   ├── Briefing summaries: "Morning: 3 emails, 1 missed call"
│   ├── Health alerts (from Neural Band): "Heart rate elevated"
│   └── Actionable: click notification → opens relevant context
│
├── Widget (macOS Sonoma widgets)
│   ├── Small: next calendar event + unread email count
│   ├── Medium: briefing summary + quick actions
│   ├── Large: full dashboard (TV status, emails, calendar, active watches)
│   └── Interactive: buttons for common actions (mute TV, check email)
│
├── Voice (menu bar mic)
│   ├── Same pipeline as CLI (Silero VAD + Whisper + TTS)
│   ├── "Hey Friday" trigger word — works system-wide
│   ├── Push-to-talk: hold Option key
│   ├── Speaks through system speakers (ElevenLabs/Kokoro)
│   └── Visual: waveform animation in menu bar when listening
│
├── Gesture Control (camera)
│   ├── Same MediaPipe pipeline as CLI
│   ├── Toggle on/off from menu bar
│   ├── Camera preview window (optional, for calibration)
│   └── Gesture guide overlay
│
├── Settings (native macOS preferences window)
│   ├── Accounts: Google (Gmail/Calendar), WhatsApp (QR scan), Twilio
│   ├── LLM: choose provider (Groq/OpenRouter/Google AI/Ollama), enter key
│   ├── Voice: on/off, TTS provider, voice selection
│   ├── Gestures: on/off, gesture → command mapping
│   ├── Notifications: what alerts you want
│   ├── Privacy: what FRIDAY can access
│   └── Advanced: .env editor, logs, developer mode (opens CLI)
│
└── Backend (same FridayCore)
    ├── Exact same Python codebase as CLI
    ├── Embedded Python runtime or PyInstaller bundle
    ├── SwiftUI ↔ Python via local WebSocket or stdin/stdout
    ├── All 11 agents, 32+ tools, same routing
    └── Data stored in same ~/.friday/ directory
```

### The Onboarding (First 60 Seconds)

This is where most apps lose people. FRIDAY has to deliver value in under a minute.

```
STEP 1: Download + Open (0-10 seconds)
├── Drag to Applications, open
├── Menu bar icon appears (FRIDAY logo)
├── Welcome screen: "Hey. I'm FRIDAY. Let's get you set up."
└── One button: "Connect with Google" (OAuth)

STEP 2: Google Sign-In (10-25 seconds)
├── Browser opens → Google OAuth
├── Grants Gmail + Calendar access
├── Returns to app: "Got it. Let me check what's going on."
└── Email + Calendar now work

STEP 3: First Wow Moment (25-45 seconds)
├── FRIDAY automatically runs a quick briefing
├── Shows in a notification: "You have 4 unread emails.
│   One from Apple Developer — your membership needs renewal.
│   Calendar: Work shift 2pm-12am today."
├── User didn't ask for this — FRIDAY just did it
└── THIS is the moment they decide to keep the app

STEP 4: "Try something" prompt (45-60 seconds)
├── Small tooltip on menu bar: "Try: Cmd+Shift+F → 'turn on the TV'"
├── Or: "Say 'Hey Friday, what's on my calendar'"
├── Quick wins that show breadth of capability
└── User has seen FRIDAY act on its own AND respond to commands

OPTIONAL (shown after first session):
├── "Connect WhatsApp" → QR scan in-app
├── "Connect SMS" → enter Twilio credentials → auto-configures
├── "Enable gestures" → camera permission → gesture guide
├── "Enable voice" → mic permission → wake word test
└── Each unlocks more capabilities — progressive disclosure
```

### The Seven Wow Moments

These are the moments that make someone screenshot the app and send it to their group chat. Design the app to deliver ALL of them within the first week of use.

**Wow 1: "It already knows" (Day 1, automatic)**

User opens app for the first time after connecting Google. Without asking, FRIDAY says: "4 unread emails. One from Apple — your dev membership needs renewal. Calendar: work at 2pm. No missed calls."

Reaction: "Wait, I didn't ask for that."
Why it works: Every other AI waits for you to ask. FRIDAY acts.

**Wow 2: "It actually did it" (Day 1, first command)**

User: "turn on the TV" → TV turns on. Not "I'll try to turn on the TV." Not "Here are instructions for turning on your TV." The TV physically turns on.

Reaction: "Holy shit it actually did it."
Why it works: Siri/Alexa have trained people to expect failure. Real action is shocking.

**Wow 3: "It controls everything from one place" (Day 1-2)**

User tries a few more:
- "mute" → TV mutes (200ms)
- "check my email" → email summary appears as notification
- "text Mom saying I'll be late" → iMessage sent
- "what's on my screen" → OCR reads the current window

Reaction: "One app does all of this?"
Why it works: People use 5 apps for what FRIDAY does in one.

**Wow 4: "The gesture thing" (Day 2-3)**

User enables gesture control. Raises fist → TV mutes. Peace sign → pause. Point up → volume up.

Reaction: *takes video, posts on social media*
Why it works: This is the viral moment. Nobody else has this. It's visually impressive. It's fun. It's Iron Man.

**Wow 5: "It held my conversation" (Day 3-5)**

User sets up a watch: "watch my messages from [friend], reply as friday". Goes to work. Comes home. Checks phone:
"💛 FRIDAY replied to [friend]: 'FRIDAY here — Travis is at work right now. He'll catch up with you tonight.'"

Reaction: "It actually replied? And it sounds natural?"
Why it works: This is autonomy people have never seen from an AI. Not a canned auto-reply. A contextual, personality-matched response.

**Wow 6: "It did the whole thing" (Week 1)**

User: "find a software engineer job at Google and tailor my CV"
FRIDAY: searches Google careers → finds matching role → reads JD → tailors CV → generates PDF → saves to desktop. "Done. CV tailored for Software Engineer at Google. Saved to your desktop."

Reaction: "It browsed a website, read the job, AND made my CV?"
Why it works: Multi-step autonomy. This would take 30 minutes manually.

**Wow 7: "It saved me" (Week 1-2, if using Neural Band)**

User falls asleep wearing Neural Band. Heart rate drops unusually low.
FRIDAY: "Hey — your heart rate dropped to 48 BPM. That's lower than your usual resting rate. Everything okay?"
User doesn't respond for 60 seconds.
FRIDAY: sends SMS to emergency contact with location.

Reaction: "It was watching out for me."
Why it works: This is the moment FRIDAY stops being a tool and becomes a companion. The trust is permanent after this.

### Key Features (Priority Order)

**Must-Have for Launch (v1.0):**
1. Menu bar presence with status indicator
2. Global hotkey command bar (Cmd+Shift+F)
3. Google OAuth onboarding (Gmail + Calendar)
4. Proactive first briefing on connect
5. Native macOS notifications for all FRIDAY events
6. Voice (Hey Friday trigger word + push-to-talk)
7. Settings UI for API keys and connections (no .env editing)

**v1.1 (2 weeks after launch):**
8. macOS widgets (small, medium, large)
9. Gesture control toggle from menu bar
10. WhatsApp QR scan in-app
11. SMS/Twilio setup wizard

**v1.2 (month after launch):**
12. Neural Band BLE pairing UI
13. Health dashboard widget
14. Notification actions (reply from notification)
15. Keyboard shortcuts customisation

### Technical Implementation

**SwiftUI ↔ FridayCore bridge:**

Two options:

**Option A: Embedded Python (recommended)**
```
macOS App (SwiftUI)
  │
  │  Local WebSocket (ws://localhost:18789)
  │
  ▼
FridayCore (Python, bundled with app)
  ├── Same codebase as CLI
  ├── Packaged via PyInstaller or embedded Python.framework
  ├── Runs as background process, started by app
  └── All data in ~/.friday/
```

Pros: exact same code, no API to build, works offline.
Cons: app bundle is larger (~200MB with Python + dependencies).

**Option B: Local HTTP API**
```
macOS App (SwiftUI)
  │
  │  HTTP POST to localhost:8741
  │
  ▼
FRIDAY Server (Python, separate process)
  ├── FastAPI/Flask exposing FridayCore
  ├── Endpoints: /command, /briefing, /status, /health
  ├── WebSocket for streaming responses
  └── Started by app on launch, killed on quit
```

Pros: clean separation, app is small, server can run independently.
Cons: need to build + maintain an API layer.

**Recommendation:** Option A for v1 (ship fast, works identical to CLI), migrate to Option B when FRIDAY Cloud exists (same API serves both local app and cloud).

---

## FRIDAY iOS App

### First Principles

The iOS app is NOT a remote terminal. It's a **companion** — like having FRIDAY in your pocket. The Mac does the heavy lifting. The phone is how you stay connected to FRIDAY when you're away from your desk.

The app needs to work in three modes:
1. **Connected to Mac/Hub** (via Tailscale) — full power, all tools
2. **Connected to FRIDAY Cloud** — full power, no Mac needed
3. **Standalone** (no connection) — basic AI chat via cloud LLM, no tools

### Architecture

```
iOS App (SwiftUI)
├── Chat Interface (primary)
│   ├── Text FRIDAY like iMessage
│   ├── Voice messages (tap to talk)
│   ├── Streaming responses (tokens appear live)
│   ├── Rich responses: emails rendered as cards, calendar as timeline
│   ├── Quick actions: "Check email" "Briefing" "TV off" as bubbles
│   └── Conversation history synced across devices
│
├── Dashboard (swipe right)
│   ├── Health vitals (if Neural Band connected)
│   │   ├── Heart rate (live), HRV, stress score
│   │   ├── SpO2, skin temp
│   │   └── Trends: daily, weekly, monthly charts
│   ├── Active watches: who's being monitored, last action
│   ├── TV status: what's playing, volume, on/off toggle
│   ├── Unread emails: count + top 3 senders
│   ├── Next calendar event
│   └── Quick actions: mute TV, check email, run briefing
│
├── Smart Home Remote (swipe left)
│   ├── TV: power, volume slider, app launcher, remote buttons
│   ├── Lights (when integrated): on/off, brightness, color
│   ├── Scenes: "movie mode" (TV on, lights dim), "leaving" (all off)
│   └── All controls route through FRIDAY → actual device commands
│
├── Voice (always-available)
│   ├── Tap mic button → push-to-talk
│   ├── "Hey Friday" trigger (when app is foregrounded)
│   ├── Siri Shortcut: "Hey Siri, ask FRIDAY" → routes to app
│   ├── Response via speaker or text
│   └── Works on Bluetooth (car, AirPods)
│
├── Neural Band Integration
│   ├── BLE pairing flow
│   ├── Live gesture feed (which gesture is detected)
│   ├── Calibration screen (2-min training)
│   ├── Gesture → command mapping editor
│   ├── Health monitoring dashboard
│   └── Emergency settings (contacts, thresholds)
│
├── Glasses Integration (future)
│   ├── Glasses status (battery, connection)
│   ├── Display settings (brightness, position)
│   ├── What FRIDAY sees (camera feed snapshot)
│   └── Acts as the compute bridge (phone LLM for glasses)
│
├── Push Notifications (native APNs)
│   ├── Watch task replies: "FRIDAY replied to Ellen's Pap"
│   ├── Briefing summaries: morning/evening
│   ├── Health alerts: heart rate, stress, fall detected
│   ├── Emergency: distress signal activated
│   ├── Smart home: "TV has been on for 4 hours"
│   └── Actionable: reply, dismiss, open context
│
├── Widgets (iOS home screen + Lock Screen)
│   ├── Small: next event + email count
│   ├── Medium: briefing + quick actions (3 buttons)
│   ├── Large: health + calendar + email + TV status
│   ├── Lock Screen: heart rate + next event
│   └── Interactive: tap widget → action fires immediately
│
├── Watch Complication (Apple Watch, future)
│   ├── Heart rate from Neural Band (displayed on Watch face)
│   ├── Quick command: tap → "Hey Friday, catch me up"
│   └── Emergency button: force press → distress protocol
│
└── Shortcuts Integration
    ├── "Ask FRIDAY" action — pass any text, get response
    ├── "FRIDAY Briefing" — run full briefing, return summary
    ├── "FRIDAY TV" — pass command ("mute", "netflix", "off")
    ├── "FRIDAY Emergency" — trigger distress protocol
    └── All available to Siri: "Hey Siri, ask FRIDAY to mute the TV"
```

### The iOS Onboarding (First 90 Seconds)

```
STEP 1: Download from App Store (0-5 seconds)
├── App icon: FRIDAY logo (clean, recognisable)
└── Open → splash: "FRIDAY — Your AI."

STEP 2: How do you run FRIDAY? (5-15 seconds)
├── Three options presented:
│   ├── "I have a Mac running FRIDAY" → Tailscale pairing
│   ├── "I want FRIDAY Cloud" → sign up ($12/mo or free trial)
│   └── "I have a FRIDAY Home Hub" → LAN discovery
└── Each path = 2-3 taps to connect

STEP 3: Connect accounts (15-40 seconds)
├── "Sign in with Google" → Gmail + Calendar
├── Skip for now (can add later)
└── Basic features work immediately

STEP 4: First Wow on Phone (40-60 seconds)
├── FRIDAY runs a quick briefing:
│   "3 unread emails. Work at 2pm. No missed calls."
├── Below the briefing: quick action buttons
│   [Check Email] [TV Off] [Briefing] [Voice]
├── User taps one → FRIDAY does it → "Done."
└── Value delivered in under a minute on phone

STEP 5: Permissions (60-90 seconds, progressive)
├── "Enable notifications?" → Yes (most users will)
├── "Enable Siri Shortcut?" → Yes
├── Neural Band detected? → "Pair now?"
└── Each permission unlocks visible new capability
```

### The iOS Wow Moments

**Wow 1: "I controlled my TV from the bus" (Day 1)**

User is on the bus home. Opens FRIDAY app on phone. Types: "turn on the TV and put on Netflix". TV at home turns on. Netflix launches. User walks in the door to Netflix playing.

Reaction: "I just turned on my TV from the bus."
Why it matters: This is the "future is here" moment. Nobody does this from a chat app.

**Wow 2: "It texted my friend FOR me" (Day 2)**

Notification on phone: "💛 FRIDAY Watch — replied to Teddy Bear: 'He's on his way home, should be there in 20.'"
User checks iMessage — FRIDAY's reply is there, matching the conversation tone perfectly.

Reaction: Screenshots it, sends to group chat.
Why it matters: AI that talks to real people on your behalf. Nobody else does this.

**Wow 3: "Siri actually worked" (Day 3)**

User driving. "Hey Siri, ask FRIDAY to check my email." Siri passes it to FRIDAY Shortcut. FRIDAY processes. Siri reads back: "FRIDAY says: 2 new emails. One from Stripe about a failed payment, one from LinkedIn."

Reaction: "Siri never actually does what I want. But through FRIDAY it worked?"
Why it matters: Turns Siri from useless into a FRIDAY relay. Apple's weakness becomes your strength.

**Wow 4: "The health thing caught something" (Week 1, with Neural Band)**

Notification at 11pm: "Your stress level has been elevated for 3 hours. HRV is 23ms (your average is 45ms). Want me to guide a breathing exercise?"
User taps "Yes" → FRIDAY guides 4-7-8 breathing. Heart rate visibly drops on the dashboard.

Reaction: "My $400 Apple Watch never told me I was stressed."
Why it matters: Proactive health insight that leads to action. Not just data — intervention.

**Wow 5: "The widget just works" (Week 1)**

User adds FRIDAY widget to home screen. Glances at phone:
```
┌─────────────────────────┐
│ FRIDAY                  │
│ ♥ 72 BPM  😌 Stress: Low │
│ 📧 2 unread  📅 Work 2pm  │
│ [Briefing] [TV Off] [Mute]│
└─────────────────────────┘
```
Taps "TV Off" from home screen. TV turns off.

Reaction: "I turned off my TV from my home screen."
Why it matters: No app open. No voice command. One tap on a widget.

**Wow 6: "Emergency actually called" (whenever — hopefully never)**

User makes distress signal (4 fingers up, thumb tucked). Neural Band detects it. Phone vibrates silently. Screen shows: "Emergency detected. Calling 999 in 10 seconds. Tap to cancel."

10 seconds pass. Phone calls 999. FRIDAY speaks: "This is FRIDAY, an AI assistant. My user needs help at [address]. Heart rate is 95 BPM, stress level is elevated. Please send help."

Simultaneously: SMS sent to emergency contacts with GPS.

Reaction: This isn't a wow moment. This is the moment FRIDAY becomes something you'd never uninstall.
Why it matters: Trust. Permanent, unshakeable trust.

### iOS Feature Priority

**v1.0 (launch):**
1. Chat interface with streaming responses
2. Tailscale / Cloud / Hub connection
3. Google OAuth (email + calendar)
4. Push notifications for all FRIDAY events
5. Quick action buttons (check email, briefing, TV control)
6. Siri Shortcuts integration
7. Basic widgets (small + medium)

**v1.1 (2 weeks):**
8. Smart home remote tab (TV controls)
9. Large widget with health data
10. Voice (push-to-talk in-app)

**v1.2 (month):**
11. Neural Band BLE pairing + health dashboard
12. Lock Screen widgets
13. Gesture calibration UI
14. Notification actions (reply inline)

**v2.0 (quarter):**
15. Glasses pairing + camera feed
16. Apple Watch complication
17. Full offline mode (on-device Gemma via CoreML)
18. Family sharing (Ellen can use FRIDAY from her phone)

### macOS + iOS Sync

Both apps share the same FRIDAY backend. The sync model:

```
Mac App                     iOS App
   │                           │
   │  ┌─────────────────────┐  │
   └──│   FRIDAY Backend    │──┘
      │                     │
      │  Option A: Mac      │  ← iOS connects via Tailscale
      │  Option B: Hub      │  ← iOS connects via LAN/Tailscale
      │  Option C: Cloud    │  ← Both connect to hosted FRIDAY
      └─────────────────────┘

Synced:
├── Conversation history
├── Memory (ChromaDB)
├── Watch tasks
├── Cron jobs
├── Settings
└── Health data

Not synced (device-specific):
├── Camera/gesture (Mac only, or glasses)
├── Neural Band BLE (paired to one device)
└── Notification preferences
```

### The "Series of Wow Events" Strategy

Don't dump all features on Day 1. Progressive revelation over the first 2 weeks:

| Day | Unlock | Wow |
|-----|--------|-----|
| Day 1 | Email + Calendar | "It briefed me without asking" |
| Day 1 | TV control | "It actually turned on my TV" |
| Day 2 | iMessage | "It read my messages" |
| Day 3 | Voice | "I just talked to my menu bar" |
| Day 3 | Gesture | "I raised my fist and my TV muted" |
| Day 4 | Watch tasks | "It replied to my friend while I slept" |
| Day 5 | SMS | "I texted FRIDAY from my dumb phone" |
| Day 7 | Job agent | "It tailored my CV and filled the form" |
| Day 10 | Deep research | "It wrote a 30-page report" |
| Day 14 | Health (Neural Band) | "It told me I was stressed before I knew" |

Each "wow" is spaced to prevent overwhelm and create a reason to come back every day. The app should surface suggestions: "Did you know FRIDAY can watch your messages? Try: 'watch Mom's messages for the next hour'"

This turns onboarding from a one-time setup into a **two-week discovery journey** where the product gets more impressive every day.

*Last updated: 2026-04-12*
