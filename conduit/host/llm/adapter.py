"""The provider-agnostic LLM interface (§10).

Given the running conversation and the *discovered* tool schemas, an adapter
returns either a tool-selection (name + arguments) or a final answer. Every
provider implements this one interface; the host loop never imports a provider
SDK. Swapping providers changes one env var (``LLM_PROVIDER``), no loop code.

The loop maintains a provider-neutral message list; each adapter translates it
into its own SDK's format. Message shapes:

    {"role": "user",        "content": str}
    {"role": "tool_call",   "name": str, "arguments": dict}   # the assistant called a tool
    {"role": "tool_result", "name": str, "content": str, "is_error": bool}
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Union

Message = dict[str, Any]

# The system instruction shared by every provider — the LLM's only job is to
# drive the codebase tools to answer the question.
SYSTEM_PROMPT = (
    "You are Conduit, an assistant that answers questions about a code repository "
    "exposed to you over the Model Context Protocol. You have read-only tools: "
    "search_code (lexical search), read_file (read a file, optionally a line range), "
    "list_symbols (functions/classes/methods), and diff (compare two files).\n"
    "\n"
    "Answer from tool evidence rather than memory, and keep the number of calls "
    "small. Your tool budget is limited; an answer supported by two calls beats an "
    "unfinished search.\n"
    "\n"
    "- Locate first (search_code or list_symbols), then read the file that matters.\n"
    "- A refused call is evidence, not a failure. The server enforces security "
    "boundaries, so if it refuses a path, that refusal already answers whether the "
    "path is readable. Report what it establishes instead of retrying.\n"
    "- Files excluded by those boundaries are also absent from the search index, so "
    "they never appear in search results. Absence from search is not proof a file "
    "does not exist. To find out whether a particular file can be read, call "
    "read_file on it directly and observe the outcome — that is the only reliable "
    "test, and it is not a guess.\n"
    "- If a search returns nothing useful, change tactic. Do not re-run the same "
    "idea with different wording.\n"
    "\n"
    "When you have enough evidence, give a concise final answer citing file paths "
    "and line numbers. If the question demands a particular form — True or False, a "
    "number, a single word — lead with exactly that."
)


@dataclass(frozen=True)
class ToolCall:
    """The LLM's decision to call a discovered tool.

    ``provider_meta`` is an opaque, provider-specific blob the adapter may attach
    (e.g. Gemini's ``thought_signature``) and read back on the next turn. The
    loop propagates it verbatim into the ``tool_call`` message and never
    interprets it, so the abstraction stays model-agnostic.
    """

    name: str
    arguments: dict[str, Any]
    provider_meta: dict[str, Any] | None = None


@dataclass(frozen=True)
class FinalAnswer:
    """The LLM's final natural-language response."""

    text: str


Decision = Union[ToolCall, FinalAnswer]


class LLMAdapter(ABC):
    """One interface behind which any provider drives tool-selection."""

    @abstractmethod
    async def decide(self, messages: list[Message], tool_schemas: list[dict[str, Any]]) -> Decision:
        """Return the next :class:`ToolCall` or a :class:`FinalAnswer`.

        Args:
            messages: The provider-neutral conversation so far (see module docs).
            tool_schemas: Tool schemas discovered from the server at runtime,
                each ``{"name", "description", "input_schema"}``.
        """
        ...


def get_adapter(provider: str | None = None) -> LLMAdapter:
    """Build the adapter selected by ``provider`` or ``$LLM_PROVIDER``.

    The loop calls this and nothing else about a provider; adding a provider is
    a new branch here plus a new module, with no change to the loop.
    """
    provider = (provider or os.environ.get("LLM_PROVIDER") or "gemini").lower()
    if provider == "gemini":
        from .gemini import GeminiAdapter

        return GeminiAdapter.from_env()
    if provider == "ollama":
        from .ollama import OllamaAdapter

        return OllamaAdapter.from_env()
    raise ValueError(
        f"unknown LLM_PROVIDER '{provider}'. Use 'gemini' or 'ollama' "
        f"(the 'stub' adapter is constructed directly in tests)."
    )
