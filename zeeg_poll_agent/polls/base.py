"""Adapter framework for booking/poll services.

Each supported service implements `PollAdapter`:

    fetch()                 -> PollData   (read the poll's options)
    submit(free_slots, id)  -> str        (cast the vote)

New services are added by subclassing and decorating with @register.
`detect_adapter(url)` picks the right one from the URL host.
"""
from __future__ import annotations

import abc
from typing import Callable, Optional, Type
from urllib.parse import urlparse

from ..models import Identity, PollData, TimeSlot

_REGISTRY: list[Type["PollAdapter"]] = []


def register(cls: Type["PollAdapter"]) -> Type["PollAdapter"]:
    _REGISTRY.append(cls)
    return cls


class PollAdapter(abc.ABC):
    """Interface every service adapter must satisfy."""

    #: lowercase substrings that, if present in the URL host, select this adapter
    host_matches: tuple[str, ...] = ()
    service_name: str = "unknown"

    def __init__(self, url: str, identity: Identity, timeout_s: float = 30.0) -> None:
        self.url = url
        self.identity = identity
        self.timeout_s = timeout_s

    @classmethod
    def handles(cls, host: str) -> bool:
        host = host.lower()
        return any(m in host for m in cls.host_matches)

    @abc.abstractmethod
    def fetch(self) -> PollData:
        """Load the poll and return its available options as TimeSlots."""

    @abc.abstractmethod
    def submit(self, free_slots: list[TimeSlot], poll: PollData) -> str:
        """Submit a vote for `free_slots` under `self.identity`.

        Returns a human-readable confirmation string. Must raise on failure.
        """


def detect_adapter(url: str, allow_generic: bool = True) -> Optional[Type[PollAdapter]]:
    host = (urlparse(url).hostname or "").lower()
    for cls in _REGISTRY:
        if cls.handles(host):
            return cls
    if allow_generic:
        # Universal fallback so *any* booking service is at least attempted.
        from .generic import GenericHttpAdapter
        return GenericHttpAdapter
    return None


def supported_services() -> list[str]:
    return sorted({c.service_name for c in _REGISTRY})


# Importing the concrete adapters registers them via the @register decorator.
def load_builtin_adapters() -> None:
    from . import (  # noqa: F401
        doodle,
        when2meet,
        calendly,
        rally,
        rallly,
        zcal,
        microsoft_bookings,
    )
