# FRIDAY CLI Reference

FRIDAY exposes two command surfaces. The **shell layer** (`friday …` invocations from a terminal) handles install-time concerns: onboarding, diagnostics, per-service setup, connectivity tests, and version upgrades. The **REPL layer** (slash commands typed into the running prompt) handles runtime state: voice, gestures, memory, background watches, and forced agent routing. Admin shell commands short-circuit before `FridayCore` ever boots, so they are safe to run even when the app is misconfigured. This doc covers every command both layers expose, where it lives in code, and when to reach for it.

Source entry points:

- [cli.py](../friday/cli.py) — REPL loop + slash-command dispatch + startup wiring
- [onboarding.py](../friday/core/onboarding.py) — `friday init` / `friday config …`
- [setup_wizard.py](../friday/core/setup_wizard.py) — `friday onboard`, `doctor`, `update`, `setup <svc>`, `test <svc>`, `heartbeat`

---

## 1. Shell commands (outside the REPL)

`friday` with no argument launches the REPL (running the first-run wizard if no profile exists). Every other `friday <subcommand>` is intercepted by one of two admin hooks in [cli.py](../friday/cli.py#L354-L368) before any orchestrator is constructed:

```
for handler in (_profile_admin, _wizard_admin):
    admin_exit = handler(sys.argv)
    if admin_exit is not None:
        sys.exit(admin_exit)
```

`_profile_admin` is `maybe_handle_admin_command` from [onboarding.py](../friday/core/onboarding.py#L282); `_wizard_admin` is the same-named function in [setup_wizard.py](../friday/core/setup_wizard.py#L1191). The first handler to return a non-None exit code wins; otherwise boot proceeds.

| Command | Purpose | Source |
|---|---|---|
| `friday` | Launch REPL (wizard runs on first run) | [cli.py:354](../friday/cli.py#L354) |
| `friday --voice` | Launch REPL with voice pipeline started | [cli.py:146](../friday/cli.py#L146) |
| `friday init` | Re-run the profile wizard (writes `~/Friday/user.json`) | [onboarding.py:293](../friday/core/onboarding.py#L293) |
| `friday config` | Print the current `user.json` | [onboarding.py:268](../friday/core/onboarding.py#L268) |
| `friday config edit` | Open `user.json` in `$EDITOR` | [onboarding.py:260](../friday/core/onboarding.py#L260) |
| `friday config path` | Print the path (scriptable) | [onboarding.py:256](../friday/core/onboarding.py#L256) |
| `friday config open` | Reveal `~/Friday/` in Finder | [onboarding.py:265](../friday/core/onboarding.py#L265) |
| `friday onboard` | Full guided setup (QuickStart or Advanced) | [setup_wizard.py:382](../friday/core/setup_wizard.py#L382) |
| `friday doctor` | Audit every integration + system dep | [setup_wizard.py:175](../friday/core/setup_wizard.py#L175) |
| `friday update` | Pull latest release via the installer that put FRIDAY here | [setup_wizard.py:1108](../friday/core/setup_wizard.py#L1108) |
| `friday heartbeat` | Explain background heartbeat + list active watches | [setup_wizard.py:940](../friday/core/setup_wizard.py#L940) |
| `friday setup <svc>` | One-shot per-service wizard | [setup_wizard.py:1209](../friday/core/setup_wizard.py#L1209) |
| `friday test <svc>` | Connectivity test for a configured service | [setup_wizard.py:1222](../friday/core/setup_wizard.py#L1222) |

### `friday init`

Re-runs the profile wizard at [run_onboarding](../friday/core/onboarding.py#L170). Prompts for name, bio, location, country code (auto-normalised from "uk"/"+44"/etc.), email, phone, GitHub, website, tone. Writes `~/Friday/user.json` with mode `0600`. Existing values are shown as defaults and preserved on empty input; hand-edited fields (slang, contact aliases, watchlist, CV) are never clobbered.

Exit codes: `0` on save. Ctrl-C during prompts exits with a "cancelled" message and non-zero status via `sys.exit`.

Example tail:

```
  ✓ Saved → ~/Friday/user.json
  Advanced fields (slang, contact aliases, watchlist, CV) live in that JSON file.
  Run `friday config edit` to open it.
```

**When to use:** after cloning on a new machine, or whenever you want to reset your identity/tone. For small tweaks, `friday config edit` is faster.

### `friday config [show|edit|path|open]`

Dispatched by [handle_config_subcommand](../friday/core/onboarding.py#L252). No subcommand defaults to `show`.

- `show` — pretty-prints `~/Friday/user.json`. If the file is missing, says so and points at `friday init`.
- `edit` — opens the file in `$EDITOR` / `$VISUAL` / `nano` (in that order). Creates an empty `{}` at mode `0600` if missing. Reloads config on exit.
- `path` — prints the absolute path to stdout and nothing else. Suitable for `$(friday config path)` in scripts.
- `open` — `open ~/Friday/` on macOS, `xdg-open` on Linux, print-path fallback elsewhere.

Unknown subcommands print usage and return exit code `2`.

**When to use:** for anything beyond the wizard's captured fields — editing `cv`, `contact_aliases`, `briefing_watchlist`, `slang`.

### `friday onboard`

Implemented at [onboard](../friday/core/setup_wizard.py#L382). Guided flow with two modes:

1. **QuickStart** — profile + system deps + one cloud LLM + health check
2. **Advanced** — QuickStart plus optional steps for Tavily, Gmail + Calendar, Twilio, ElevenLabs, X, voice, gestures

Each step prints `[N/total] <label>` and calls into the same `setup_*` functions used by `friday setup <svc>`. Safe to re-run: existing config is shown with a "skip?" prompt rather than overwritten.

**When to use:** first machine setup, or after a major update when you want to review everything.

### `friday doctor`

Implemented at [doctor](../friday/core/setup_wizard.py#L175). Prints two tables:

1. **Integrations** — profile, CV, LLM provider, Ollama, Gmail/Calendar, Tavily, Twilio, X, voice, gestures, WhatsApp bridge, ngrok — each marked `✓` or `○` with a short detail.
2. **System dependencies** — Python 3.12+, uv, ollama, node, ngrok, brew — each with version string or install hint.

Header strip shows `friday-os <version> · via <method> · <N> tools across <M> modules · `friday update` to refresh`. The install method (`uv tool`, `pipx`, `pip --user`, `source`, `Mac app`) is detected by `_detect_install_method` at [setup_wizard.py:1043](../friday/core/setup_wizard.py#L1043).

Returns `0`. If anything is missing the footer lists counts and suggests `friday onboard` or `friday setup deps`.

**When to use:** when something isn't working and you want a single view of what's configured. Run this before filing a bug report.

### `friday update`

Implemented at [update](../friday/core/setup_wizard.py#L1108). Detects install method via `sys.executable`'s path, shows installed version vs. the latest commit SHA on `main`, confirms the upgrade command, and shells out:

- `uv_tool` → `uv tool install --force --reinstall 'friday-os @ git+https://github.com/angeloasante/Jarvis'`
- `pipx` → `pipx reinstall friday-os`
- `pip_user` → `pip install --user --upgrade 'friday-os @ git+...'`
- `dev` → `git pull && uv sync`
- `mac_app` → prints DMG download link (no auto-update for the bundled app)
- `unknown` → lists manual options, returns `1`

Exit code mirrors the child installer's (`0` on success). Config in `~/Friday/` and `~/.friday/` is never touched.

**When to use:** any time. Prints the upgrade plan before running; answer `n` at the confirm prompt to back out.

### `friday heartbeat`

Implemented at [heartbeat](../friday/core/setup_wizard.py#L940). Explains the background loop (silent ~30-minute inbox/calendar/calls poll plus conversational watch tasks that poll every 60s), prints the `HEARTBEAT.md` config path if one exists, and lists every active watch from `runner.list_watches()` with its instruction and interval.

**When to use:** when you want to know what FRIDAY is actively monitoring, or when a watch feels stuck. Pair with `/clearwatches` in the REPL to wipe everything.

### `friday setup <component>`

Dispatched at [setup_wizard.py:1209](../friday/core/setup_wizard.py#L1209). Each handler writes keys into `~/.friday/.env` (mode `0600`) via `_write_env_updates`, which also injects them into `os.environ` so the current process sees them. Supported components:

| Component | What it does | Notes |
|---|---|---|
| `deps` | Brew-install missing system tools | Only offers packages whose hint starts with `brew install` |
| `openrouter` | Save `OPENROUTER_API_KEY`; optionally pick a tool-capable model from the live catalogue | Writes `CLOUD_MODEL` if a model is selected |
| `groq` | Save `GROQ_API_KEY` | Validates `gsk_` prefix |
| `tavily` | Save `TAVILY_API_KEY` | Powers the research agent's web search |
| `elevenlabs` | Save `ELEVENLABS_API_KEY` + optional `ELEVENLABS_VOICE_ID` | Leave unset to fall back to local Kokoro TTS |
| `x` | Save `X_BEARER_TOKEN` plus optional OAuth 1.0a quad for posting | Read-only works with bearer alone |
| `twilio` | Save `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`, `CONTACT_PHONE`, optional `NGROK_DOMAIN` | Validates `AC…` SID + E.164 phone |
| `gmail` | Browser-based Google OAuth via the shipped shared client | Caches token at `~/.friday/google_token.json` |
| `voice` | Set `FRIDAY_VOICE=true` and pick ElevenLabs vs. Kokoro | STT is always local (Whisper) |
| `gestures` | Download the MediaPipe task file (~8 MB) and set `FRIDAY_GESTURES=true` | Prints macOS camera-permission instructions |

Exit codes: `0` on save/skip, `1` if prerequisites missing, `2` on validation failure. Unknown components return `2` and list the available ones.

**When to use:** when you just want to wire up one service without running the full onboarding flow.

### `friday test <component>`

Dispatched at [setup_wizard.py:1222](../friday/core/setup_wizard.py#L1222). Real connectivity checks:

| Component | What it verifies |
|---|---|
| `llm` | Sends "say hi in 3 words" to the configured cloud provider; prints the reply |
| `gmail` | Fetches one unread email via `read_emails` |
| `twilio` | Sends a test SMS to `CONTACT_PHONE` |
| `tv` | Calls `tv_status` on the paired LG TV (same LAN required) |

Exit codes: `0` if the call succeeds, `1` if prerequisites are unmet (no key, no token, no `CONTACT_PHONE`), `2` on exception. Unknown components return `2`.

**When to use:** after `friday setup <svc>`, to prove the key actually works before you hit the REPL.

---

## 2. REPL slash commands

Inside the running prompt (`▶ `), anything starting with `/` is handled inline at [cli.py:211](../friday/cli.py#L211) before reaching the orchestrator. Everything else is shipped to `friday.fast_path` and then (if no fast-path match) to `dispatch_background_agent`.

| Slash | Purpose | Source |
|---|---|---|
| `/help` | Print the slash-command menu + current voice/gesture status | [cli.py:211](../friday/cli.py#L211) |
| `/quit` | Stop voice + gesture listeners, exit the loop | [cli.py:249](../friday/cli.py#L249) |
| `/clear` | Clear the in-memory conversation | [cli.py:257](../friday/cli.py#L257) |
| `/memory` | Show the ten most recent stored memories | [cli.py:262](../friday/cli.py#L262) |
| `/voice` | Toggle the voice pipeline on/off | [cli.py:273](../friday/cli.py#L273) |
| `/listening-on` | Resume ambient mic listening (voice must be running) | [cli.py:330](../friday/cli.py#L330) |
| `/listening-off` | Pause ambient mic without tearing down the pipeline | [cli.py:322](../friday/cli.py#L322) |
| `/gestures` | Toggle gesture detection | [cli.py:289](../friday/cli.py#L289) |
| `/gestures-on` | Explicitly start gestures | [cli.py:289](../friday/cli.py#L289) |
| `/gestures-off` | Explicitly stop gestures + release camera | [cli.py:289](../friday/cli.py#L289) |
| `/clearwatches` | Deactivate every row in `watch_tasks` where `active=1` | [cli.py:313](../friday/cli.py#L313) |

### `/help`

Prints the full menu in four groups (Commands, Voice, Gesture Control, Background, Agent Override) and a final status line showing `Voice: ON/OFF | Gestures: ON/OFF`. The status is derived from each listener's `_running` flag. No side effects.

### `/quit`

Calls `voice_pipeline.stop()` and `gesture_listener.stop()` if either is running, prints "Session terminated.", breaks out of the REPL loop. The heartbeat and cron scheduler tasks are daemon-like and exit with the process.

### `/clear`

Calls `friday.conversation.clear()`. Purely in-memory — persisted memories are untouched. Useful when a long tangent is polluting the context window.

### `/memory`

Calls `friday.memory.get_recent(10)` and prints each entry as `> [category] content…` truncated to 80 chars. If the store is empty, prints "No memories stored yet." Does not read from or trigger the LLM.

### `/voice`

Toggles the voice pipeline. If running, `stop()` + drop the reference. Otherwise imports `VoicePipeline`, wires it to the current asyncio loop, and `start()`s it. Failures print `✗ Voice failed: <err>` and leave state unchanged.

### `/listening-on` and `/listening-off`

Call `voice_pipeline.set_listening(True|False)` when the pipeline exists — the wake-word loop stays spun up but ignores (or resumes) ambient audio. If the pipeline isn't running they print "Voice pipeline not running. Start with /voice".

**When to use vs. `/voice`:** `/listening-off` keeps the audio stack warm (cheap resume). `/voice off` tears everything down.

### `/gestures`, `/gestures-on`, `/gestures-off`

A single handler at [cli.py:289](../friday/cli.py#L289) covers all three. The logic:

```
is_on    = gesture_listener and gesture_listener._running
want_on  = /gestures-on OR (/gestures AND !is_on)
want_off = /gestures-off OR (/gestures AND is_on)
```

Starting instantiates `GestureListener` with the asyncio loop. Stopping releases the camera. Explicit on/off on a listener that's already in that state prints "Gestures already ON/OFF" (no-op). Failures print `✗ Gestures failed: <err>`.

### `/clearwatches`

Reads the memory store's SQLite DB directly:

```sql
SELECT COUNT(*) FROM watch_tasks WHERE active = 1;
UPDATE watch_tasks SET active = 0 WHERE active = 1;
```

Prints `:: Cleared N active watch task(s)`. Watch definitions stay in the table (so they can be resurrected), they just stop firing. To list what's running without clearing, use `friday heartbeat` from a second terminal.

---

## 3. Agent override prefixes

When input starts with `@agent_name`, the router skips classification and jumps straight to that agent. `/help` documents these at [cli.py:232-240](../friday/cli.py#L232-L240):

| Prefix | Forces routing to |
|---|---|
| `@comms` | Comms agent (email, SMS, WhatsApp, iMessage) |
| `@research` | Research agent (Tavily web search + synthesis) |
| `@household` | Household agent (LG TV, smart home) |
| `@system` | System agent (shell, files, macOS automation) |
| `@social` | Social agent (X / Twitter) |
| `@code` | Code agent (repo edits, git, execution) |
| `@job` | Job agent (CV tailoring, application drafting) |
| `@memory` | Memory agent (explicit store / recall) |

Prefixes are pattern-matched by the router rather than by the REPL loop itself — the REPL ships the full line (including `@prefix`) into `friday.fast_path` and then into `dispatch_background_agent`. That means agent prefixes also work from SMS, voice, and any other input channel that feeds the orchestrator.

**When to use:** when you know better than the classifier. Good examples: `@research what did OpenAI announce today` to force a web search rather than a pre-trained answer; `@code refactor friday/core/llm.py` to skip research/comms paths.

---

## 4. First-run flow

What a brand-new user sees when they type `friday` the very first time, stepping through [cli.py:354-377](../friday/cli.py#L354-L377):

1. Both admin hooks run — neither matches (argv is just `["friday"]`), both return `None`.
2. `ensure_friday_dir()` creates `~/Friday/` and drops a `README.md` explaining the single-file config layout. A one-time `migrate_from_legacy()` picks up any old-format config.
3. `needs_onboarding()` returns `True` because `user.json` is missing.
4. If stdin is a TTY, `run_onboarding()` ([onboarding.py:170](../friday/core/onboarding.py#L170)) prints the banner, explains the flow, and prompts for the profile fields (name, bio, location, country code with smart normalisation, email, phone, GitHub, website, tone). Any field can be skipped with Enter.
5. `user.json` is written at mode `0600`, the in-memory config is reloaded, and the user is shown the saved path with a hint to run `friday config edit` for advanced fields.
6. Control returns to `run()`, which calls `asyncio.run(main())`.
7. `main()` prints the green FRIDAY banner, constructs `FridayCore`, starts the heartbeat + cron scheduler, kicks off GitHub project sync, optionally starts voice (if `--voice`), optionally starts gestures (if `FRIDAY_GESTURES=true`), optionally starts the Twilio SMS server + ngrok tunnel.
8. The prompt_toolkit session opens at `▶ ` with history at `~/.friday/.friday_history`.

On every subsequent launch steps 3–5 are skipped and the REPL comes up immediately. If stdin is not a TTY (e.g. FRIDAY piped from a script) the wizard is skipped even on a fresh machine — the user is expected to have shipped a `user.json` or to run `friday init` interactively.

Recommended first-time path for a fresh user: `friday onboard` instead of `friday` — same profile wizard, plus system-dep check, LLM provider selection, and a final `friday doctor` verification. After that, any `friday` invocation drops straight into the REPL.
