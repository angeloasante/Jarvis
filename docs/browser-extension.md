# FRIDAY Browser Bridge (Chrome Extension)

A Chrome extension that lets FRIDAY agents act in the user's **real**
Chrome session — alongside the existing headless Playwright path.

| | Playwright (`browser_*` tools) | Browser bridge (`browser_ext_*` tools) |
|---|---|---|
| Where the browser lives | A separate Chromium FRIDAY launches | Your real Chrome — same tabs you're already in |
| Logged-in sessions | Cold every time | Works automatically — cookies, password manager, SSO |
| Visual feedback to the user | Hidden by default | Spinning gradient ring + page-wide "AI is reading" overlay |
| Anti-bot detection | Detectable (`navigator.webdriver`) | Indistinguishable from a human |
| Cross-browser | Chromium + Firefox + WebKit | Chrome / Edge only |
| Concurrent agents | Many tabs, many contexts | One real Chrome at a time |
| Speed of action | Direct DOM API, ~10 ms | WebSocket round-trip, ~30–100 ms |

The two are designed to coexist. Agents pick based on phrasing — "open
… on my browser", "fill the form on my screen", "apply on LinkedIn" →
extension; headless research / parallel scraping → Playwright.

---

## 1. Architecture

```
                       FRIDAY process                              your real Chrome
                       ──────────────                              ────────────────
  ┌─────────────────┐                                          ┌──────────────────┐
  │ browser_ext_    │       ┌─────────────────────────┐        │ background.js     │
  │ tools.py        │──────►│ browser_ext/bridge.py   │◄══WS══►│  (service worker) │
  │   navigate()    │       │   ws://127.0.0.1:3210   │        │                   │
  │   click()       │       │   action queue          │        │  ↓ chrome.tabs    │
  │   fill()        │       │   snapshot store        │        │   sendMessage     │
  │   get_text()    │       │   token auth            │        │                   │
  │   highlight()   │       └─────────────────────────┘        │ content_script.js │
  │   scan()        │                                          │ ─ DOM ops         │
  └─────────────────┘                                          │ ─ overlay CSS     │
         ↑                                                      └──────────────────┘
         │                                                              │
   used by:                                                       lives in tabs
     system_agent ("fill the form on my screen")
     job_agent   ("apply on linkedin")
```

**Three modules, three jobs:**

- [`friday/browser_ext/bridge.py`](../friday/browser_ext/bridge.py) — async WebSocket server. One extension at a time; second connection replaces the first. Auth via `FRIDAY_BROWSER_EXT_TOKEN` (auto-minted on first start).
- [`friday/tools/browser_ext_tools.py`](../friday/tools/browser_ext_tools.py) — 10 LLM-facing tools that send JSON actions over the bridge and await structured results. Fail gracefully when no extension is connected (returns `ToolResult(success=False, ErrorCode.CONFIG_MISSING)`, never raises).
- [`extension/browser-bridge/`](../extension/browser-bridge/) — the Chrome extension itself: manifest, service worker, content script, popup.

---

## 2. Setup

```bash
friday setup browser-ext
```

Walks you through:

1. Open `chrome://extensions`
2. Toggle **Developer mode**
3. **Load unpacked** → pick `extension/browser-bridge/`
4. Click the FRIDAY toolbar icon → paste the token shown in the wizard → **Save & Connect**

The token also lives in `~/Friday/.env` as `FRIDAY_BROWSER_EXT_TOKEN`. Same value used by the bridge to authenticate the extension's `hello` message.

To verify:

```bash
friday               # in the repl:
> /browser-ext       # → ":: Browser-ext bridge — CONNECTED  (port 3210)"
                     # → "extension: FRIDAY Browser Bridge  v0.1.0  tabs=14"
```

`friday doctor` also has a row for the bridge.

---

## 3. Wire protocol

WebSocket, JSON-per-message. Documented in [`friday/browser_ext/protocol.py`](../friday/browser_ext/protocol.py).

### Inbound (extension → bridge)

| Type | Purpose |
|---|---|
| `hello` | First message after connect. `{type, token, name, version}` |
| `heartbeat` | Tabs list + liveness, every 5 s |
| `result` | Response to a previously-pushed action: `{type, id, ok, data, error}` |
| `snapshot` | Unsolicited tab summary (DOM diff or full text) |
| `dom_event` | Page-side observation worth knowing about |

### Outbound (bridge → extension)

Every action message has the same envelope: `{id, action, metadata}`. The extension replies with a `result` matching `id`.

| Action | Where it runs | What it does |
|---|---|---|
| `ping` | service worker | Round-trip latency check |
| `navigate` | service worker | `chrome.tabs.update(tabId, {url})` |
| `get_active_tab` | content script | Returns URL, title, readable text |
| `list_tabs` | service worker | Every open tab |
| `click` | content script | CSS-selector OR visible-text targeting |
| `fill` | content script | Sets `.value` via React-friendly setter + dispatches `input`/`change` |
| `get_text` | content script | Cleaned `innerText`; drops scripts/styles/nav/aside/footer |
| `scroll` | content script | Absolute or relative |
| `scanning_start` | content script | Page-wide "AI analysing" overlay (gradient frame + moving beam + label pill) |
| `scanning_stop` | content script | Tear it down early |
| `highlight` | content script | Spinning conic-gradient ring on a specific element |

### Auth

Single-token model. The bridge mints a URL-safe 24-byte token on first start and writes it to `~/Friday/.env`. The extension popup asks for it once and stores it in `chrome.storage.local`. Each connection's `hello` message must echo it.

