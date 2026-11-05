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
import re
from typing import Any

from groq import AsyncGroq

from .adapter import SYSTEM_PROMPT, Decision, FinalAnswer, LLMAdapter, Message, ToolCall

DEFAULT_MODEL = "openai/gpt-oss-120b"

# Groq validates every tool call against its schema and rejects the whole
# response (HTTP 400, code tool_use_failed) when one doesn't match, e.g. a
# search_code call with an empty query. Seen in a real demo run.
TOOL_CALL_RETRIES = 2

_SCHEMA_ERROR = re.compile(r"parameters for tool (\w+) did not match schema: errors: \[(.*?)\]", re.S)


def rejected_tool_call(error: str) -> str | None:
    """What was wrong, if ``error`` is Groq refusing an invalid tool call; else None."""
    lowered = error.lower()
    if "tool call validation failed" not in lowered and "tool_use_failed" not in lowered:
        return None
    match = _SCHEMA_ERROR.search(error)
    if match:
        tool, details = match.groups()
        return f"its arguments for {tool} didn't match the schema ({details.strip('` ').replace('`', '')})"
    return "it didn't match the tool's schema"


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
        api_messages = _to_messages(messages, self.system_prompt)
        for attempt in range(TOOL_CALL_RETRIES + 1):
            try:
                response = await self._client.chat.completions.create(
                    model=self.model, messages=api_messages, **kwargs
                )
                break
            except Exception as exc:  # noqa: BLE001 — only a rejected tool call is retried
                problem = rejected_tool_call(str(exc))
                if problem is None or attempt == TOOL_CALL_RETRIES:
                    raise
                # Groq checked the model's tool call against the schema and refused
                # the whole response. Say what was wrong, as the server would have,
                # and let the model try again. Not added to the loop's history.
                api_messages = api_messages + [{
                    "role": "user",
                    "content": f"Your last tool call was rejected before it ran: {problem}. "
                               "Call the tool again with arguments that match its schema, or answer.",
                }]
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
