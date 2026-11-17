"""Keyed hashing for personal data.

Tax IDs, audit emails, client addresses, and request bodies are hashed with one HMAC-SHA256
key and a distinct prefix per kind, so a hash of one kind never matches a hash of another.
The audit table and the customers table therefore hold no raw tax ID, email, or IP address
that a leaked table could expose to a dictionary attack without the key.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any

TAX_ID_PREFIX = b"tax_id:"
EMAIL_PREFIX = b"email:"
CLIENT_PREFIX = b"client:"
REQUEST_PREFIX = b"request:"
LAST_CHARACTERS = 4


class PiiHasher:
    """Computes keyed hashes under one key version."""

    def __init__(self, key: bytes, key_version: str) -> None:
        self._key = key
        self.key_version = key_version

    def _digest(self, prefix: bytes, value: str) -> str:
        return hmac.new(self._key, prefix + value.encode("utf-8"), hashlib.sha256).hexdigest()

    def tax_id(self, normalized_tax_id: str) -> str:
        """Hash a normalized tax ID."""
        return self._digest(TAX_ID_PREFIX, normalized_tax_id)

    def email(self, canonical_email: str) -> str:
        """Hash a canonical email address."""
        return self._digest(EMAIL_PREFIX, canonical_email)

    def client(self, client_id: str) -> str:
        """Hash a client address."""
        return self._digest(CLIENT_PREFIX, client_id)

    def fingerprint(self, body: Mapping[str, Any]) -> str:
        """Hash the canonical JSON form of a request body."""
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return self._digest(REQUEST_PREFIX, canonical)


def last_characters(value: str) -> str:
    """Return the last four characters of a normalized tax ID, for display."""
    return value[-LAST_CHARACTERS:]
