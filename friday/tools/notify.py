"""FRIDAY Notifications — send alerts to the user's iPhone.

Two channels:
  - iMessage to self: instant notification (heartbeat, watch alerts)
  - SMS via Twilio: actual text message (results, proactive delivery)

The recipient is read from ``~/.friday/user.json`` (``phone`` field)
with ``CONTACT_PHONE`` as an env-var override.
"""

import os
import subprocess
import logging

log = logging.getLogger("friday.notify")


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


def send_phone_notification(
    title: str,
    body: str = "",
    priority: str = "normal",
) -> bool:
    """Send a notification to the user's iPhone via iMessage to self.

    Args:
        title: Notification title (e.g. "2 urgent emails unread")
        body: Optional detail text
        priority: "critical", "high", "normal", or "low"

    Returns:
        True if sent successfully.
    """
    # Build message with emoji prefix based on priority
    prefix = {
        "critical": "🚨",
        "high": "⚠️",
        "normal": "🔔",
        "low": "💬",
    }.get(priority, "🔔")

    message = f"{prefix} FRIDAY — {title}"
    if body:
        message += f"\n{body}"

    # Escape for AppleScript
    safe_msg = message.replace("\\", "\\\\").replace('"', '\\"')

    target_number = _user_phone()
    if not target_number:
        log.warning("Skipping phone notification — no phone configured (user.json or CONTACT_PHONE)")
        return False

    script = f'''
    tell application "Messages"
        set targetService to 1st account whose service type = iMessage
        set targetBuddy to participant "{target_number}" of targetService
        send "{safe_msg}" to targetBuddy
    end tell'''

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            log.info(f"Phone notification sent: {title}")
            return True
        log.error(f"Notification failed: {result.stderr}")
        return False
    except Exception as e:
        log.error(f"Notification error: {e}")
        return False


async def notify_phone_async(text: str):
    """Async wrapper for heartbeat/cron callbacks.

    Parses text into title + body. Also prints to CLI.
    """
    from rich.console import Console
    console = Console()

    # Split on first period or dash for title/body
    if " — " in text:
        title, body = text.split(" — ", 1)
    elif ". " in text:
        title, body = text.split(". ", 1)
    else:
        title, body = text, ""

    # Determine priority from content
    low = text.lower()
    if any(w in low for w in ("urgent", "critical", "emergency", "asap")):
        priority = "critical"
    elif any(w in low for w in ("important", "action required")):
        priority = "high"
    else:
        priority = "normal"

    # Send to phone
    send_phone_notification(title=title.strip(), body=body.strip(), priority=priority)

    # Also print to CLI
    console.print(f"\n  [bold yellow]💛 FRIDAY[/bold yellow] [yellow]{text}[/yellow]")
    console.print(f"  [dim yellow]↑ sent to phone[/dim yellow]\n")


def _strip_markdown(text: str) -> str:
    """Strip markdown formatting for plain-text SMS."""
    import re
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)   # **bold** → bold
    text = re.sub(r'\*(.+?)\*', r'\1', text)        # *italic* → italic
    text = re.sub(r'`(.+?)`', r'\1', text)          # `code` → code
    text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)  # ### heading → heading
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)      # images
    text = re.sub(r'\[(.+?)\]\(.*?\)', r'\1', text)  # [link](url) → link
    return text.strip()


async def send_result_sms(text: str) -> bool:
    """Send a FRIDAY result to the user via SMS (Twilio).

    For delivering actual results/content to the user's phone —
    NOT the same as iMessage-to-self notifications. Use this when
    the user says "text me the results" or "send that to me on SMS".

    Strips markdown, truncates to 1500 chars.
    """
    try:
        from friday.tools.sms_tools import send_sms
        to = _user_phone()
        if not to:
            log.error("Result SMS skipped — no phone configured (user.json or CONTACT_PHONE)")
            return False
        text = _strip_markdown(text)
        if len(text) > 1500:
            text = text[:1497] + "..."
        result = await send_sms(to=to, message=text)
        if result.success:
            log.info(f"Result SMS sent to {to}")
            return True
        log.error(f"Result SMS failed: {result.error}")
        return False
    except Exception as e:
        log.error(f"Result SMS error: {e}")
        return False
