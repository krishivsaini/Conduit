"""Living with a requests-per-minute limit (the Gemini free tier allows 5).

One question makes several model calls back to back, one per tool step, so a
multi-step question can trip a per-minute limit partway through even when the
day's quota is far from spent. :class:`Paced` wraps any adapter: it can space
calls out, and it waits out a per-minute 429 for the delay the provider asks
for. A per-day limit is passed straight through, because waiting won't fix it.

Used by the CLI (wait-and-retry only) and by eval/run_eval.py (paced as well).
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .adapter import Decision, LLMAdapter, Message


def is_rate_limit(err: str) -> bool:
    return any(t in err.lower() for t in ("429", "resource_exhausted", "quota", "rate limit"))


def _compact(err: str) -> str:
    return re.sub(r"[\s_-]", "", err.lower())


def is_per_day_limit(err: str) -> bool:
    return is_rate_limit(err) and "perday" in _compact(err)


def per_minute_wait(err: str) -> float | None:
    """Seconds to wait if ``err`` is a per-minute rate limit, else None.

    Providers name the limit they hit: Gemini's quotaId
    (``...PerMinutePerProject...``), Groq's message ("requests per minute (RPM)
    ... Please try again in 2.5s"). A per-minute limit clears by itself, so it
    means wait and retry; a per-day one means stop.
    """
    if not is_rate_limit(err) or "perminute" not in _compact(err) or is_per_day_limit(err):
        return None
    gemini = re.search(r"retryDelay'?\"?:\s*'?\"?(\d+(?:\.\d+)?)s", err)
    groq = re.search(r"try again in (?:(\d+)m)?(\d+(?:\.\d+)?)(ms|s)", err)
    if gemini:
        return float(gemini.group(1)) + 2
    if groq:
        minutes, amount, unit = groq.groups()
        seconds = float(amount) / (1000 if unit == "ms" else 1) + 60 * int(minutes or 0)
        return seconds + 1
    return 30.0


class Paced(LLMAdapter):
    """Wraps an adapter: spaces calls to ``rpm`` (0 = no spacing) and waits out
    per-minute 429s, up to ``retries`` times. Per-day limits are re-raised."""

    def __init__(
        self,
        inner: LLMAdapter,
        rpm: float = 0,
        retries: int = 6,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        clock: Callable[[], float] = time.monotonic,
        on_wait: Callable[[float], None] | None = None,
    ) -> None:
        self.inner = inner
        self.model = getattr(inner, "model", None)
        self.interval = 60.0 / rpm if rpm > 0 else 0.0
        self.retries = retries
        self._sleep = sleep or (lambda s: asyncio.sleep(s))  # looked up per call
        self._clock = clock
        self._on_wait = on_wait or (lambda s: print(f"      (per-minute limit; waiting {s:.0f}s)"))
        self._last: float | None = None

    async def decide(self, messages: list[Message], tool_schemas: list[dict[str, Any]]) -> Decision:
        for attempt in range(self.retries + 1):
            if self._last is not None:
                wait = self.interval - (self._clock() - self._last)
                if wait > 0:
                    await self._sleep(wait)
            self._last = self._clock()
            try:
                return await self.inner.decide(messages, tool_schemas)
            except Exception as exc:  # noqa: BLE001 — provider errors
                wait = per_minute_wait(str(exc))
                if wait is None or attempt == self.retries:
                    raise
                self._on_wait(wait)
                await self._sleep(wait)
        raise AssertionError("unreachable")
