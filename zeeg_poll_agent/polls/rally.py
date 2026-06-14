"""Rally (rally.co) adapter — browser-rendered group scheduling poll.

Distinct from Rallly (rallly.co), which has its own HTTP adapter.
"""
from __future__ import annotations

from .base import register
from .generic import GenericBrowserAdapter


@register
class RallyAdapter(GenericBrowserAdapter):
    host_matches = ("rally.co",)
    service_name = "rally"
    wait_selector = "[data-slot-start], [data-date], time[datetime]"
