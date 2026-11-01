"""Proves the deny-list: secrets are never read, searched, or listed (§8.2).

Day 4 covers the matcher and read_file enforcement. The search/tree assertions
turn on when those tools land (Days 5-6) and re-use the same deny-list.
"""

from __future__ import annotations

import pytest

from mcp.server.fastmcp.exceptions import ToolError

from conduit.server.app import build_server, load_config
from conduit.server.security.denylist import is_denied


# --- The matcher: secrets are denied ---------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        ".env.production",
        "service.key",
        "src/service.key",
        "config/.env",
        "certs/app.pem",
        "keys/id_rsa",
        "deploy/id_ed25519",
        ".git/config",
        "nested/.git/HEAD",
        "CREDENTIALS",  # case-insensitive
        ".ENV",  # case-insensitive
    ],
)
def test_secrets_are_denied(path):
    assert is_denied(path) is True


# --- The matcher: ordinary source is NOT denied (no over-blocking) ---------


@pytest.mark.parametrize(
    "path",
    [
        "src/auth.py",
        "src/payments.py",
        "README.md",
        "env.py",  # not .env
        ".environment",  # not .env / .env.*
        "src/keys.py",  # not *.key
        "notes/credentials.md",  # not exactly 'credentials'
    ],
)
def test_ordinary_files_are_allowed(path):
    assert is_denied(path) is False


# --- Enforcement: read_file refuses denied files ---------------------------


async def test_read_file_refuses_env_file(sample_repo):
    mcp = build_server(load_config(str(sample_repo)))
    with pytest.raises(ToolError) as exc:
        await mcp.call_tool("read_file", {"path": ".env"})
    assert "deny-list" in str(exc.value)


async def test_read_file_refuses_key_file(sample_repo):
    mcp = build_server(load_config(str(sample_repo)))
    with pytest.raises(ToolError) as exc:
        await mcp.call_tool("read_file", {"path": "service.key"})
    assert "deny-list" in str(exc.value)


async def test_read_file_still_serves_ordinary_files(sample_repo):
    """The deny-list must not break reading legitimate files."""
    mcp = build_server(load_config(str(sample_repo)))
    result = await mcp.call_tool("read_file", {"path": "src/auth.py"})
    # call_tool returns (content, structured) — just assert no error was raised.
    assert result is not None


# --- Turn on once the tools exist (Days 5-6), re-using the same deny-list ---


async def test_denied_file_not_in_search_results(sample_repo):
    """A secret that really exists in the (denied) .env must not be searchable."""
    # Sanity: the token IS present on disk, so a 0-result proves exclusion,
    # not mere absence.
    assert "PAYMENT_PROVIDER_KEY" in (sample_repo / ".env").read_text()

    mcp = build_server(load_config(str(sample_repo)))
    _content, structured = await mcp.call_tool("search_code", {"query": "PAYMENT_PROVIDER_KEY"})
    assert structured["total_matches"] == 0


async def test_denied_files_absent_from_repo_tree(sample_repo):
    """The repo_tree resource must exclude deny-listed files but keep real ones."""
    import json

    mcp = build_server(load_config(str(sample_repo)))
    contents = await mcp.read_resource("repo://tree")
    tree = json.loads(contents[0].content)

    names: set[str] = set()

    def collect(node: dict) -> None:
        names.add(node["name"])
        for child in node.get("children", []):
            collect(child)

    collect(tree)

    assert ".env" not in names
    assert "service.key" not in names
    # sanity: ordinary files still appear
    assert "auth.py" in names


# --- The deny-list is checked on the RESOLVED path --------------------------
# Matching only the name the client typed would let an innocently named symlink
# (notes.txt -> .env) walk a secret straight past the deny-list.


@pytest.fixture
def repo_with_disguised_secrets(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / ".env").write_text("API_KEY=FAKE_disguised_secret_fixture\n")
    (root / ".git" / "config").write_text("[remote] url = FAKE_disguised_git_fixture\n")
    (root / "notes.txt").symlink_to(root / ".env")                       # file symlink
    (root / "docs").symlink_to(root / ".git", target_is_directory=True)  # directory symlink
    (root / "ok.txt").write_text("nothing secret here\n")
    return root


@pytest.mark.parametrize("disguise", ["notes.txt", "docs/config"])
async def test_a_symlink_to_a_secret_is_refused(repo_with_disguised_secrets, disguise):
    mcp = build_server(load_config(str(repo_with_disguised_secrets)))
    with pytest.raises(ToolError) as exc:
        await mcp.call_tool("read_file", {"path": disguise})
    assert "deny-list" in str(exc.value)
    with pytest.raises(ToolError) as exc:
        await mcp.call_tool("diff", {"a": "ok.txt", "b": disguise})
    assert "deny-list" in str(exc.value)


async def test_a_symlinked_secret_never_reaches_search(repo_with_disguised_secrets):
    mcp = build_server(load_config(str(repo_with_disguised_secrets)))
    for token in ("FAKE_disguised_secret_fixture", "FAKE_disguised_git_fixture"):
        _content, found = await mcp.call_tool("search_code", {"query": token})
        assert found["total_matches"] == 0, token
