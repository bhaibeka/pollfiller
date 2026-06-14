"""Offline tests proving the generic extractor parses real-world page shapes,
and that every named service routes to the right adapter."""
import json
import os
import unittest
from datetime import datetime, timezone

os.environ.setdefault("ZEEG_API_TOKEN", "dummy-token-for-tests")

from zeeg_poll_agent.polls.base import detect_adapter, load_builtin_adapters
from zeeg_poll_agent.polls.extract import extract_slots_from_html, parse_datetime

load_builtin_adapters()
UTC = timezone.utc


class TestParseDatetime(unittest.TestCase):
    def test_iso_with_offset(self):
        dt = parse_datetime("2026-04-15T09:00:00-04:00")
        self.assertEqual(dt, datetime(2026, 4, 15, 13, 0, tzinfo=UTC))

    def test_epoch_ms_and_seconds(self):
        base = datetime(2026, 4, 15, 9, 0, tzinfo=UTC)
        self.assertEqual(parse_datetime(int(base.timestamp() * 1000)), base)
        self.assertEqual(parse_datetime(int(base.timestamp())), base)

    def test_naive_uses_tz_hint(self):
        from zoneinfo import ZoneInfo
        dt = parse_datetime("2026-04-15T09:00:00", tz_hint=ZoneInfo("America/Toronto"))
        self.assertEqual(dt, datetime(2026, 4, 15, 13, 0, tzinfo=UTC))


class TestExtractNextData(unittest.TestCase):
    def test_rallly_style_next_data(self):
        # Mirrors how a Next.js poll (Rallly) embeds options + duration.
        payload = {
            "props": {"pageProps": {"poll": {
                "title": "Team sync",
                "options": [
                    {"id": "o1", "start": "2026-04-15T13:00:00Z", "duration": 60},
                    {"id": "o2", "start": "2026-04-16T15:00:00Z", "duration": 30},
                ],
            }}}
        }
        html = f'<html><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script></body></html>'
        slots = extract_slots_from_html(html)
        self.assertEqual(len(slots), 2)
        self.assertEqual(slots[0].start, datetime(2026, 4, 15, 13, 0, tzinfo=UTC))
        self.assertEqual((slots[0].end - slots[0].start).seconds // 60, 60)
        self.assertEqual((slots[1].end - slots[1].start).seconds // 60, 30)


class TestExtractJsonLd(unittest.TestCase):
    def test_event_jsonld(self):
        blob = [
            {"@type": "Event", "startDate": "2026-04-15T09:00:00Z", "endDate": "2026-04-15T10:00:00Z"},
            {"@type": "Event", "startDate": "2026-04-15T11:00:00Z", "endDate": "2026-04-15T11:30:00Z"},
        ]
        html = f'<script type="application/ld+json">{json.dumps(blob)}</script>'
        slots = extract_slots_from_html(html)
        self.assertEqual(len(slots), 2)
        self.assertEqual(slots[0].end, datetime(2026, 4, 15, 10, 0, tzinfo=UTC))


class TestExtractAttributes(unittest.TestCase):
    def test_time_and_data_attributes(self):
        html = (
            '<div>'
            '<time datetime="2026-04-15T14:00:00Z">2 PM</time>'
            '<button data-start-time="2026-04-15T15:00:00Z" data-duration="45">3 PM</button>'
            '</div>'
        )
        slots = extract_slots_from_html(html)
        starts = sorted(s.start for s in slots)
        self.assertEqual(starts, [
            datetime(2026, 4, 15, 14, 0, tzinfo=UTC),
            datetime(2026, 4, 15, 15, 0, tzinfo=UTC),
        ])
        # The 3 PM slot carries a clickable selector for the browser submit path.
        sel = [s.payload.get("selector") for s in slots if s.start.hour == 15][0]
        self.assertIn("data-start-time", sel)

    def test_empty_when_no_times(self):
        self.assertEqual(extract_slots_from_html("<html><p>hello</p></html>"), [])


class TestServiceRouting(unittest.TestCase):
    CASES = {
        "https://doodle.com/poll/abc": "doodle",
        "https://www.when2meet.com/?123-xy": "when2meet",
        "https://calendly.com/team/intro": "calendly",
        "https://zcal.co/i/abcd": "zcal",
        "https://bookings.cloud.microsoft/public/x/y": "microsoft-bookings",
        "https://rallly.co/invite/abcd": "rallly",
        "https://rally.co/p/abcd": "rally",
        # Unknown host still routes to the universal fallback.
        "https://some-new-scheduler.example/p/1": "generic-http",
    }

    def test_routing(self):
        for url, expected in self.CASES.items():
            with self.subTest(url=url):
                cls = detect_adapter(url)
                self.assertIsNotNone(cls)
                self.assertEqual(cls.service_name, expected)

    def test_rally_vs_rallly_distinct(self):
        self.assertEqual(detect_adapter("https://rally.co/x").service_name, "rally")
        self.assertEqual(detect_adapter("https://rallly.co/x").service_name, "rallly")


class TestGenericAdapterPipeline(unittest.TestCase):
    def test_http_adapter_fetch_returns_polldata(self):
        # Drive the real adapter path, swapping only the network fetch for a fixture.
        from zeeg_poll_agent.models import Identity
        from zeeg_poll_agent.polls.generic import GenericHttpAdapter

        payload = {"props": {"pageProps": {"poll": {
            "title": "Grant call",
            "options": [
                {"id": "o1", "start": "2026-04-15T13:00:00Z", "duration": 30},
                {"id": "o2", "start": "2026-04-15T14:00:00Z", "duration": 30},
                {"id": "o3", "start": "2026-04-16T09:00:00Z", "duration": 30},
            ],
        }}}}
        html = (
            '<html><head><title>Grant call</title></head><body>'
            f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
            '</body></html>'
        )
        a = GenericHttpAdapter("https://rallly.co/invite/xyz", Identity("B HK", "b@uhn.ca"))
        a._fetch_html = lambda: html  # type: ignore[method-assign]
        poll = a.fetch()
        self.assertEqual(poll.title, "Grant call")
        self.assertEqual(len(poll.slots), 3)
        self.assertEqual(poll.slots[0].start, datetime(2026, 4, 15, 13, 0, tzinfo=UTC))


if __name__ == "__main__":
    unittest.main(verbosity=2)
