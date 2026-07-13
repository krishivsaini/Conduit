"""Gemini adapter (free tier, default) — implements LLMAdapter via google-genai.

Model: gemini-3.5-flash (verified current on Day 1). Declares the discovered
tool schemas as Gemini function declarations (passing our Pydantic JSON-Schema
straight through ``parameters_json_schema``) and reads back the model's
function calls. Automatic function calling is disabled — *we* drive the loop.

The google-genai client is synchronous, so the blocking call runs in a thread.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from google import genai
from google.genai import types

from .adapter import Decision, FinalAnswer, LLMAdapter, Message, SYSTEM_PROMPT, ToolCall

DEFAULT_MODEL = "gemini-3.5-flash"


class GeminiAdapter(LLMAdapter):
    """Drives tool-selection with Gemini function calling."""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        self.model = model
        self._client = genai.Client(api_key=api_key)

    @classmethod
    def from_env(cls) -> "GeminiAdapter":
        key = os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise RuntimeError(
                "GOOGLE_API_KEY is not set. Add it to your environment or .env, "
                "or set LLM_PROVIDER=ollama to run fully locally."
            )
        return cls(key, os.environ.get("GEMINI_MODEL", DEFAULT_MODEL))

    async def decide(self, messages: list[Message], tool_schemas: list[dict[str, Any]]) -> Decision:
        contents = _to_contents(messages)
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[_to_tool(tool_schemas)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        response = await asyncio.to_thread(
            self._client.models.generate_content,
            model=self.model,
            contents=contents,
            config=config,
        )

        for part in _parts(response):
            call = getattr(part, "function_call", None)
            if call is not None:
                # Gemini 3.x requires the model's function-call turn to be
                # echoed back with its thought_signature on the next request.
                meta = {"thought_signature": getattr(part, "thought_signature", None)}
                return ToolCall(name=call.name, arguments=dict(call.args or {}), provider_meta=meta)
        return FinalAnswer(text=(response.text or "").strip())


def _to_tool(tool_schemas: list[dict[str, Any]]) -> types.Tool:
    """Turn discovered tool schemas into a Gemini Tool of function declarations."""
    declarations = [
        types.FunctionDeclaration(
            name=s["name"],
            description=s.get("description") or "",
            parameters_json_schema=s["input_schema"],
        )
        for s in tool_schemas
    ]
    return types.Tool(function_declarations=declarations)


def _to_contents(messages: list[Message]) -> list[types.Content]:
    """Translate neutral messages into Gemini Content turns."""
    contents: list[types.Content] = []
    for m in messages:
        role = m["role"]
        if role == "user":
            contents.append(types.Content(role="user", parts=[types.Part(text=m["content"])]))
        elif role == "tool_call":
            part = types.Part(function_call=types.FunctionCall(name=m["name"], args=m["arguments"]))
            signature = (m.get("meta") or {}).get("thought_signature")
            if signature is not None:
                part.thought_signature = signature
            contents.append(types.Content(role="model", parts=[part]))
        elif role == "tool_result":
            contents.append(
                types.Content(
                    role="user",
                    parts=[types.Part.from_function_response(name=m["name"], response={"result": m["content"]})],
                )
            )
    return contents


def _parts(response: Any) -> list[Any]:
    """Safely pull the parts out of a generate_content response."""
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return []
    content = getattr(candidates[0], "content", None)
    return list(getattr(content, "parts", None) or [])
