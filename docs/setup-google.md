# Connecting Gmail + Google Calendar to FRIDAY

## Overview

FRIDAY ships with its own shared OAuth 2.0 client bundled inside the package (`friday/data/google_client.json`), so hooking up Gmail and Google Calendar is a one-step "Sign in with Google" flow — exactly like clicking the Sign in button in the Mac app's Settings pane. You do **not** need to create a Google Cloud project, enable APIs, or register an OAuth client of your own. Just run `friday setup gmail`, consent in the browser, and FRIDAY can read your mail, send drafts, check your calendar, and create events straight from the CLI, Mac app, or voice.

---

## How it works under the hood

### OAuth client resolution order

Every time FRIDAY needs Google credentials, `friday/tools/google_auth.py` walks a short resolution chain:

1. **Bundled client** — `friday/data/google_client.json`
   Ships inside the `friday-os` pip package. This is what 99% of users hit. It's a shared client that FRIDAY uses for everyone, so there's no quota config for you to worry about. Wins if it exists.

2. **User-provided client** — `~/.friday/google_credentials.json`
   Power-user override. If you've created your own Google Cloud project and want FRIDAY to use your OAuth client instead of the shared one, drop the downloaded `client_secrets.json` here and rename it. Only consulted if the bundled client is missing (e.g. you stripped it from a custom build).

The exact code:

```python
FRIDAY_DIR      = Path.home() / ".friday"
BUNDLED_CLIENT  = Path(__file__).parent.parent / "data" / "google_client.json"
USER_CLIENT     = FRIDAY_DIR / "google_credentials.json"
TOKEN_FILE      = FRIDAY_DIR / "google_token.json"

def _active_client_path() -> Path | None:
    if BUNDLED_CLIENT.exists():
        return BUNDLED_CLIENT
    if USER_CLIENT.exists():
        return USER_CLIENT
    return None
```

### Token caching

Regardless of which OAuth client signed you in, the resulting per-user access + refresh token pair is cached at:

```
~/.friday/google_token.json
```

This file is yours alone — the bundled client only issues it; it never leaves your machine. FRIDAY auto-refreshes the access token using the refresh token on every call, so once you've signed in you rarely re-auth. If refresh fails (e.g. you revoked access from Google's side), FRIDAY deletes the token and the next tool call tells you to re-run `friday setup gmail`.

---

## Scopes granted

FRIDAY asks for exactly these OAuth scopes during the consent screen (from `SCOPES` in `google_auth.py`):

```python
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
]
```

Plain English:

