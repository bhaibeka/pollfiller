"""The agent: given a poll URL, read it, check Zeeg, select free slots, submit."""
from __future__ import annotations

import logging
from typing import Optional

from .config import Config
from .conflicts import partition_slots
from .models import SelectionResult
from .polls import detect_adapter, load_builtin_adapters, supported_services
from .urls import unwrap_url
from .zeeg_client import ZeegClient

log = logging.getLogger("zeeg_poll_agent")


class PollAgent:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.zeeg = ZeegClient(
            token=config.zeeg_token,
            base_url=config.zeeg_base_url,
            timeout_s=config.request_timeout_s,
        )
        load_builtin_adapters()

    def diagnose(self, url: str) -> dict:
        """Probe a poll URL without touching Zeeg.

        Reports which adapter handled it, how many slots were extracted, and a
        sample — the quickest way to confirm the agent can read a given poll.
        """
        from .polls.base import detect_adapter

        url = unwrap_url(url)
        info: dict = {"url": url, "ok": False}
        adapter_cls = detect_adapter(url)
        info["service"] = getattr(adapter_cls, "service_name", None)
        try:
            adapter = adapter_cls(url, self.config.identity, self.config.request_timeout_s)
            poll = adapter.fetch()
            info.update(
                ok=True,
                title=poll.title,
                slot_count=len(poll.slots),
                sample=[
                    {"start": s.start.isoformat(), "end": s.end.isoformat()}
                    for s in poll.slots[:5]
                ],
            )
        except Exception as e:  # noqa: BLE001
            info["error"] = f"{type(e).__name__}: {e}"
        return info

    def list_scheduling_pages(self) -> list[dict]:
        """Active scheduling pages, used to pick the availability source."""
        return self.zeeg.list_scheduling_pages()

    def default_page(self, pages: list[dict] | None = None) -> dict | None:
        """Pick a sensible default availability source.

        Prefers an active personal one-on-one page (best represents "my own
        availability across connected calendars").
        """
        pages = pages if pages is not None else self.list_scheduling_pages()
        if not pages:
            return None
        active = [p for p in pages if p.get("isActive")]
        pool = active or pages
        personal = [
            p for p in pool
            if (p.get("profile") or {}).get("type", "").lower() == "user"
            and p.get("type") == "ONE_ON_ONE"
        ]
        return (personal or pool)[0]

    def find_free_slots(
        self,
        url: str,
        time_zone: str,
        owner_slug: str | None = None,
        event_type_slug: str | None = None,
    ) -> SelectionResult:
        """Read a poll and list slots that don't conflict with any connected
        calendar. Does not submit anything — for the review-and-fill workflow.
        """
        from .availability import free_and_conflicting

        url = unwrap_url(url)
        adapter_cls = detect_adapter(url)
        if adapter_cls is None:
            raise ValueError(
                f"No adapter matched {url}. Supported services: "
                f"{', '.join(supported_services())}."
            )
        adapter = adapter_cls(url, self.config.identity, self.config.request_timeout_s)
        poll = adapter.fetch()

        if not (owner_slug and event_type_slug):
            page = self.default_page()
            if page is None:
                raise RuntimeError("No Zeeg scheduling page available to read availability from.")
            owner_slug = self.zeeg.owner_slug_for(page)
            event_type_slug = page["slug"]

        free, conflicting = free_and_conflicting(
            self.zeeg, poll, owner_slug, event_type_slug, time_zone
        )
        return SelectionResult(
            poll=poll,
            busy=[],
            free_slots=free,
            conflicting_slots=conflicting,
            submitted=False,
            submission_detail=(
                f"{len(free)} conflict-free slot(s) found via connected-calendar "
                f"availability (source: {owner_slug}/{event_type_slug})."
            ),
        )

    def run(self, url: str, dry_run: bool = True) -> SelectionResult:
        """Process one poll.

        dry_run=True (default) computes the selection but does NOT submit, so you
        can review what the agent would do before letting it vote for real.
        """
        url = unwrap_url(url)
        adapter_cls = detect_adapter(url)
        if adapter_cls is None:
            raise ValueError(
                f"No adapter matched {url}. Supported services: "
                f"{', '.join(supported_services())}."
            )
        adapter = adapter_cls(
            url=url,
            identity=self.config.identity,
            timeout_s=self.config.request_timeout_s,
        )

        log.info("Reading %s poll: %s", adapter.service_name, url)
        poll = adapter.fetch()
        log.info("Poll '%s' has %d time option(s)", poll.title, len(poll.slots))

        window_start = min(s.start for s in poll.slots)
        window_end = max(s.end for s in poll.slots)
        log.info("Checking Zeeg for conflicts between %s and %s", window_start, window_end)
        busy = self.zeeg.busy_intervals(
            window_start, window_end, lookback_hours=self.config.busy_lookback_hours
        )
        log.info("Found %d busy interval(s) from Zeeg", len(busy))

        free, conflicting = partition_slots(poll.slots, busy)
        log.info("%d free, %d conflicting", len(free), len(conflicting))

        result = SelectionResult(
            poll=poll, busy=busy, free_slots=free, conflicting_slots=conflicting
        )

        if not free:
            result.submission_detail = "No conflict-free slots; nothing submitted."
            return result

        if dry_run:
            result.submission_detail = (
                f"DRY RUN — would vote for {len(free)} slot(s); not submitted."
            )
            return result

        detail = adapter.submit(free, poll)
        result.submitted = True
        result.submission_detail = detail
        log.info("Submission complete: %s", detail)
        return result

    def verify_credentials(self) -> dict:
        """Confirm the Zeeg token works; returns the authenticated user."""
        return self.zeeg.whoami()
