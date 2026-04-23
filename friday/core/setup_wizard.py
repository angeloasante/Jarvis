"""Setup wizards, diagnostic checks, and connectivity tests.

All commands are subcommands of the `friday` CLI:

    friday onboard             → full guided flow (QuickStart / Advanced)
    friday doctor              → audit every integration + show version
    friday update              → pull + install the latest release
    friday setup <component>   → one-shot per-service wizard
    friday test <component>    → connectivity test for a configured service
    friday heartbeat           → explain background watches + list active ones

Side note: every setup writes to ``~/.friday/.env`` so pip-installed users keep
their keys outside the repo. ``friday/core/config.py`` already loads that file
ahead of the repo-local ``.env``.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.rule import Rule
from rich.table import Table

from friday.core.user_config import USER, FRIDAY_DIR as PROFILE_DIR, CONFIG_PATH

console = Console()

RUNTIME_DIR  = Path.home() / ".friday"      # Hidden — runtime OAuth tokens, DB, models
PROFILE_ENV  = Path.home() / "Friday" / ".env"   # Visible — user-facing API keys
LEGACY_ENV   = RUNTIME_DIR / ".env"          # Pre-migration location; we still read it
ENV_PATH     = PROFILE_ENV                   # Where new writes go
GOOGLE_TOKEN = RUNTIME_DIR / "google_token.json"   # OAuth token cache stays in runtime dir
MODELS_DIR = RUNTIME_DIR / "models"
GESTURE_TASK = MODELS_DIR / "gesture_recognizer.task"
GESTURE_TASK_URL = (
    "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/"
    "gesture_recognizer/float16/latest/gesture_recognizer.task"
)


# ── System dependency detection ─────────────────────────────────────────────

def _which(binary: str) -> str | None:
    from shutil import which
    return which(binary)


def _version_of(binary: str, flag: str = "--version") -> str:
    try:
        out = subprocess.run([binary, flag], capture_output=True, text=True, timeout=5)
        return (out.stdout or out.stderr).strip().splitlines()[0][:60]
    except Exception:
        return ""


def _system_deps() -> list[tuple[str, str, bool, str, str]]:
    """Return [(name, install_hint, present, version, why_needed), ...]."""
    import sys as _sys
    py_ok = _sys.version_info >= (3, 12)
    rows: list[tuple[str, str, bool, str, str]] = [
        ("Python 3.12+", "use python.org or `uv python install 3.12`",
         py_ok, f"{_sys.version_info.major}.{_sys.version_info.minor}.{_sys.version_info.micro}",
         "FRIDAY requires 3.12+"),
        ("uv", "curl -LsSf https://astral.sh/uv/install.sh | sh",
         bool(_which("uv")), _version_of("uv") if _which("uv") else "",
         "fast Python package manager (recommended for dev installs)"),
        ("ollama", "brew install ollama" if _which("brew") else "https://ollama.com/download",
         bool(_which("ollama")), _version_of("ollama") if _which("ollama") else "",
         "local LLM fallback when offline (optional)"),
        ("node", "brew install node" if _which("brew") else "https://nodejs.org",
         bool(_which("node")), _version_of("node") if _which("node") else "",
         "required for the WhatsApp bridge"),
        ("ngrok", "brew install ngrok" if _which("brew") else "https://ngrok.com/download",
         bool(_which("ngrok")), _version_of("ngrok", "version") if _which("ngrok") else "",
         "exposes Twilio SMS webhook publicly"),
        ("brew (macOS)", "https://brew.sh",
         bool(_which("brew")), _version_of("brew") if _which("brew") else "",
         "convenient installer for ollama/ngrok/node on macOS"),
    ]
    return rows


# ── .env helpers ─────────────────────────────────────────────────────────────

def _read_env() -> dict[str, str]:
    """Union of ~/Friday/.env + ~/.friday/.env + repo-local .env (first-write-wins)."""
    env: dict[str, str] = {}
    for path in (PROFILE_ENV, LEGACY_ENV, Path.cwd() / ".env"):
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, _, v = s.partition("=")
            env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def _write_env_updates(updates: dict[str, str]) -> None:
    """Write/merge keys into ~/Friday/.env. Comments + unrelated keys preserved."""
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing_lines: list[str] = []
    existing_keys: dict[str, int] = {}   # key → line index

    if ENV_PATH.exists():
        existing_lines = ENV_PATH.read_text().splitlines()
        for i, line in enumerate(existing_lines):
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k = s.split("=", 1)[0].strip()
            existing_keys[k] = i

    for key, value in updates.items():
        new_line = f"{key}={value}"
        if key in existing_keys:
            existing_lines[existing_keys[key]] = new_line
        else:
            existing_lines.append(new_line)

    ENV_PATH.write_text("\n".join(existing_lines).rstrip() + "\n")
    try:
        os.chmod(ENV_PATH, 0o600)
    except OSError:
        pass
    # Reload process env so the current `friday` session sees the new values.
    for k, v in updates.items():
        os.environ[k] = v


def _ask(prompt: str, default: str = "", secret: bool = False) -> str:
    """Read a value from stdin. Use getpass for secrets so they don't echo."""
    suffix = f" [{default}]" if default and not secret else ""
    if secret:
        import getpass
        try:
            ans = getpass.getpass(f"  {prompt}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit("\n  Cancelled.")
    else:
        try:
            ans = input(f"  {prompt}{suffix}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit("\n  Cancelled.")
    return ans or default


def _confirm(prompt: str, default: bool = True) -> bool:
    suffix = "Y/n" if default else "y/N"
    try:
        ans = input(f"  {prompt} [{suffix}]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if not ans:
        return default
    return ans in ("y", "yes")


# ── Doctor — audit every integration ────────────────────────────────────────

def _check(label: str, ok: bool, detail: str = "") -> tuple[str, bool, str]:
    return (label, ok, detail)


def doctor() -> int:
    """Print a status line for every integration."""
    env = _read_env()
    rows: list[tuple[str, bool, str]] = []

    # Profile
    rows.append(_check(
        "Profile (user.json)", USER.is_configured,
        f"{CONFIG_PATH}" if USER.is_configured else "run `friday init`"
    ))
    rows.append(_check(
        "CV attached", bool(USER.cv and USER.cv.get("experience")),
        f"{len(USER.cv.get('experience', []))} jobs" if USER.cv else "add `cv` key to user.json"
    ))

    # LLM providers
    has_openrouter = bool(env.get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_API_KEY"))
    has_groq       = bool(env.get("GROQ_API_KEY")       or os.environ.get("GROQ_API_KEY"))
    has_cloud_explicit = bool(env.get("CLOUD_API_KEY") or os.environ.get("CLOUD_API_KEY"))
    provider = (
        "CLOUD_API_KEY (manual)" if has_cloud_explicit else
        "Groq" if has_groq else
        "OpenRouter" if has_openrouter else
        None
    )
    rows.append(_check(
        "LLM cloud provider", bool(provider),
        provider or "run `friday setup openrouter` or `friday setup groq`"
    ))

    # Ollama fallback
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1)
        ollama_up = True
    except Exception:
        ollama_up = False
    rows.append(_check(
        "Ollama (local)", ollama_up,
        "running on :11434" if ollama_up else "not running (optional — local fallback)"
    ))

    # Google / Gmail / Calendar — we ship a shared OAuth client, so presence of
    # the cached access token is what tells us the user has actually signed in.
    rows.append(_check(
        "Gmail + Calendar (signed in)", GOOGLE_TOKEN.exists(),
        "logged in" if GOOGLE_TOKEN.exists() else "run `friday setup gmail`"
    ))

    # Tavily (web search)
    has_tavily = bool(env.get("TAVILY_API_KEY") or os.environ.get("TAVILY_API_KEY"))
    rows.append(_check(
        "Tavily (web search)", has_tavily,
        "configured" if has_tavily else "run `friday setup tavily`"
    ))

    # Twilio
    has_twilio = all(env.get(k) or os.environ.get(k) for k in
                     ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER"))
    rows.append(_check(
        "Twilio (SMS in/out)", has_twilio,
        "configured" if has_twilio else "run `friday setup twilio`"
    ))

    # Telegram (second channel, rich media)
    has_tg = bool((env.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN", "")).strip())
    rows.append(_check(
        "Telegram (rich media)", has_tg,
        "configured" if has_tg else "optional — run `friday setup telegram`"
    ))

    # X / Twitter
    has_x = bool(env.get("X_BEARER_TOKEN") or os.environ.get("X_BEARER_TOKEN"))
    rows.append(_check(
        "X / Twitter", has_x,
        "bearer token present" if has_x else "run `friday setup x`"
    ))

    # Voice
    voice_flag = env.get("FRIDAY_VOICE", "").lower() == "true"
    has_eleven = bool(env.get("ELEVENLABS_API_KEY") or os.environ.get("ELEVENLABS_API_KEY"))
    rows.append(_check(
        "Voice pipeline", voice_flag,
        ("ON" + (" · ElevenLabs" if has_eleven else " · Kokoro (local)")) if voice_flag else "run `friday setup voice`"
    ))

    # Gestures
    has_gesture_task = GESTURE_TASK.exists()
    gesture_flag = env.get("FRIDAY_GESTURES", "").lower() == "true"
    rows.append(_check(
        "Hand gestures",
        has_gesture_task and gesture_flag,
        ("ON" if gesture_flag else "OFF") + (" · task file present" if has_gesture_task else " · task file missing") if has_gesture_task else "run `friday setup gestures`"
    ))

    # WhatsApp bridge
    wa_dir = RUNTIME_DIR / "whatsapp"
    wa_ready = wa_dir.exists() and (wa_dir / "server.js").exists()
    rows.append(_check(
        "WhatsApp (Baileys)", wa_ready,
        "bridge installed" if wa_ready else "optional — see docs/whatsapp-setup.md"
    ))

    # ngrok (for SMS webhooks)
    try:
        subprocess.run(["ngrok", "version"], capture_output=True, timeout=3)
        has_ngrok = True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        has_ngrok = False
    rows.append(_check(
        "ngrok (SMS webhook)", has_ngrok,
        "installed" if has_ngrok else "optional — needed for Twilio inbound SMS"
    ))

    # Render config table
    console.print()
    console.print(Rule("FRIDAY · doctor", style="green"))
    console.print()
    # Version strip — quick glance at what's running
    method, _detail = _detect_install_method()
    method_label = {
        "uv_tool": "uv tool", "pipx": "pipx", "pip_user": "pip --user",
        "dev": "source", "mac_app": "Mac app", "unknown": "?",
    }.get(method, method)
    tools_n, modules_n = _tool_inventory()
    console.print(f"  [dim]friday-os {_installed_version()}  ·  via {method_label}  ·  {tools_n} tools across {modules_n} modules  ·  `friday update` to refresh[/dim]")
    console.print()
    t = Table(show_header=True, header_style="bold green", box=None, pad_edge=False,
              title="Integrations", title_style="dim", title_justify="left")
    t.add_column("Component", no_wrap=True)
    t.add_column("Status", no_wrap=True)
    t.add_column("Detail", overflow="fold")
    for label, ok, detail in rows:
        mark = "[green]✓[/green]" if ok else "[yellow]○[/yellow]"
        t.add_row(label, mark, detail)
    console.print(t)

    # System deps
    console.print()
    dt = Table(show_header=True, header_style="bold green", box=None, pad_edge=False,
               title="System dependencies", title_style="dim", title_justify="left")
    dt.add_column("Tool", no_wrap=True)
    dt.add_column("Status", no_wrap=True)
    dt.add_column("Version / install hint", overflow="fold")
    dep_rows = _system_deps()
    for name, install_hint, ok, version, *_ in dep_rows:
        mark = "[green]✓[/green]" if ok else "[yellow]○[/yellow]"
        dt.add_row(name, mark, version or install_hint)
    console.print(dt)
    console.print()

    missing_cfg = [r for r in rows if not r[1]]
    missing_deps = [d for d in dep_rows if not d[2]]
    if missing_cfg or missing_deps:
        msgs = []
        if missing_cfg:
            msgs.append(f"{len(missing_cfg)} integration{'s' if len(missing_cfg)!=1 else ''}")
        if missing_deps:
            msgs.append(f"{len(missing_deps)} dependenc{'ies' if len(missing_deps)!=1 else 'y'}")
        console.print(f"  [dim]Missing: {', '.join(msgs)} — run [cyan]friday onboard[/cyan] for guided setup or [cyan]friday setup deps[/cyan] for system tools only.[/dim]")
    else:
        console.print("  [green]All set.[/green]")
    console.print()
    return 0


# ── setup deps — install missing system tools ───────────────────────────────

def setup_deps() -> int:
    """Detect missing system deps and offer brew-install for the easy ones."""
    console.print()
    console.print(Rule("System dependencies", style="green"))
    console.print()

    deps = _system_deps()
    missing = [d for d in deps if not d[2]]
    if not missing:
        console.print("  [green]✓ All system tools present.[/green]")
        console.print()
        return 0

    console.print("  Missing tools:")
    for name, hint, _, _, why in missing:
        console.print(f"    · [yellow]{name}[/yellow] — {why}")
        console.print(f"      install: [dim]{hint}[/dim]")
    console.print()

    has_brew = bool(_which("brew"))
    if not has_brew:
        console.print("  [dim]`brew` not found — install manually using the hints above.[/dim]")
        return 1

    brew_installable = [d for d in missing if d[1].startswith("brew install")]
    if not brew_installable:
        console.print("  [dim]Nothing brew can install here. Use the manual hints above.[/dim]")
        return 1

    names = ", ".join(d[0] for d in brew_installable)
    if not _confirm(f"Install these with brew? ({names})", default=True):
        return 0

    for name, hint, *_ in brew_installable:
        pkg = hint.replace("brew install ", "", 1)
        console.print(f"  [dim]$ brew install {pkg}[/dim]")
        rc = subprocess.call(["brew", "install", pkg])
        if rc != 0:
            console.print(f"  [red]brew install {pkg} failed (exit {rc}).[/red]")
    console.print()
    console.print("  Re-run [cyan]friday doctor[/cyan] to verify.")
    console.print()
    return 0


# ── onboard — the OpenClaw-style QuickStart / Advanced guided flow ──────────

def onboard() -> int:
    """Single guided flow: dependencies → profile → LLM → optional integrations → test.

    Mirrors `openclaw onboard`: binary QuickStart/Advanced entry, preserves
    existing config on re-run, ends with a health check.
    """
    console.print()
    console.print(Rule("FRIDAY · onboard", style="green"))
    console.print()
    console.print("  Personal AI Operating System — guided setup.")
    console.print("  Safe to re-run: existing config is preserved unless you overwrite it.")
    console.print()
    console.print("  [bold]1.[/bold] QuickStart  — profile + one cloud LLM + system dep check")
    console.print("  [bold]2.[/bold] Advanced    — all of the above + Gmail, Twilio, voice, gestures, Ollama")
    console.print()
    mode = _ask("Pick 1 or 2", default="1")
    advanced = mode.strip() == "2"

    steps = [
        ("Profile",       _step_profile),
        ("System deps",   _step_deps),
        ("LLM provider",  _step_llm),
    ]
    if advanced:
        steps += [
            ("Tavily (web search)", lambda: _step_optional("Tavily", setup_tavily)),
            ("Gmail + Calendar",    lambda: _step_optional("Gmail + Calendar", setup_gmail)),
            ("Twilio (SMS)",        lambda: _step_optional("Twilio", setup_twilio)),
            ("ElevenLabs (TTS)",    lambda: _step_optional("ElevenLabs", setup_elevenlabs)),
            ("X / Twitter",         lambda: _step_optional("X", setup_x)),
            ("Voice",               lambda: _step_optional("Voice", setup_voice)),
            ("Gestures",            lambda: _step_optional("Gestures", setup_gestures)),
        ]
    steps.append(("Health check", _step_doctor))

    total = len(steps)
    for i, (label, fn) in enumerate(steps, 1):
        console.print()
        console.print(f"[bold green][{i}/{total}][/bold green] [bold]{label}[/bold]")
        fn()

    console.print()
    console.print(Rule("Done", style="green"))
    console.print()
    console.print("  Next:")
    console.print("    [cyan]friday[/cyan]              — launch the REPL")
    console.print("    [cyan]friday test llm[/cyan]     — verify cloud connectivity")
    console.print("    [cyan]friday heartbeat[/cyan]    — see how background watches work")
    console.print()
    return 0


# step helpers
def _step_profile() -> None:
    from friday.core.onboarding import run_onboarding, needs_onboarding
    if needs_onboarding():
        run_onboarding()
    else:
        console.print(f"  [green]✓[/green] Profile already configured ({USER.name}) — skipping.")
        if _confirm("  Re-run the profile wizard?", default=False):
            run_onboarding()


def _step_deps() -> None:
    deps = _system_deps()
    missing = [d for d in deps if not d[2]]
    if not missing:
        console.print("  [green]✓[/green] All system tools present.")
        return
    for name, hint, _, _, why in missing:
        console.print(f"    · [yellow]{name}[/yellow] — {why}")
    if _confirm("  Run `friday setup deps` to install what's missing?", default=True):
        setup_deps()


def _step_llm() -> None:
    env = _read_env()
    has_any = any(env.get(k) or os.environ.get(k) for k in
                  ("OPENROUTER_API_KEY", "GROQ_API_KEY", "CLOUD_API_KEY"))
    if has_any:
        console.print("  [green]✓[/green] Cloud LLM already configured.")
        if not _confirm("  Change the provider?", default=False):
            return
    console.print("  Pick a cloud provider:")
    console.print("    1. OpenRouter  — widest model selection, free tier, lets you pick a specific model")
    console.print("    2. Groq        — fastest latency (~500 tok/s), fewer models")
    console.print("    3. Skip        — use Ollama locally only")
    pick = _ask("Pick 1, 2, or 3", default="1")
    if pick == "1":
        setup_openrouter()
    elif pick == "2":
        setup_groq()
    else:
        console.print("  [dim]Skipped. FRIDAY will use Ollama if running locally.[/dim]")


def _step_optional(label: str, fn: Callable[[], int]) -> None:
    if _confirm(f"  Set up {label} now?", default=False):
        fn()
    else:
        console.print(f"  [dim]Skipped {label}. You can run it later with `friday setup …`.[/dim]")


def _step_doctor() -> None:
    doctor()


# ── OpenRouter — pick a model ────────────────────────────────────────────────

def _fetch_openrouter_models() -> list[dict]:
    """Return models that support tool calling. No auth needed for listing."""
    try:
        with urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=10) as r:
            data = json.loads(r.read())
    except Exception as e:
        console.print(f"  [red]Couldn't fetch model list: {e}[/red]")
        return []

    models = data.get("data", [])
    tool_capable = [
        m for m in models
        if "tools" in (m.get("supported_parameters") or [])
    ]
    # Sort cheapest first (prompt price per 1K tokens).
    def cost(m):
        try:
            return float(m.get("pricing", {}).get("prompt", 0))
        except (TypeError, ValueError):
            return 9.0
    tool_capable.sort(key=cost)
    return tool_capable


def _link(url: str, label: str | None = None) -> str:
    """Rich-formatted clickable hyperlink. Works in modern terminals."""
    label = label or url
    return f"[link={url}]{label}[/link]"


def _simple_key_setup(
    service: str,
    url: str,
    env_var: str,
    key_hint: str,
    blurb: str,
    prefix: str | None = None,
    secret: bool = True,
) -> int:
    """Shared shape for 'just paste your API key' setups.

    Opens the signup/key page as a clickable link, takes the key, writes it.
    """
    console.print()
    console.print(Rule(f"{service}", style="green"))
    console.print()
    console.print(f"  {blurb}")
    console.print(f"  Grab a key: {_link(url)}")
    console.print()
    env = _read_env()
    current = env.get(env_var, "") or os.environ.get(env_var, "")
    if current:
        console.print(f"  [dim]{env_var} already set.[/dim]")
        if not _confirm("Replace it?", default=False):
            return 0
    key = _ask(f"Paste your {service} key ({key_hint})", secret=secret)
    if not key:
        console.print("  [yellow]Skipped.[/yellow]")
        return 0
    if prefix and not key.startswith(prefix):
        console.print(f"  [red]Doesn't look like a {service} key (expected prefix '{prefix}') — aborting.[/red]")
        return 2
    _write_env_updates({env_var: key})
    console.print(f"  [green]✓ Saved[/green] → {ENV_PATH}")
    return 0


def setup_openrouter() -> int:
    """Paste key → optionally pick a specific model from the live catalogue."""
    console.print()
    console.print(Rule("OpenRouter", style="green"))
    console.print()
    console.print("  Unified API for many model providers — free tier + paid.")
    console.print(f"  Grab a key: {_link('https://openrouter.ai/settings/keys')}")
    console.print()

    env = _read_env()
    current_key = env.get("OPENROUTER_API_KEY", "") or os.environ.get("OPENROUTER_API_KEY", "")
    if current_key:
        console.print(f"  [dim]OPENROUTER_API_KEY already set.[/dim]")
        if not _confirm("Replace it?", default=False):
            # Still offer to change the model
            if not _confirm("Change the selected model?", default=False):
                return 0
            key = current_key
        else:
            key = _ask("Paste your OpenRouter key (sk-or-v1-…)", secret=True)
    else:
        key = _ask("Paste your OpenRouter key (sk-or-v1-…)", secret=True)

    if not key or not key.startswith("sk-or"):
        console.print("  [red]Not a valid OpenRouter key — aborting.[/red]")
        return 2

    # Skip the model picker if the user doesn't want it
    if _confirm("Pick a specific model? (otherwise FRIDAY uses its default)", default=True):
        console.print("  Fetching tool-capable models…")
        models = _fetch_openrouter_models()
        if models:
            top = models[:20]
            t = Table(show_header=True, header_style="bold green", box=None)
            t.add_column("#", no_wrap=True)
            t.add_column("Model", overflow="fold")
            t.add_column("$/1M prompt", justify="right")
            t.add_column("Ctx", justify="right")
            for i, m in enumerate(top, 1):
                mid = m["id"]
                try:
                    per_1m = float(m.get("pricing", {}).get("prompt", 0)) * 1_000_000
                    cost = "free" if per_1m < 0.0001 else f"${per_1m:,.2f}"
                except (TypeError, ValueError):
                    cost = "—"
                ctx = m.get("context_length") or "—"
                t.add_row(str(i), mid, cost, str(ctx))
            console.print()
            console.print(t)
            console.print()
            pick = _ask("Pick number (or paste a model id)", default="1")
            if pick.isdigit() and 1 <= int(pick) <= len(top):
                model_id = top[int(pick) - 1]["id"]
            else:
                model_id = pick
            _write_env_updates({"OPENROUTER_API_KEY": key, "CLOUD_MODEL": model_id})
            console.print(f"  [green]✓ Saved[/green] → {ENV_PATH}   · model: [cyan]{model_id}[/cyan]")
            return 0

    _write_env_updates({"OPENROUTER_API_KEY": key})
    console.print(f"  [green]✓ Saved[/green] → {ENV_PATH}")
    return 0


def setup_groq() -> int:
    return _simple_key_setup(
        service="Groq",
        url="https://console.groq.com/keys",
        env_var="GROQ_API_KEY",
        key_hint="gsk_…",
        blurb="Fastest cloud inference (~500 tok/s).",
        prefix="gsk_",
    )


def setup_gemma() -> int:
    """Google AI Studio — free Gemma 4 access straight from Google.

    This is a DIFFERENT key from the Gmail OAuth one. Gemma keys come from
    Google AI Studio (aistudio.google.com/app/apikey), not Google Cloud Console.
    Free tier is generous: 14,400 requests/day, 4M tokens/minute.
    """
    console.print()
    console.print(Rule("Google AI Studio — Gemma 4 free tier", style="green"))
    console.print()
    console.print("  Google's direct Gemma API. Free tier: 14,400 requests/day.")
    console.print(f"  Grab a key: {_link('https://aistudio.google.com/app/apikey')}")
    console.print()
    console.print("  [bold yellow]Note:[/bold yellow] this is NOT the same as your Gmail OAuth setup.")
    console.print("  Gmail uses a Cloud Console OAuth client; Gemma uses an AI Studio key.")
    console.print()

    env = _read_env()
    current = env.get("GOOGLE_AI_STUDIO_KEY", "") or env.get("GEMINI_API_KEY", "")
    if current:
        console.print(f"  [dim]Already set.[/dim]")
        if not _confirm("Replace?", default=False):
            return 0

    key = _ask("Paste your AI Studio key (AIza…)", secret=True)
    if not key:
        console.print("  [yellow]Skipped.[/yellow]")
        return 0
    if not key.startswith("AIza"):
        console.print("  [red]That doesn't look like an AI Studio key (expected 'AIza…' prefix).[/red]")
        if not _confirm("Save anyway?", default=False):
            return 2

    _write_env_updates({"GOOGLE_AI_STUDIO_KEY": key})
    console.print(f"  [green]✓ Saved[/green] → {ENV_PATH}")
    console.print("  This becomes a fallback in the cloud chain: OpenRouter → Google AI → Groq → Ollama.")
    return 0


def setup_tavily() -> int:
    return _simple_key_setup(
        service="Tavily",
        url="https://app.tavily.com",
        env_var="TAVILY_API_KEY",
        key_hint="tvly-…",
        blurb="Web search used by the research agent. Free tier covers normal use.",
        prefix="tvly-",
    )


def setup_elevenlabs() -> int:
    rc = _simple_key_setup(
        service="ElevenLabs",
        url="https://elevenlabs.io/app/settings/api-keys",
        env_var="ELEVENLABS_API_KEY",
        key_hint="sk_…",
        blurb="Cloud TTS (~75ms latency). Leave it unset to fall back to local Kokoro.",
    )
    if rc == 0:
        env = _read_env()
        current_voice = env.get("ELEVENLABS_VOICE_ID", "")
        voice = _ask("ELEVENLABS_VOICE_ID (optional — Enter for default 'George')",
                     default=current_voice)
        if voice and voice != current_voice:
            _write_env_updates({"ELEVENLABS_VOICE_ID": voice})
    return rc


def setup_x() -> int:
    """X/Twitter auth — OAuth 2.0 bearer token is the simplest shape."""
    console.print()
    console.print(Rule("X (Twitter)", style="green"))
    console.print()
    console.print("  X API v2 — posting, mentions, search.")
    console.print(f"  Create an app + tokens: {_link('https://developer.x.com/en/portal/dashboard')}")
    console.print(f"  (free 'Basic' tier is enough for posting + reading)")
    console.print()
    env = _read_env()
    updates: dict[str, str] = {}
    bearer = _ask("X_BEARER_TOKEN (long base64-ish string)",
                  default=env.get("X_BEARER_TOKEN", ""), secret=True)
    if bearer:
        updates["X_BEARER_TOKEN"] = bearer
    # Posting needs OAuth 1.0a too
    console.print()
    console.print("  To [bold]post[/bold] tweets you also need these four (otherwise leave blank):")
    for var, prompt in [
        ("X_API_KEY",             "X_API_KEY (consumer key)"),
        ("X_API_SECRET",          "X_API_SECRET (consumer secret)"),
        ("X_ACCESS_TOKEN",        "X_ACCESS_TOKEN"),
        ("X_ACCESS_TOKEN_SECRET", "X_ACCESS_TOKEN_SECRET"),
    ]:
        val = _ask(prompt, default=env.get(var, ""), secret=True)
        if val:
            updates[var] = val

    if not updates:
        console.print("  [yellow]Nothing to save.[/yellow]")
        return 0
    _write_env_updates(updates)
    console.print(f"  [green]✓ Saved {len(updates)} key{'s' if len(updates)!=1 else ''}[/green] → {ENV_PATH}")
    return 0


# ── Twilio ───────────────────────────────────────────────────────────────────

def setup_twilio() -> int:
    """Three fields from the Twilio console, plus your own number.

    After saving creds, detects ngrok/tailscale, opens a tunnel on the SMS
    port (3200), and auto-configures the Twilio number's inbound webhook
    so there's no manual 'paste the URL into the Twilio console' step.
    """
    console.print()
    console.print(Rule("Twilio (SMS)", style="green"))
    console.print()
    console.print("  Send SMS + receive SMS to control FRIDAY remotely.")
    console.print(f"  Console: {_link('https://console.twilio.com')}")
    console.print()

    env = _read_env()
    sid   = _ask("TWILIO_ACCOUNT_SID (AC…)",           default=env.get("TWILIO_ACCOUNT_SID", ""))
    token = _ask("TWILIO_AUTH_TOKEN",                  secret=True)
    phone = _ask("TWILIO_PHONE_NUMBER (E.164)",        default=env.get("TWILIO_PHONE_NUMBER", ""))
    contact = _ask("CONTACT_PHONE (your own number)",  default=env.get("CONTACT_PHONE", USER.phone))

    if not sid.startswith("AC") or not token or not phone.startswith("+"):
        console.print("  [red]Missing or invalid values — aborting.[/red]")
        return 2

    updates = {
        "TWILIO_ACCOUNT_SID": sid,
        "TWILIO_AUTH_TOKEN": token,
        "TWILIO_PHONE_NUMBER": phone,
        "CONTACT_PHONE": contact,
    }
    _write_env_updates(updates)
    console.print(f"  [green]✓ Saved[/green] → {ENV_PATH}")

    # ── Tunnel: ngrok > tailscale > skip ─────────────────────────────────
    console.print()
    console.print("  [bold]Inbound webhook[/bold] — Twilio needs a public HTTPS URL to send SMS to.")
    public_url = _setup_twilio_tunnel(env)
    if not public_url:
        console.print("  [yellow]Skipped tunnel.[/yellow] Inbound SMS won't work until a tunnel is configured.")
        console.print("  Install ngrok ([dim]brew install ngrok[/dim]) or tailscale, then re-run `friday setup twilio`.")
        return 0

    # ── Auto-configure Twilio number's webhook via API ───────────────────
    webhook_url = f"{public_url.rstrip('/')}/sms"
    if _update_twilio_webhook(sid, token, phone, webhook_url):
        console.print(f"  [green]✓ Twilio webhook auto-configured[/green] → [cyan]{webhook_url}[/cyan]")
    else:
        console.print(f"  [yellow]Couldn't auto-configure Twilio.[/yellow] Manually set the SMS webhook to:")
        console.print(f"    [cyan]{webhook_url}[/cyan] (POST)")
        console.print(f"  Phone number settings: {_link('https://console.twilio.com/us1/develop/phone-numbers/manage/incoming')}")
    return 0


def _setup_twilio_tunnel(env: dict[str, str]) -> str | None:
    """Start ngrok or tailscale funnel on port 3200 and return the public URL.

    Returns None if no tunnel tool is available or the user opts out.
    """
    sms_port = env.get("SMS_PORT") or os.getenv("SMS_PORT", "3200")
    has_ngrok = bool(_which("ngrok"))
    has_ts = bool(_which("tailscale"))

    if not has_ngrok and not has_ts:
        console.print("  [dim]Neither ngrok nor tailscale found.[/dim]")
        console.print("  Install one:")
        console.print("    • ngrok:      [cyan]brew install ngrok[/cyan] (free, quickest)")
        console.print("    • tailscale:  [cyan]brew install --cask tailscale[/cyan] (free, more stable)")
        return None

    # Offer the tool the user has. Prefer ngrok — 30s setup, stable URL.
    # Tailscale Funnel needs the host to be logged in + funnel enabled.
    if has_ngrok and _confirm("  Use ngrok to open a public tunnel now?", default=True):
        return _start_ngrok(sms_port, env)
    if has_ts and _confirm("  Use Tailscale Funnel to open a public tunnel now?", default=True):
        return _start_tailscale_funnel(sms_port)
    return None


def _start_ngrok(sms_port: str, env: dict[str, str]) -> str | None:
    """Spawn ngrok on the SMS port and scrape the public URL from its local API."""
    import subprocess, time, json, urllib.request

    # Kill any prior ngrok that might be holding the port/tunnel
    subprocess.run(["pkill", "-f", "ngrok http"], capture_output=True, timeout=3)
    time.sleep(1)

    # If the user has a reserved static domain, use it — URL won't change.
    static_domain = env.get("NGROK_DOMAIN", "").strip()
    args = ["ngrok", "http", sms_port]
    if static_domain:
        args += ["--domain", static_domain]

    console.print(f"  Starting ngrok on :{sms_port}…")
    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        console.print(f"  [red]ngrok failed to start: {e}[/red]")
        return None

    # Wait for the local API (127.0.0.1:4040) to publish the tunnel URL
    for _ in range(20):
        time.sleep(0.5)
        try:
            with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=1) as r:
                payload = json.loads(r.read())
            tunnels = payload.get("tunnels") or []
            https = next((t.get("public_url") for t in tunnels if t.get("proto") == "https"), None)
            if https:
                # Remember the URL so cli.py can re-launch ngrok on startup
                if static_domain:
                    _write_env_updates({"NGROK_DOMAIN": static_domain})
                else:
                    # No reserved domain — the URL is ephemeral, only
                    # useful for this session. Still save it so cli.py
                    # doesn't spawn a second ngrok on startup.
                    _write_env_updates({"NGROK_PUBLIC_URL": https})
                return https
        except Exception:
            continue

    console.print("  [red]ngrok started but its local API didn't respond.[/red] "
                  "Check auth with [cyan]ngrok config check[/cyan].")
    return None


def _start_tailscale_funnel(sms_port: str) -> str | None:
    """Start Tailscale Funnel on SMS port and parse the public URL."""
    import subprocess, re as _re

    # Funnel requires: (1) logged-in, (2) HTTPS cert provisioned, (3) node ACL
    # allows funnel. We run `tailscale funnel --bg` which handles the provision.
    console.print(f"  Starting Tailscale Funnel on :{sms_port}…")
    try:
        res = subprocess.run(
            ["tailscale", "funnel", "--bg", f"http://127.0.0.1:{sms_port}"],
            capture_output=True, text=True, timeout=20,
        )
    except Exception as e:
        console.print(f"  [red]tailscale funnel failed: {e}[/red]")
        return None

    # The command prints something like:
    #   Available on the internet:
    #   https://my-mac.tailnet-xyz.ts.net/
    combined = (res.stdout or "") + (res.stderr or "")
    m = _re.search(r"https://[A-Za-z0-9.-]+\.ts\.net/?", combined)
    if m:
        url = m.group(0).rstrip("/")
        _write_env_updates({"TAILSCALE_FUNNEL_URL": url})
        return url

    console.print(f"  [yellow]Couldn't parse Funnel URL.[/yellow] Output:")
    console.print(f"  [dim]{combined.strip()[:300]}[/dim]")
    console.print("  Enable funnel: [cyan]tailscale set --advertise-funnel[/cyan] "
                  "or see [link]https://tailscale.com/kb/1223/funnel[/link]")
    return None


def _update_twilio_webhook(sid: str, token: str, phone: str, webhook_url: str) -> bool:
    """PATCH the Twilio IncomingPhoneNumber so SMS POSTs land on webhook_url."""
    import urllib.parse, urllib.request, base64, json

    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    base = f"https://api.twilio.com/2010-04-01/Accounts/{sid}"

    # 1. Look up the phone's SID (the SID of the number, not the account).
    try:
        listing_url = f"{base}/IncomingPhoneNumbers.json?PhoneNumber={urllib.parse.quote(phone)}"
        req = urllib.request.Request(listing_url, headers={"Authorization": f"Basic {auth}"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        numbers = data.get("incoming_phone_numbers") or []
        if not numbers:
            console.print(f"  [yellow]No phone {phone} on this Twilio account.[/yellow]")
            return False
        phone_sid = numbers[0]["sid"]
    except Exception as e:
        console.print(f"  [red]Twilio phone lookup failed: {type(e).__name__}: {e}[/red]")
        return False

    # 2. PATCH it.
    try:
        update_url = f"{base}/IncomingPhoneNumbers/{phone_sid}.json"
        body = urllib.parse.urlencode({"SmsUrl": webhook_url, "SmsMethod": "POST"}).encode()
        req = urllib.request.Request(
            update_url, data=body, method="POST",
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
        return True
    except Exception as e:
        console.print(f"  [red]Twilio webhook update failed: {type(e).__name__}: {e}[/red]")
        return False


# ── Telegram ─────────────────────────────────────────────────────────────────

def setup_telegram() -> int:
    """Telegram bot — second channel alongside SMS for rich media (50 MB/file).

    Flow:
      1. Prompt for bot token from @BotFather.
      2. Verify the token via ``getMe``.
      3. Auto-discover the user's chat_id by polling ``getUpdates`` — the
         user taps /start in Telegram, we grab the chat_id, save it to the
         allowlist. No manual ID lookup needed.
      4. Save to ~/Friday/.env. Restart FRIDAY to pick up the listener.
    """
    import json, time, urllib.parse, urllib.request

    console.print()
    console.print(Rule("Telegram (rich-media channel)", style="green"))
    console.print()
    console.print("  Telegram gives FRIDAY a second messaging channel with support for")
    console.print("  photos, audio, voice notes, and documents up to 50 MB per file.")
    console.print(f"  SMS stays on top for no-signal fallback — this is additive.")
    console.print()
    console.print("  [bold]1. Create a bot[/bold]")
    console.print(f"     Open Telegram → message {_link('https://t.me/BotFather')}")
    console.print("     Send: [cyan]/newbot[/cyan] → pick a name → pick a username ending in 'bot'")
    console.print("     Copy the token BotFather gives you (looks like 123456:ABC-DEF…).")
    console.print()

    env = _read_env()
    token = _ask("TELEGRAM_BOT_TOKEN",
                 default=env.get("TELEGRAM_BOT_TOKEN", ""),
                 secret=True)
    if not token or ":" not in token:
        console.print("  [red]Invalid token — aborting.[/red]")
        return 2

    # Verify the token
    try:
        with urllib.request.urlopen(
            f"https://api.telegram.org/bot{token}/getMe", timeout=10,
        ) as r:
            me = json.loads(r.read())
    except Exception as e:
        console.print(f"  [red]Couldn't reach Telegram: {type(e).__name__}: {e}[/red]")
        return 2
    if not me.get("ok"):
        console.print(f"  [red]Token rejected by Telegram: {me.get('description','?')}[/red]")
        return 2
    bot_username = me["result"].get("username", "?")
    console.print(f"  [green]✓ Token valid[/green] — bot is [cyan]@{bot_username}[/cyan]")

    # Auto-discover chat_id
    console.print()
    console.print("  [bold]2. Link your chat[/bold]")
    console.print(f"     Open Telegram → search for [cyan]@{bot_username}[/cyan] → hit Start.")
    console.print(f"     Or tap this link: {_link(f'https://t.me/{bot_username}')}")
    console.print(f"     I'll wait up to 60s for your message…")

    # Drain any queued updates so we only pick up NEW /start events
    try:
        with urllib.request.urlopen(
            f"https://api.telegram.org/bot{token}/getUpdates?offset=-1&timeout=0", timeout=5,
        ) as r:
            drain = json.loads(r.read())
        offset = (drain.get("result") or [{}])[-1].get("update_id", 0) + 1 if drain.get("result") else 0
    except Exception:
        offset = 0

    chat_id: str | int | None = None
    deadline = time.time() + 60
    while time.time() < deadline and not chat_id:
        try:
            url = (f"https://api.telegram.org/bot{token}/getUpdates"
                   f"?timeout=10&offset={offset}")
            with urllib.request.urlopen(url, timeout=15) as r:
                upd = json.loads(r.read())
            for u in upd.get("result") or []:
                offset = u["update_id"] + 1
                msg = u.get("message") or u.get("edited_message") or {}
                chat = msg.get("chat") or {}
                if chat.get("id"):
                    chat_id = chat["id"]
                    who = (msg.get("from") or {}).get("username") or chat.get("title") or "you"
                    console.print(f"  [green]✓ Linked[/green] — chat_id [cyan]{chat_id}[/cyan] ({who})")
                    break
        except Exception:
            time.sleep(1)

    updates = {"TELEGRAM_BOT_TOKEN": token}
    if chat_id:
        # Lock the bot to this chat by default — can be widened later.
        updates["TELEGRAM_ALLOWED_CHAT_IDS"] = str(chat_id)
    else:
        console.print("  [yellow]Timed out waiting for /start.[/yellow] "
                      "The bot will accept any chat until you set "
                      "[cyan]TELEGRAM_ALLOWED_CHAT_IDS[/cyan] manually.")

    _write_env_updates(updates)
    console.print(f"  [green]✓ Saved[/green] → {ENV_PATH}")
    console.print()
    console.print("  [dim]Restart FRIDAY for the listener to pick up.[/dim]")
    return 0


# ── Gmail / Google ───────────────────────────────────────────────────────────

def setup_gmail() -> int:
    """Google Gmail + Calendar — just a browser login.

    FRIDAY ships a shared OAuth client at ``friday/data/google_client.json``,
    so there's no GCP project to create. Click the button, consent in the
    browser, done. The only friction is Google's "unverified app" warning,
    which shows once until FRIDAY gets through Google's app verification.
    """
    console.print()
    console.print(Rule("Google (Gmail + Calendar)", style="green"))
    console.print()

    if GOOGLE_TOKEN.exists():
        console.print(f"  [green]✓[/green] Already signed in (token at [dim]{GOOGLE_TOKEN}[/dim])")
        if not _confirm("Re-run the sign-in flow?", default=False):
            return 0

    console.print("  Heads up: you'll see Google's 'This app isn't verified' warning once.")
    console.print("  Click [cyan]Advanced[/cyan] → [cyan]Go to FRIDAY (unsafe)[/cyan]. That's normal for")
    console.print("  community-built tools until FRIDAY clears Google app verification.")
    console.print("  Your data only moves between your browser, Google, and this machine.")
    console.print()

    if not _confirm("Open the browser to sign in?", default=True):
        return 0

    try:
        from friday.tools.google_auth import authenticate
        authenticate()
        console.print(f"  [green]✓ Signed in[/green]")
        return 0
    except Exception as e:
        console.print(f"  [red]Sign-in failed: {e}[/red]")
        return 2


# ── Voice + gestures ─────────────────────────────────────────────────────────

def setup_voice() -> int:
    console.print()
    console.print(Rule("Voice pipeline setup", style="green"))
    console.print()
    console.print("  FRIDAY's voice mode:")
    console.print("    · Ambient listen → say 'Friday' any time")
    console.print("    · STT runs fully local (Silero VAD + MLX Whisper) — nothing leaves your mac")
    console.print("    · TTS: ElevenLabs (cloud, ~75ms) or Kokoro (local, ~500ms)")
    console.print()

    env = _read_env()
    enable = _confirm("Enable voice pipeline (FRIDAY_VOICE=true)?", default=True)

    updates = {"FRIDAY_VOICE": "true" if enable else "false"}

    if enable:
        console.print()
        console.print("  TTS choice:")
        console.print("    1. ElevenLabs (cloud, fastest) — needs API key")
        console.print("    2. Kokoro (local, private) — auto-downloads model on first use")
        pick = _ask("Pick 1 or 2", default="2")
        if pick == "1":
            el_key = _ask("ELEVENLABS_API_KEY", default=env.get("ELEVENLABS_API_KEY", ""), secret=True)
            if el_key:
                updates["ELEVENLABS_API_KEY"] = el_key
            voice_id = _ask("ELEVENLABS_VOICE_ID (blank = 'George' default)",
                            default=env.get("ELEVENLABS_VOICE_ID", ""))
            if voice_id:
                updates["ELEVENLABS_VOICE_ID"] = voice_id

    _write_env_updates(updates)
    console.print(f"  [green]✓ Saved[/green] → {ENV_PATH}")
    if enable:
        console.print("  Launch with: [cyan]friday --voice[/cyan] · or toggle at runtime: [cyan]/voice[/cyan]")
    return 0


def setup_gestures() -> int:
    console.print()
    console.print(Rule("Hand gesture control setup", style="green"))
    console.print()
    console.print("  Camera-based gesture control via MediaPipe. Runs fully local.")
    console.print()
    console.print("  [bold yellow]macOS heads-up:[/bold yellow] FRIDAY runs gesture detection on a background thread,")
    console.print("  so macOS can't auto-prompt for camera access. Before enabling, grant")
    console.print("  permission manually:")
    console.print("    [cyan]System Settings → Privacy & Security → Camera[/cyan]")
    console.print("  …and toggle on whichever terminal app you launched `friday` from")
    console.print("  (Terminal, iTerm, Warp, Ghostty, etc.), or Friday.app if you're on the Mac build.")
    console.print()

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    if GESTURE_TASK.exists():
        console.print(f"  [green]✓[/green] MediaPipe task already at {GESTURE_TASK}")
    else:
        console.print(f"  Downloading MediaPipe gesture model (~8 MB)…")
        try:
            urllib.request.urlretrieve(GESTURE_TASK_URL, GESTURE_TASK)
            console.print(f"  [green]✓ Downloaded[/green] → {GESTURE_TASK}")
        except Exception as e:
            console.print(f"  [red]Download failed: {e}[/red]")
            return 2

    enable = _confirm("Enable gestures (FRIDAY_GESTURES=true)?", default=True)
    _write_env_updates({"FRIDAY_GESTURES": "true" if enable else "false"})
    console.print(f"  [green]✓ Saved[/green] → {ENV_PATH}")
    if enable:
        console.print("  Launch FRIDAY — camera opens automatically. Toggle at runtime: [cyan]/gestures[/cyan]")
    return 0


# ── Tests ────────────────────────────────────────────────────────────────────

def _run_async(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_llm() -> int:
    console.print()
    console.print(Rule("Test · LLM", style="green"))
    try:
        from friday.core.llm import cloud_chat, extract_text
        from friday.core.config import USE_CLOUD, CLOUD_MODEL_NAME
    except Exception as e:
        console.print(f"  [red]Import failed: {e}[/red]")
        return 2

    if not USE_CLOUD:
        console.print("  [yellow]No cloud key configured.[/yellow] Run `friday setup openrouter` or `friday setup groq`.")
        return 1

    console.print(f"  model: [cyan]{CLOUD_MODEL_NAME}[/cyan]")
    console.print("  sending: 'say hi in 3 words'…")
    try:
        resp = cloud_chat(messages=[{"role": "user", "content": "say hi in 3 words"}], max_tokens=20)
        text = extract_text(resp).strip()
        console.print(f"  [green]✓[/green] response: {text}")
        return 0
    except Exception as e:
        console.print(f"  [red]Call failed: {e}[/red]")
        return 2


def test_gmail() -> int:
    console.print()
    console.print(Rule("Test · Gmail", style="green"))
    if not GOOGLE_TOKEN.exists():
        console.print("  [yellow]Not signed in.[/yellow] Run `friday setup gmail`.")
        return 1
    try:
        from friday.tools.email_tools import read_emails
        r = _run_async(read_emails(filter="unread", limit=1, include_body=False))
        if not r.success:
            console.print(f"  [red]{r.error.message if r.error else 'Failed.'}[/red]")
            return 2
        count = len(r.data.get("emails", [])) if isinstance(r.data, dict) else len(r.data or [])
        console.print(f"  [green]✓[/green] fetched {count} unread email(s)")
        return 0
    except Exception as e:
        console.print(f"  [red]Call failed: {e}[/red]")
        return 2


def test_twilio() -> int:
    console.print()
    console.print(Rule("Test · Twilio", style="green"))
    env = _read_env()
    to = env.get("CONTACT_PHONE") or USER.phone or os.environ.get("CONTACT_PHONE", "")
    if not to:
        console.print("  [yellow]No CONTACT_PHONE set.[/yellow] Run `friday setup twilio`.")
        return 1
    try:
        from friday.tools.sms_tools import send_sms
        r = _run_async(send_sms(to=to, message="FRIDAY test SMS — reply if you got this."))
        if r.success:
            console.print(f"  [green]✓[/green] SMS sent to {to}")
            return 0
        console.print(f"  [red]Failed: {r.error.message if r.error else 'unknown'}[/red]")
        return 2
    except Exception as e:
        console.print(f"  [red]Call failed: {e}[/red]")
        return 2


def test_tv() -> int:
    console.print()
    console.print(Rule("Test · LG TV", style="green"))
    try:
        from friday.tools.tv_tools import tv_status
        r = _run_async(tv_status())
        if r.success:
            console.print(f"  [green]✓[/green] {r.data}")
            return 0
        console.print(f"  [yellow]TV unreachable: {r.error.message if r.error else 'no response'}[/yellow]")
        console.print("  (First-time pairing requires the TV to be on the same LAN and prompted for approval.)")
        return 1
    except Exception as e:
        console.print(f"  [red]Call failed: {e}[/red]")
        return 2


# ── Heartbeat explainer ──────────────────────────────────────────────────────

def heartbeat() -> int:
    console.print()
    console.print(Rule("FRIDAY · heartbeat", style="green"))
    console.print()
    console.print(
        "  The heartbeat is a background loop that runs while FRIDAY is open.\n"
        "  Two jobs:\n\n"
        "  [bold]1. Silent checks[/bold] — every ~30min, glances at your inbox, calendar,\n"
        "     missed calls, and active monitors. Zero LLM cost unless something\n"
        "     actionable is found; then it nudges you.\n\n"
        "  [bold]2. Watch tasks[/bold] — standing orders you give conversationally.\n"
        "     \"watch my partner's messages for the next hour, reply as FRIDAY if she texts\"\n"
        "     Heartbeat checks every 60s; one LLM call per detected trigger.\n"
    )

    cfg_path = Path(__file__).parent.parent.parent / "HEARTBEAT.md"
    if cfg_path.exists():
        console.print(f"  Config file: [cyan]{cfg_path}[/cyan]  (interval, quiet hours, daily cap)")
    else:
        console.print("  [dim]No HEARTBEAT.md — FRIDAY uses defaults: 30-minute interval, quiet 1am–7am, 3 nudges/day.[/dim]")

    console.print()
    console.print("  Active watch tasks:")
    try:
        from friday.background.heartbeat import get_heartbeat_runner
        runner = get_heartbeat_runner()
        watches = runner.list_watches()
        if not watches:
            console.print("    [dim](none)[/dim]")
        else:
            for w in watches:
                console.print(f"    · {w.get('instruction', '')[:80]}   [dim]every {w.get('interval_seconds')}s[/dim]")
    except Exception as e:
        console.print(f"    [yellow]Couldn't list watches: {e}[/yellow]")

    console.print()
    console.print("  Useful commands:")
    console.print("    [cyan]\"watch X for the next hour, reply if …\"[/cyan]  — create a standing order")
    console.print("    [cyan]/clearwatches[/cyan]                            — cancel all active watches")
    console.print()
    return 0


# ── CLI dispatch ─────────────────────────────────────────────────────────────

# ── Update — detect how FRIDAY was installed, run the right upgrade ─────────
#
# The goal: a single `friday update` that works no matter how the user got
# FRIDAY. We sniff `sys.executable`'s path to figure out which tool owns us,
# then shell out to that tool's upgrade command.

_GITHUB_REPO = "angeloasante/Jarvis"


def _installed_version() -> str:
    try:
        from importlib.metadata import version
        return version("friday-os")
    except Exception:
        return "unknown"


def _tool_inventory() -> tuple[int, int]:
    """Walk friday.tools and count every TOOL_SCHEMAS entry.

    Returns (total_tools, module_count). Used by `friday doctor` so users can
    see at a glance that their install brought every tool down.
    """
    import importlib, pkgutil
    try:
        import friday.tools as _tools_pkg
    except Exception:
        return (0, 0)

    total = 0
    modules = 0
    for info in pkgutil.iter_modules(_tools_pkg.__path__):
        name = info.name
        if name.startswith("_") or name == "browser_tools_old":
            continue
        try:
            m = importlib.import_module(f"friday.tools.{name}")
        except Exception:
            continue
        schemas = getattr(m, "TOOL_SCHEMAS", None)
        if isinstance(schemas, dict):
            total += len(schemas)
            modules += 1
    return (total, modules)


def _latest_git_sha() -> tuple[str, str]:
    """Fetch the short SHA + commit subject of origin/main. Never raises."""
    url = f"https://api.github.com/repos/{_GITHUB_REPO}/commits/main"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        return data["sha"][:10], (data.get("commit", {}).get("message", "") or "").splitlines()[0]
    except Exception:
        return "", ""


def _detect_install_method() -> tuple[str, str]:
    """Return (method, description). `method` is one of:

        uv_tool   — installed via `uv tool install friday-os`
        pipx      — installed via `pipx install friday-os`
        pip_user  — installed via `pip install --user friday-os`
        dev       — running from a source checkout (uv sync / pip install -e)
        mac_app   — bundled Python inside Friday.app
        unknown   — fall back to manual instructions
    """
    exe = Path(sys.executable).resolve()
    exe_str = str(exe)

    # Mac app bundles Python at .../Friday.app/Contents/Resources/python/bin/python3
    if ".app/Contents/Resources/python" in exe_str:
        return "mac_app", f"bundled inside Friday.app ({exe})"

    # Dev install wins over every other detection: if the `friday` module is
    # being imported from a directory that looks like a git repo with its
    # own pyproject.toml naming friday-os, we're running from a checkout.
    try:
        import friday as _friday_mod
        friday_path = Path(_friday_mod.__file__).resolve().parent
        # walk up a couple levels looking for the repo root
        for ancestor in [friday_path.parent, *friday_path.parents]:
            if (ancestor / ".git").is_dir() and (ancestor / "pyproject.toml").is_file():
                return "dev", f"source checkout at {ancestor}"
    except Exception:
        pass

    # uv tool installs live at ~/.local/share/uv/tools/<name>/ or $UV_TOOL_DIR.
    # Critical: `uv tool install` symlinks the venv's python to UV's shared
    # interpreter at ~/.local/share/uv/python/, so sys.executable does NOT
    # contain /uv/tools/. We have to check the entry-point script instead —
    # sys.argv[0] stays pointing at .../uv/tools/<name>/bin/<script>.
    uv_tool_dir = os.environ.get("UV_TOOL_DIR", str(Path.home() / ".local/share/uv/tools"))
    try:
        argv0 = Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0] else exe
        argv0_str = str(argv0)
    except Exception:
        argv0_str = ""
    if (
        uv_tool_dir in exe_str
        or "/uv/tools/" in exe_str
        or uv_tool_dir in argv0_str
        or "/uv/tools/" in argv0_str
    ):
        return "uv_tool", f"uv tool install friday-os  ({argv0_str or exe})"

    # pipx venvs live at ~/.local/share/pipx/venvs/<name>/
    if "/pipx/venvs/" in exe_str or "/pipx/venvs/" in argv0_str:
        return "pipx", f"pipx install friday-os  ({exe})"

    # Plain `pip install --user` → user-site packages dir
    import site
    user_base = Path(site.getuserbase()).resolve()
    if str(user_base) in exe_str or "site-packages" in exe_str:
        return "pip_user", f"pip install (python at {exe})"

    return "unknown", f"python at {exe}"


def _upgrade_cmd_for(method: str) -> list[str] | None:
    """Command that, when run, reinstalls the latest FRIDAY for this method."""
    if method == "uv_tool":
        # --reinstall forces a fresh pull; handy when installed from git (no
        # semver to compare, so `uv tool upgrade` alone is a no-op).
        return ["uv", "tool", "install", "--force", "--reinstall",
                f"friday-os @ git+https://github.com/{_GITHUB_REPO}"]
    if method == "pipx":
        return ["pipx", "reinstall", "friday-os"]
    if method == "pip_user":
        # Some managed environments (UV's shared interpreter, Python built
        # from source without ensurepip) don't ship pip. If pip is missing,
        # defer to uv tool install instead — that's the most common route
        # for interpreter-managed installs on modern macOS.
        import importlib.util as _iu
        if _iu.find_spec("pip") is None:
            return ["uv", "tool", "install", "--force", "--reinstall",
                    f"friday-os @ git+https://github.com/{_GITHUB_REPO}"]
        return [sys.executable, "-m", "pip", "install", "--user", "--upgrade",
                f"friday-os @ git+https://github.com/{_GITHUB_REPO}"]
    if method == "dev":
        return ["bash", "-lc", "git pull && uv sync"]
    return None  # mac_app / unknown handled separately


def update() -> int:
    """Update FRIDAY in place using whatever installer put it here."""
    console.print()
    console.print(Rule("FRIDAY · update", style="green"))
    console.print()

    method, detail = _detect_install_method()
    current = _installed_version()
    tools_n, modules_n = _tool_inventory()
    sha, subject = _latest_git_sha()

    # Version panel
    t = Table(show_header=False, box=None, pad_edge=False)
    t.add_column(style="dim", no_wrap=True)
    t.add_column(overflow="fold")
    t.add_row("installed",      f"friday-os {current}  ({tools_n} tools, {modules_n} modules)")
    t.add_row("install method", detail)
    if sha:
        t.add_row("latest on main", f"{sha}  {subject}")
    console.print(t)
    console.print()
    console.print("  [dim]Update pulls the full tree — new files, new agents, new tools, new features,[/dim]")
    console.print("  [dim]and updated dependencies.  It's not just a version bump.[/dim]")
    console.print()

    if method == "mac_app":
        console.print("  You're running the bundled Mac app. To update, download the")
        console.print(f"  latest [cyan]Friday.dmg[/cyan] from:")
        console.print(f"    [cyan]https://github.com/{_GITHUB_REPO}/releases/latest[/cyan]")
        console.print("  Drag it to Applications (replacing the old one). Nothing in")
        console.print("  ~/Friday/ or ~/.friday/ is touched — your config survives.")
        return 0

    cmd = _upgrade_cmd_for(method)
    if not cmd:
        console.print(f"  [yellow]Couldn't auto-detect how FRIDAY is installed.[/yellow]")
        console.print("  Manual options (pick the one that matches how you installed):")
        console.print(f"    [cyan]uv tool install --force --reinstall 'friday-os @ git+https://github.com/{_GITHUB_REPO}'[/cyan]")
        console.print(f"    [cyan]pipx reinstall friday-os[/cyan]")
        console.print(f"    [cyan]pip install --user --upgrade 'friday-os @ git+https://github.com/{_GITHUB_REPO}'[/cyan]")
        return 1

    # Show command, confirm, exec
    pretty = " ".join(cmd) if not (cmd[0] == "bash" and len(cmd) > 2) else cmd[-1]
    console.print(f"  Running: [cyan]{pretty}[/cyan]")
    console.print()
    if not _confirm("Proceed?", default=True):
        return 0

    rc = subprocess.call(cmd)
    console.print()
    if rc == 0:
        new_version = _installed_version()  # won't pick up new version in THIS process
        console.print(f"  [green]✓ Updated.[/green]  Restart FRIDAY to pick up the new code.")
        if new_version != current:
            console.print(f"  [dim]{current} → {new_version}[/dim]")
    else:
        console.print(f"  [red]Update failed (exit {rc}).[/red]")
    console.print()
    return rc


_SETUP_COMMANDS: dict[str, Callable[[], int]] = {
    "deps":       setup_deps,
    "openrouter": setup_openrouter,
    "gemma":      setup_gemma,
    "groq":       setup_groq,
    "tavily":     setup_tavily,
    "elevenlabs": setup_elevenlabs,
    "x":          setup_x,
    "twilio":     setup_twilio,
    "telegram":   setup_telegram,
    "gmail":      setup_gmail,
    "voice":      setup_voice,
    "gestures":   setup_gestures,
}

_TEST_COMMANDS: dict[str, Callable[[], int]] = {
    "llm":    test_llm,
    "gmail":  test_gmail,
    "twilio": test_twilio,
    "tv":     test_tv,
}


def maybe_handle_admin_command(argv: list[str]) -> int | None:
    """Handle `friday doctor/setup/test/heartbeat`. Return exit code or None."""
    if len(argv) < 2:
        return None
    cmd = argv[1]

    if cmd == "doctor":
        return doctor()

    if cmd == "onboard":
        return onboard()

    if cmd == "update":
        return update()

    if cmd == "heartbeat":
        return heartbeat()

    if cmd == "setup":
        if len(argv) < 3:
            console.print("  [yellow]Usage:[/yellow] [cyan]friday setup <component>[/cyan]")
            console.print("  Components: " + ", ".join(_SETUP_COMMANDS))
            return 2
        sub = argv[2]
        handler = _SETUP_COMMANDS.get(sub)
        if not handler:
            console.print(f"  [red]Unknown component: {sub}[/red]")
            console.print("  Available: " + ", ".join(_SETUP_COMMANDS))
            return 2
        return handler()

    if cmd == "test":
        if len(argv) < 3:
            console.print("  [yellow]Usage:[/yellow] [cyan]friday test <component>[/cyan]")
            console.print("  Components: " + ", ".join(_TEST_COMMANDS))
            return 2
        sub = argv[2]
        handler = _TEST_COMMANDS.get(sub)
        if not handler:
            console.print(f"  [red]Unknown component: {sub}[/red]")
            console.print("  Available: " + ", ".join(_TEST_COMMANDS))
            return 2
        return handler()

    return None