| Scope | What it lets FRIDAY do |
| --- | --- |
| `gmail.readonly` | Read messages, threads, labels — no writes. Powers `read_emails`, `search_emails`, `read_email_thread`. |
| `gmail.send` | Send mail on your behalf. Only fires when you explicitly confirm. Powers `send_email` and `send_draft`. |
| `gmail.modify` | Add/remove labels (STARRED, TRASH, SPAM, custom). Powers `label_email`. |
| `gmail.compose` | Create and edit drafts. Drafts land in your Gmail Drafts folder for review before sending. Powers `draft_email` and `edit_draft`. |
| `calendar.readonly` | Read events from any calendar you own (legacy fallback — FRIDAY's active calendar tool reads from macOS Calendar via AppleScript). |
| `calendar.events` | Create/modify events on your primary calendar. Paired with `calendar.readonly` for a future Google-first calendar tool. |
| `userinfo.email` | Fetch the email address of the signed-in account so the Mac app can show you who's connected. |
| `userinfo.profile` | Fetch the display name + profile picture for the Settings footer in the Mac app. |
| `openid` | Standard OIDC — lets `userinfo.*` work. |

FRIDAY never requests offline Drive, Contacts, Photos, or account-management scopes. If a future version needs one, the scope list grows, and you'll see a re-consent prompt the next time you auth.

---

## Setup

### Standard path — 99% of users

```bash
friday setup gmail
```

The wizard:

1. Tells you about the unverified-app warning you're about to see.
2. Prompts "Open the browser to sign in?" — hit Enter.
3. Opens your default browser to Google's consent screen.
4. You pick a Google account.
5. You see a red-ish warning screen that says **"Google hasn't verified this app"**. Click **Advanced**, then **Go to FRIDAY (unsafe)**. That label is Google's default wording for every community-built OAuth app that hasn't paid for their verification review. It doesn't mean the app is actually unsafe — it means Google hasn't looked at the code yet.
6. Review the requested scopes, click **Continue**.
7. The browser redirects to a localhost page saying "The authentication flow has completed". You can close the tab.
8. Terminal prints `AUTHENTICATED: you@example.com|Your Name` and saves the token.

Total time: ~20 seconds.

### Power-user path — bring your own OAuth client

Do this if you want your own Google Cloud quota, want to run the app through Google's verification review, or just prefer not to use FRIDAY's shared client.

1. Go to the [Google Cloud Console](https://console.cloud.google.com) and create a new project (or pick an existing one).
2. Enable the **Gmail API** and **Google Calendar API** for that project (APIs & Services → Library).
3. Configure an OAuth consent screen (APIs & Services → OAuth consent screen). External + testing mode is fine for personal use.
4. Create an OAuth 2.0 Client ID of type **Desktop app** (APIs & Services → Credentials → Create Credentials → OAuth client ID).
5. Download the JSON. Move it to:
   ```bash
   mkdir -p ~/.friday
   mv ~/Downloads/client_secret_*.json ~/.friday/google_credentials.json
   ```
6. Delete the bundled client so FRIDAY falls through to yours (optional — only needed if you're on a source checkout and want to force user-client behavior):
   ```bash
   rm $(python -c "import friday, pathlib; print(pathlib.Path(friday.__file__).parent / 'data' / 'google_client.json')")
   ```
   Then run `friday setup gmail` as normal.

---

## Why you'd use BYO

- **Remove the unverified-app warning.** Once you've gone through Google's verification review, your users (or you) no longer see the red Advanced screen.
- **Your own rate limits.** Gmail API has generous default quotas; for heavy automation a dedicated project gives you a known ceiling and its own dashboards.
- **Privacy.** Nothing about the shared client exposes your data — Google issues a token scoped to your account, and only your machine holds it — but some users prefer knowing every OAuth hop is under their own GCP account for audit/isolation reasons.
- **Verification path.** If you fork FRIDAY and ship it to others, BYO is a prerequisite for submitting the app to Google for verification.

---

## What you can do once connected

Ten tools become available: 8 for email, 2 for calendar.

### Email tools (`friday/tools/email_tools.py`)

All eight tools are async and return a `ToolResult` with structured `data` plus metadata. Write operations (`send_email`, `send_draft`, `create_event`) require `confirm=True` as a safety gate — calling them without confirmation returns a preview and the instruction to call again with `confirm=True`.

| Tool | What it does | Example prompt |
| --- | --- | --- |
| `read_emails` | Fetches inbox mail, sorted by priority (senders like Stripe/Paystack/GitHub float up). Filter by `unread`, `today`, `urgent`, or any Gmail query like `from:devpost`. | "check my unread emails" / "any emails from devpost?" |
| `search_emails` | Full Gmail search syntax (`from:`, `subject:`, `has:attachment`, `before:`, `after:`). Returns bodies. | "find emails about the Railway bill last month" |
| `read_email_thread` | Pulls an entire conversation by thread ID, with all message bodies. | "read the full thread for that email" |
| `draft_email` | Creates a Gmail draft in your Drafts folder. Does not send. | "draft a reply to mum saying I'll be home Sunday" |
| `edit_draft` | Updates any field of an existing draft. Leave fields blank to keep them. | "change the draft to cc Ellen" |
| `send_email` | Sends a new email. Requires `confirm=True` — FRIDAY always previews first. | "send it" (after a draft is reviewed) |
| `send_draft` | Sends an existing Gmail draft by ID. Requires `confirm=True`. | "send draft r-8289…" |
| `label_email` | Add/remove labels — `STARRED`, `IMPORTANT`, `TRASH`, `SPAM`, or any custom label. | "archive this" / "star that email from Paystack" |

Signatures, condensed:

```python
async def read_emails(filter: str = "all", limit: int = 10,
                     include_body: bool = False, label: str = "INBOX") -> ToolResult
async def search_emails(query: str, limit: int = 10) -> ToolResult
async def read_email_thread(thread_id: str) -> ToolResult
async def draft_email(to: str, subject: str, body: str) -> ToolResult
async def edit_draft(draft_id: str, to: str = None,
                     subject: str = None, body: str = None) -> ToolResult
async def send_email(to: str, subject: str, body: str,
                     reply_to_thread_id: Optional[str] = None,
                     confirm: bool = False) -> ToolResult
async def send_draft(draft_id: str, confirm: bool = False) -> ToolResult
async def label_email(email_id: str, add_labels: list[str] = None,
                     remove_labels: list[str] = None) -> ToolResult
```

Priority tagging: `read_emails` sorts by sender reputation. Senders matched in `PRIORITY_SENDERS` (Paystack and Stripe are "critical"; Railway, Modal, GitHub are "high") bubble up first, so you don't miss billing or deploy mail in a full inbox.

### Calendar tools (`friday/tools/calendar_tools.py`)

These actually read from **macOS Calendar** via AppleScript, which means they cover iCloud, Google Calendar, Exchange, and any other account you've synced to the Mac Calendar app — no Google token needed for read/write. The Google Calendar scopes are kept in the OAuth consent so a future cross-platform calendar path can use them directly.

| Tool | What it does | Example prompt |
| --- | --- | --- |
| `get_calendar` | Lists events for `today`, `tomorrow`, `next_event`, or any ISO date. View `day` or `week`. | "what's on my calendar tomorrow?" / "next event?" |
| `create_event` | Creates an event in the selected macOS calendar (which syncs to iCloud/Google). Requires `confirm=True`. | "book dentist Friday at 3pm for 45 minutes" |

```python
async def get_calendar(date: str = "today", view: str = "day") -> ToolResult
async def create_event(title: str, date: str, start_time: str,
                       duration: int = 30, calendar_name: str = "Calendar",
                       location: Optional[str] = None,
                       description: Optional[str] = None,
                       confirm: bool = False) -> ToolResult
```

`get_calendar` also flags events scheduled between 10pm and 4am with a `warning` field so FRIDAY can nudge you if you're booking over coding hours.

---

## Testing

Once you've signed in, verify everything works:

```bash
friday test gmail
```

The test fetches one unread email via `read_emails(filter="unread", limit=1)` and prints the result. Success looks like:

```
Test · Gmail ──────────────────────────────────
  ✓ fetched 1 unread email(s)
```

Failure modes and what they mean are covered below.

---

## Troubleshooting

### "This app isn't verified"

**What you see:** A red-accented Google screen mid-sign-in that says FRIDAY hasn't been verified.

**What it means:** FRIDAY's shared OAuth client hasn't (yet) been submitted to Google's app verification program. Google surfaces this warning for every community-built OAuth app until it has.

**What to do:** Click **Advanced**, then **Go to FRIDAY (unsafe)**. Consent to the scopes. That's it — the warning is a one-time prompt per account.

### Token refresh failures

**Symptom:** `friday test gmail` fails with an auth error, or tools return `Google API not configured`.

**Fix:** Delete the cached token and re-authenticate.

```bash
rm ~/.friday/google_token.json
friday setup gmail
```

This happens if you revoked FRIDAY's access from Google, if the refresh token expired (rare but possible after very long inactivity), or if the stored token file got corrupted.

### "Insufficient permissions" / scope errors

**Symptom:** A specific Gmail call fails citing missing scopes, usually after FRIDAY updates its scope list.

**Fix:** The cached token was granted with an older scope set. Re-auth to update.

```bash
rm ~/.friday/google_token.json
friday setup gmail
```

You'll see the consent screen once more and the new scopes will be attached.

### 100-user cap

**Symptom:** During sign-in, Google says the app has reached its user limit.

**What it means:** Unverified OAuth apps are capped at 100 distinct users across all of Google. As FRIDAY grows this can bump against the ceiling on the shared client.

**What to do:** Use the bring-your-own path above — create your own GCP project and point `~/.friday/google_credentials.json` at your own client. Your own project has its own 100-user ceiling (and no ceiling at all if you submit for verification). For the shared client, watch the repo for news on FRIDAY's verification status.

---

## Mac app integration

The Mac app's Settings pane has a "Sign in with Google" button. Behind the scenes, `Friday-mac/.../GmailAuth.swift` shells out to the same Python module the CLI uses:

```
python -m friday.tools.google_auth
```

It parses the `AUTHENTICATED: email|name` line that `authenticate()` prints on success to populate the profile footer. This means:

- Signing in via the Mac app Settings button is **exactly equivalent** to running `friday setup gmail` in the terminal.
- Tokens saved by one are picked up by the other — same `~/.friday/google_token.json`.
- Signing out of the Mac app deletes that same file.

So pick whichever surface you prefer; they share state.

---

## Revoking access

Two things to do, in order:

1. Revoke FRIDAY's token on Google's side. Visit:
   **https://myaccount.google.com/permissions**
   Find FRIDAY in the list, click it, then "Remove access".

2. Delete the local token cache so FRIDAY stops trying to use it:
   ```bash
   rm ~/.friday/google_token.json
   ```

That's a full disconnect — the next tool call will tell you Google isn't configured, and you can re-auth any time with `friday setup gmail`.

---

## File reference

- `/Users/travismoore/Desktop/JARVIS/friday/tools/google_auth.py` — OAuth client resolution, scopes, token caching, profile fetch
- `/Users/travismoore/Desktop/JARVIS/friday/tools/email_tools.py` — 8 Gmail tools + schemas
- `/Users/travismoore/Desktop/JARVIS/friday/tools/calendar_tools.py` — 2 calendar tools (macOS Calendar via AppleScript)
- `/Users/travismoore/Desktop/JARVIS/friday/core/setup_wizard.py` — `setup_gmail()` wizard, `test_gmail()` verifier
- `/Users/travismoore/Desktop/JARVIS/friday/data/google_client.json` — bundled shared OAuth client (ships with pip install)
- `~/.friday/google_credentials.json` — bring-your-own OAuth client (optional override)
- `~/.friday/google_token.json` — per-user access + refresh token cache
