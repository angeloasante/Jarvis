# Installing FRIDAY

The single source of truth for getting FRIDAY on your machine. Everything here is read out of the actual install scripts, CLI entry points, and wizards — not aspirational.

FRIDAY is a Python 3.12+ application distributed as the `friday-os` package. It installs a single `friday` CLI that handles the REPL, voice pipeline, gestures, background heartbeat, and every admin/setup command.

- Package: `friday-os` (see [pyproject.toml](../pyproject.toml))
- Entry point: `friday = friday.cli:run` → [cli.py](../friday/cli.py)
- Requires: Python **3.12+**, macOS (Linux partially supported)

---

## 1. Pick an install pathway

Five ways to install. All five end with a working `friday` command on your PATH.

| Pathway | Who it's for | Isolation | Auto-installs Python |
|---|---|---|---|
| **curl one-liner** | First-time users who want the shortest path | uv-managed venv | Yes (via uv) |
| **uv tool** | Users who already have uv and want control | uv-managed venv | Yes |
| **pipx** | Python devs who prefer pipx | pipx venv | No |
| **pip --user** | Restricted environments, CI, or containers | User site-packages | No |
| **git source** | Contributors, people hacking on FRIDAY itself | Local checkout | No |

### 1a. curl one-liner (recommended)

```sh
curl -fsSL https://raw.githubusercontent.com/angeloasante/Jarvis/main/install.sh | sh
```

What [install.sh](../install.sh) actually does:

