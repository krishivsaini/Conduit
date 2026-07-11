"""The host loop: discover → LLM selects tool → call → feed result → respond.

The loop depends only on the adapter interface (conduit.host.llm.adapter) and
the MCP client — never on a provider SDK directly (§10). This is what keeps the
project provider-agnostic.

Status: scaffolded on Day 1; implemented on Day 9.
"""

from __future__ import annotations

from .client import MCPCodebaseClient
from .llm.adapter import LLMAdapter


async def run_turn(client: MCPCodebaseClient, adapter: LLMAdapter, user_message: str) -> str:
    """Answer one user message by discovering and driving the server's tools.

    Steps: discover tool schemas → adapter selects a tool + args → client calls
    it over MCP → feed the result back → adapter composes a final answer
    (iterating with more tool calls as needed).
    """
    raise NotImplementedError("Day 9: discover→select→call→respond loop")
