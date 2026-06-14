"""when2meet adapter.

when2meet has no API at all. The page embeds the grid in JavaScript:
`TimeOfSlot[i]=<epoch_seconds>` lists every 15-minute cell. Participation works
by (1) POST /ProcessLogin.php with a name (and optional password) to obtain a
PersonID, then (2) POST /SaveTimeSlot.php once per cell to mark availability.

⚠️  Undocumented and brittle. The numeric event id is taken from the URL query
(`?28473822-AbCdEf` -> 28473822). If when2meet changes its endpoints, use the
Playwright adapter, which drives the grid visually instead.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests

from ..models import PollData, TimeSlot
from .base import PollAdapter, register

_SLOT_RE = re.compile(r"TimeOfSlot\[(\d+)\]\s*=\s*(\d+)\s*;")
_SLOT_SECONDS = 15 * 60  # when2meet cells are 15 minutes


@register
class When2MeetAdapter(PollAdapter):
    host_matches = ("when2meet.com",)
    service_name = "when2meet"

    def _event_id(self) -> str:
        query = urlparse(self.url).query  # e.g. "28473822-AbCdEf"
        if not query:
            # Some links use a path; fall back to digits in the URL.
            m = re.search(r"(\d{5,})", self.url)
            if not m:
                raise ValueError(f"Could not find when2meet event id in {self.url}")
            return m.group(1)
        return query.split("-")[0]

    def _base(self) -> str:
        p = urlparse(self.url)
        return f"{p.scheme}://{p.netloc}"

    def fetch(self) -> PollData:
        s = requests.Session()
        s.headers.update({"User-Agent": "zeeg-poll-agent/1.0"})
        html = s.get(self.url, timeout=self.timeout_s).text
        epochs = sorted({int(m.group(2)) for m in _SLOT_RE.finditer(html)})
        if not epochs:
            raise ValueError(
                "No TimeOfSlot entries found — when2meet markup changed; use the "
                "browser adapter."
            )
        title_m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        slots = [
            TimeSlot(
                start=datetime.fromtimestamp(e, tz=timezone.utc),
                end=datetime.fromtimestamp(e, tz=timezone.utc) + timedelta(seconds=_SLOT_SECONDS),
                external_id=str(e),
                payload={"slotEpoch": e},
            )
            for e in epochs
        ]
        return PollData(
            url=self.url,
            service=self.service_name,
            title=(title_m.group(1).strip() if title_m else "when2meet"),
            slots=slots,
            timezone_name="UTC",
            raw={"eventId": self._event_id(), "cookies": s.cookies.get_dict()},
        )

    def submit(self, free_slots, poll: PollData) -> str:
        base = self._base()
        event_id = poll.raw["eventId"]
        s = requests.Session()
        s.headers.update({"User-Agent": "zeeg-poll-agent/1.0"})
        login = s.post(
            f"{base}/ProcessLogin.php",
            data={"id": event_id, "name": self.identity.name, "password": ""},
            timeout=self.timeout_s,
        )
        person_id = login.text.strip()
        if not person_id.isdigit():
            raise RuntimeError(
                f"when2meet login did not return a numeric PersonID (got "
                f"{person_id[:80]!r}). The login flow may have changed."
            )
        for slot in free_slots:
            r = s.post(
                f"{base}/SaveTimeSlot.php",
                data={
                    "person": person_id,
                    "event": event_id,
                    "slot": slot.payload["slotEpoch"],
                    "value": 1,  # 1 = available
                },
                timeout=self.timeout_s,
            )
            if r.status_code >= 400:
                raise RuntimeError(
                    f"SaveTimeSlot failed for {slot} ({r.status_code})."
                )
        return (
            f"Marked {len(free_slots)} free 15-min cell(s) available as "
            f"{self.identity.name} (PersonID {person_id})."
        )
