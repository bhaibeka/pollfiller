"""Pure, side-effect-free conflict logic. Fully unit-testable offline."""
from __future__ import annotations

from .models import BusyInterval, TimeSlot


def partition_slots(
    slots: list[TimeSlot],
    busy: list[BusyInterval],
) -> tuple[list[TimeSlot], list[TimeSlot]]:
    """Split `slots` into (free, conflicting).

    A slot is *conflicting* if it overlaps any busy interval. Overlap uses
    half-open intervals, so a meeting ending exactly when a slot starts does
    NOT count as a conflict (10:00–11:00 busy does not block an 11:00 slot).
    """
    free: list[TimeSlot] = []
    conflicting: list[TimeSlot] = []
    for slot in slots:
        if any(slot.overlaps(b.start, b.end) for b in busy):
            conflicting.append(slot)
        else:
            free.append(slot)
    return free, conflicting
