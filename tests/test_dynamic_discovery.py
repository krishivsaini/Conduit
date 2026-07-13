"""Proves discovery is real: the client learns the server's tools at runtime
via MCP, hardcoding nothing (§9).

The basic proof (client's discovered set == what the server advertises) is here.
The stronger proof — the client uses a newly added/renamed tool with NO client
change — lands on Day 11.
"""

from __future__ import annotations

import pytest

from conduit.host.client import MCPCodebaseClient, conduit_server_params
from conduit.server.app import build_server, load_config


async def test_client_discovers_server_tools_without_hardcoding(sample_repo):
    """The client's runtime-discovered tool set equals what the server exposes."""
    # Source of truth: what the server actually advertises.
    expected = {t.name for t in build_server(load_config(str(sample_repo)))._tool_manager.list_tools()}

    # What the client learns over MCP — it hardcodes no tool names.
    async with MCPCodebaseClient(conduit_server_params(sample_repo)) as client:
        discovered = {t.name for t in await client.discover_tools()}

    assert discovered == expected
    assert discovered  # non-empty


@pytest.mark.skip(reason="Day 11: prove client uses a newly added/renamed tool with no client change")
def test_client_uses_a_newly_added_tool_without_code_change():
    ...
