"""Runtime configuration.

Secrets (the Zeeg token) are read from the environment or the `zeeg_api`
token file at the project root, never hard-coded. Export ``ZEEG_API_TOKEN``
or drop the token into the `zeeg_api` file.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .models import Identity

ZEEG_BASE_URL = "https://api.zeeg.me/v2"

# Token file at the project root (the directory above this package).
ZEEG_TOKEN_FILE = Path(__file__).resolve().parent.parent / "zeeg_api"


def _read_token() -> str:
    """Return the Zeeg token from the environment or the `zeeg_api` file."""
    token = os.environ.get("ZEEG_API_TOKEN", "").strip()
    if token:
        return token
    try:
        return ZEEG_TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


@dataclass
class Config:
    zeeg_token: str
    identity: Identity
    zeeg_base_url: str = ZEEG_BASE_URL
    # How far before the earliest poll slot we look for already-running events.
    busy_lookback_hours: int = 24
    request_timeout_s: float = 30.0

    @classmethod
    def from_env(cls) -> "Config":
        token = _read_token()
        if not token:
            raise RuntimeError(
                f"No Zeeg token found. Export ZEEG_API_TOKEN or store the token "
                f"in {ZEEG_TOKEN_FILE}. Never commit your token to source control."
            )
        name = os.environ.get("VOTER_NAME", "Benjamin Haibe-Kains").strip()
        email = os.environ.get("VOTER_EMAIL", "benjamin.haibe-kains@uhn.ca").strip()
        return cls(zeeg_token=token, identity=Identity(name=name, email=email))
