"""Doodle adapter.

Doodle has no *public, documented* API, but the web app talks to a JSON
endpoint under `https://doodle.com/api` / `https://api.doodle.com`. This adapter
targets that internal API, which is the most reliable way to read options and
cast a vote without driving a full browser.

⚠️  Because the endpoint is undocumented it can change without notice. The code
is defensive and raises clear errors if the response shape differs from what we
expect, so you can adjust `_parse_options` / `submit` against a live poll. If
the JSON API stops working, switch this poll to the Playwright-based
`GenericBrowserAdapter` (see polls/generic_playwright.py).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import requests

from ..models import PollData, TimeSlot
from .base import PollAdapter, register

_POLL_ID_RE = re.compile(r"/(?:poll|meeting/participate/id)/([A-Za-z0-9]+)")


def _epoch_or_iso(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        # Doodle uses milliseconds since epoch for time options.
        return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise ValueError(f"unrecognised time value: {value!r}")


@register
class DoodleAdapter(PollAdapter):
    host_matches = ("doodle.com",)
    service_name = "doodle"
    api_base = "https://doodle.com/api/v2.0"

    def _poll_id(self) -> str:
        m = _POLL_ID_RE.search(self.url)
        if not m:
            # Last path segment fallback.
            seg = self.url.rstrip("/").split("/")[-1].split("?")[0]
            if seg:
                return seg
            raise ValueError(f"Could not extract a Doodle poll id from {self.url}")
        return m.group(1)

    def _session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
        return s

    def fetch(self) -> PollData:
        poll_id = self._poll_id()
        s = self._session()
        resp = s.get(f"{self.api_base}/polls/{poll_id}", timeout=self.timeout_s)
        resp.raise_for_status()
        data = resp.json()
        slots = self._parse_options(data)
        return PollData(
            url=self.url,
            service=self.service_name,
            title=data.get("title", "Doodle poll"),
            slots=slots,
            timezone_name=data.get("timeZone", "UTC"),
            raw={"pollId": poll_id, "response": data},
        )

    def _parse_options(self, data: dict) -> list[TimeSlot]:
        options = data.get("options") or []
        slots: list[TimeSlot] = []
        for opt in options:
            if opt.get("allday"):
                continue  # date-only polls are out of scope for calendar conflict checks
            try:
                start = _epoch_or_iso(opt.get("start"))
                end = _epoch_or_iso(opt.get("end") or opt.get("start"))
            except ValueError:
                continue
            if end <= start:
                continue
            slots.append(
                TimeSlot(
                    start=start,
                    end=end,
                    external_id=str(opt.get("id")),
                    payload={"optionId": opt.get("id")},
                )
            )
        if not slots:
            raise ValueError(
                "No time-based options parsed from the Doodle poll. The poll may "
                "be date-only, or the API shape changed (inspect raw response)."
            )
        return slots

    def submit(self, free_slots, poll: PollData) -> str:
        poll_id = poll.raw["pollId"]
        option_ids = {o["id"] for o in (poll.raw["response"].get("options") or [])}
        free_ids = {s.payload["optionId"] for s in free_slots}
        # Doodle expects a preference per option; "yes" for free, "no" otherwise.
        preferences = [
            {"optionId": oid, "participantAvailability": "YES" if oid in free_ids else "NO"}
            for oid in option_ids
        ]
        body = {
            "name": self.identity.name,
            "email": self.identity.email,
            "preferences": preferences,
        }
        s = self._session()
        resp = s.post(
            f"{self.api_base}/polls/{poll_id}/participants",
            json=body,
            timeout=self.timeout_s,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Doodle submission failed ({resp.status_code}): {resp.text[:300]}. "
                "The participant payload shape may have changed; verify against a "
                "live poll or fall back to the browser adapter."
            )
        return f"Voted YES on {len(free_ids)} option(s) as {self.identity.name}."
