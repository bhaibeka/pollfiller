"""Service-agnostic time-slot extraction.

The goal is to support *any* booking service, not just a hard-coded list. Given
a page's HTML, we try several strategies in order and return whatever time slots
we can find:

  1. Embedded app state — ``__NEXT_DATA__`` (Next.js: Rallly, many others),
     ``__NUXT__``, ``window.__INITIAL_STATE__`` — walked recursively for objects
     that look like time options.
  2. JSON-LD (``<script type="application/ld+json">``) Event/Reservation nodes.
  3. HTML datetime carriers: ``<time datetime>``, ``[data-start-time]``,
     ``[data-start]``, ``[data-slot-start]``, ``[data-date]``.

Everything here is pure (HTML string in, TimeSlots out) so it is fully testable
offline and works identically whether the HTML came from `requests` (static /
server-rendered pages) or from a rendered Playwright DOM (client-rendered SPAs).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Iterable, Optional

from ..models import TimeSlot

_START_KEYS = ("start", "starttime", "start_time", "startdate", "start_date",
               "begin", "from", "datetime", "time")
_END_KEYS = ("end", "endtime", "end_time", "enddate", "end_date", "until", "to")
_DURATION_KEYS = ("duration", "durationminutes", "duration_minutes", "length", "minutes")


def parse_datetime(value: Any, tz_hint: timezone | Any = timezone.utc) -> Optional[datetime]:
    """Best-effort parse of a datetime from ISO strings or epoch numbers."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        # Heuristic: ms vs seconds since epoch.
        seconds = value / 1000.0 if value > 1e11 else float(value)
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        # Pure epoch in a string.
        if re.fullmatch(r"\d{10,13}", s):
            return parse_datetime(int(s), tz_hint)
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz_hint)
        return dt.astimezone(timezone.utc)
    return None


def _duration_minutes(obj: dict) -> Optional[int]:
    for k in _DURATION_KEYS:
        for key in obj:
            if key.lower() == k:
                v = obj[key]
                if isinstance(v, (int, float)) and v > 0:
                    return int(v)
                if isinstance(v, str) and v.isdigit():
                    return int(v)
    return None


def _slot_from_obj(obj: dict, tz_hint) -> Optional[TimeSlot]:
    lower = {k.lower(): k for k in obj.keys()}
    start = None
    for k in _START_KEYS:
        if k in lower:
            start = parse_datetime(obj[lower[k]], tz_hint)
            if start:
                break
    if not start:
        return None
    end = None
    for k in _END_KEYS:
        if k in lower:
            end = parse_datetime(obj[lower[k]], tz_hint)
            if end:
                break
    if not end:
        mins = _duration_minutes(obj)
        end = start + timedelta(minutes=mins or 30)
    if end <= start:
        end = start + timedelta(minutes=30)
    oid = None
    for idk in ("id", "optionid", "option_id", "uuid", "key"):
        if idk in lower:
            oid = str(obj[lower[idk]])
            break
    return TimeSlot(start=start, end=end, external_id=oid, payload={"source": "json"})


def _walk_json(node: Any, tz_hint, found: list[TimeSlot], seen: set) -> None:
    if isinstance(node, dict):
        slot = _slot_from_obj(node, tz_hint)
        if slot:
            key = (slot.start, slot.end)
            if key not in seen:
                seen.add(key)
                found.append(slot)
        for v in node.values():
            _walk_json(v, tz_hint, found, seen)
    elif isinstance(node, list):
        for v in node:
            _walk_json(v, tz_hint, found, seen)


def _script_jsons(html: str, var_patterns: Iterable[str]) -> list[Any]:
    out: list[Any] = []
    # <script id="__NEXT_DATA__" type="application/json">...</script>
    for m in re.finditer(
        r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL
    ):
        try:
            out.append(json.loads(m.group(1)))
        except json.JSONDecodeError:
            pass
    # window.__X__ = {...};
    for pat in var_patterns:
        for m in re.finditer(pat + r"\s*=\s*(\{.*?\})\s*;?\s*</script>", html, re.DOTALL):
            try:
                out.append(json.loads(m.group(1)))
            except json.JSONDecodeError:
                pass
    return out


def _jsonld(html: str) -> list[Any]:
    out: list[Any] = []
    for m in re.finditer(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL
    ):
        try:
            out.append(json.loads(m.group(1)))
        except json.JSONDecodeError:
            pass
    return out


class _AttrTimeParser(HTMLParser):
    """Collect datetime-bearing attributes from tags."""
    ATTRS = ("datetime", "data-start-time", "data-start", "data-slot-start",
             "data-date", "data-begin")

    def __init__(self) -> None:
        super().__init__()
        self.hits: list[dict[str, str]] = []

    def handle_starttag(self, tag, attrs):
        d = {k: v for k, v in attrs if v is not None}
        for a in self.ATTRS:
            if a in d:
                self.hits.append({"tag": tag, "attr": a, "value": d[a],
                                  "duration": d.get("data-duration", ""),
                                  "end": d.get("data-end-time", d.get("data-end", ""))})
                break


def extract_slots_from_html(html: str, tz_hint=timezone.utc) -> list[TimeSlot]:
    """Return time slots discovered in `html`, trying each strategy in turn."""
    found: list[TimeSlot] = []
    seen: set = set()

    # 1) Embedded app state (Next.js etc.)
    for blob in _script_jsons(html, [r"window\.__INITIAL_STATE__", r"window\.__NUXT__"]):
        _walk_json(blob, tz_hint, found, seen)

    # 2) JSON-LD
    for blob in _jsonld(html):
        _walk_json(blob, tz_hint, found, seen)

    # 3) datetime-bearing attributes
    if not found:
        p = _AttrTimeParser()
        try:
            p.feed(html)
        except Exception:  # noqa: BLE001 - tolerate malformed markup
            pass
        for hit in p.hits:
            start = parse_datetime(hit["value"], tz_hint)
            if not start:
                continue
            end = parse_datetime(hit["end"], tz_hint) if hit["end"] else None
            if not end:
                mins = int(hit["duration"]) if hit["duration"].isdigit() else 30
                end = start + timedelta(minutes=mins)
            key = (start, end)
            if key in seen:
                continue
            seen.add(key)
            found.append(TimeSlot(
                start=start, end=end, external_id=hit["value"],
                payload={"source": "attr", "selector": f"[{hit['attr']}='{hit['value']}']"},
            ))

    found.sort(key=lambda s: s.start)
    return found
