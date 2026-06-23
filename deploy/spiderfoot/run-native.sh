#!/usr/bin/env bash
# Run SpiderFoot natively — NO Docker, NO VPS. Pure Python, on your Mac.
#
#   bash deploy/spiderfoot/run-native.sh
#
# First run clones SpiderFoot + sets up its own venv (~2 min). Subsequent runs
# just start the server. It listens on http://127.0.0.1:5001 (localhost only).
# Then point FRIDAY at it:   echo 'SPIDERFOOT_URL=http://127.0.0.1:5001' >> ~/Friday/.env
#
# Stop it with Ctrl-C. Leave this terminal open while you want deep scans.
set -euo pipefail

SF_DIR="${SPIDERFOOT_DIR:-$HOME/Friday/spiderfoot}"
PORT="${SPIDERFOOT_PORT:-5001}"

if [ ! -d "$SF_DIR/.git" ]; then
  echo ":: Cloning SpiderFoot into $SF_DIR ..."
  git clone --depth 1 https://github.com/smicallef/spiderfoot.git "$SF_DIR"
fi

cd "$SF_DIR"

if [ ! -d ".venv" ]; then
  echo ":: Creating venv + installing requirements (one-time, ~2 min) ..."
  python3 -m venv .venv
  ./.venv/bin/python -m pip install --quiet --upgrade pip
  ./.venv/bin/pip install --quiet -r requirements.txt
fi

echo ":: SpiderFoot starting on http://127.0.0.1:${PORT}  (Ctrl-C to stop)"
echo ":: Add API keys (Shodan, VirusTotal, DeHashed...) in the web UI → Settings."
exec ./.venv/bin/python ./sf.py -l "127.0.0.1:${PORT}"
