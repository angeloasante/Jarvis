"""FRIDAY Notifications — send alerts to Travis's iPhone via iMessage to self.

Sends an iMessage to Travis's own number. Instant delivery, real notification.
Later: replace with native FRIDAY iOS app + APNs when the Mac Mini server is set up.
"""

import subprocess
import logging

log = logging.getLogger("friday.notify")

TRAVIS_NUMBER = "+447555834656"


def send_phone_notification(
    title: str,
    body: str = "",
    priority: str = "normal",
) -> bool:
    """Send a notification to Travis's iPhone via iMessage to self.

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

    script = f'''
    tell application "Messages"
        set targetService to 1st account whose service type = iMessage
        set targetBuddy to participant "{TRAVIS_NUMBER}" of targetService
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
