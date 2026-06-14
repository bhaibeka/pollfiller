"""Local web interface.

Paste a poll URL, and the app lists every proposed slot that does NOT conflict
with any of your connected calendars (via Zeeg's availability endpoint), so you
can fill the poll yourself in seconds.

Run with:

    # token comes from the `zeeg_api` file, or override with the env var:
    export ZEEG_API_TOKEN=...        # admin:full token (optional override)
    python -m zeeg_poll_agent.webapp

Then open http://127.0.0.1:5000 .

Security: this server wields a full-admin Zeeg token, so it binds to localhost
only by default. Do not expose it to the network.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_file

from .agent import PollAgent
from .config import Config
from .polls import supported_services

_HERE = Path(__file__).resolve().parent
_INDEX = _HERE / "web" / "index.html"

# How long after the last browser ping the server shuts itself down.
_CLOSE_GRACE_S = 4.0       # after an explicit "closing" beacon (cancelled by any ping)
_IDLE_BACKSTOP_S = 150.0   # if pings stop without a beacon (covers crashes / throttling)
_STARTUP_GRACE_S = 120.0   # allow time for the browser to open and ping first


def _remove_pidfile() -> None:
    path = os.environ.get("POLLFILLER_PIDFILE")
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


def _shutdown_soon(delay: float = 0.3) -> None:
    """Exit the process shortly, after the current response is flushed."""
    def _die() -> None:
        time.sleep(delay)
        _remove_pidfile()
        os._exit(0)

    threading.Thread(target=_die, daemon=True).start()


def create_app() -> Flask:
    app = Flask(__name__)
    config = Config.from_env()
    agent = PollAgent(config)

    # Liveness state shared between the heartbeat routes and the watchdog.
    hb = {"last": time.monotonic(), "seen": False, "deadline": None}
    app.config["_heartbeat"] = hb

    @app.get("/")
    def index():
        return send_file(_INDEX)

    @app.post("/api/heartbeat")
    def heartbeat():
        # A live page; cancel any pending shutdown (reload or another open tab).
        hb["last"] = time.monotonic()
        hb["seen"] = True
        hb["deadline"] = None
        return ("", 204)

    @app.post("/api/closing")
    def closing():
        # The page is going away. Arm a short shutdown that any other tab's next
        # heartbeat (or a reload) will cancel, so we only stop when the last
        # window is truly gone.
        hb["deadline"] = time.monotonic() + _CLOSE_GRACE_S
        return ("", 204)

    @app.get("/api/health")
    def health():
        return jsonify(status="ok", services=supported_services(),
                       voter=config.identity.name)

    @app.get("/api/whoami")
    def whoami():
        try:
            return jsonify(agent.verify_credentials())
        except Exception as e:  # noqa: BLE001
            return jsonify(error=str(e)), 502

    @app.get("/api/pages")
    def pages():
        try:
            raw = agent.list_scheduling_pages()
        except Exception as e:  # noqa: BLE001
            return jsonify(error=str(e)), 502
        default = agent.default_page(raw)
        out = []
        for p in raw:
            out.append({
                "label": f"{p.get('title')} ({p.get('duration')} min)",
                "ownerSlug": agent.zeeg.owner_slug_for(p),
                "eventTypeSlug": p.get("slug"),
                "duration": p.get("duration"),
                "isActive": p.get("isActive"),
                "isDefault": default is not None and p.get("slug") == default.get("slug"),
            })
        return jsonify(pages=out)

    @app.post("/api/diagnose")
    def diagnose():
        body = request.get_json(force=True, silent=True) or {}
        url = (body.get("url") or "").strip()
        if not url:
            return jsonify(error="A poll URL is required."), 400
        return jsonify(agent.diagnose(url))

    @app.post("/api/analyze")
    def analyze():
        body = request.get_json(force=True, silent=True) or {}
        url = (body.get("url") or "").strip()
        if not url:
            return jsonify(error="A poll URL is required."), 400
        tz = (body.get("timezone") or "America/Toronto").strip()
        owner = (body.get("ownerSlug") or "").strip() or None
        slug = (body.get("eventTypeSlug") or "").strip() or None
        try:
            result = agent.find_free_slots(url, time_zone=tz, owner_slug=owner, event_type_slug=slug)
        except Exception as e:  # noqa: BLE001
            return jsonify(error=str(e)), 502

        def ser(slots):
            return [{"startUtc": s.start.isoformat(), "endUtc": s.end.isoformat()} for s in slots]

        return jsonify(
            poll={"title": result.poll.title, "service": result.poll.service, "url": url},
            timezone=tz,
            detail=result.submission_detail,
            free=ser(result.free_slots),
            conflicting=ser(result.conflicting_slots),
        )

    return app


def _start_watchdog(hb: dict) -> None:
    """Shut the server down once the browser stops pinging (window closed)."""
    start = time.monotonic()

    def _loop() -> None:
        while True:
            time.sleep(1.0)
            now = time.monotonic()
            deadline = hb["deadline"]
            if deadline is not None and now >= deadline:
                _shutdown_soon(0.0)
                return
            if not hb["seen"]:
                if now - start > _STARTUP_GRACE_S:  # browser never connected
                    _shutdown_soon(0.0)
                    return
                continue
            if now - hb["last"] > _IDLE_BACKSTOP_S:  # pings stopped without a beacon
                _shutdown_soon(0.0)
                return

    threading.Thread(target=_loop, daemon=True).start()


def main() -> None:
    host = os.environ.get("HOST", "127.0.0.1")
    # Default 8765 avoids macOS's AirPlay Receiver, which listens on port 5000.
    port = int(os.environ.get("PORT", "8765"))
    app = create_app()
    # Auto-shutdown when the browser window closes (disable with POLLFILLER_NO_AUTOSHUTDOWN=1).
    if os.environ.get("POLLFILLER_NO_AUTOSHUTDOWN") != "1":
        _start_watchdog(app.config["_heartbeat"])
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
