"""First-run onboarding + config subcommands for the FRIDAY CLI.

Single config file: ``~/Friday/user.json`` (visible in Finder, chmod 600).
Contains everything FRIDAY knows about the user — identity, tone, slang,
contact aliases, CV, briefing watchlist — so the full picture loads with
the model on every call.

Commands:
    friday            → runs the wizard if user.json is missing, then launches
    friday init       → force re-run the onboarding wizard
    friday config     → show current config path + contents
    friday config edit → open user.json in $EDITOR
    friday config path → print the path
    friday config open → reveal the folder in Finder (macOS)
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.rule import Rule

from friday.core.user_config import (
    CONFIG_PATH,
    FRIDAY_DIR,
    USER,
    UserConfig,
    migrate_from_legacy,
    reload,
    write,
)

console = Console()

README_PATH = FRIDAY_DIR / "README.md"


# ── Visible README inside ~/Friday/ ──────────────────────────────────────────

_README = """# ~/Friday/

This is where FRIDAY stores **your personal config**. Everything it knows
about you is in one file: `user.json`. It's separate from the codebase so
you can update FRIDAY without losing your setup, and nothing personal ever
ends up in git.

## The one file

`user.json` holds:

- **Identity** — `name`, `bio`, `location`, `email`, `phone`, `github`, `website`
- **Voice** — `tone`, `slang` (vocabulary FRIDAY treats as understood)
- **Relationships** — `contact_aliases` (nickname → real person mappings)
- **Briefing watchlist** — X handles and topics for daily briefings
- **CV** — full experience, projects, skills, education — used for job
  applications and injected into the model's context so every answer is
  grounded in who you actually are

## Edit it

```bash
friday init            # interactive wizard
friday config          # print the current contents
friday config edit     # open in $EDITOR
friday config open     # reveal in Finder (macOS)
friday config path     # print the path (scriptable)
```

Or open `user.json` in any JSON editor — it's just a dict.

## Privacy

- The file is chmod 600. Only your user account can read it.
- Nothing here is sent to any LLM unless your prompt actually needs it
  (e.g. drafting an email with your signature pulls from `user.json`).
- To wipe everything: `rm -rf ~/Friday` — FRIDAY recreates defaults on next run.
- Runtime data (WhatsApp session, browser profile, SQLite cache) still
  lives in `~/.friday/` (hidden) — that's not meant to be hand-edited.
