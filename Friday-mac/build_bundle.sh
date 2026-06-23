#!/usr/bin/env bash
#
# build_bundle.sh — Bundle Python + FridayCore into Friday.app
#
# Uses python-build-standalone (the relocatable Python used by uv, Rye,
# Positron, etc.) instead of PyInstaller. Handles native dependencies
# like chromadb, pydantic-core, numpy cleanly.
#
# After running: Friday.app/Contents/Resources/python/ contains a fully
# self-contained Python 3.12 with FridayCore installed. Users don't need
# Python, uv, or the repo — just the .app.
#
# Usage:
#   ./build_bundle.sh            # build + install into the Debug .app
#   ./build_bundle.sh release    # build + install into the Release .app
#
set -euo pipefail

MODE="${1:-debug}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILD_DIR="$SCRIPT_DIR/build/python_bundle"

# python-build-standalone — 3.12, arm64 macOS, install_only variant (no headers)
PYTHON_VERSION="3.12.7"
PBS_RELEASE="20241016"
PBS_FILE="cpython-${PYTHON_VERSION}+${PBS_RELEASE}-aarch64-apple-darwin-install_only.tar.gz"
PBS_URL="https://github.com/indygreg/python-build-standalone/releases/download/${PBS_RELEASE}/${PBS_FILE}"

# Where the Swift build outputs the .app (varies by mode/user/DerivedData)
XCODE_PROJECT="$SCRIPT_DIR/Friday/Friday.xcodeproj"
case "$MODE" in
    debug)
        DERIVED="$(xcodebuild -project "$XCODE_PROJECT" -scheme Friday -configuration Debug -showBuildSettings 2>/dev/null \
            | awk -F ' = ' '/^ *TARGET_BUILD_DIR = / {print $2}' | head -1 | sed 's/^[[:space:]]*//')"
        ;;
    release)
        DERIVED="$(xcodebuild -project "$XCODE_PROJECT" -scheme Friday -configuration Release -showBuildSettings 2>/dev/null \
            | awk -F ' = ' '/^ *TARGET_BUILD_DIR = / {print $2}' | head -1 | sed 's/^[[:space:]]*//')"
        ;;
    *)
        echo "Unknown mode: $MODE (use debug|release)" >&2; exit 1;;
esac

if [ -z "$DERIVED" ]; then
    echo "Couldn't find Xcode TARGET_BUILD_DIR. Build the app first in Xcode." >&2
    exit 1
fi

APP_PATH="$DERIVED/Friday.app"
if [ ! -d "$APP_PATH" ]; then
    echo "No app at $APP_PATH. Build in Xcode first." >&2
    exit 1
fi

# ─────────────────────────────────────────────────────────────
# Step 1. Download relocatable Python (cache in build/)
# ─────────────────────────────────────────────────────────────

mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

if [ ! -d "python" ]; then
    echo "→ Downloading python-build-standalone ${PYTHON_VERSION} …"
    if [ ! -f "$PBS_FILE" ]; then
        curl -L -o "$PBS_FILE" "$PBS_URL"
    fi
    echo "→ Extracting …"
    tar -xzf "$PBS_FILE"  # extracts to ./python/
fi

PY_BIN="$BUILD_DIR/python/bin/python3"
PIP_BIN="$BUILD_DIR/python/bin/pip3"

if [ ! -x "$PY_BIN" ]; then
    echo "Python binary missing at $PY_BIN" >&2
    exit 1
fi

echo "→ Python: $($PY_BIN --version)"

# ─────────────────────────────────────────────────────────────
# Step 2. Install FridayCore + core dependencies
#
# Heavy deps excluded from v1 bundle (user can install separately):
#   mediapipe, opencv-python — gestures (Swift CoreML port coming)
#   playwright, selenium    — browser automation (Safari AppleScript works)
#   mlx-whisper, kokoro-onnx, sounddevice, onnxruntime — voice
#
# What IS bundled: LLM routing, agents, email/calendar, iMessage/WhatsApp,
# SMS, TV control, X/Twitter, research, memory, docx generation.
# ─────────────────────────────────────────────────────────────

echo "→ Upgrading pip + installing core deps …"
"$PY_BIN" -m pip install --upgrade pip setuptools wheel --quiet

