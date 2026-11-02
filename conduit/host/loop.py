"""The host loop: discover → LLM selects tool → call → feed result → respond.

The loop depends only on the adapter interface (conduit.host.llm.adapter) and
the MCP client — never on a provider SDK directly (§10). It also records each
tool invocation so the CLI can make the MCP loop legible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from mcp.types import CallToolResult

from .client import MCPCodebaseClient
from .llm.adapter import FinalAnswer, LLMAdapter, ToolCall

# Bound the agent so a confused model can't loop forever.
MAX_STEPS = 8

# Warn the model once when this many calls remain, so it converges instead of
# opening a fresh line of enquiry it has no budget to finish.
LOW_BUDGET_AT = 2

_LOW_BUDGET_NUDGE = (
    "Only {n} tool calls remain. Stop exploring, spend them deliberately, and then "
    "answer from the evidence you have."
)

# Exhausting the budget used to end the turn with no answer at all, throwing away
# every piece of evidence already gathered. Ask once more instead, offering no
# tools, which leaves the model nothing to do but answer in text.
_FINAL_NUDGE = (
    "Your tool budget is spent and no further tool calls are available. Answer the "
    "question now from the evidence above. A refusal from the server is itself "
    "evidence — say what it establishes. If you still cannot be certain, state what "
    "you did determine and what remains unknown."
)

_NO_ANSWER = "(stopped after the maximum number of tool steps without a final answer)"


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


# Resources are context the server offers for the model to read, not actions to
# call. Each is attached to the question, capped so a large repo can't flood it.
MAX_RESOURCE_CHARS = 8000


async def _resource_context(client: MCPCodebaseClient) -> str:
    """Read every resource the server advertises, as context for the model.

    Nothing about a particular resource is hardcoded: whatever the server lists
    is attached, JSON is compacted, and a resource that fails to load is skipped
    rather than failing the turn.
    """
    try:
        resources = await client.discover_resources()
    except Exception:  # noqa: BLE001 — context is optional; the tools still work
        return ""
    blocks = []
    for r in resources:
        try:
            text = await client.read_resource(r.uri)
        except Exception:  # noqa: BLE001
            continue
        if r.mime_type == "application/json":
            try:
                text = json.dumps(json.loads(text), separators=(",", ":"))
            except ValueError:
                pass
        if len(text) > MAX_RESOURCE_CHARS:
            text = text[:MAX_RESOURCE_CHARS] + " …[truncated]"
        blocks.append(f"Resource {r.uri} ({r.name}):\n{text}")
    return "\n\n".join(blocks)


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
    on_step: Callable[[ToolInvocation], None] | None = None,
    attach_resources: bool = True,
) -> LoopResult:
    """Answer one user message by discovering and driving the server's tools.

    Discovers tool schemas at runtime, then loops: adapter selects a tool + args
    → client calls it over MCP → feed the result back → repeat until the adapter
    returns a final answer (or the step budget is exhausted).

    ``on_step`` is an optional synchronous callback invoked with each
    ToolInvocation as it completes, so a caller can render the loop live rather
    than waiting for the turn to finish. Omitting it leaves behaviour unchanged.

    ``attach_resources`` reads the server's advertised resources (here, the
    repo's file tree) and puts them ahead of the question, so the model can go
    straight to the right file instead of spending tool calls finding it.
    """
    discovered = await client.discover_tools()
    tool_schemas = [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in discovered
    ]

    context = await _resource_context(client) if attach_resources else ""
    first = f"{context}\n\nQuestion: {user_message}" if context else user_message
    messages: list[dict[str, Any]] = [{"role": "user", "content": first}]
    steps: list[ToolInvocation] = []

    for taken in range(max_steps):
        if max_steps - taken == LOW_BUDGET_AT and steps:
            messages.append(
                {"role": "user", "content": _LOW_BUDGET_NUDGE.format(n=LOW_BUDGET_AT)}
            )

        decision = await adapter.decide(messages, tool_schemas)

        if isinstance(decision, FinalAnswer):
            return LoopResult(answer=decision.text, steps=steps)

        assert isinstance(decision, ToolCall)
        result = await client.call_tool(decision.name, decision.arguments)
        text = _result_text(result)
        invocation = ToolInvocation(
            name=decision.name,
            arguments=decision.arguments,
            result_text=text,
            is_error=bool(result.isError),
        )
        steps.append(invocation)
        if on_step is not None:
            on_step(invocation)
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

    # Budget exhausted. Rather than discarding the evidence, make one last call
    # with no tools offered so the model has to commit to an answer.
    return LoopResult(
        answer=await _forced_answer(adapter, messages),
        steps=steps,
        hit_step_limit=True,
    )


async def _forced_answer(adapter: LLMAdapter, messages: list[dict[str, Any]]) -> str:
    """Ask for a text answer with no tools available, so the model must reply.

    A failure here must not lose the turn, so any provider error falls back to
    the old "no answer" text.
    """
    messages.append({"role": "user", "content": _FINAL_NUDGE})
    try:
        decision = await adapter.decide(messages, [])
    except Exception:  # noqa: BLE001 — a failed last gasp must not raise
        return _NO_ANSWER
    if isinstance(decision, FinalAnswer) and decision.text.strip():
        return decision.text.strip()
    return _NO_ANSWER
