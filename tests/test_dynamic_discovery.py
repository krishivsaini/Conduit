"""Proves discovery is real: the client uses a newly added/renamed server tool
with NO client-side change, because it discovered it at runtime (§9).

Implemented on Day 11.
"""

import pytest

pytestmark = pytest.mark.skip(reason="Day 11: implement dynamic-discovery proof")


def test_client_discovers_server_tools_without_hardcoding():
    """The client's tool list equals what the server advertised."""
    ...


def test_client_uses_a_newly_added_tool_without_code_change():
    """Add/rename a tool on the server; the client uses it unmodified."""
    ...