1. Detects the system Python and warns if it's older than 3.12 (informational — uv ships its own).
2. Installs [`uv`](https://docs.astral.sh/uv/) from Astral if not already present.
3. Runs `uv tool install --force --python 3.12 "friday-os @ git+https://github.com/angeloasante/Jarvis"` — installs FRIDAY into an isolated uv-managed environment using Python 3.12.
4. Ensures the `uv tool` shim directory is on your PATH for the current shell session.
5. Kicks off `friday onboard` for first-run setup.

Environment overrides the installer respects:

```sh
# Install from PyPI instead of git (once a release is published)
FRIDAY_SOURCE=pypi curl -fsSL https://raw.githubusercontent.com/angeloasante/Jarvis/main/install.sh | sh

# Install from a fork
FRIDAY_REPO=https://github.com/yourfork/Jarvis curl -fsSL https://raw.githubusercontent.com/angeloasante/Jarvis/main/install.sh | sh
```

### 1b. uv tool (manual)

If you already trust uv and want to skip the bash script:

```sh
# Install uv if needed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install FRIDAY from git
uv tool install --python 3.12 "friday-os @ git+https://github.com/angeloasante/Jarvis"

# First-run setup
friday onboard
```

Use `--force --reinstall` to redo the install from scratch. This is the same command `friday update` runs under the hood.

### 1c. pipx

```sh
# Install pipx if needed (see https://pipx.pypa.io)
brew install pipx
pipx ensurepath

# Install FRIDAY
pipx install "friday-os @ git+https://github.com/angeloasante/Jarvis"

# First-run setup
friday onboard
```

Requires Python 3.12+ as the default Python pipx uses. Force a specific Python with `pipx install --python /path/to/python3.12 …`.

### 1d. pip --user

Minimal, no extra tools. Works in restricted environments (corporate, CI, servers):

```sh
python3.12 -m pip install --user "friday-os @ git+https://github.com/angeloasante/Jarvis"

# Make sure ~/.local/bin is on your PATH (or wherever `python -m site --user-base`/bin points)
export PATH="$HOME/.local/bin:$PATH"

friday onboard
```

### 1e. git source (for contributors)

Clone, sync dependencies with uv, run in place:

```sh
git clone https://github.com/angeloasante/Jarvis.git
cd Jarvis
uv sync
uv run friday onboard
```

Or `pip install -e .` in a venv if you prefer pip. `friday update` will run `git pull && uv sync` when it detects this install method.

---

## 2. First-run setup: `friday onboard`

`friday onboard` is the guided flow. It is idempotent — re-running it preserves existing config and only fills in what's missing. See [setup_wizard.py](../friday/core/setup_wizard.py) for the implementation.

It asks one question first: **QuickStart (1)** or **Advanced (2)**.

### QuickStart

Three steps, enough to start talking to FRIDAY:

1. **Profile** — runs the `friday init` wizard (see below) if `~/Friday/user.json` doesn't exist yet.
2. **System deps** — detects missing tools (Python 3.12+, uv, ollama, node, ngrok, brew) and offers to `brew install` the easy ones.
3. **LLM provider** — pick one: OpenRouter (widest model selection + free tier), Groq (fastest), or skip (Ollama-only).
4. **Health check** — runs `friday doctor` at the end.

### Advanced

Everything from QuickStart, plus optional prompts for:

- Tavily (web search for the research agent)
- Gmail + Calendar (Google OAuth sign-in)
- Twilio (SMS in/out, optionally with an ngrok domain for inbound webhooks)
- ElevenLabs (cloud TTS)
- X / Twitter (bearer token + optional posting credentials)
- Voice pipeline (ambient listen, TTS engine selection)
- Hand gesture control (MediaPipe model download, camera permissions note)

Every optional step can be skipped and run later with `friday setup <component>`.

---

## 3. Profile wizard: `friday init`

`friday init` is the interactive profile wizard. It writes `~/Friday/user.json` — the single source of truth for everything FRIDAY knows about you. Implementation in [onboarding.py](../friday/core/onboarding.py).

Run it directly any time:

```sh
friday init
```

It asks, in order:

| Field | Example | Used for |
|---|---|---|
| `name` | `Alex` | How FRIDAY addresses you |
| `bio` | `ML engineer, Lagos` | One-line context for prompts |
| `location` | `London, UK` | Geographic context |
| `country_code` | `GB` | ISO-3166-1 alpha-2. Accepts `UK`, `+44`, `44`, `United Kingdom` — auto-normalised. |
| `email` | `you@example.com` | SMS-to-self, email signatures |
| `phone` | `+447555...` | E.164, used by Twilio |
| `github` | `your-handle` | Optional — enables project sync |
| `website` | `https://...` | Optional |
| `tone` | `direct, dry humour` | Free-form voice note injected into prompts |

Press Enter on any field to skip it.

Advanced fields (`slang`, `contact_aliases`, `briefing_watchlist`, `cv`) aren't asked in the wizard — they live in the same JSON file and are hand-edited. Run `friday config edit` to open it in `$EDITOR`.

---

## 4. Health check: `friday doctor`

```sh
friday doctor
```

Prints the installed version, install method, total tool count, and a status row for every integration. Each row is `[component] [status] [detail]`. See [setup_wizard.py](../friday/core/setup_wizard.py).

| Row | What passing means | What failing means |
|---|---|---|
| Profile (user.json) | `~/Friday/user.json` exists with at least a name | Run `friday init` |
| CV attached | `cv.experience` populated in user.json | Hand-edit the `cv` key |
| LLM cloud provider | OpenRouter, Groq, or explicit CLOUD_API_KEY is set | Run `friday setup openrouter` or `friday setup groq` |
| Ollama (local) | Something replies on `http://localhost:11434` | Optional — only needed as offline fallback |
| Gmail + Calendar | `~/.friday/google_token.json` exists | Run `friday setup gmail` |
| Tavily | `TAVILY_API_KEY` in env or `~/.friday/.env` | Run `friday setup tavily` |
| Twilio | `TWILIO_ACCOUNT_SID` + `AUTH_TOKEN` + `PHONE_NUMBER` set | Run `friday setup twilio` |
| X / Twitter | `X_BEARER_TOKEN` set | Run `friday setup x` |
| Voice pipeline | `FRIDAY_VOICE=true` | Run `friday setup voice` |
| Hand gestures | Model downloaded AND `FRIDAY_GESTURES=true` | Run `friday setup gestures` |
| WhatsApp (Baileys) | `~/.friday/whatsapp/server.js` present | Optional — see [whatsapp-setup.md](./whatsapp-setup.md) |
| ngrok | binary on PATH | Optional — needed for Twilio inbound SMS |

A second table lists system dependencies (Python 3.12+, uv, ollama, node, ngrok, brew). Passing rows show the version; failing rows show the install hint.

---

## 5. Updating: `friday update`

```sh
friday update
```

Updates FRIDAY in place using whatever installer put it there. It sniffs `sys.executable` to detect the install method, then runs the correct reinstall command. See `_detect_install_method()` in [setup_wizard.py](../friday/core/setup_wizard.py).

| Detected method | Detection heuristic | Command it runs |
|---|---|---|
| `uv_tool` | Path contains `/uv/tools/` or `$UV_TOOL_DIR` | `uv tool install --force --reinstall 'friday-os @ git+https://github.com/angeloasante/Jarvis'` |
| `pipx` | Path contains `/pipx/venvs/` | `pipx reinstall friday-os` |
| `pip_user` | Path inside the user site-packages dir | `pip install --user --upgrade 'friday-os @ git+…'` |
| `dev` | `friday/` imports from a dir with `.git` and `pyproject.toml` | `git pull && uv sync` |
| `mac_app` | Path contains `.app/Contents/Resources/python` | Prints instructions to download latest `Friday.dmg` |
| `unknown` | None of the above | Prints manual options for each install method |

Important: `friday update` pulls the **full tree** — new agents, new tools, new skills, new dependencies. Not a version bump only. Restart FRIDAY after updating for the new code to take effect. `~/Friday/` and `~/.friday/` are never touched by updates.

For the Mac app (`Friday.app`), the update flow points to the releases page — download the new `.dmg`, drag to Applications, config survives.

---

## 6. Config subcommands: `friday config`

Four subcommands for managing `~/Friday/user.json`. See [onboarding.py](../friday/core/onboarding.py).

```sh
friday config          # print contents (same as `friday config show`)
friday config edit     # open in $EDITOR (falls back to $VISUAL, then nano)
friday config path     # print the absolute path — useful in scripts
friday config open     # reveal in Finder (macOS) or xdg-open (Linux)
```

Script example:

```sh
jq '.name' "$(friday config path)"
```

---

## 7. Where everything lives

FRIDAY splits user-facing config from runtime data on purpose.

| Path | Purpose | Hand-editable? |
|---|---|---|
| `~/Friday/user.json` | Your profile — identity, tone, slang, contacts, CV | Yes, encouraged |
| `~/Friday/README.md` | Auto-generated explainer (see [onboarding.py](../friday/core/onboarding.py)) | Regenerated on install |
| `~/.friday/.env` | API keys written by setup wizards (chmod 600) | Yes, if you're careful |
| `~/.friday/google_token.json` | Cached Gmail + Calendar OAuth token | No — regenerate via `friday setup gmail` |
| `~/.friday/models/` | MediaPipe gesture model, Kokoro TTS weights | No |
| `~/.friday/whatsapp/` | Baileys Node bridge + session data | No |
| `~/.friday/` (other) | SQLite memory DB, ChromaDB vectors, history, browser profile | No |

`~/Friday/` is a visible directory on purpose. `~/.friday/` is hidden on purpose. The single user.json file is chmod 600 (owner read/write only) because it holds email and phone.

Pre-0.4 config at `~/.friday/user.json` and `~/.friday/cv.json` is auto-migrated to `~/Friday/user.json` the first time `friday` runs.

---

## 8. Setup and test subcommands

Each optional integration has a dedicated wizard. Run them any time — they are safe to re-run.

```sh
friday setup deps          # brew-install missing system tools
friday setup openrouter    # OpenRouter key + model picker
friday setup groq          # Groq key
friday setup tavily        # Tavily web search key
friday setup gmail         # Google OAuth browser login
friday setup twilio        # Twilio SMS credentials + ngrok domain
friday setup x             # X/Twitter bearer + OAuth1 tokens
friday setup elevenlabs    # ElevenLabs TTS key + voice id
friday setup voice         # Enable ambient listen + TTS engine pick
friday setup gestures      # Download MediaPipe model + enable
```

And connectivity tests to verify each service works end-to-end:

```sh
friday test llm            # Sends "say hi in 3 words" to your cloud provider
friday test gmail          # Fetches 1 unread email
friday test twilio         # Sends an SMS to CONTACT_PHONE
friday test tv             # Pings LG TV on LAN
```

---

## 9. Uninstalling

| Install method | Uninstall command |
|---|---|
| curl one-liner / uv tool | `uv tool uninstall friday-os` |
| pipx | `pipx uninstall friday-os` |
| pip --user | `python3.12 -m pip uninstall friday-os` |
| git source | `rm -rf` the checkout |
| Mac app | Drag `Friday.app` to the Trash |

To wipe personal data as well:

```sh
rm -rf ~/Friday      # profile, user.json
rm -rf ~/.friday     # runtime, tokens, memory DB, .env
```

FRIDAY recreates defaults on the next run.

---

## 10. Launching

Once `friday doctor` is green on the rows you care about:

```sh
friday                 # text REPL
friday --voice         # text + ambient voice (say "Friday")
```

Runtime toggles (inside the REPL): `/voice`, `/gestures`, `/listening-on`, `/listening-off`, `/help` for the full list. See [cli.py](../friday/cli.py).
