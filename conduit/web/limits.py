"""Rate limiting for the public demo.

The demo runs on a free hosting tier against a free-tier LLM quota, so the
scarce resource is *upstream model calls*, not CPU. Two independent ceilings:

  * **per-IP** — one visitor cannot burn the day's quota on their own.
  * **global daily** — kept deliberately below the provider's free-tier daily
    limit, so the API degrades into a clear "demo quota reached" message
    instead of leaking a provider 429 to a visitor.

State is in-memory and resets when the instance restarts. That is the correct
trade for a single-instance demo: no datastore, no cost, and the failure mode
(a restart grants a few extra calls) is harmless. Recorded transcripts are
served entirely outside this limiter, so the page stays useful once the live
budget is gone.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Callable

# Live questions one IP may ask per hour.
PER_IP_LIMIT = 3
PER_IP_WINDOW_SECONDS = 3600

# Live questions the whole demo may make per day, across all visitors.
#
# Sized against a measured constraint, not a guess: the Gemini free tier allows
# 20 generate_content requests per day *per model*, and one question costs one
# request per loop step (2-4 in practice). Eight questions is therefore roughly
# the real ceiling. Set it higher only alongside a paid key.
GLOBAL_DAILY_LIMIT = 8
DAY_SECONDS = 86400

# Stop tracking IPs beyond this many, so a spray of unique addresses cannot
# grow the table without bound. The global ceiling is the real backstop.
MAX_TRACKED_IPS = 5000


class RateLimiter:
    """Sliding-window limiter over live model-backed requests.

    Args:
        per_ip: Requests allowed per IP within ``per_ip_window``.
        per_ip_window: Length of the per-IP window, in seconds.
        global_daily: Requests allowed across all IPs within 24 hours.
        clock: Monotonic time source; injectable so tests need no sleeping.
    """

    def __init__(
        self,
        per_ip: int = PER_IP_LIMIT,
        per_ip_window: float = PER_IP_WINDOW_SECONDS,
        global_daily: int = GLOBAL_DAILY_LIMIT,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._per_ip = per_ip
        self._per_ip_window = per_ip_window
        self._global_daily = global_daily
        self._clock = clock
        self._by_ip: dict[str, deque[float]] = {}
        self._global: deque[float] = deque()

    def check(self, ip: str) -> str | None:
        """Record a request from ``ip``; return None to allow, or a reason to refuse.

        The global ceiling is evaluated first so that exhausting the day's model
        budget produces one consistent message regardless of who is asking.
        """
        now = self._clock()
        self._expire(self._global, now, DAY_SECONDS)
        if len(self._global) >= self._global_daily:
            return (
                "The demo's daily budget for live questions is used up. "
                "The recorded runs below are real captured traces and still work."
            )

        bucket = self._by_ip.get(ip)
        if bucket is None:
            if len(self._by_ip) >= MAX_TRACKED_IPS:
                self._prune(now)
            bucket = self._by_ip.setdefault(ip, deque())
        self._expire(bucket, now, self._per_ip_window)
        if len(bucket) >= self._per_ip:
            return (
                f"Rate limit: {self._per_ip} live questions per hour. "
                "The recorded runs below are unlimited."
            )

        bucket.append(now)
        self._global.append(now)
        return None

    @staticmethod
    def _expire(bucket: deque[float], now: float, window: float) -> None:
        """Drop timestamps that have fallen out of the trailing window."""
        cutoff = now - window
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

    def _prune(self, now: float) -> None:
        """Drop IP buckets whose entries have all expired."""
        for ip in list(self._by_ip):
            self._expire(self._by_ip[ip], now, self._per_ip_window)
            if not self._by_ip[ip]:
                del self._by_ip[ip]
