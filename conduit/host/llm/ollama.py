"""Ollama adapter (local, offline) — implements LLMAdapter via the ollama client.

Uses Ollama tool-calling with a tool-capable local model (e.g. mistral). This
is the zero-external-dependency path that proves provider-agnosticism.

Status: interface aligned on Day 9; implemented on Day 10.
"""

from __future__ import annotations

import os
from typing import Any

from .adapter import Decision, LLMAdapter, Message

DEFAULT_MODEL = "mistral"


class OllamaAdapter(LLMAdapter):
    """Drives tool-selection with a local Ollama model."""

    def __init__(self, model: str = DEFAULT_MODEL, host: str = "http://localhost:11434") -> None:
        self.model = model
        self.host = host

    @classmethod
    def from_env(cls) -> "OllamaAdapter":
        return cls(
            os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL),
            os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
        )

    async def decide(self, messages: list[Message], tool_schemas: list[dict[str, Any]]) -> Decision:
        raise NotImplementedError("Day 10: Ollama tool-calling adapter")
