"""Use a free provider first, and a paid one when the free one is rate limited.

The ``auto`` provider (the default) is Gemini's free tier backed by Groq. When
Gemini answers with a rate limit, the same call goes to Groq, so the question
still gets answered. The primary is tried again after a cooldown: a minute for a
per-minute limit, an hour for a daily one (Gemini's daily quota resets at
midnight Pacific, and checking hourly costs one request).

Two rules keep this safe:
  - Only rate limits fall back. Any other error is raised, so a real bug or bad
    request is never hidden behind a provider switch.
  - A question that has switched finishes on the fallback. Providers can't
    continue each other's tool calls reliably (Gemini 3 needs the thought
    signatures it issued itself), so switching back waits for the next question.

The adapter is shared: the web demo runs several questions through one at once.
So which question is on the fallback is not stored in the adapter, where one
question could overwrite another's. It is read from the question's own history:
every tool call the fallback makes is marked (in ``provider_meta``, which the
loop carries back verbatim), and a history holding a marked call stays on the
fallback.
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable
from typing import Any

from .adapter import Decision, LLMAdapter, Message, ToolCall
from .pacing import is_per_day_limit, is_rate_limit

PER_MINUTE_COOLDOWN = 60.0
PER_DAY_COOLDOWN = 3600.0

# The provider_meta key that marks a tool call as made by the fallback.
FALLBACK_MARK = "conduit_fallback"


def _on_fallback(messages: list[Message]) -> bool:
    """True if the fallback made any of this question's tool calls so far."""
    return any(
        m.get("role") == "tool_call" and (m.get("meta") or {}).get(FALLBACK_MARK)
        for m in messages
    )


class FallbackAdapter(LLMAdapter):
    """Delegates to ``primary``, or to ``fallback`` while ``primary`` is rate limited."""

    def __init__(
        self,
        primary: LLMAdapter,
        fallback: LLMAdapter,
        *,
        clock: Callable[[], float] = time.monotonic,
        on_switch: Callable[[str], None] | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self._clock = clock
        self._on_switch = on_switch or (lambda reason: None)
        self._primary_after = 0.0  # don't try the primary before this time
        self.active = primary

    @property
    def model(self) -> str | None:
        return getattr(self.active, "model", None)

    @property
    def system_prompt(self) -> str:  # type: ignore[override]
        return self.primary.system_prompt

    @system_prompt.setter
    def system_prompt(self, value: str) -> None:
        self.primary.system_prompt = value
        self.fallback.system_prompt = value

    async def decide(self, messages: list[Message], tool_schemas: list[dict[str, Any]]) -> Decision:
        if not _on_fallback(messages) and self._clock() >= self._primary_after:
            try:
                decision = await self.primary.decide(messages, tool_schemas)
                self.active = self.primary
                return decision
            except Exception as exc:  # noqa: BLE001 — only rate limits fall back
                text = str(exc)
                if not is_rate_limit(text):
                    raise
                daily = is_per_day_limit(text)
                self._primary_after = self._clock() + (PER_DAY_COOLDOWN if daily else PER_MINUTE_COOLDOWN)
                self._on_switch("daily quota used up" if daily else "rate limited")
        self.active = self.fallback
        decision = await self.fallback.decide(messages, tool_schemas)
        if isinstance(decision, ToolCall):
            meta = {**(decision.provider_meta or {}), FALLBACK_MARK: True}
            decision = dataclasses.replace(decision, provider_meta=meta)
        return decision
