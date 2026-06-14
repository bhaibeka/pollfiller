"""Offline tests for the availability-based free/busy logic and web routes."""
import os
import unittest
from datetime import datetime, timedelta, timezone

os.environ.setdefault("ZEEG_API_TOKEN", "dummy-token-for-tests")

from zeeg_poll_agent.availability import free_and_conflicting
from zeeg_poll_agent.models import PollData, TimeSlot

UTC = timezone.utc


class FakeZeeg:
    """Stand-in for ZeegClient returning canned connected-calendar availability."""
    def __init__(self, avail):
        self._avail = avail
        self.calls = []

    def available_slots(self, owner_slug, event_type_slug, start_date, end_date, time_zone, duration=None):
        self.calls.append((owner_slug, event_type_slug, start_date, end_date, time_zone, duration))
        return self._avail


def poll_with(slots):
    return PollData(url="x", service="doodle", title="t", slots=slots)


class TestAvailabilityMatching(unittest.TestCase):
    def test_free_when_time_listed_busy_otherwise(self):
        # Two 30-min options at 13:00 and 14:00 UTC on 2026-04-15.
        s1 = TimeSlot(datetime(2026, 4, 15, 13, 0, tzinfo=UTC), datetime(2026, 4, 15, 13, 30, tzinfo=UTC))
        s2 = TimeSlot(datetime(2026, 4, 15, 14, 0, tzinfo=UTC), datetime(2026, 4, 15, 14, 30, tzinfo=UTC))
        # Zeeg (in UTC) reports only 13:00 available -> 14:00 is a calendar conflict.
        fake = FakeZeeg({"2026-04-15": {"13:00"}})
        free, conf = free_and_conflicting(fake, poll_with([s1, s2]), "ben", "30min", "UTC")
        self.assertEqual([s.start.hour for s in free], [13])
        self.assertEqual([s.start.hour for s in conf], [14])

    def test_timezone_conversion(self):
        # 17:00 UTC == 13:00 America/Toronto (EDT, -4) on 2026-04-15.
        s = TimeSlot(datetime(2026, 4, 15, 17, 0, tzinfo=UTC), datetime(2026, 4, 15, 17, 30, tzinfo=UTC))
        fake = FakeZeeg({"2026-04-15": {"13:00"}})
        free, conf = free_and_conflicting(fake, poll_with([s]), "ben", "30min", "America/Toronto")
        self.assertEqual(len(free), 1)
        # Duration was passed through as 30 minutes.
        self.assertEqual(fake.calls[0][5], 30)

    def test_durations_queried_separately(self):
        s30 = TimeSlot(datetime(2026, 4, 15, 9, 0, tzinfo=UTC), datetime(2026, 4, 15, 9, 30, tzinfo=UTC))
        s60 = TimeSlot(datetime(2026, 4, 15, 10, 0, tzinfo=UTC), datetime(2026, 4, 15, 11, 0, tzinfo=UTC))
        fake = FakeZeeg({"2026-04-15": {"09:00", "10:00"}})
        free, conf = free_and_conflicting(fake, poll_with([s30, s60]), "ben", "30min", "UTC")
        self.assertEqual(len(free), 2)
        durations = sorted(c[5] for c in fake.calls)
        self.assertEqual(durations, [30, 60])


class TestWebRoutes(unittest.TestCase):
    def test_index_and_health(self):
        from zeeg_poll_agent.webapp import create_app
        app = create_app()
        client = app.test_client()
        self.assertEqual(client.get("/").status_code, 200)
        h = client.get("/api/health").get_json()
        self.assertEqual(h["status"], "ok")
        self.assertIn("doodle", h["services"])

    def test_analyze_requires_url(self):
        from zeeg_poll_agent.webapp import create_app
        client = create_app().test_client()
        r = client.post("/api/analyze", json={})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
