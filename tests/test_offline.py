"""Offline tests for the parts that need no network. Run with:

    python -m unittest discover -s tests -v
"""
import unittest
from datetime import datetime, timedelta, timezone

from zeeg_poll_agent.conflicts import partition_slots
from zeeg_poll_agent.models import BusyInterval, TimeSlot

UTC = timezone.utc


def slot(h0, m0, h1, m1, day=15):
    return TimeSlot(
        start=datetime(2026, 4, day, h0, m0, tzinfo=UTC),
        end=datetime(2026, 4, day, h1, m1, tzinfo=UTC),
    )


def busy(h0, m0, h1, m1, day=15):
    return BusyInterval(
        start=datetime(2026, 4, day, h0, m0, tzinfo=UTC),
        end=datetime(2026, 4, day, h1, m1, tzinfo=UTC),
    )


class TestModels(unittest.TestCase):
    def test_naive_datetime_rejected(self):
        with self.assertRaises(ValueError):
            TimeSlot(start=datetime(2026, 4, 15, 9), end=datetime(2026, 4, 15, 10))

    def test_end_must_follow_start(self):
        with self.assertRaises(ValueError):
            slot(10, 0, 9, 0)

    def test_overlap_true_when_intersecting(self):
        self.assertTrue(slot(9, 0, 10, 0).overlaps(
            datetime(2026, 4, 15, 9, 30, tzinfo=UTC),
            datetime(2026, 4, 15, 9, 45, tzinfo=UTC),
        ))

    def test_adjacent_intervals_do_not_overlap(self):
        # 9-10 busy should NOT block a 10-11 slot (half-open intervals).
        self.assertFalse(slot(10, 0, 11, 0).overlaps(
            datetime(2026, 4, 15, 9, 0, tzinfo=UTC),
            datetime(2026, 4, 15, 10, 0, tzinfo=UTC),
        ))


class TestPartition(unittest.TestCase):
    def test_free_when_no_busy(self):
        slots = [slot(9, 0, 9, 30), slot(10, 0, 10, 30)]
        free, conf = partition_slots(slots, [])
        self.assertEqual(len(free), 2)
        self.assertEqual(conf, [])

    def test_conflict_detected(self):
        slots = [slot(9, 0, 9, 30), slot(11, 0, 11, 30)]
        free, conf = partition_slots(slots, [busy(8, 45, 9, 15)])
        self.assertEqual([s.start.hour for s in free], [11])
        self.assertEqual([s.start.hour for s in conf], [9])

    def test_boundary_touch_is_free(self):
        slots = [slot(10, 0, 10, 30)]
        free, conf = partition_slots(slots, [busy(9, 0, 10, 0)])
        self.assertEqual(len(free), 1)
        self.assertEqual(conf, [])

    def test_multiple_busy_intervals(self):
        slots = [slot(9, 0, 9, 30), slot(10, 0, 10, 30), slot(13, 0, 13, 30)]
        free, conf = partition_slots(slots, [busy(9, 0, 9, 30), busy(13, 15, 14, 0)])
        self.assertEqual([s.start.hour for s in free], [10])
        self.assertEqual(sorted(s.start.hour for s in conf), [9, 13])


class TestUrlUnwrapping(unittest.TestCase):
    def test_clean_url_unchanged(self):
        from zeeg_poll_agent.urls import unwrap_url

        u = "https://www.when2meet.com/?37027874-eWSHc"
        self.assertEqual(unwrap_url(u), u)

    def test_safelinks_unwrap(self):
        from zeeg_poll_agent.urls import unwrap_url

        wrapped = (
            "https://can01.safelinks.protection.outlook.com/?url="
            "https%3A%2F%2Fdoodle.com%2Fgroup-poll%2Fparticipate%2FdBX3jpoa"
            "&data=05%7C02%7C&reserved=0"
        )
        self.assertEqual(
            unwrap_url(wrapped),
            "https://doodle.com/group-poll/participate/dBX3jpoa",
        )

    def test_nested_safelinks_then_urldefense_v3(self):
        from zeeg_poll_agent.urls import unwrap_url

        wrapped = (
            "https://can01.safelinks.protection.outlook.com/?url="
            "https%3A%2F%2Furldefense.com%2Fv3%2F__https%3A%2F%2Fwww.when2meet.com"
            "%2F%3F37027874-eWSHc__%3B!!CjcC7IQ!I3feT747m7L43blxsKJiGLN-bYTOI5_M7QN"
            "97ibiXekjDY9fJ2BTD9u1zf6ly_wWzzywcHJ8axGdgZiu5XM6XO8HfFxgcToRkw%24"
            "&data=05%7C02%7C&reserved=0"
        )
        self.assertEqual(unwrap_url(wrapped), "https://www.when2meet.com/?37027874-eWSHc")

    def test_urldefense_v3_with_replaced_chars(self):
        from zeeg_poll_agent.urls import unwrap_url
        import base64

        # Target https://a.io/x : "://" is a 3-char run (**D), then "/" a single *.
        # Replaced characters, in order, are ":" "/" "/" then "/" -> ":///".
        b64 = base64.urlsafe_b64encode(b":///").decode().rstrip("=")
        v3 = f"https://urldefense.com/v3/__https**Da.io*x__;{b64}!!sig$"
        self.assertEqual(unwrap_url(v3), "https://a.io/x")


class TestAdapterParsingOffline(unittest.TestCase):
    def test_doodle_option_parsing_iso(self):
        from zeeg_poll_agent.models import Identity
        from zeeg_poll_agent.polls.doodle import DoodleAdapter

        a = DoodleAdapter(
            "https://doodle.com/group-poll/participate/dBX3jpoa",
            Identity("B HK", "b@uhn.ca"),
        )
        # New group-poll API: options carry ISO-8601 startAt/endAt.
        options = [
            {"id": "o1", "startAt": "2026-04-15T09:00:00Z", "endAt": "2026-04-15T09:30:00Z"},
            {"id": "o2", "startAt": "2026-04-15T10:00:00Z", "endAt": "2026-04-15T10:30:00Z"},
            {"id": "o3", "allDay": True},  # ignored
        ]
        slots = a._parse_options(options)
        self.assertEqual(len(slots), 2)
        self.assertEqual(slots[0].payload["optionId"], "o1")
        self.assertEqual(slots[0].start, datetime(2026, 4, 15, 9, 0, tzinfo=UTC))

    def test_doodle_poll_id_from_group_poll_url(self):
        from zeeg_poll_agent.models import Identity
        from zeeg_poll_agent.polls.doodle import DoodleAdapter

        a = DoodleAdapter(
            "https://doodle.com/group-poll/participate/dBX3jpoa",
            Identity("x", "y@z"),
        )
        self.assertEqual(a._poll_id(), "dBX3jpoa")

    def test_when2meet_event_id_and_slot_regex(self):
        from zeeg_poll_agent.models import Identity
        from zeeg_poll_agent.polls.when2meet import When2MeetAdapter, _SLOT_RE

        a = When2MeetAdapter("https://www.when2meet.com/?28473822-AbCdEf", Identity("x", "y@z"))
        self.assertEqual(a._event_id(), "28473822")
        html = "TimeOfSlot[0]=1776243600;TimeOfSlot[1]=1776244500;"
        epochs = sorted(int(m.group(2)) for m in _SLOT_RE.finditer(html))
        self.assertEqual(epochs, [1776243600, 1776244500])


if __name__ == "__main__":
    unittest.main(verbosity=2)
