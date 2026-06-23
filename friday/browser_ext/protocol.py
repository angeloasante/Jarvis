"""Wire-protocol constants for the FRIDAY ⇄ Chrome extension WebSocket.

Both ends speak the same JSON shapes — defining them in one place keeps
the Python and JS sides honest. Anything sent that isn't documented here
gets dropped and logged at DEBUG.
"""

# Server endpoint
WS_HOST = "127.0.0.1"
WS_PORT = 3210         # 3200 = SMS server, 3210 = browser-ext bridge

# ── Inbound message types (extension → bridge) ──────────────────────────────
MSG_HELLO     = "hello"      # first message, includes auth token + ext version
MSG_HEARTBEAT = "heartbeat"  # tabs list + connection liveness
MSG_RESULT    = "result"     # response to a previous action
MSG_SNAPSHOT  = "snapshot"   # full DOM/text snapshot of a tab
MSG_DOM_EVENT = "dom_event"  # spontaneous DOM change notification

# ── Outbound action types (bridge → extension) ──────────────────────────────
# Connection / lifecycle
ACT_PING            = "ping"
ACT_DISCONNECT      = "disconnect"

# Navigation + tab control
ACT_NAVIGATE        = "navigate"          # open url in active or named tab
ACT_GET_ACTIVE_TAB  = "get_active_tab"    # return tab id, url, title, text
ACT_LIST_TABS       = "list_tabs"

# DOM operations
ACT_CLICK           = "click"             # by selector or by visible text
ACT_FILL            = "fill"              # type into an input
ACT_GET_TEXT        = "get_text"          # readable text via Readability.js
ACT_SCROLL          = "scroll"            # scroll-to / scroll-by

# Visual feedback (the "AI is reading" effect)
ACT_SCANNING_START  = "scanning_start"
ACT_SCANNING_STOP   = "scanning_stop"
ACT_HIGHLIGHT       = "highlight"         # spotlight specific elements

# ── Action result codes ─────────────────────────────────────────────────────
OK    = "ok"
ERROR = "error"
TIMEOUT = "timeout"
