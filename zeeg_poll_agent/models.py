"""Core data structures shared across the agent.

All datetimes inside the agent are timezone-aware and normalised to UTC.
Poll services hand us local wall-clock times plus a timezone; adapters are
responsible for converting to UTC before handing TimeSlot objects back.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError(f"datetime {dt!r} is naive; a timezone is required")
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class TimeSlot:
    """A single option offered by a poll.

    `external_id` / `payload` carry whatever the specific poll service needs in
    order to submit a vote for this slot later (an option id, a grid cell index,
    a DOM selector, ...). The agent treats them as opaque.
    """

    start: datetime
    end: datetime
    external_id: Optional[str] = None
    label: Optional[str] = None
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", _as_utc(self.start))
        object.__setattr__(self, "end", _as_utc(self.end))
        if self.end <= self.start:
            raise ValueError(f"slot end {self.end} must be after start {self.start}")

    def overlaps(self, other_start: datetime, other_end: datetime) -> bool:
        """Half-open interval overlap test: [start, end) vs [other_start, other_end)."""
        return self.start < _as_utc(other_end) and _as_utc(other_start) < self.end

    def __str__(self) -> str:
        return self.label or f"{self.start.isoformat()} → {self.end.isoformat()}"


@dataclass(frozen=True)
class BusyInterval:
    """A block of time during which the user is unavailable."""

    start: datetime
    end: datetime
    source: str = "zeeg"
    title: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", _as_utc(self.start))
        object.__setattr__(self, "end", _as_utc(self.end))


@dataclass
class Identity:
    """Who we vote as."""

    name: str
    email: str


@dataclass
class PollData:
    """Normalised view of a poll, produced by an adapter's `fetch`."""

    url: str
    service: str
    title: str
    slots: list[TimeSlot]
    timezone_name: str = "UTC"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class SelectionResult:
    poll: PollData
    busy: list[BusyInterval]
    free_slots: list[TimeSlot]
    conflicting_slots: list[TimeSlot]
    submitted: bool = False
    submission_detail: str = ""
