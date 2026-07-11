"""Ollama adapter (local, offline) — implements LLMAdapter via the ollama client.

Uses Ollama tool-calling with a tool-capable local model (e.g. mistral). This
is the zero-external-dependency path that proves provider-agnosticism.

Status: scaffolded on Day 1; implemented on Day 10.
"""

from __future__ import annotations

from typing import Any

from .adapter import Decision, LLMAdapter


class OllamaAdapter(LLMAdapter):
    """Drives tool-selection with a local Ollama model."""

    def __init__(self, model: str = "mistral", host: str = "http://localhost:11434") -> None:
        self.model = model
        self.host = host

    async def decide(
        self,
        user_message: str,
        tool_schemas: list[dict[str, Any]],
        history: list[dict[str, Any]] | None = None,
    ) -> Decision:
        raise NotImplementedError("Day 10: Ollama tool-calling adapter")