"$PIP_BIN" install --quiet \
    "apscheduler>=3.11.2" \
    "chromadb>=1.5.5" \
    "google-api-python-client>=2.193.0" \
    "google-auth-httplib2>=0.3.0" \
    "google-auth-oauthlib>=1.3.0" \
    "httpx>=0.28.1" \
    "ollama>=0.6.1" \
    "prompt-toolkit>=3.0.52" \
    "python-dotenv>=1.2.2" \
    "pywebostv>=0.8.9" \
    "rich>=14.3.3" \
    "tavily-python>=0.7.23" \
    "wakeonlan>=3.1.0" \
    "weasyprint>=63.0" \
    "jinja2>=3.1.6" \
    "pypdf>=6.9.1" \
    "pdfplumber>=0.11.9" \
    "tweepy>=4.16.0" \
    "numpy>=1.26.0" \
    "openai>=2.29.0" \
    "python-docx>=1.2.0" \
    "twilio>=9.10.4"

echo "→ Installing FridayCore from repo (non-editable — copies the source) …"
"$PIP_BIN" install --quiet "$REPO_ROOT" --no-deps

# ─────────────────────────────────────────────────────────────
# Step 3. Strip unnecessary bytes (tests, caches, docs)
# ─────────────────────────────────────────────────────────────

echo "→ Pruning unnecessary files …"
find "$BUILD_DIR/python" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "$BUILD_DIR/python" -name "*.pyc" -delete 2>/dev/null || true
find "$BUILD_DIR/python" -name "tests" -type d -exec rm -rf {} + 2>/dev/null || true
find "$BUILD_DIR/python" -name "test_*.py" -delete 2>/dev/null || true

# ─────────────────────────────────────────────────────────────
# Step 4. Copy the fully-relocatable Python into Friday.app
# ─────────────────────────────────────────────────────────────

RESOURCES="$APP_PATH/Contents/Resources"
TARGET="$RESOURCES/python"

echo "→ Copying bundled Python into $TARGET …"
rm -rf "$TARGET"
mkdir -p "$RESOURCES"
cp -R "$BUILD_DIR/python" "$TARGET"

# Ship a "defaults" env file with the FRIDAY-team-managed keys (Tavily, etc.)
# so users don't have to bring their own for built-in capabilities. This file
# is plain-text inside the .app — only put SHARED keys you're OK exposing.
echo "→ Writing bundled friday_defaults.env (shared service keys) …"
DEFAULTS_ENV="$RESOURCES/friday_defaults.env"
{
    echo "# Auto-generated at build time. Shared FRIDAY service keys."
    echo "# Per-user keys (Gmail, OpenRouter, Twilio) come from the macOS app's UI."
    if [ -f "$REPO_ROOT/.env" ]; then
        # Pull only the keys we explicitly want to ship.
        for k in TAVILY_API_KEY; do
            line=$(grep "^${k}=" "$REPO_ROOT/.env" || true)
            if [ -n "$line" ]; then
                echo "$line"
            fi
        done
    fi
} > "$DEFAULTS_ENV"

# Sanity check — run the BUNDLED binary (not the build dir) and confirm it
# can import friday from its own site-packages, not the repo.
echo "→ Sanity check — running bundled Python from app location:"
"$TARGET/bin/python3" -c "
import friday, sys
assert '/Resources/python/' in friday.__file__, f'WRONG LOCATION: {friday.__file__}'
print(f'  friday: {friday.__file__}')
print(f'  sys.executable: {sys.executable}')
"
"$TARGET/bin/python3" -c "from friday.core.oneshot_runner import run_stream; print('  oneshot_runner importable')"

# ─────────────────────────────────────────────────────────────
# Step 5. Report sizes
# ─────────────────────────────────────────────────────────────

BUNDLE_SIZE=$(du -sh "$TARGET" | cut -f1)
APP_SIZE=$(du -sh "$APP_PATH" | cut -f1)

echo ""
echo "✅ Done. Bundled Python is $BUNDLE_SIZE. Total .app is $APP_SIZE."
echo "   $APP_PATH"
echo ""
echo "Next: rebuild the Swift target or re-run to pick up the bundle."
