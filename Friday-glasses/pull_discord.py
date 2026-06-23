"""
pull_discord.py — one-shot dump of a single Discord channel's history.

Used to pull #general (or any channel) from a server you're already a member of,
to a local JSON file. Ran interactively, once, then deleted.

Usage:
    export DISCORD_USER_TOKEN="<your token from DevTools Network tab>"
    python pull_discord.py <channel_id> [max_messages]

Example:
    export DISCORD_USER_TOKEN="MTIzNDU2..."
    python pull_discord.py 1148712345678901234 5000

Output:
    brilliant_labs_general_<timestamp>.json  (in the current directory)

Safety notes:
    - This hits the Discord HTTP API at normal rate limits (50 msgs per request,
      1 request per ~1.5s). A 5000-message pull takes ~2-3 minutes.
    - Uses a real Chrome user-agent so it looks like a browser session.
    - Runs once, exits. No background activity.
    - Against Discord's ToS on automated access. Low practical risk for a
      one-shot read, but non-zero. Rotate your password afterwards (changes
      token), don't leave this script running.
"""

from __future__ import annotations
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

API = "https://discord.com/api/v9"

# Real Chrome headers so the request looks indistinguishable from the web client.
HEADERS_BASE = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://discord.com/channels/@me",
    "X-Discord-Locale": "en-US",
    "X-Debug-Options": "bugReporterEnabled",
}


def _get(url: str, token: str) -> list[dict]:
    req = urllib.request.Request(url, headers={**HEADERS_BASE, "Authorization": token})
    # Retry loop — if Discord rate-limits (429), sleep and retry once.
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                retry_after = float(e.headers.get("Retry-After", 5))
                print(f"  rate-limited, sleeping {retry_after:.1f}s", file=sys.stderr)
                time.sleep(retry_after)
                continue
            raise


def pull_channel(token: str, channel_id: str, max_messages: int = 5000) -> list[dict]:
    """Paginate backward through history 50 messages at a time."""
    out: list[dict] = []
    before: str | None = None
    batch = 0
    while len(out) < max_messages:
        url = f"{API}/channels/{channel_id}/messages?limit=50"
        if before:
            url += f"&before={before}"
        msgs = _get(url, token)
        if not msgs:
            break
        out.extend(msgs)
        before = msgs[-1]["id"]
        batch += 1
        print(f"  batch {batch}: {len(out):>5} messages so far "
              f"(oldest at {msgs[-1]['timestamp'][:10]})", file=sys.stderr)
        # Be polite — 1.5s between requests well under Discord's official 50/s cap.
        time.sleep(1.5)
    return out[:max_messages]


def main() -> None:
    token = os.environ.get("DISCORD_USER_TOKEN", "").strip()
    if not token:
        sys.exit(
            "DISCORD_USER_TOKEN not set. Grab it from DevTools → Network → "
            "any /api request → Headers → 'authorization'."
        )

    if len(sys.argv) < 2:
        sys.exit("usage: python pull_discord.py <channel_id> [max_messages=5000]")

    channel_id = sys.argv[1]
    max_messages = int(sys.argv[2]) if len(sys.argv) > 2 else 5000

    # Fetch channel metadata for the filename.
    print(f"→ fetching channel {channel_id}…", file=sys.stderr)
    ch = _get(f"{API}/channels/{channel_id}", token)
    guild_id = ch.get("guild_id")
    guild_name = "dm"
    if guild_id:
        guild = _get(f"{API}/guilds/{guild_id}", token)
        guild_name = guild.get("name", "server").lower().replace(" ", "_")

    channel_name = ch.get("name", channel_id).lower().replace(" ", "_")
    print(f"→ server: {guild_name}  channel: #{channel_name}", file=sys.stderr)

    print(f"→ pulling up to {max_messages} messages…", file=sys.stderr)
    messages = pull_channel(token, channel_id, max_messages)

    # Sort oldest → newest for easier reading.
    messages.sort(key=lambda m: m["timestamp"])

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path(f"{guild_name}_{channel_name}_{stamp}.json")
    out_path.write_text(json.dumps({
        "server": guild_name,
        "channel": channel_name,
        "channel_id": channel_id,
        "exported_at": datetime.now().isoformat(),
        "message_count": len(messages),
        "messages": messages,
    }, indent=2, ensure_ascii=False))
    print(f"\n✓ wrote {len(messages)} messages → {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
