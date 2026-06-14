"""Calendly adapter.

Calendly renders its scheduling page client-side, so we render with Playwright
and use the shared extractor (Calendly exposes slot start times via
``[data-start-time]`` / ``<time datetime>`` on the rendered page).

Note: standard Calendly links book exactly ONE slot, while Meeting Polls let you
mark several. Either way this lists the conflict-free options; for single-slot
links you'd pick one yourself.
"""
from __future__ import annotations

from .base import register
from .generic import GenericBrowserAdapter


@register
class CalendlyAdapter(GenericBrowserAdapter):
    host_matches = ("calendly.com",)
    service_name = "calendly"
    wait_selector = "[data-start-time], button[data-container='time-button'], time[datetime]"
