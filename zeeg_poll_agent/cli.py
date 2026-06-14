"""Command-line interface.

Examples
--------
    # Verify the Zeeg token works:
    python -m zeeg_poll_agent.cli --check

    # See what the agent WOULD do (no vote cast) — recommended first run:
    python -m zeeg_poll_agent.cli "https://doodle.com/poll/abc123"

    # Actually submit the vote:
    python -m zeeg_poll_agent.cli "https://doodle.com/poll/abc123" --submit
"""
from __future__ import annotations

import argparse
import logging
import sys

from .agent import PollAgent
from .config import Config
from .models import SelectionResult
from .polls import load_builtin_adapters, supported_services


def _print_result(res: SelectionResult) -> None:
    print(f"\nPoll:     {res.poll.title}  ({res.poll.service})")
    print(f"Options:  {len(res.poll.slots)}")
    print(f"Busy:     {len(res.busy)} interval(s) from connected Zeeg calendars")
    print(f"\nFree (will vote): {len(res.free_slots)}")
    for s in res.free_slots:
        print(f"  ✓ {s.start.isoformat()} → {s.end.isoformat()}")
    print(f"\nConflicting (skipped): {len(res.conflicting_slots)}")
    for s in res.conflicting_slots:
        print(f"  ✗ {s.start.isoformat()} → {s.end.isoformat()}")
    print(f"\n{res.submission_detail}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Auto-fill meeting polls from Zeeg availability.")
    parser.add_argument("url", nargs="?", help="Poll URL (doodle, when2meet, calendly, rally, ...)")
    parser.add_argument("--submit", action="store_true", help="Actually cast the vote (default is dry-run).")
    parser.add_argument("--diagnose", action="store_true", help="Probe the poll URL only (detect service + count slots); no Zeeg, no vote.")
    parser.add_argument("--check", action="store_true", help="Only verify the Zeeg token, then exit.")
    parser.add_argument("--list-services", action="store_true", help="List supported poll services.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.list_services:
        load_builtin_adapters()
        print("Supported services:", ", ".join(supported_services()))
        return 0

    try:
        config = Config.from_env()
    except RuntimeError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 2

    agent = PollAgent(config)

    if args.check:
        try:
            who = agent.verify_credentials()
            print("Zeeg token OK. Authenticated as:", who)
            return 0
        except Exception as e:  # noqa: BLE001
            print(f"Zeeg check failed: {e}", file=sys.stderr)
            return 1

    if not args.url:
        parser.error("a poll URL is required (or use --check / --list-services)")

    if args.diagnose:
        import json
        print(json.dumps(agent.diagnose(args.url), indent=2))
        return 0

    try:
        result = agent.run(args.url, dry_run=not args.submit)
    except Exception as e:  # noqa: BLE001
        print(f"Error: {e}", file=sys.stderr)
        return 1

    _print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
