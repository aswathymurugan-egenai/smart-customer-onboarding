"""System implementations of the clock and id ports."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from datetime import UTC, datetime

UUID_VERSION = 7
_UUID7_RANDOM_BYTES = 10
_MILLISECOND_BYTES = 6


def new_uuid7() -> str:
    """Return a UUIDv7 string, using the standard library when it has one (Python 3.14+)."""
    native = getattr(uuid, "uuid7", None)
    if native is not None:
        return str(native())
    millis = time.time_ns() // 1_000_000
    raw = bytearray(millis.to_bytes(_MILLISECOND_BYTES, "big") + os.urandom(_UUID7_RANDOM_BYTES))
    raw[6] = (raw[6] & 0x0F) | (UUID_VERSION << 4)
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(raw)))


class SystemClock:
    """The wall clock and the event loop's sleep."""

    def now(self) -> datetime:
        """Current UTC time."""
        return datetime.now(UTC)

    def monotonic(self) -> float:
        """Monotonic seconds."""
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        """Wait without blocking the event loop."""
        await asyncio.sleep(seconds)


class Uuid7Generator:
    """Generates UUIDv7 identifiers."""

    def new_id(self) -> str:
        """Return a fresh UUIDv7."""
        return new_uuid7()
