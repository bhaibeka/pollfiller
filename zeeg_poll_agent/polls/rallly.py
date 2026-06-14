"""Rallly (rallly.co) adapter — open-source poll, distinct from rally.co.

Rallly is a Next.js app that embeds poll data (options with start time and
duration) in the page's ``__NEXT_DATA__`` blob, so the static-HTML extractor
reads it without a browser.
"""
from __future__ import annotations

from .base import register
from .generic import GenericHttpAdapter


@register
class RalllyAdapter(GenericHttpAdapter):
    host_matches = ("rallly.co",)
    service_name = "rallly"
