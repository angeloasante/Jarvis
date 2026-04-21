#!/usr/bin/env sh
# FRIDAY installer.
#
#   curl -fsSL https://raw.githubusercontent.com/angeloasante/Jarvis/main/install.sh | sh
#
# What this does (and doesn't):
#   - installs `uv` (Astral's Python tool manager) if you don't have it
#   - uses uv to install `friday-os` into an isolated environment
#   - puts the `friday` command on your PATH
#   - kicks off `friday onboard` for first-run setup
#   - does NOT touch your system Python or anything else
#
# Read it first. This is the internet. `curl | sh` only runs what you trust.
#
set -eu

FRIDAY_REPO="${FRIDAY_REPO:-https://github.com/angeloasante/Jarvis}"
# Set FRIDAY_SOURCE=pypi to install the published wheel once it's up on PyPI.
# Defaults to installing straight from the git main branch so the latest code
# is always available even before a release.
FRIDAY_SOURCE="${FRIDAY_SOURCE:-git}"

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
dim()  { printf "\033[2m%s\033[0m\n" "$1"; }
ok()   { printf "\033[32m  ✓\033[0m %s\n" "$1"; }
err()  { printf "\033[31m  ✗\033[0m %s\n" "$1" >&2; }

echo ""
bold "FRIDAY · installer"
echo ""

# ── 1. Python check ──────────────────────────────────────────────────────────
#
# We don't require a system Python — uv bootstraps its own. But if one's
# already there and it's too old we warn, so users aren't surprised when
# friday refuses to boot under Python 3.11.
if command -v python3 >/dev/null 2>&1; then
    PY_VER="$(python3 -c 'import sys; print(".".join(map(str,sys.version_info[:2])))' 2>/dev/null || echo "?")"
    dim "  system python: ${PY_VER}"
fi

# ── 2. uv ────────────────────────────────────────────────────────────────────
if ! command -v uv >/dev/null 2>&1; then
    bold "Installing uv (Python tool manager, ~20MB)…"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Astral's installer adds ~/.local/bin to PATH in your shell RC — but the
    # current shell doesn't know yet, so add it for this session.
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v uv >/dev/null 2>&1; then
        err "uv install failed. Install manually: https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi
    ok "uv installed"
else
    ok "uv already installed ($(uv --version | awk '{print $2}'))"
fi

# ── 3. friday-os ─────────────────────────────────────────────────────────────
bold "Installing friday-os…"

case "$FRIDAY_SOURCE" in
    pypi)
        uv tool install --force --python 3.12 friday-os
        ;;
    git|*)
        uv tool install --force --python 3.12 "friday-os @ git+${FRIDAY_REPO}"
        ;;
esac

# Make sure the tool shim dir is on PATH for this session (uv warns but
# doesn't abort when the dir isn't exported yet).
UV_BIN="$(uv tool dir --bin 2>/dev/null || echo "")"
if [ -n "$UV_BIN" ] && [ -d "$UV_BIN" ]; then
    case ":$PATH:" in
        *":$UV_BIN:"*) : ;;
        *) export PATH="$UV_BIN:$PATH" ;;
    esac
fi

if ! command -v friday >/dev/null 2>&1; then
    err "Install looked fine but 'friday' is not on PATH."
    dim "Try: export PATH=\"$UV_BIN:\$PATH\" (add this to ~/.zshrc or ~/.bashrc)"
    exit 1
fi

ok "friday installed at $(command -v friday)"
echo ""

# ── 4. Onboarding ────────────────────────────────────────────────────────────
bold "Running first-run setup…"
echo ""
friday onboard

echo ""
bold "Done."
dim "  Launch anytime with:  friday"
dim "  Check status:          friday doctor"
dim "  Edit your profile:     friday config edit"
echo ""
