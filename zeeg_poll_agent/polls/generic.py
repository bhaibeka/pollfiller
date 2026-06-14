"""Universal adapters that work on *any* booking service.

`GenericHttpAdapter` fetches the page with `requests` and runs the shared
extractor. It handles services that server-render their slots or embed them in
page state (e.g. Next.js `__NEXT_DATA__`), with no browser needed.

`GenericBrowserAdapter` renders the page with Playwright first (for client-side
SPAs like Calendly / zcal / Microsoft Bookings) and runs the same extractor on
the resulting DOM, then offers a best-effort generic vote/submit.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
from zoneinfo import ZoneInfo

import requests

from ..models import PollData, TimeSlot
from .base import PollAdapter
from .extract import extract_slots_from_html


def _tz(name: str):
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001
        from datetime import timezone
        return timezone.utc


class GenericHttpAdapter(PollAdapter):
    service_name = "generic-http"
    host_matches = ()  # selected only as an explicit fallback
    default_tz = "UTC"

    def _fetch_html(self) -> str:
        s = requests.Session()
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; zeeg-poll-agent/1.0)",
            "Accept": "text/html,application/json",
        })
        r = s.get(self.url, timeout=self.timeout_s)
        r.raise_for_status()
        return r.text

    def fetch(self) -> PollData:
        html = self._fetch_html()
        slots = extract_slots_from_html(html, tz_hint=_tz(self.default_tz))
        if not slots:
            raise ValueError(
                f"Could not extract time slots from {self.url} via static HTML. "
                "The page is likely a client-rendered SPA — use the browser "
                "adapter (install Playwright) or add a service-specific adapter."
            )
        import re
        m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        return PollData(
            url=self.url, service=self.service_name,
            title=(m.group(1).strip() if m else self.service_name),
            slots=slots, timezone_name=self.default_tz, raw={"html_len": len(html)},
        )

    def submit(self, free_slots, poll: PollData) -> str:
        raise NotImplementedError(
            f"{self.service_name}: automatic submission isn't implemented for this "
            "service. Use the web app to list free slots and fill the poll yourself."
        )


class GenericBrowserAdapter(GenericHttpAdapter):
    service_name = "generic-browser"
    headless = True
    wait_selector: str | None = None

    @contextmanager
    def _page(self) -> Iterator[object]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                f"The {self.service_name} adapter needs Playwright: "
                "`pip install playwright && playwright install chromium`."
            ) from e
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            try:
                page = browser.new_page()
                page.set_default_timeout(self.timeout_s * 1000)
                page.goto(self.url, wait_until="networkidle")
                if self.wait_selector:
                    try:
                        page.wait_for_selector(self.wait_selector, timeout=self.timeout_s * 1000)
                    except Exception:  # noqa: BLE001
                        pass
                yield page
            finally:
                browser.close()

    def fetch(self) -> PollData:
        with self._page() as page:
            html = page.content()
            title = page.title()
        slots = extract_slots_from_html(html, tz_hint=_tz(self.default_tz))
        if not slots:
            raise ValueError(
                f"No slots found on the rendered {self.service_name} page. The "
                "extraction heuristics may need a service-specific hint."
            )
        return PollData(
            url=self.url, service=self.service_name, title=title,
            slots=slots, timezone_name=self.default_tz,
        )

    def submit(self, free_slots, poll: PollData) -> str:
        with self._page() as page:
            for slot in free_slots:
                sel = slot.payload.get("selector")
                if sel:
                    el = page.query_selector(sel)
                    if el:
                        el.click()
            for ns in ("input[name='name']", "input[name='full_name']", "input[placeholder*='name' i]"):
                el = page.query_selector(ns)
                if el:
                    el.fill(self.identity.name)
                    break
            for es in ("input[type='email']", "input[name='email']"):
                el = page.query_selector(es)
                if el:
                    el.fill(self.identity.email)
                    break
            for bs in ("button[type='submit']", "button:has-text('Submit')",
                       "button:has-text('Save')", "button:has-text('Schedule')",
                       "button:has-text('Confirm')", "button:has-text('Vote')"):
                el = page.query_selector(bs)
                if el:
                    el.click()
                    page.wait_for_load_state("networkidle")
                    return f"Submitted {len(free_slots)} slot(s) as {self.identity.name}."
        raise RuntimeError(f"Could not find a submit control on the {self.service_name} page.")
