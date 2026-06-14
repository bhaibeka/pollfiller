"""URL normalization.

Links pasted from email clients are often wrapped by a security scanner that
rewrites the real destination into a redirect URL — most commonly Microsoft
Outlook "Safe Links". Unwrap those so the real poll URL reaches the adapters.

Example::

    https://can01.safelinks.protection.outlook.com/?url=https%3A%2F%2Fdoodle.com%2F...&data=...
        -> https://doodle.com/...
"""
from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse

# Hosts that wrap the real URL in a query parameter, and the params to check
# (in priority order). Matched as a substring of the lowercased host.
_REDIRECTORS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("safelinks.protection.outlook.com", ("url",)),       # Microsoft 365 Safe Links
    ("linkprotect.cudasvc.com", ("a", "url")),            # Barracuda
    ("protect-us.mimecast.com", ("url",)),                # Mimecast
    ("urldefense.com", ("u",)),                           # Proofpoint (v2 only)
    ("google.com", ("q", "url")),                         # Google redirect
)

_MAX_HOPS = 5


def unwrap_url(url: str) -> str:
    """Return the underlying URL, unwrapping known redirect wrappers.

    Safe to call on any URL: a normal (unwrapped) URL is returned unchanged.
    Handles nested wrappers up to a small hop limit.
    """
    current = (url or "").strip()
    for _ in range(_MAX_HOPS):
        host = (urlparse(current).hostname or "").lower()
        params = next((p for h, p in _REDIRECTORS if h in host), None)
        if not params:
            return current
        query = parse_qs(urlparse(current).query)
        nested = next(
            (query[p][0] for p in params if query.get(p) and query[p][0]),
            None,
        )
        if not nested:
            return current
        decoded = unquote(nested)
        if decoded == current:  # no progress; avoid looping
            return current
        current = decoded
    return current
