"""In-memory sliding-window rate limiter, one window per client and operation.

State lives in one process, so each instance counts on its own. Shared storage waits until
the API runs more than one instance.
"""

from __future__ import annotations

import math
from collections import deque

from app.config import Operation, Settings
from app.domain.errors import RateLimited
from app.services.ports import Clock

SWEEP_INTERVAL = 1000


class SlidingWindowRateLimiter:
    """Counts calls per client and operation inside a sliding window."""

    def __init__(self, settings: Settings, clock: Clock) -> None:
        self._settings = settings
        self._clock = clock
        self._calls: dict[tuple[str, Operation], deque[float]] = {}
        self._since_sweep = 0

    def check(self, client_id: str, operation: Operation) -> None:
        """Record one call, or raise `RateLimited` with the seconds until the window frees."""
        rule = self._settings.rate_rule(operation)
        now = self._clock.monotonic()
        window = self._calls.setdefault((client_id, operation), deque())
        self._evict(window, now, rule.window_seconds)
        if len(window) >= rule.limit:
            retry_after = max(1, math.ceil(window[0] + rule.window_seconds - now))
            raise RateLimited(retry_after)
        window.append(now)
        self._sweep(now)

    @staticmethod
    def _evict(window: deque[float], now: float, window_seconds: int) -> None:
        while window and now - window[0] >= window_seconds:
            window.popleft()

    def _sweep(self, now: float) -> None:
        self._since_sweep += 1
        if self._since_sweep < SWEEP_INTERVAL:
            return
        self._since_sweep = 0
        for key in list(self._calls):
            window = self._calls[key]
            self._evict(window, now, self._settings.rate_rule(key[1]).window_seconds)
            if not window:
                del self._calls[key]
