#!/usr/bin/env bash
#
# Launch the Zeeg poll-filler web interface from any machine.
#
# The code and your zeeg_api token live in this folder (synced via Google
# Drive). The Python environment and the Chromium browser do NOT — they are
# built locally, OUTSIDE the Drive folder, so Drive never tries to sync
# platform-specific binaries between machines.
#
# Usage:
#   ./run.sh            # first run sets up, then starts the server
#   ./run.sh setup      # (re)install dependencies, e.g. after a git pull
#
set -euo pipefail

# Resolve this script's folder regardless of where it's launched from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Local venv, kept off Google Drive. Override with POLLFILLER_VENV if you like.
VENV="${POLLFILLER_VENV:-$HOME/.venvs/pollfiller}"

PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  echo "ERROR: python3 not found on PATH. Install Python 3.9+ first." >&2
  exit 1
fi

setup() {
  echo "Setting up local environment at: $VENV"
  "$PY" -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r "$SCRIPT_DIR/requirements.txt"
  echo "Installing Chromium for Playwright (one-time, ~100 MB)..."
  "$VENV/bin/python" -m playwright install chromium
  echo "Setup complete."
}

# Explicit setup request, or first-time auto-setup.
if [ "${1:-}" = "setup" ] || [ ! -x "$VENV/bin/python" ]; then
  setup
fi

# Don't scatter __pycache__/*.pyc into the Drive folder.
export PYTHONDONTWRITEBYTECODE=1

# On macOS, open the browser once the server is up (set POLLFILLER_NO_BROWSER=1 to skip).
if command -v open >/dev/null 2>&1 && [ "${POLLFILLER_NO_BROWSER:-}" != "1" ]; then
  (
    for _ in $(seq 1 90); do
      if curl -fsS -o /dev/null "http://127.0.0.1:5000/" 2>/dev/null; then
        open "http://127.0.0.1:5000/"
        break
      fi
      sleep 1
    done
  ) &
fi

cd "$SCRIPT_DIR"
echo "Starting Zeeg poll-filler at http://127.0.0.1:5000  (Ctrl-C to stop)"
exec "$VENV/bin/python" -m zeeg_poll_agent.webapp
