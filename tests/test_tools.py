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


# --- Arguments a tool doesn't take ------------------------------------------
# FastMCP ignores unknown arguments. A real model called
# read_file(line_start=1, line_end=3) and silently got the whole file; it also
# called search_code(path=...) expecting a scoped search and got the whole repo.


@pytest.mark.parametrize("tool, args, hint", [
    ("read_file", {"path": "src/auth.py", "line_start": 1, "line_end": 3},
     ["'line_start' (did you mean 'start_line'?)", "'line_end' (did you mean 'end_line'?)"]),
    ("search_code", {"query": "charge", "file": "src/payments.py"}, ["'file'", "query, limit, offset"]),
    ("list_symbols", {"pth": "src/auth.py"}, ["'pth' (did you mean 'path'?)"]),
    ("diff", {"a": "src/auth.py", "b": "src/utils.py", "context": 3}, ["'context'", "Its arguments are: a, b"]),
])
async def test_an_unknown_argument_is_refused_with_the_right_names(server, tool, args, hint):
    with pytest.raises(ToolError) as exc:
        await server.call_tool(tool, args)
    msg = str(exc.value)
    assert all(h in msg for h in hint), msg
    assert "Traceback" not in msg


async def test_the_refusal_reaches_a_real_client_as_a_tool_error(sample_repo):
    from conduit.host.client import MCPCodebaseClient, conduit_server_params

    async with MCPCodebaseClient(conduit_server_params(sample_repo)) as client:
        bad = await client.call_tool("read_file", {"path": "src/auth.py", "line_start": 1})
        good = await client.call_tool("read_file", {"path": "src/auth.py", "start_line": 1, "end_line": 3})
    assert bad.isError and "did you mean 'start_line'" in bad.content[0].text
    assert not good.isError and '"end_line": 3' in good.content[0].text


async def test_the_documented_arguments_still_work(server):
    s = await structured(server, "read_file", {"path": "src/auth.py", "start_line": 1, "end_line": 3})
    assert (s["start_line"], s["end_line"]) == (1, 3)


# --- Narrowing search and symbols to a file or directory ---------------------
# Real runs asked for this 26 times (search_code(path=...)), and list_symbols
# given a directory used to answer "0 symbols" instead of listing them.


async def test_search_can_be_narrowed_to_a_file_or_directory(server):
    everywhere = await structured(server, "search_code", {"query": "def "})
    in_file = await structured(server, "search_code", {"query": "def ", "path": "src/payments.py"})
    in_dir = await structured(server, "search_code", {"query": "def ", "path": "src"})
    assert {m["path"] for m in in_file["matches"]} == {"src/payments.py"}
    assert in_file["total_matches"] < in_dir["total_matches"] <= everywhere["total_matches"]
    root = await structured(server, "search_code", {"query": "def ", "path": "."})
    assert root["total_matches"] == everywhere["total_matches"]


async def test_list_symbols_takes_a_directory(server):
    s = await structured(server, "list_symbols", {"path": "src"})
    assert {"authenticate", "charge", "redact"} <= {x["name"] for x in s["symbols"]}
    assert all(x["path"].startswith("src/") for x in s["symbols"])


async def test_a_prefix_is_not_a_directory(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("def inside(): pass\n")
    (tmp_path / "src_old.py").write_text("def outside(): pass\n")
    server = build_server(load_config(str(tmp_path)))
    s = await structured(server, "list_symbols", {"path": "src"})
    assert [x["name"] for x in s["symbols"]] == ["inside"]


@pytest.mark.parametrize("path, refusal", [
    ("../", "outside the repo root"),
    (".env", "deny-list"),
    ("src/nope", "does not exist"),
])
async def test_a_scope_goes_through_the_same_boundaries(server, path, refusal):
    for tool, args in [("search_code", {"query": "x", "path": path}), ("list_symbols", {"path": path})]:
        with pytest.raises(ToolError, match=refusal):
            await server.call_tool(tool, args)


async def test_a_null_for_an_unknown_argument_is_ignored(server):
    s = await structured(server, "search_code", {"query": "charge", "file": None})
    assert s["total_matches"] > 0
