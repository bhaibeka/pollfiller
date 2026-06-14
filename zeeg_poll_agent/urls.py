"""URL normalization.

Links pasted from email clients are often wrapped by a security scanner that
rewrites the real destination into a redirect URL — Microsoft Outlook "Safe
Links", Proofpoint "urldefense", Barracuda, Mimecast, etc. Wrappers also nest
(Safe Links around a urldefense link is common). Unwrap them so the real poll
URL reaches the adapters.

Example::

    https://can01.safelinks.protection.outlook.com/?url=https%3A%2F%2Furldefense.com%2Fv3%2F__https%3A%2F%2Fwhen2meet.com%2F%3F123__%3B!!...
        -> https://when2meet.com/?123
"""
from __future__ import annotations

import base64
import re
from urllib.parse import parse_qs, unquote, urlparse

# Hosts that wrap the real URL in a query parameter, and the params to check
# (in priority order). Matched as a substring of the lowercased host.
_REDIRECTORS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("safelinks.protection.outlook.com", ("url",)),       # Microsoft 365 Safe Links
    ("linkprotect.cudasvc.com", ("a", "url")),            # Barracuda
    ("protect-us.mimecast.com", ("url",)),                # Mimecast
    ("urldefense.proofpoint.com", ("u",)),                # Proofpoint v2 (query param)
    ("google.com", ("q", "url")),                         # Google redirect
)

_MAX_HOPS = 6

# Base64 alphabet Proofpoint v3 uses for the run-length byte after "**".
_B64_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
_V3_RE = re.compile(r"/v3/__(?P<url>.+?)__;(?P<repl>.*?)(?:!|$)", re.DOTALL)


def _decode_urldefense_v3(url: str) -> str:
    """Decode a Proofpoint urldefense v3 link.

    v3 stores the real URL in the path between ``__`` and ``__;`` with special
    characters replaced by ``*`` (single) or ``**<n>`` (a run of n chars); the
    replaced characters themselves are base64-encoded in the ``__;<b64>!``
    segment. Returns the input unchanged if it isn't a v3 link.
    """
    m = _V3_RE.search(url)
    if not m:
        return url
    encoded, b64 = m.group("url"), m.group("repl")
    replaced = ""
    if b64:
        try:
            replaced = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)).decode(
                "utf-8", "replace"
            )
        except Exception:  # noqa: BLE001 — malformed; fall back to no substitutions
            replaced = ""

    out: list[str] = []
    ri = i = 0
    while i < len(encoded):
        ch = encoded[i]
        if ch != "*":
            out.append(ch)
            i += 1
            continue
        if encoded[i : i + 2] == "**" and i + 2 < len(encoded):
            n = _B64_ALPHABET.find(encoded[i + 2])
            n = n if n >= 0 else 0
            out.append(replaced[ri : ri + n])
            ri += n
            i += 3
        else:  # single replaced character
            out.append(replaced[ri : ri + 1])
            ri += 1
            i += 1
    return "".join(out)


def unwrap_url(url: str) -> str:
    """Return the underlying URL, unwrapping known redirect wrappers.

    Safe to call on any URL: a normal (unwrapped) URL is returned unchanged.
    Handles nested wrappers (e.g. Safe Links around urldefense) up to a hop limit.
    """
    current = (url or "").strip()
    for _ in range(_MAX_HOPS):
        host = (urlparse(current).hostname or "").lower()

        # Proofpoint v3 uses path encoding, not a query parameter.
        if "urldefense.com" in host and "/v3/" in current:
            decoded = _decode_urldefense_v3(current)
            if decoded == current:
                return current
            current = decoded
            continue

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
