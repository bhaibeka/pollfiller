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
from pathlib import Path

from flask import Flask, jsonify, request, send_file

from .agent import PollAgent
from .config import Config
from .polls import supported_services

_HERE = Path(__file__).resolve().parent
_INDEX = _HERE / "web" / "index.html"


def create_app() -> Flask:
    app = Flask(__name__)
    config = Config.from_env()
    agent = PollAgent(config)

    @app.get("/")
    def index():
        return send_file(_INDEX)

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


def main() -> None:
    host = os.environ.get("HOST", "127.0.0.1")
    # Default 8765 avoids macOS's AirPlay Receiver, which listens on port 5000.
    port = int(os.environ.get("PORT", "8765"))
    create_app().run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
