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
#   ./run.sh            # first run sets up, then starts the server (foreground)
#   ./run.sh setup      # (re)install dependencies, e.g. after a git pull
#
# When launched by PollFiller.app (POLLFILLER_APP_MODE=1) it instead starts the
# server detached in the background, opens the browser, and returns — so the
# launching Terminal window can close without stopping the server.
#
set -euo pipefail

# Resolve this script's folder regardless of where it's launched from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Local venv, kept off Google Drive. Override with POLLFILLER_VENV if you like.
VENV="${POLLFILLER_VENV:-$HOME/.venvs/pollfiller}"

URL="http://127.0.0.1:8765/"
STATE_DIR="$HOME/.pollfiller"
PIDFILE="$STATE_DIR/server.pid"
LOGFILE="$STATE_DIR/server.log"

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
cd "$SCRIPT_DIR"

# Open a URL in a NEW browser window (rather than reusing an existing tab).
# Honors $POLLFILLER_BROWSER if set; otherwise prefers a Chromium-family browser,
# then Safari, then the system default.
open_url_new_window() {
  local url="$1"
  command -v open >/dev/null 2>&1 || return 0
  if [ -n "${POLLFILLER_BROWSER:-}" ]; then
    open -na "$POLLFILLER_BROWSER" --args --new-window "$url" 2>/dev/null && return 0
  fi
  local b
  for b in "Google Chrome" "Brave Browser" "Microsoft Edge" "Arc" "Chromium"; do
    if open -Ra "$b" >/dev/null 2>&1; then
      open -na "$b" --args --new-window "$url" 2>/dev/null && return 0
    fi
  done
  if open -Ra "Safari" >/dev/null 2>&1; then
    osascript >/dev/null 2>&1 <<OSA && return 0
tell application "Safari"
  activate
  make new document with properties {URL:"$url"}
end tell
OSA
  fi
  open "$url"
}

# Open the browser once the server responds (set POLLFILLER_NO_BROWSER=1 to skip).
open_browser_when_ready() {
  command -v open >/dev/null 2>&1 || return 0
  [ "${POLLFILLER_NO_BROWSER:-}" = "1" ] && return 0
  (
    for _ in $(seq 1 90); do
      if curl -fsS -o /dev/null "$URL" 2>/dev/null; then
        open_url_new_window "$URL"
        break
      fi
      sleep 1
    done
  ) &
}

# Close the Terminal window this script is running in (used in app mode so the
# window disappears once the detached server is up). No-op outside a TTY.
close_own_terminal_window() {
  [ -t 1 ] || return 0
  local mytty
  mytty="$(tty 2>/dev/null || true)"
  [ -n "$mytty" ] || return 0
  (
    sleep 1
    osascript >/dev/null 2>&1 <<OSA || true
tell application "Terminal"
  repeat with w in windows
    repeat with t in tabs of w
      if tty of t is "$mytty" then close w
    end repeat
  end repeat
end tell
OSA
  ) &
}

if [ "${POLLFILLER_APP_MODE:-}" = "1" ]; then
  # Background mode: detach the server so the Terminal can close, then exit.
  # POLLFILLER_PIDFILE lets the server remove its own pidfile when it
  # self-shuts-down (e.g. after the browser window is closed).
  mkdir -p "$STATE_DIR"
  POLLFILLER_PIDFILE="$PIDFILE" nohup "$VENV/bin/python" -m zeeg_poll_agent.webapp >"$LOGFILE" 2>&1 &
  srv_pid=$!
  echo "$srv_pid" >"$PIDFILE"
  disown 2>/dev/null || true
  up=0
  for _ in $(seq 1 90); do
    if curl -fsS -o /dev/null "$URL" 2>/dev/null; then up=1; break; fi
    kill -0 "$srv_pid" 2>/dev/null || break  # process died (e.g. port already in use)
    sleep 1
  done
  if [ "$up" != "1" ]; then
    echo "ERROR: server failed to start (see $LOGFILE). $URL may already be in use." >&2
    kill "$srv_pid" 2>/dev/null || true
    rm -f "$PIDFILE"
    exit 1
  fi
  open_browser_when_ready
  echo "PollFiller is running in the background. This window will close."
  close_own_terminal_window
  exit 0
fi

# Foreground mode: visible logs, Ctrl-C to stop.
open_browser_when_ready
echo "Starting Zeeg poll-filler at $URL  (Ctrl-C to stop)"
exec "$VENV/bin/python" -m zeeg_poll_agent.webapp
