"""The provider-agnostic LLM interface (§10).

Given a user message and the *discovered* tool schemas, an adapter returns
either a tool-selection (name + arguments) or a final answer. Every provider
implements this one interface; the host loop never imports a provider SDK.

This contract is defined on Day 1 (it's the seam the whole design hinges on);
the concrete adapters land on Days 9-10.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Union


@dataclass(frozen=True)
class ToolCall:
    """The LLM's decision to call a discovered tool."""

    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class FinalAnswer:
    """The LLM's final natural-language response."""

    text: str


Decision = Union[ToolCall, FinalAnswer]


class LLMAdapter(ABC):
    """One interface behind which any provider drives tool-selection."""

    @abstractmethod
    async def decide(
        self,
        user_message: str,
        tool_schemas: list[dict[str, Any]],
        history: list[dict[str, Any]] | None = None,
    ) -> Decision:
        """Return the next :class:`ToolCall` or a :class:`FinalAnswer`.

        Args:
            user_message: The user's request.
            tool_schemas: Tool schemas discovered from the server at runtime.
            history: Prior tool calls + results in this turn, if any.
        """
        ...


def get_adapter(provider: str) -> LLMAdapter:
    """Factory: build the adapter selected by ``LLM_PROVIDER``.

    Status: scaffolded on Day 1; wired to real adapters on Days 9-10.
    """
    raise NotImplementedError("Days 9-10: gemini / ollama / stub selection")
