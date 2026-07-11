"""Deterministic stub adapter — no network, for tests.

Proves the host loop is provider-independent: the same loop that runs on Gemini
and Ollama also runs on this canned adapter (test_model_agnostic.py).

Status: scaffolded on Day 1; implemented on Day 10.
"""

from __future__ import annotations

from typing import Any

from .adapter import Decision, LLMAdapter


class StubAdapter(LLMAdapter):
    """Returns a scripted sequence of decisions for deterministic tests."""

    def __init__(self, script: list[Decision] | None = None) -> None:
        self._script = list(script or [])

    async def decide(
        self,
        user_message: str,
        tool_schemas: list[dict[str, Any]],
        history: list[dict[str, Any]] | None = None,
    ) -> Decision:
        raise NotImplementedError("Day 10: scripted deterministic decisions")
