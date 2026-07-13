"""Deterministic stub adapter — no network, for tests and offline loop checks.

Proves the host loop is provider-independent: the same loop that runs on Gemini
and Ollama also runs on this canned adapter (test_model_agnostic.py). It plays
back a scripted sequence of decisions, one per :meth:`decide` call.
"""

from __future__ import annotations

from typing import Any

from .adapter import Decision, FinalAnswer, LLMAdapter, Message


class StubAdapter(LLMAdapter):
    """Returns a scripted sequence of decisions for deterministic tests.

    Args:
        script: The decisions to return in order. When exhausted, returns a
            generic :class:`FinalAnswer`.
    """

    def __init__(self, script: list[Decision] | None = None) -> None:
        self._script = list(script or [])
        self._i = 0
        # Recorded for assertions: what the loop passed us each call.
        self.calls: list[tuple[list[Message], list[dict[str, Any]]]] = []

    async def decide(self, messages: list[Message], tool_schemas: list[dict[str, Any]]) -> Decision:
        self.calls.append((list(messages), list(tool_schemas)))
        if self._i < len(self._script):
            decision = self._script[self._i]
            self._i += 1
            return decision
        return FinalAnswer(text="(stub: no more scripted decisions)")
