"""Decide which poll slots are free using Zeeg's connected-calendar availability.

This is the source of truth requested: availability is collected across ALL
connected calendars (Google / Outlook / etc.) via Zeeg's availability endpoint,
not just events booked through Zeeg.

A poll slot ``[start, start+duration)`` is considered FREE when Zeeg reports a
bookable start at exactly that local time for that duration on that date.

Caveat: the availability endpoint returns start times on the scheduling page's
own increment (e.g. every 15 or 30 minutes). If a poll proposes an off-grid
start (say 09:10) that the page never offers, that slot can't be confirmed and
is reported as a conflict to stay on the safe side. Picking a scheduling page
with a fine increment minimises this.
"""
from __future__ import annotations

from collections import defaultdict
from zoneinfo import ZoneInfo

from .models import PollData, TimeSlot
from .zeeg_client import ZeegClient


def _duration_minutes(slot: TimeSlot) -> int:
    return max(1, round((slot.end - slot.start).total_seconds() / 60))


def free_and_conflicting(
    zeeg: ZeegClient,
    poll: PollData,
    owner_slug: str,
    event_type_slug: str,
    time_zone: str,
) -> tuple[list[TimeSlot], list[TimeSlot]]:
    """Split poll slots into (free, conflicting) using connected-calendar data."""
    tz = ZoneInfo(time_zone)

    # Group poll slots by duration so we query the availability grid correctly.
    by_duration: dict[int, list[TimeSlot]] = defaultdict(list)
    for s in poll.slots:
        by_duration[_duration_minutes(s)].append(s)

    free: list[TimeSlot] = []
    conflicting: list[TimeSlot] = []

    for duration, slots in by_duration.items():
        locals_ = [(s, s.start.astimezone(tz)) for s in slots]
        start_date = min(local.date() for _, local in locals_).isoformat()
        end_date = max(local.date() for _, local in locals_).isoformat()

        avail = zeeg.available_slots(
            owner_slug=owner_slug,
            event_type_slug=event_type_slug,
            start_date=start_date,
            end_date=end_date,
            time_zone=time_zone,
            duration=duration,
        )

        for slot, local in locals_:
            date_key = local.date().isoformat()
            hhmm = local.strftime("%H:%M")
            if hhmm in avail.get(date_key, set()):
                free.append(slot)
            else:
                conflicting.append(slot)

    free.sort(key=lambda s: s.start)
    conflicting.sort(key=lambda s: s.start)
    return free, conflicting
