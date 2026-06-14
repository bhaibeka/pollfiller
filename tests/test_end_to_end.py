"""Capstone: exercise PollAgent.find_free_slots() end to end with both network
boundaries (poll fetch + Zeeg availability) stubbed, proving the whole pipeline
produces the right free/conflicting split."""
import json
import os
import unittest
from datetime import datetime, timezone

os.environ.setdefault("ZEEG_API_TOKEN", "dummy-token-for-tests")

from zeeg_poll_agent.agent import PollAgent
from zeeg_poll_agent.config import Config
from zeeg_poll_agent.polls.generic import GenericHttpAdapter

UTC = timezone.utc


def _rallly_html():
    payload = {"props": {"pageProps": {"poll": {
        "title": "Lab meeting",
        "options": [
            {"id": "o1", "start": "2026-04-15T13:00:00Z", "duration": 30},  # free
            {"id": "o2", "start": "2026-04-15T14:00:00Z", "duration": 30},  # conflict
            {"id": "o3", "start": "2026-04-16T13:00:00Z", "duration": 30},  # free
        ],
    }}}}
    return ('<html><head><title>Lab meeting</title></head><body>'
            f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
            '</body></html>')


class TestEndToEnd(unittest.TestCase):
    def setUp(self):
        self.agent = PollAgent(Config.from_env())
        # Stub the poll fetch (network) with a fixture.
        self._orig_fetch = GenericHttpAdapter._fetch_html
        GenericHttpAdapter._fetch_html = lambda self_: _rallly_html()
        # Stub Zeeg connected-calendar availability (network).
        # In UTC: 13:00 free both days; 14:00 NOT offered on the 15th (calendar conflict).
        self.agent.zeeg.available_slots = lambda **kw: {
            "2026-04-15": {"13:00"},
            "2026-04-16": {"13:00"},
        }

    def tearDown(self):
        GenericHttpAdapter._fetch_html = self._orig_fetch

    def test_pipeline_splits_free_and_conflicting(self):
        result = self.agent.find_free_slots(
            "https://rallly.co/invite/xyz",
            time_zone="UTC",
            owner_slug="ben",          # provided so no scheduling-page lookup (network) is needed
            event_type_slug="meeting",
        )
        free_starts = sorted(s.start for s in result.free_slots)
        conf_starts = sorted(s.start for s in result.conflicting_slots)
        self.assertEqual(free_starts, [
            datetime(2026, 4, 15, 13, 0, tzinfo=UTC),
            datetime(2026, 4, 16, 13, 0, tzinfo=UTC),
        ])
        self.assertEqual(conf_starts, [datetime(2026, 4, 15, 14, 0, tzinfo=UTC)])
        self.assertEqual(result.poll.service, "rallly")
        self.assertFalse(result.submitted)


if __name__ == "__main__":
    unittest.main(verbosity=2)
