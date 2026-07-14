"""Ollama adapter (local, offline) — implements LLMAdapter via the ollama client.

Uses Ollama tool-calling with a tool-capable local model (e.g. mistral). This
is the zero-external-dependency path that proves provider-agnosticism: the same
host loop that runs on Gemini runs here with no network and no API key.
"""

from __future__ import annotations

import os
from typing import Any

from ollama import AsyncClient

from .adapter import Decision, FinalAnswer, LLMAdapter, Message, SYSTEM_PROMPT, ToolCall

DEFAULT_MODEL = "mistral"
DEFAULT_HOST = "http://localhost:11434"


class OllamaAdapter(LLMAdapter):
    """Drives tool-selection with a local Ollama model."""

    def __init__(self, model: str = DEFAULT_MODEL, host: str = DEFAULT_HOST) -> None:
        self.model = model
        self.host = host
        self._client = AsyncClient(host=host)

    @classmethod
    def from_env(cls) -> "OllamaAdapter":
        return cls(
            os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL),
            os.environ.get("OLLAMA_HOST", DEFAULT_HOST),
        )

    async def decide(self, messages: list[Message], tool_schemas: list[dict[str, Any]]) -> Decision:
        response = await self._client.chat(
            model=self.model,
            messages=_to_messages(messages),
            tools=_to_tools(tool_schemas),
            options={"temperature": 0},  # deterministic tool selection
        )
        message = response.message
        calls = getattr(message, "tool_calls", None)
        if calls:
            fn = calls[0].function
            return ToolCall(name=fn.name, arguments=dict(fn.arguments or {}))
        return FinalAnswer(text=(message.content or "").strip())


def _to_tools(tool_schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn discovered tool schemas into Ollama (OpenAI-style) tool specs."""
    return [
        {
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s.get("description") or "",
                "parameters": s["input_schema"],
            },
        }
        for s in tool_schemas
    ]


def _to_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Translate neutral messages into Ollama chat messages (with a system prompt)."""
    out: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in messages:
        role = m["role"]
        if role == "user":
            out.append({"role": "user", "content": m["content"]})
        elif role == "tool_call":
            out.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"function": {"name": m["name"], "arguments": m["arguments"]}}],
                }
            )
        elif role == "tool_result":
            out.append({"role": "tool", "content": m["content"], "tool_name": m["name"]})
    return out
