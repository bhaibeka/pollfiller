# Poll Availability Agent

Given a meeting-poll link, this reads the proposed time slots, checks them
against **all your connected calendars in Zeeg**, and tells you which slots are
conflict-free. It ships in two forms:

- **Web app** (the version you asked for) — paste a URL, get the free slots
  listed so you can fill the poll yourself.
- **CLI agent** — the same logic, plus optional auto-submission of your vote.

Supported out of the box: **Doodle, when2meet, Calendly, zcal, Microsoft
Bookings, Rallly (rallly.co), Rally (rally.co)** — plus a **universal fallback**
that attempts *any* other booking service by extracting time slots generically.

| Service | Host(s) | How it's read |
|---|---|---|
| Doodle | doodle.com | internal JSON API (no browser) |
| when2meet | when2meet.com | embedded grid JS (no browser) |
| Rallly | rallly.co | `__NEXT_DATA__` page state (no browser) |
| Calendly | calendly.com | rendered page (Playwright) |
| zcal | zcal.co | rendered page (Playwright) |
| Microsoft Bookings | bookings.cloud.microsoft, book.ms, outlook.office(365).com | rendered page (Playwright) |
| Rally | rally.co | rendered page (Playwright) |
| **anything else** | * | generic extractor (static HTML, else Playwright) |

### How "any booking service" works
Unknown hosts fall through to a generic extractor that pulls time slots from a
page using, in order: embedded app state (`__NEXT_DATA__`, `__NUXT__`,
`__INITIAL_STATE__`), JSON-LD `Event` nodes, and datetime-bearing HTML
(`<time datetime>`, `data-start-time`, …). Pages that server-render or embed
their data are read without a browser; pure client-side SPAs need Playwright.

---

## How availability is determined

The key requirement is that free/busy reflects *every* connected calendar
(Google, Outlook, …), not just meetings booked through Zeeg. To do that the app
calls Zeeg's availability endpoint:

```
GET /availability/{ownerSlug}/event-types/{eventTypeSlug}
```

Zeeg computes those slots by subtracting both Zeeg bookings **and every connected
external calendar** from the scheduling page's working hours. A poll slot is
marked **free** only if Zeeg offers a bookable start at exactly that local time
and duration.

This endpoint requires an **`admin:full`** (or `timetable`) token and a paid
plan. An `events:read`-only token can see Zeeg bookings but *not* external
calendars, so use the admin token here.

> **Grid caveat.** Availability start times follow the scheduling page's own
> increment (e.g. every 15 or 30 min). A poll proposing an off-grid time (9:10
> on a page that books on the half-hour) can't be confirmed and is listed under
> conflicts to stay safe. Choosing a fine-grained scheduling page avoids this.

---

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env          # then paste your ZEEG_API_TOKEN into .env
set -a && source .env && set +a
```

Verify the token:

```bash
python -m zeeg_poll_agent.cli --check
```

## Web app (paste URL → list free slots)

```bash
python -m zeeg_poll_agent.webapp
# open http://127.0.0.1:5000
```

Paste the poll URL, confirm the time zone (auto-detected), optionally pick which
Zeeg scheduling page to use as the availability source, and hit **Find my free
slots**. Free times are grouped by day with a one-click "copy" button. The web
app only reads — it never submits for you.

## CLI

```bash
# List free slots (no vote cast) — recommended first:
python -m zeeg_poll_agent.cli "https://doodle.com/poll/abc123"

# Cast the vote under your name/email:
python -m zeeg_poll_agent.cli "https://doodle.com/poll/abc123" --submit

python -m zeeg_poll_agent.cli --list-services
```

## Verifying it works on a real poll

The 26 offline tests cover the parsing/conflict logic, the generic extractor
(Next.js state, JSON-LD, datetime attributes), service routing for all named
hosts, and the full `find_free_slots` pipeline with the network stubbed:

```bash
python -m unittest discover -s tests -v
```

To confirm a *live* poll can be read (run this in your own networked
environment), use the diagnostic — it detects the service and counts slots
without touching Zeeg or voting:

```bash
python -m zeeg_poll_agent.cli "https://rallly.co/invite/…" --diagnose
# {"url": "...", "service": "rallly", "ok": true, "slot_count": 6, "sample": [...]}
```

The web app has the same probe behind the **“Test poll only”** button.

> **Why testing happens on your side.** The named services gate their internal
> APIs and slot data behind a live session / real invite URL, so true
> end-to-end reads must run from your machine with network access (and Playwright
> for the SPA-based ones). The diagnostic above makes that a one-liner. If a
> service’s layout drifts, the adapter fails loudly with guidance rather than
> silently returning wrong slots.

---

## Architecture

```
zeeg_poll_agent/
  models.py          TimeSlot / BusyInterval / PollData / SelectionResult
  config.py          env-based config (token never hard-coded)
  zeeg_client.py     Zeeg v2 API: whoami, scheduling pages, availability, events
  availability.py    connected-calendar free/busy matching (the core logic)
  conflicts.py       pure interval-overlap helper (used by the submit flow)
  agent.py           orchestration: find_free_slots(), run()
  cli.py             command-line entry point
  webapp.py          Flask app
  web/index.html     single-page UI
  polls/
    base.py          PollAdapter interface + registry + URL routing (+ generic fallback)
    extract.py       service-agnostic slot extraction (Next.js/JSON-LD/datetime attrs)
    generic.py       GenericHttpAdapter + GenericBrowserAdapter (the universal engine)
    doodle.py        Doodle internal JSON API
    when2meet.py     when2meet grid scraping + AJAX
    rallly.py        Rallly (rallly.co) via __NEXT_DATA__
    calendly.py      Calendly (Playwright)
    zcal.py          zcal (Playwright)
    microsoft_bookings.py   MS Bookings public page (Playwright)
    rally.py         Rally (rally.co) (Playwright)
```

**Adding a service:** usually nothing is needed — the generic fallback tries
first. For a tuned adapter, subclass `GenericHttpAdapter` (server-rendered /
embedded data) or `GenericBrowserAdapter` (SPA), set `host_matches` /
`service_name` (and `wait_selector` for SPAs), and decorate with `@register`.

### Adapter notes
- **Doodle / when2meet / Rallly** read structured data straight from the page
  or an internal endpoint — fast, no browser. They fail loudly with guidance if
  a response shape drifts.
- **Calendly / zcal / Microsoft Bookings / Rally** are client-side apps, so
  they're rendered with Playwright and read via the generic extractor. Standard
  single-slot links (Calendly, MS Bookings) list bookable slots to pick from
  rather than multi-vote.

---

## Security

These tokens are powerful (the admin one can read/modify your whole workspace):

1. **Rotate both tokens you shared** — pasting a token into any chat or file
   should be treated as exposing it. Regenerate them at
   `app.zeeg.me/account/settings/api-access`.
2. The token is read from the `ZEEG_API_TOKEN` environment variable and is
   never written into source. Keep `.env` out of version control.
3. The web app binds to `127.0.0.1` by default. Don't expose it to a network
   while it holds an admin token.
```