If the token is wrong, the bridge closes with code `1008 / "bad token"` and the extension stops auto-reconnecting until the user updates the token in the popup.

---

## 4. Visual overlay

Borrowed in spirit from [Moonwalk](https://github.com/OactoDev/Moonwalk) (MIT). Three CSS layers, all at `z-index: 2147483646`+ so page CSS can't override them:

```css
.friday-scanning-frame    /* gradient border around viewport */
.friday-scanning-beam     /* horizontal scan line top → bottom */
.friday-scanning-label    /* pill: "FRIDAY analysing page…" */

/* per-element */
.friday-hl::before        /* spinning conic-gradient ring */
```

Key tricks (lifted directly):

- **`@property --fr-angle`** — Houdini custom property (Chrome 85+) that animates a CSS variable as an angle. The conic gradient rotates via keyframes alone, no JS spin loop, no jank.
- **Mask-composite XOR** — cuts the inside of the gradient out so it only shows in a 2 px ring around the element. Precise glow without a wrapper element.
- **`isolation: isolate`** — fresh stacking context per highlighted element so neighbouring `z-index` from page CSS can't interfere.

Used automatically:

- `browser_ext_click` flashes the target element 600 ms before the click
- `browser_ext_fill` flashes the input as it types
- `browser_ext_scan` is a manual call before long page-reads — gives the user feedback that FRIDAY is doing something, even when the actual work is invisible

---

## 5. LLM-facing tools

| Tool | Use case |
|---|---|
| `browser_ext_navigate(url)` | "open YouTube" / "go to anthropic.com on my browser" |
| `browser_ext_get_active_tab()` | "fill the form on my screen", "summarise what I'm reading" |
| `browser_ext_list_tabs()` | "what tabs do I have open" |
| `browser_ext_click(selector OR text)` | Form submit buttons, links, login flows |
| `browser_ext_fill(selector, value)` | Type into inputs (React/Vue/Angular safe) |
| `browser_ext_get_text(selector?)` | Read logged-in pages (private dashboards, subscription content) |
| `browser_ext_scroll(x, y, by?)` | Position-based scrolling |
| `browser_ext_scan(label, duration_ms)` | Show the page-wide "AI is reading" overlay |
| `browser_ext_highlight(selector OR text)` | Draw the user's attention to an element |
| `browser_ext_status()` | Diagnostic — connection state |

All ten are loaded into:

- `system_agent` — primary home, "do something on the screen" cases
- `job_agent` — for sites that fingerprint headless Chrome (LinkedIn, Greenhouse) or need MFA-protected sessions

When the extension isn't connected, every tool returns:

```python
ToolResult(success=False, error=ToolError(
    code=ErrorCode.CONFIG_MISSING,
    message=("FRIDAY browser extension isn't connected. "
             "Install it (chrome://extensions → Load unpacked → "
             "extension/browser-bridge/) and paste your "
             "FRIDAY_BROWSER_EXT_TOKEN into the popup."),
    severity=Severity.LOW, recoverable=True,
))
```

The agent sees the failure and falls back to the Playwright tools (`browser_navigate` etc.) without further user intervention.

---

## 6. Diagnostics

```bash
# In FRIDAY repl
/browser-ext        # one-line status

# Or directly
curl -sv ws://127.0.0.1:3210 2>&1 | head     # nothing — it's a WebSocket, not HTTP

# Watch the bridge log
tail -f ~/Library/Logs/friday.log | grep "browser_ext"
```

**Common issues:**

| Symptom | Cause | Fix |
|---|---|---|
| Popup says `✗ Not connected — no token` | First install, no token saved | Paste `FRIDAY_BROWSER_EXT_TOKEN` from `~/Friday/.env` |
| Popup says `✗ Not connected — bad token` | Token in popup ≠ token in `~/Friday/.env` | Re-paste from `friday setup browser-ext` |
| `connect-src` CSP error in DevTools console | Manifest CSP doesn't allow `ws://127.0.0.1:*` | Already permitted in `manifest.json`. If a custom build edited it, restore. |
| Connects then drops every ~30 s | Heartbeats stopped reaching the bridge (e.g. service worker terminated by Chrome) | Click the toolbar icon to reactivate, or open a new tab — Chrome wakes the worker. |
| Tools time out on `chrome://` pages | Content scripts can't run on chrome:// or extension pages | Switch to a regular tab. |

---

## 7. Security notes

- The bridge is bound to `127.0.0.1` only — no external network access. A token check still runs on every connection because other local processes (different Macs apps, dev tools, etc.) could in theory open the port.
- The extension has `host_permissions: <all_urls>` — it can read and modify every page you visit. That's the same permission level as 1Password, Grammarly, etc. The popup shows which token is bound so you can revoke it from `chrome://extensions` at any time.
- No telemetry. The extension never talks to any server other than `ws://127.0.0.1:3210`. Manifest CSP enforces this.
- Visual overlay is local-only — nothing is uploaded or recorded.

---

## See also

- [`friday/browser_ext/bridge.py`](../friday/browser_ext/bridge.py) — bridge implementation
- [`friday/browser_ext/protocol.py`](../friday/browser_ext/protocol.py) — full message-type list
- [`friday/tools/browser_ext_tools.py`](../friday/tools/browser_ext_tools.py) — LLM-facing tool surface
- [`extension/browser-bridge/`](../extension/browser-bridge/) — extension source
- Headless complement: [`friday/tools/browser_tools.py`](../friday/tools/browser_tools.py) — Playwright path
