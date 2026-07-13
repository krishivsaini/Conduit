"""The host loop: discover → LLM selects tool → call → feed result → respond.

The loop depends only on the adapter interface (conduit.host.llm.adapter) and
the MCP client — never on a provider SDK directly (§10). It also records each
tool invocation so the CLI can make the MCP loop legible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mcp.types import CallToolResult

from .client import MCPCodebaseClient
from .llm.adapter import FinalAnswer, LLMAdapter, ToolCall

# Bound the agent so a confused model can't loop forever.
MAX_STEPS = 8


@dataclass
class ToolInvocation:
    """One tool call the loop made on the model's behalf."""

    name: str
    arguments: dict[str, Any]
    result_text: str
    is_error: bool


@dataclass
class LoopResult:
    """The outcome of a turn: the final answer plus the tool calls made."""

    answer: str
    steps: list[ToolInvocation] = field(default_factory=list)
    hit_step_limit: bool = False


def _result_text(result: CallToolResult) -> str:
    """Flatten a tool result's text content (what we feed back to the model)."""
    parts = [getattr(c, "text", None) for c in result.content]
    return "\n".join(p for p in parts if p)


async def run_turn(
    client: MCPCodebaseClient,
    adapter: LLMAdapter,
    user_message: str,
    *,
    max_steps: int = MAX_STEPS,
) -> LoopResult:
    """Answer one user message by discovering and driving the server's tools.

    Discovers tool schemas at runtime, then loops: adapter selects a tool + args
    → client calls it over MCP → feed the result back → repeat until the adapter
    returns a final answer (or the step budget is exhausted).
    """
    discovered = await client.discover_tools()
    tool_schemas = [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in discovered
    ]

    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]
    steps: list[ToolInvocation] = []

    for _ in range(max_steps):
        decision = await adapter.decide(messages, tool_schemas)

        if isinstance(decision, FinalAnswer):
            return LoopResult(answer=decision.text, steps=steps)

        assert isinstance(decision, ToolCall)
        result = await client.call_tool(decision.name, decision.arguments)
        text = _result_text(result)
        steps.append(
            ToolInvocation(
                name=decision.name,
                arguments=decision.arguments,
                result_text=text,
                is_error=bool(result.isError),
            )
        )
        messages.append(
            {
                "role": "tool_call",
                "name": decision.name,
                "arguments": decision.arguments,
                "meta": decision.provider_meta,
            }
        )
        messages.append(
            {"role": "tool_result", "name": decision.name, "content": text, "is_error": bool(result.isError)}
        )

    return LoopResult(
        answer="(stopped after the maximum number of tool steps without a final answer)",
        steps=steps,
        hit_step_limit=True,
    )