"""


# ── First-run detection ──────────────────────────────────────────────────────

def needs_onboarding() -> bool:
    """True if ~/Friday/user.json is missing or blank."""
    return not USER.is_configured


def ensure_friday_dir() -> None:
    """Create ~/Friday/ and write README if missing. Run a one-time legacy migration."""
    FRIDAY_DIR.mkdir(parents=True, exist_ok=True)
    if not README_PATH.exists():
        README_PATH.write_text(_README)
    migrate_from_legacy()


# ── Interactive wizard ───────────────────────────────────────────────────────

def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        ans = input(f"  {prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit("\n  Onboarding cancelled.")
    return ans or default


# Minimal ISO-3166-1 alpha-2 map — enough to catch what users actually type.
# (Full list is ~250 codes; the common confusions are names / phone codes.)
_COUNTRY_NAME_TO_ISO = {
    "united kingdom": "GB", "uk": "GB", "britain": "GB", "england": "GB", "scotland": "GB", "wales": "GB",
    "united states": "US", "usa": "US", "america": "US",
    "canada": "CA", "ghana": "GH", "nigeria": "NG", "south africa": "ZA",
    "kenya": "KE", "germany": "DE", "france": "FR", "spain": "ES", "italy": "IT",
    "portugal": "PT", "netherlands": "NL", "ireland": "IE", "australia": "AU",
    "new zealand": "NZ", "japan": "JP", "china": "CN", "india": "IN",
    "brazil": "BR", "mexico": "MX", "argentina": "AR",
}
# Phone dialling codes → ISO — catches "44", "+44", "+1", etc.
_PHONE_TO_ISO = {
    "1": "US", "44": "GB", "233": "GH", "234": "NG", "27": "ZA", "254": "KE",
    "49": "DE", "33": "FR", "34": "ES", "39": "IT", "351": "PT", "31": "NL",
    "353": "IE", "61": "AU", "64": "NZ", "81": "JP", "86": "CN", "91": "IN",
    "55": "BR", "52": "MX", "54": "AR",
}


def _normalise_country_code(raw: str) -> str | None:
    """Turn 'uk' / 'United Kingdom' / '+44' / 'GB' → 'GB'. None if unrecognised."""
    s = raw.strip().lower().replace("+", "")
    if not s:
        return None
    # Name/alias match FIRST so 'uk' resolves to 'GB' (the real ISO code)
    # rather than the literal string 'UK', which isn't an ISO-3166-1 alpha-2.
    if s in _COUNTRY_NAME_TO_ISO:
        return _COUNTRY_NAME_TO_ISO[s]
    # Phone dialling code
    if s.isdigit() and s in _PHONE_TO_ISO:
        return _PHONE_TO_ISO[s]
    # Already a 2-letter ISO code? Accept it verbatim (uppercased).
    if len(s) == 2 and s.isalpha():
        return s.upper()
    return None


def _ask_country_code(default: str) -> str:
    """Prompt for country_code, auto-correct common mistakes, re-prompt once if invalid."""
    while True:
        raw = _ask("Country code (ISO 2-letter, e.g. GB, US, NG)", default)
        if not raw:
            return default
        normalised = _normalise_country_code(raw)
        if normalised:
            if normalised.lower() != raw.lower():
                console.print(f"  [dim]↳ interpreted as '{normalised}'[/dim]")
            return normalised
        console.print(
            f"  [yellow]'{raw}' isn't an ISO-3166 code.[/yellow] "
            "Use a 2-letter code (GB, US, NG, IN…). Press Enter to keep the default."
        )


def run_onboarding() -> UserConfig:
    """Interactive wizard. Writes ~/Friday/user.json and returns the config."""
    ensure_friday_dir()

    console.print()
    console.print(Rule("FRIDAY — First-run setup", style="green"))
    console.print()
    console.print("  Personal AI Operating System. Let's set a few things up.")
    console.print(f"  Writes to [cyan]{CONFIG_PATH}[/cyan] — edit any time.")
    console.print("  Press Enter to skip any field.")
    console.print()

    existing = USER

    name         = _ask("Your first name (how FRIDAY should address you)", existing.name)
    bio          = _ask("One-line bio (e.g. 'ML engineer, Lagos')", existing.bio)
    location     = _ask("Location (City, Country)", existing.location)
    country_code = _ask_country_code(existing.country_code or "US")
    email        = _ask("Email (for SMS-to-self + signatures)", existing.email)
    phone        = _ask("Phone (E.164, e.g. +447555834656)", existing.phone)
    github       = _ask("GitHub username (optional)", existing.github)
    website      = _ask("Website / portfolio URL (optional)", existing.website)
    tone         = _ask("Tone note (free-form, e.g. 'direct, dry humour')", existing.tone)

    cfg = UserConfig(
        name=name,
        bio=bio,
        location=location,
        country_code=country_code or "US",
        email=email,
        phone=phone,
        github=github,
        website=website,
        tone=tone,
        # Preserve anything the user hand-edited.
        slang=existing.slang,
        contact_aliases=existing.contact_aliases,
        briefing_watchlist=existing.briefing_watchlist,
        cv=existing.cv,
    )
    write(cfg)
    reload()

    console.print()
    console.print(f"  [green]✓ Saved[/green] → {CONFIG_PATH}")
    console.print(f"  [dim]Advanced fields (slang, contact aliases, watchlist, CV) live in that JSON file.[/dim]")
    console.print(f"  [dim]Run [cyan]friday config edit[/cyan] to open it.[/dim]")
    console.print()
    return cfg


# ── `friday config` subcommand ───────────────────────────────────────────────

def _pretty_print_config() -> None:
    if not CONFIG_PATH.exists():
        console.print(f"  [yellow]No config at {CONFIG_PATH}[/yellow]")
        console.print("  Run [cyan]friday init[/cyan] to create one.")
        return
    console.print(f"  [dim]{CONFIG_PATH}[/dim]")
    console.print()
    console.print(CONFIG_PATH.read_text())


def _open_in_editor(path: Path) -> int:
    ensure_friday_dir()
    if not path.exists():
        path.write_text("{}\n")
        os.chmod(path, 0o600)
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"
    return subprocess.call([editor, str(path)])


def _reveal_in_finder() -> int:
    ensure_friday_dir()
    if platform.system() == "Darwin":
        return subprocess.call(["open", str(FRIDAY_DIR)])
    if platform.system() == "Linux":
        return subprocess.call(["xdg-open", str(FRIDAY_DIR)])
    console.print(f"  [dim]Folder:[/dim] {FRIDAY_DIR}")
    return 0


def handle_config_subcommand(args: list[str]) -> int:
    """Handle `friday config [show|edit|path|open]`. Returns exit code."""
    sub = args[0] if args else "show"

    if sub == "path":
        print(CONFIG_PATH)
        return 0

    if sub == "edit":
        rc = _open_in_editor(CONFIG_PATH)
        reload()
        return rc

    if sub == "open":
        return _reveal_in_finder()

    if sub == "show":
        _pretty_print_config()
        return 0

    console.print(f"  [red]Unknown config subcommand: {sub}[/red]")
    console.print(
        "  Try: [cyan]friday config[/cyan] | [cyan]friday config edit[/cyan] "
        "| [cyan]friday config open[/cyan] | [cyan]friday config path[/cyan]"
    )
    return 2


# ── CLI dispatch hook ────────────────────────────────────────────────────────

def maybe_handle_admin_command(argv: list[str]) -> int | None:
    """Return an exit code if argv is an admin command, None to continue normal boot.

    Parsed forms:
      friday init
      friday config [show|edit|path|open]
    """
    if len(argv) < 2:
        return None

    cmd = argv[1]
    if cmd == "init":
        run_onboarding()
        return 0

    if cmd == "config":
        return handle_config_subcommand(argv[2:])

    return None
