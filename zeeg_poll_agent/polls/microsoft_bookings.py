"""Microsoft Bookings public self-service page adapter.

The public booking page (bookings.cloud.microsoft, book.ms, or the Outlook
/book path) is a SPA that loads available times anonymously. The documented
Graph `getStaffAvailability` API needs authentication, so for a public poll/booking
link we render the page with Playwright and extract the visible slots.
"""
from __future__ import annotations

from .base import register
from .generic import GenericBrowserAdapter


@register
class MicrosoftBookingsAdapter(GenericBrowserAdapter):
    host_matches = (
        "bookings.cloud.microsoft",
        "book.ms",
        "outlook.office365.com",
        "outlook.office.com",
    )
    service_name = "microsoft-bookings"
    wait_selector = "[data-start-time], time[datetime], button[aria-label*=':']"
