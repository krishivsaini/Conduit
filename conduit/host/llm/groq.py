"""Groq adapter — implements LLMAdapter via the groq client (OpenAI-style API).

Groq serves open-weight models (default ``openai/gpt-oss-120b``) behind the
OpenAI chat-completions format, with paid rate limits far above the Gemini free
tier, which makes it the practical provider for full eval runs.

OpenAI-style tool calling pairs every tool result with the id of the call that
produced it. The neutral message list doesn't carry ids, so the id the model
issued travels in ``ToolCall.provider_meta`` (which the loop passes back
verbatim), and a result is matched to the tool call just before it. A call
without an id, such as one replayed from a recording, gets a stable synthetic one.
"""

from __future__ import annotations

import json
import os
from typing import Any

from groq import AsyncGroq

from .adapter import SYSTEM_PROMPT, Decision, FinalAnswer, LLMAdapter, Message, ToolCall

DEFAULT_MODEL = "openai/gpt-oss-120b"


class GroqAdapter(LLMAdapter):
    """Drives tool-selection with a model hosted on Groq."""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        self.model = model
        self._client = AsyncGroq(api_key=api_key)

    @classmethod
    def from_env(cls) -> "GroqAdapter":
        key = os.environ.get("GROQ_API_KEY")
        if not key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Create a key at https://console.groq.com/keys "
                "and add it to .env."
            )
        return cls(key, os.environ.get("GROQ_MODEL", DEFAULT_MODEL))

    async def decide(self, messages: list[Message], tool_schemas: list[dict[str, Any]]) -> Decision:
        kwargs: dict[str, Any] = {}
        if tool_schemas:  # no tools => the model must answer in text
            kwargs["tools"] = _to_tools(tool_schemas)
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=_to_messages(messages, self.system_prompt),
            **kwargs,
        )
        message = response.choices[0].message
        if message.tool_calls:
            call = message.tool_calls[0]  # the loop runs one tool per step
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            return ToolCall(
                name=_known_name(call.function.name, tool_schemas),
                arguments=arguments if isinstance(arguments, dict) else {},
                provider_meta={"tool_call_id": call.id},
            )
        return FinalAnswer(text=(message.content or "").strip())


def _known_name(name: str, tool_schemas: list[dict[str, Any]]) -> str:
    """Undo a namespace the model invented: gpt-oss models sometimes call
    ``repo_browser.list_symbols`` for a tool named ``list_symbols``. Mapped only
    when the suffix names exactly one discovered tool; otherwise the name is
    passed through and the server reports it as unknown."""
    names = {s["name"] for s in tool_schemas}
    if name in names or "." not in name:
        return name
    suffix = name.rsplit(".", 1)[1]
    return suffix if suffix in names else name


def _to_tools(tool_schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn discovered tool schemas into OpenAI-style function tools."""
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


def _to_messages(messages: list[Message], system_prompt: str = SYSTEM_PROMPT) -> list[dict[str, Any]]:
    """Translate neutral messages into OpenAI-style chat messages."""
    out: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    call_id = None
    for n, m in enumerate(messages):
        role = m["role"]
        if role == "user":
            out.append({"role": "user", "content": m["content"]})
        elif role == "tool_call":
            call_id = (m.get("meta") or {}).get("tool_call_id") or f"call_{n}"
            out.append({
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": call_id,
                    "type": "function",
                    "function": {"name": m["name"], "arguments": json.dumps(m["arguments"])},
                }],
            })
        elif role == "tool_result":
            out.append({"role": "tool", "tool_call_id": call_id or f"call_{n}", "content": m["content"]})
    return out
