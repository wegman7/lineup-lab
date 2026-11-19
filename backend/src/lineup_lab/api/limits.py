"""Per-visitor rate limit and daily spending cap, held in memory.

Correct only because the PoC runs as a single Cloud Run instance (technical spec §7).
IP addresses live in memory only and are never written anywhere (functional spec §7).
"""

import math
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

WINDOW_S = 3600


class RateLimiter:
    def __init__(self, per_hour: int, clock: Callable[[], float] = time.time):
        self.per_hour = per_hour
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def check(self, ip: str) -> int | None:
        """Record a request. Returns None if allowed, else seconds until the next slot opens."""
        now = self._clock()
        hits = self._hits.setdefault(ip, deque())
        while hits and hits[0] <= now - WINDOW_S:
            hits.popleft()
        if len(hits) >= self.per_hour:
            return max(1, math.ceil(hits[0] + WINDOW_S - now))
        hits.append(now)
        if len(self._hits) > 10_000:  # forget visitors with no recent requests
            self._hits = {k: v for k, v in self._hits.items() if v and v[-1] > now - WINDOW_S}
        return None


class SpendTracker:
    def __init__(self, cap_usd: float, clock: Callable[[], float] = time.time):
        self.cap_usd = cap_usd
        self._clock = clock
        self._day = self._today()
        self.spent = 0.0

    def _today(self):
        return datetime.fromtimestamp(self._clock(), UTC).date()

    def _roll(self) -> None:
        today = self._today()
        if today != self._day:
            self._day, self.spent = today, 0.0

    def add(self, usd: float) -> None:
        self._roll()
        self.spent += usd

    def exhausted(self) -> bool:
        self._roll()
        return self.spent >= self.cap_usd

    def resets_at(self) -> datetime:
        self._roll()
        return datetime(self._day.year, self._day.month, self._day.day, tzinfo=UTC) + timedelta(
            days=1
        )
