"""Gemini adapter (free tier, default) — implements LLMAdapter via google-genai.

Model: gemini-3.5-flash (verified current on Day 1). Uses Gemini function
calling to map discovered tool schemas to tool-selections.

Status: scaffolded on Day 1; implemented on Day 9.
"""

from __future__ import annotations

from typing import Any

from .adapter import Decision, LLMAdapter


class GeminiAdapter(LLMAdapter):
    """Drives tool-selection with Gemini function calling."""

    def __init__(self, api_key: str, model: str = "gemini-3.5-flash") -> None:
        self.model = model
        self._api_key = api_key

    async def decide(
        self,
        user_message: str,
        tool_schemas: list[dict[str, Any]],
        history: list[dict[str, Any]] | None = None,
    ) -> Decision:
        raise NotImplementedError("Day 9: Gemini function-calling adapter")
