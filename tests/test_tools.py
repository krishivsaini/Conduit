"""Each tool: valid input -> valid structured output; bad input -> actionable
error (never a raw stack trace).

Proves the tools are both useful (correct structured results) and safe to fail
(actionable messages the LLM can recover from).
"""

from __future__ import annotations

import pytest

from mcp.server.fastmcp.exceptions import ToolError

from conduit.server.app import build_server, load_config


@pytest.fixture
def server(sample_repo):
    return build_server(load_config(str(sample_repo)))


async def structured(server, name, args):
    _content, data = await server.call_tool(name, args)
    return data


# --- read_file --------------------------------------------------------------


async def test_read_file_valid_returns_structured(server):
    s = await structured(server, "read_file", {"path": "src/auth.py", "start_line": 1, "end_line": 20})
    assert s["path"] == "src/auth.py"
    assert s["total_lines"] > 20
    assert s["start_line"] == 1 and s["end_line"] == 20
    assert "def authenticate" in s["content"]  # defined at line 14


async def test_read_file_missing_is_actionable(server):
    with pytest.raises(ToolError) as exc:
        await server.call_tool("read_file", {"path": "src/nope.py"})
    msg = str(exc.value)
    assert "does not exist" in msg
    assert "Traceback" not in msg


async def test_read_file_traversal_is_actionable(server):
    with pytest.raises(ToolError) as exc:
        await server.call_tool("read_file", {"path": "../../etc/passwd"})
    assert "outside the repo root" in str(exc.value)


async def test_read_file_bad_range_is_actionable(server):
    with pytest.raises(ToolError) as exc:
        await server.call_tool("read_file", {"path": "src/utils.py", "start_line": 9999})
    assert "exceeds the file length" in str(exc.value)


# --- search_code ------------------------------------------------------------


async def test_search_returns_structured_matches(server):
    s = await structured(server, "search_code", {"query": "authenticate"})
    assert s["total_matches"] >= 1
    assert all({"path", "line", "snippet"} <= m.keys() for m in s["matches"])


async def test_search_pagination(server):
    p1 = await structured(server, "search_code", {"query": "def ", "limit": 1, "offset": 0})
    assert p1["count"] == 1
    if p1["total_matches"] > 1:
        assert p1["has_more"] is True
        assert p1["next_offset"] == 1


async def test_search_no_match_is_not_error(server):
    s = await structured(server, "search_code", {"query": "zzz_no_such_token_zzz"})
    assert s["total_matches"] == 0
    assert s["matches"] == []


# --- list_symbols -----------------------------------------------------------


async def test_list_symbols_by_path(server):
    s = await structured(server, "list_symbols", {"path": "src/payments.py"})
    names = {(x["name"], x["kind"]) for x in s["symbols"]}
    assert ("PaymentError", "class") in names
    assert ("charge", "function") in names


async def test_list_symbols_by_query(server):
    s = await structured(server, "list_symbols", {"query": "authenticate"})
    assert any(x["name"] == "authenticate" for x in s["symbols"])


async def test_list_symbols_denied_path_is_actionable(server):
    with pytest.raises(ToolError) as exc:
        await server.call_tool("list_symbols", {"path": ".env"})
    assert "deny-list" in str(exc.value)


# --- diff -------------------------------------------------------------------


async def test_diff_identical(server):
    s = await structured(server, "diff", {"a": "src/auth.py", "b": "src/auth.py"})
    assert s["identical"] is True
    assert s["added_lines"] == 0 and s["removed_lines"] == 0


async def test_diff_differs(server):
    s = await structured(server, "diff", {"a": "src/auth.py", "b": "src/utils.py"})
    assert s["identical"] is False
    assert s["added_lines"] > 0 and s["removed_lines"] > 0


async def test_diff_denied_file_is_actionable(server):
    with pytest.raises(ToolError) as exc:
        await server.call_tool("diff", {"a": "src/auth.py", "b": ".env"})
    assert "deny-list" in str(exc.value)


async def test_diff_missing_file_is_actionable(server):
    with pytest.raises(ToolError) as exc:
        await server.call_tool("diff", {"a": "src/auth.py", "b": "src/nope.py"})
    assert "does not exist" in str(exc.value)
