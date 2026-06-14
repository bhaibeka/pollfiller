"""Client for the Zeeg public REST API (v2).

Built against the official documentation at https://developer.zeeg.me .

Scope note
----------
The token used here is expected to carry `events:read`. With that scope the
reliable source of "busy" time is **List Scheduled Events** — i.e. meetings that
were booked *through* Zeeg.

Events that live only in an externally connected calendar (Google / Outlook) and
were never booked via Zeeg are *not* returned by this endpoint. Zeeg does expose
a slot-availability endpoint that already nets out connected-calendar conflicts
(`GET /availability/{ownerSlug}/event-types/{eventTypeSlug}`), but that endpoint
requires the `timetable` or `admin:full` scope and a paid plan. If you have such
a token, see `AvailabilityBusyProvider` below for a drop-in alternative.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterator, Optional

import requests

from .models import BusyInterval


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


class ZeegError(RuntimeError):
    pass


class ZeegClient:
    def __init__(
        self,
        token: str,
        base_url: str,
        timeout_s: float = 30.0,
        availability_timeout_s: float | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout_s
        self._availability_timeout = availability_timeout_s or timeout_s
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            }
        )

    # -- low level ---------------------------------------------------------
    def _get(
        self,
        path: str,
        params: Optional[dict] = None,
        timeout: Optional[float] = None,
        retries: int = 1,
    ) -> dict:
        url = path if path.startswith("http") else f"{self._base}/{path.lstrip('/')}"
        timeout = timeout or self._timeout
        last_exc: Optional[Exception] = None
        for attempt in range(retries + 1):
            try:
                resp = self._session.get(url, params=params, timeout=timeout)
                break
            except requests.exceptions.Timeout as e:  # slow endpoints are flaky
                last_exc = e
        else:
            raise ZeegError(
                f"Zeeg request to {url} timed out after {retries + 1} attempt(s) "
                f"({timeout:.0f}s each). The availability service may be busy; "
                "try again."
            ) from last_exc
        if resp.status_code == 401:
            raise ZeegError(
                "Zeeg rejected the token (401). Check the token in the `zeeg_api` "
                "file or the ZEEG_API_TOKEN env var."
            )
        if resp.status_code == 403:
            raise ZeegError(
                "Zeeg returned 403 Forbidden — the token lacks the scope for "
                f"this endpoint ({url})."
            )
        if resp.status_code >= 400:
            raise ZeegError(f"Zeeg {resp.status_code} for {url}: {resp.text[:300]}")
        return resp.json()

    # -- public ------------------------------------------------------------
    def whoami(self) -> dict:
        """Validate the token and return the authenticated user."""
        return self._get("/whoami")

    def iter_scheduled_events(
        self,
        min_start: datetime,
        max_start: datetime,
        status: str = "confirmed",
    ) -> Iterator[dict]:
        """Yield scheduled events whose startTime falls in [min_start, max_start]."""
        page = 1
        while True:
            params = {
                "minStartTime": _iso_utc(min_start),
                "maxStartTime": _iso_utc(max_start),
                "count": 100,
                "page": page,
                "sort": "asc",
            }
            if status:
                params["status"] = status
            data = self._get("/scheduled-events", params=params)
            for ev in data.get("collection", []):
                yield ev
            pagination = data.get("pagination") or {}
            current = pagination.get("currentPage", page)
            total = pagination.get("totalPages", page)
            if not pagination.get("nextPage") or current >= total:
                break
            page = current + 1

    def list_scheduling_pages(self) -> list[dict]:
        """Return all scheduling pages (event types) the user hosts."""
        pages: list[dict] = []
        page = 1
        while True:
            data = self._get("/event-types", params={"count": 100, "page": page})
            pages.extend(data.get("collection", []))
            pg = data.get("pagination") or {}
            if not pg.get("nextPage") or pg.get("currentPage", page) >= pg.get("totalPages", page):
                break
            page = pg["currentPage"] + 1
        return pages

    @staticmethod
    def owner_slug_for(page: dict) -> str:
        """Derive the availability `ownerSlug` for a scheduling page.

        Personal pages use the host's slug; shared types (Round Robin / Flexi /
        Collective) use the literal "shared", matching the availability API.
        """
        profile = page.get("profile") or {}
        if (profile.get("type") or "").lower() == "user" and profile.get("slug"):
            return profile["slug"]
        # Fall back to parsing the public scheduling URL: zeeg.me/{owner}/{slug}
        url = page.get("schedulingUrl", "")
        parts = [p for p in url.split("/") if p]
        if len(parts) >= 2:
            owner = parts[-2]
            if owner in {"R", "F", "C"}:
                return "shared"
            return owner
        return "shared"

    def available_slots(
        self,
        owner_slug: str,
        event_type_slug: str,
        start_date: str,
        end_date: str,
        time_zone: str,
        duration: Optional[int] = None,
    ) -> dict[str, set[str]]:
        """Return availability that already accounts for ALL connected calendars.

        This calls `GET /availability/{ownerSlug}/event-types/{eventTypeSlug}`,
        whose results Zeeg computes by subtracting both Zeeg bookings and every
        connected external calendar (Google, Outlook, ...) from the page's
        working hours.

        Returns a mapping of ``"YYYY-MM-DD" -> {"HH:MM", ...}`` of bookable start
        times in `time_zone`.
        """
        params = {
            "startDate": start_date,
            "endDate": end_date,
            "timeZone": time_zone,
        }
        if duration:
            params["duration"] = duration
        data = self._get(
            f"/availability/{owner_slug}/event-types/{event_type_slug}",
            params=params,
            timeout=self._availability_timeout,
        )
        out: dict[str, set[str]] = {}
        for day in data.get("availability", []):
            date = day.get("date")
            if not date:
                continue
            times: set[str] = set()
            for slot in day.get("slots", []):
                if isinstance(slot, str):
                    times.add(slot)
                elif isinstance(slot, dict) and slot.get("time"):
                    times.add(slot["time"])
            out[date] = times
        return out

    def busy_intervals(
        self,
        window_start: datetime,
        window_end: datetime,
        lookback_hours: int = 24,
    ) -> list[BusyInterval]:
        """Return confirmed bookings overlapping the window as busy intervals.

        `lookback_hours` widens the query backwards so an event that started
        before the window but is still running is not missed.
        """
        min_start = window_start - timedelta(hours=lookback_hours)
        intervals: list[BusyInterval] = []
        for ev in self.iter_scheduled_events(min_start, window_end, status="confirmed"):
            if (ev.get("status") or "").lower() == "cancelled":
                continue
            try:
                start = datetime.fromisoformat(ev["startTime"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(ev["endTime"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            # Keep only events that actually overlap the window of interest.
            if end <= window_start or start >= window_end:
                continue
            intervals.append(
                BusyInterval(
                    start=start,
                    end=end,
                    source="zeeg:scheduled_event",
                    title=ev.get("title", ""),
                )
            )
        return intervals
