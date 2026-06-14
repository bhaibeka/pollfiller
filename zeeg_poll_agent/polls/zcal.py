"""zcal (zcal.co) adapter — browser-rendered scheduling page / meeting poll."""
from __future__ import annotations

from .base import register
from .generic import GenericBrowserAdapter


@register
class ZcalAdapter(GenericBrowserAdapter):
    host_matches = ("zcal.co",)
    service_name = "zcal"
    wait_selector = "[data-start-time], time[datetime], [data-testid*='slot']"
