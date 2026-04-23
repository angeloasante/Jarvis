"""Telegram bot — second channel alongside SMS.

Uses long polling (no public tunnel required) so it keeps working
when ngrok / Tailscale aren't running. SMS remains the fallback for
no-data / bad-signal scenarios; Telegram handles rich media (50 MB
per file) when you have a connection.
"""
from friday.telegram.bot import start_bot

__all__ = ["start_bot"]
