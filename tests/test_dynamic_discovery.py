"""Proves discovery is real: the client learns the server's tools at runtime
via MCP, hardcoding nothing (§9).

Two proofs:
  1. The client's discovered set equals what the server advertises.
  2. The stronger one — add a tool the client has never heard of and the
     *unmodified* client discovers and calls it (the MCP value proposition).
"""

from __future__ import annotations

import sys
from pathlib import Path

from mcp import StdioServerParameters

from conduit.host.client import MCPCodebaseClient, conduit_server_params
from conduit.server.app import build_server, load_config

FIXTURE_SERVER = Path(__file__).parent / "fixtures" / "augmented_server.py"


async def test_client_discovers_server_tools_without_hardcoding(sample_repo):
    """The client's runtime-discovered tool set equals what the server exposes."""
    # Source of truth: what the server actually advertises.
    expected = {t.name for t in build_server(load_config(str(sample_repo)))._tool_manager.list_tools()}

    # What the client learns over MCP — it hardcodes no tool names.
    async with MCPCodebaseClient(conduit_server_params(sample_repo)) as client:
        discovered = {t.name for t in await client.discover_tools()}

    assert discovered == expected
    assert discovered  # non-empty


async def test_client_uses_a_newly_added_tool_without_code_change(sample_repo):
    """Add a tool the client never heard of; the UNCHANGED client uses it."""
    # The production server's tool set — what the client normally sees.
    baseline = {t.name for t in build_server(load_config(str(sample_repo)))._tool_manager.list_tools()}

    # Spawn an AUGMENTED server that adds 'reverse_text'. Same client class as
    # production — zero client-side changes.
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(FIXTURE_SERVER), "--repo-root", str(sample_repo)],
    )
    async with MCPCodebaseClient(params) as client:
        discovered = {t.name for t in await client.discover_tools()}

        # The new tool appears purely via runtime discovery...
        assert "reverse_text" in discovered
        assert "reverse_text" not in baseline
        assert baseline <= discovered  # the standard tools are still there

        # ...and the unmodified client can CALL it.
        result = await client.call_tool("reverse_text", {"text": "conduit"})
        text = "".join(getattr(c, "text", "") for c in result.content)
        assert "tiudnoc" in text


# --- Resources are discovered and used too ----------------------------------


async def test_the_file_tree_resource_reaches_the_model(sample_repo):
    """The host reads repo://tree and puts it ahead of the question, so the
    model can go straight to a file. Deny-listed files are not in it."""
    from conduit.host.llm.adapter import FinalAnswer
    from conduit.host.llm.stub import StubAdapter
    from conduit.host.loop import run_turn

    stub = StubAdapter([FinalAnswer("ok")])
    async with MCPCodebaseClient(conduit_server_params(sample_repo)) as client:
        await run_turn(client, stub, "Where is charge defined?")

    first = stub.calls[0][0][0]["content"]
    assert "repo://tree" in first and "src/payments.py" in first
    assert first.endswith("Question: Where is charge defined?")
    assert ".env" not in first and "service.key" not in first


async def test_resources_can_be_left_out(sample_repo):
    from conduit.host.llm.adapter import FinalAnswer
    from conduit.host.llm.stub import StubAdapter
    from conduit.host.loop import run_turn

    stub = StubAdapter([FinalAnswer("ok")])
    async with MCPCodebaseClient(conduit_server_params(sample_repo)) as client:
        await run_turn(client, stub, "Where is charge defined?", attach_resources=False)
    assert stub.calls[0][0][0]["content"] == "Where is charge defined?"


async def test_a_resource_the_host_never_heard_of_is_attached(sample_repo):
    """Same property as for tools: a resource added only on the server reaches
    the model with no host change."""
    from conduit.host.llm.adapter import FinalAnswer
    from conduit.host.llm.stub import StubAdapter
    from conduit.host.loop import run_turn

    params = StdioServerParameters(
        command=sys.executable, args=[str(FIXTURE_SERVER), "--repo-root", str(sample_repo)]
    )
    stub = StubAdapter([FinalAnswer("ok")])
    async with MCPCodebaseClient(params) as client:
        await run_turn(client, stub, "What changed in 2.0?")

    first = stub.calls[0][0][0]["content"]
    assert "notes://release" in first
    assert "renamed charge() to bill()" in first
