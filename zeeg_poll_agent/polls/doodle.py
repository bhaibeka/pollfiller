"""Doodle adapter (new "group poll" product).

Doodle's current group polls are a client-rendered SPA backed by a private API
at ``https://api.doodle.com/scheduling/scheduling-attempts/{id}`` that requires
an anonymous OAuth bearer token the web app mints via Keycloak. Rather than
re-implement that auth dance, this adapter drives a headless browser
(Playwright) to load the participate page — letting the app authenticate — then
reads the JSON the page itself fetched:

    GET  /scheduling/scheduling-attempts/{id}           -> poll metadata
    GET  /scheduling/scheduling-attempts/{id}/options   -> the time options

⚠️  This is an undocumented API and can change without notice. The parsing is
defensive and raises clear errors if the response shape differs. Requires
``pip install playwright && playwright install chromium``.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from ..models import PollData, TimeSlot
from .base import PollAdapter, register

# Matches the id in /poll/{id}, /group-poll/participate/{id}, /meeting/participate/id/{id}.
_POLL_ID_RE = re.compile(r"/(?:poll|participate(?:/id)?)/([A-Za-z0-9]+)")

_API_BASE = "https://api.doodle.com/scheduling/scheduling-attempts"
# Far in the past so we capture every proposed option, not just future ones.
_FROM_DATE = "2000-01-01T00:00:00.000Z"


def _parse_iso(value: Any) -> datetime:
    """Parse Doodle's ISO-8601 timestamps (e.g. '2026-07-27T11:00:00Z')."""
    if not isinstance(value, str):
        raise ValueError(f"unrecognised time value: {value!r}")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@register
class DoodleAdapter(PollAdapter):
    host_matches = ("doodle.com",)
    service_name = "doodle"
    api_base = _API_BASE

    def _poll_id(self) -> str:
        m = _POLL_ID_RE.search(self.url)
        if m:
            return m.group(1)
        seg = self.url.rstrip("/").split("/")[-1].split("?")[0]
        if seg:
            return seg
        raise ValueError(f"Could not extract a Doodle poll id from {self.url}")

    # -- parsing (pure; unit-tested offline) -------------------------------
    def _parse_options(self, options: list[dict]) -> list[TimeSlot]:
        slots: list[TimeSlot] = []
        for opt in options:
            if opt.get("allDay"):
                continue  # date-only polls are out of scope for calendar conflicts
            try:
                start = _parse_iso(opt.get("startAt"))
                end = _parse_iso(opt.get("endAt") or opt.get("startAt"))
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

    # -- browser-driven fetch ---------------------------------------------
    def fetch(self) -> PollData:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "The Doodle adapter needs Playwright to read the group poll: "
                "`pip install playwright && playwright install chromium`."
            ) from e

        poll_id = self._poll_id()
        meta_url = f"{self.api_base}/{poll_id}"
        captured: dict[str, Any] = {}

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.set_default_timeout(self.timeout_s * 1000)

                def on_response(resp):  # capture metadata + the auth token
                    if resp.url.split("?")[0].rstrip("/") == meta_url and resp.status == 200:
                        try:
                            captured["meta"] = resp.json()
                            captured["token"] = resp.request.headers.get("authorization")
                        except Exception:  # noqa: BLE001
                            pass

                page.on("response", on_response)
                page.goto(self.url, wait_until="domcontentloaded")

                # Wait for the app to authenticate and fetch the poll metadata.
                deadline = int(self.timeout_s * 1000)
                waited = 0
                while "token" not in captured and waited < deadline:
                    page.wait_for_timeout(300)
                    waited += 300
                if not captured.get("token"):
                    raise RuntimeError(
                        f"Timed out reading Doodle poll {poll_id}: the page never "
                        "authenticated. The poll may be private, expired, or the "
                        "site changed."
                    )

                options = self._fetch_all_options(page, poll_id, captured["token"])
            finally:
                browser.close()

        meta = captured.get("meta") or {}
        slots = self._parse_options(options)
        tz_raw = meta.get("timezone") or "UTC"
        tz_name = tz_raw.split(";")[0] or "UTC"  # "Europe/Amsterdam;...;GMT+2" -> "Europe/Amsterdam"
        return PollData(
            url=self.url,
            service=self.service_name,
            title=meta.get("title", "Doodle poll"),
            slots=slots,
            timezone_name=tz_name,
            raw={"pollId": poll_id, "meta": meta, "options": options},
        )

    def _fetch_all_options(self, page, poll_id: str, token: str) -> list[dict]:
        """Page through the options endpoint from within the authenticated page."""
        js = """
        async ([base, id, token, fromDate]) => {
          const out = [];
          let pageNo = 0, total = Infinity;
          while (out.length < total) {
            const url = `${base}/${id}/options?page=${pageNo}&pageSize=100`
                      + `&sortBy=START_AT&fromDate=${fromDate}`;
            const r = await fetch(url, {headers: {authorization: token, accept: 'application/json'}});
            if (!r.ok) return {error: r.status};
            const d = await r.json();
            total = d.totalCount ?? (d.options || []).length;
            const opts = d.options || [];
            out.push(...opts);
            if (opts.length === 0) break;
            pageNo += 1;
          }
          return {options: out};
        }
        """
        result = page.evaluate(js, [self.api_base, poll_id, token, _FROM_DATE])
        if isinstance(result, dict) and result.get("error"):
            raise RuntimeError(
                f"Doodle options request failed (HTTP {result['error']}) for poll {poll_id}."
            )
        return (result or {}).get("options", [])

    def submit(self, free_slots, poll: PollData) -> str:
        raise NotImplementedError(
            "Automatic vote submission isn't implemented for Doodle's new group "
            "polls. Use the web app to list conflict-free slots and fill the poll "
            "yourself."
        )
