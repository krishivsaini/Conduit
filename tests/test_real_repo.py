"""The server holds up on a real repository, not just the three-file sample.

On a real checkout the index has to stay current while files change, respect
the repo's own .gitignore, honour a deployment's extra deny patterns, page
through results that don't fit in one reply, and hand the model a tree that
fits in its context instead of one cut off mid-JSON.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from conduit.server import indexer
from conduit.server.app import build_server, load_config
from conduit.server.indexer import TREE_MAX_CHARS, RepoIndex

ROOT = Path(__file__).resolve().parents[1]


async def call(server, name, args):
    _content, data = await server.call_tool(name, args)
    return data


async def tree(server) -> dict:
    contents = await server.read_resource("repo://tree")
    return json.loads(next(iter(contents)).content)


def tree_paths(node: dict) -> set[str]:
    out = {node["path"]}
    for child in node.get("children", ()):
        out |= tree_paths(child)
    return out


def bump(path: Path, text: str) -> None:
    """Rewrite a file and move its mtime on, so even a coarse clock sees it."""
    path.write_text(text)
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000_000))


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("def handler():\n    return 'ok'\n")
    return root


# --- One index, kept current ------------------------------------------------


def test_the_repo_is_walked_once_at_startup(repo, monkeypatch):
    walks = []
    real = RepoIndex._walk
    monkeypatch.setattr(RepoIndex, "_walk", lambda self: walks.append(1) or real(self))
    build_server(load_config(str(repo)))
    assert len(walks) == 1  # was 2: search_code and list_symbols each built their own


async def test_edits_after_startup_are_searchable(repo):
    server = build_server(load_config(str(repo)))
    assert (await call(server, "search_code", {"query": "late_arrival"}))["total_matches"] == 0

    new = repo / "src" / "late.py"
    new.write_text("def late_arrival():\n    pass\n")
    found = await call(server, "search_code", {"query": "late_arrival"})
    assert [(m["path"], m["line"]) for m in found["matches"]] == [("src/late.py", 1)]
    symbols = await call(server, "list_symbols", {"query": "late_arrival"})
    assert [s["name"] for s in symbols["symbols"]] == ["late_arrival"]

    bump(new, "def renamed():\n    pass\n")
    assert (await call(server, "search_code", {"query": "late_arrival"}))["total_matches"] == 0
    assert (await call(server, "search_code", {"query": "renamed"}))["total_matches"] == 1

    new.unlink()
    assert (await call(server, "search_code", {"query": "renamed"}))["total_matches"] == 0


async def test_a_secret_created_after_startup_is_still_never_indexed(repo):
    server = build_server(load_config(str(repo)))
    (repo / ".env").write_text("TOKEN=late-secret-value\n")
    (repo / "src" / "deploy.key").write_text("late-secret-value\n")
    assert (await call(server, "search_code", {"query": "late-secret"}))["total_matches"] == 0
    assert {".env", "src/deploy.key"}.isdisjoint(tree_paths(await tree(server)))


def test_unchanged_files_are_not_reread(repo, monkeypatch):
    index = RepoIndex(repo)
    index.build()
    loads = []
    real = RepoIndex._load
    monkeypatch.setattr(RepoIndex, "_load", staticmethod(lambda *a: loads.append(a[1]) or real(*a)))
    index.refresh()
    assert loads == []
    bump(repo / "src" / "app.py", "def handler():\n    return 'changed'\n")
    index.refresh()
    assert loads == ["src/app.py"]


# --- .gitignore -------------------------------------------------------------


@pytest.fixture
def ignoring_repo(repo) -> Path:
    (repo / ".gitignore").write_text("out/\n*.log\n!keep.log\nPLAN.md\n")
    (repo / "out").mkdir()
    (repo / "out" / "bundle.js").write_text("const marker = 'IGNORED_MARKER';\n")
    (repo / "debug.log").write_text("IGNORED_MARKER\n")
    (repo / "keep.log").write_text("KEPT_MARKER\n")
    (repo / "PLAN.md").write_text("IGNORED_MARKER private plan\n")
    # A deeper .gitignore overrides a shallower one, `!` included.
    (repo / "src" / ".gitignore").write_text("local_*.py\n!trace.log\n")
    (repo / "src" / "trace.log").write_text("KEPT_MARKER\n")
    (repo / "src" / "local_settings.py").write_text("IGNORED_MARKER = 1\n")
    (repo / ".git" / "info").mkdir(parents=True)
    (repo / ".git" / "info" / "exclude").write_text("scratch/\n")
    (repo / "scratch").mkdir()
    (repo / "scratch" / "notes.txt").write_text("IGNORED_MARKER\n")
    # Files named like directory-only rules ("out/") or vendor dirs ("build"):
    # git ignores only the directories, so these files are served.
    (repo / "src" / "out").write_text("served\n")
    (repo / "build").write_text("#!/bin/sh\n")
    return repo


async def test_gitignored_files_are_not_listed_or_searched(ignoring_repo):
    server = build_server(load_config(str(ignoring_repo)))
    assert (await call(server, "search_code", {"query": "IGNORED_MARKER"}))["total_matches"] == 0
    # A `!` rule re-includes, as in git.
    kept = await call(server, "search_code", {"query": "KEPT_MARKER"})
    assert [m["path"] for m in kept["matches"]] == ["keep.log", "src/trace.log"]

    paths = tree_paths(await tree(server))
    assert {"out", "debug.log", "PLAN.md", "src/local_settings.py", "scratch"}.isdisjoint(paths)
    assert {"keep.log", "src/app.py", ".gitignore"} <= paths


IGNORED_PATHS = ["PLAN.md", "debug.log", "out/bundle.js", "src/local_settings.py", "scratch/notes.txt"]


@pytest.mark.parametrize("path", IGNORED_PATHS)
async def test_gitignored_files_are_not_served_either(ignoring_repo, path):
    """.gitignore is itself served, and it names the files a repo keeps private:
    'not listed but readable by exact path' would hand a model the list."""
    server = build_server(load_config(str(ignoring_repo)))
    assert "PLAN.md" in (await call(server, "read_file", {"path": ".gitignore"}))["content"]
    for tool, args in [("read_file", {"path": path}), ("diff", {"a": "keep.log", "b": path}),
                       ("list_symbols", {"path": path})]:
        with pytest.raises(ToolError, match="is not served") as exc:
            await server.call_tool(tool, args)
        assert "IGNORED_MARKER" not in str(exc.value)


async def test_a_reincluded_file_is_served(ignoring_repo):
    server = build_server(load_config(str(ignoring_repo)))
    for path in ("keep.log", "src/trace.log"):
        assert "KEPT_MARKER" in (await call(server, "read_file", {"path": path}))["content"]


async def test_a_file_named_like_an_ignored_directory_is_served(ignoring_repo):
    server = build_server(load_config(str(ignoring_repo)))
    for path in ("src/out", "build"):
        assert (await call(server, "read_file", {"path": path}))["total_lines"] == 1


async def test_vendor_directories_are_not_served(repo):
    (repo / "node_modules" / "left-pad").mkdir(parents=True)
    (repo / "node_modules" / "left-pad" / "index.js").write_text("module.exports = 1\n")
    server = build_server(load_config(str(repo)))
    with pytest.raises(ToolError, match="vendor or cache directory"):
        await server.call_tool("read_file", {"path": "node_modules/left-pad/index.js"})


async def test_a_symlink_to_an_ignored_file_is_not_served(ignoring_repo):
    (ignoring_repo / "notes.md").symlink_to(ignoring_repo / "PLAN.md")
    server = build_server(load_config(str(ignoring_repo)))
    with pytest.raises(ToolError, match="is not served"):
        await server.call_tool("read_file", {"path": "notes.md"})


async def test_a_gitignore_cannot_reinclude_a_secret(repo):
    (repo / ".gitignore").write_text("!.env\n!*.key\n")
    (repo / ".env").write_text("TOKEN=still-secret\n")
    server = build_server(load_config(str(repo)))
    with pytest.raises(ToolError, match="deny-list"):
        await server.call_tool("read_file", {"path": ".env"})
    assert (await call(server, "search_code", {"query": "still-secret"}))["total_matches"] == 0


def test_what_is_served_is_exactly_what_is_listed(ignoring_repo):
    """One view of the repo: every file on disk is either in the index and
    readable, or absent from it and refused, never one without the other."""
    from conduit.server.access import FileAccessError, resolve_allowed_path

    index = RepoIndex(ignoring_repo)
    index.build()
    for path in ignoring_repo.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        rel = path.relative_to(ignoring_repo).as_posix()
        try:
            resolve_allowed_path(ignoring_repo, rel)
            served = True
        except FileAccessError:
            served = False
        assert served == (rel in index._entries), rel


# --- A configurable deny-list -----------------------------------------------


async def test_extra_deny_patterns_apply_everywhere(repo, monkeypatch):
    (repo / "internal").mkdir()
    (repo / "internal" / "notes.md").write_text("DENIED_MARKER\n")
    (repo / "src" / "answers.txt").write_text("DENIED_MARKER\n")
    monkeypatch.setenv("CONDUIT_DENY", "internal/, answers.txt")
    server = build_server(load_config(str(repo)))

    assert (await call(server, "search_code", {"query": "DENIED_MARKER"}))["total_matches"] == 0
    assert {"internal", "src/answers.txt"}.isdisjoint(tree_paths(await tree(server)))
    for path in ("internal/notes.md", "src/answers.txt"):
        with pytest.raises(ToolError, match="deny-list"):
            await server.call_tool("read_file", {"path": path})
    with pytest.raises(ToolError, match="deny-list"):
        await server.call_tool("diff", {"a": "src/app.py", "b": "src/answers.txt"})


def test_configuring_the_deny_list_can_only_add_to_it(monkeypatch):
    monkeypatch.setenv("CONDUIT_DENY", "")
    assert set(load_config(".").deny_patterns) >= set(indexer.DEFAULT_DENY_PATTERNS)
    monkeypatch.setenv("CONDUIT_DENY", "!.env, ,")
    patterns = load_config(".", deny=["extra/"]).deny_patterns
    assert patterns[: len(indexer.DEFAULT_DENY_PATTERNS)] == indexer.DEFAULT_DENY_PATTERNS
    assert "extra/" in patterns and "" not in patterns


async def test_the_server_cli_passes_deny_patterns_through(repo):
    from conduit.host.client import MCPCodebaseClient, conduit_server_params

    (repo / "src" / "answers.txt").write_text("x\n")
    async with MCPCodebaseClient(conduit_server_params(repo, deny=["answers.txt"])) as client:
        result = await client.call_tool("read_file", {"path": "src/answers.txt"})
    assert result.isError and "deny-list" in result.content[0].text


async def test_a_deny_pattern_in_the_shell_reaches_a_server_the_host_launches(repo, monkeypatch):
    """MCP's stdio client hands a server only HOME, PATH and a few others, so a
    CONDUIT_DENY the user exported would be dropped without the host forwarding it."""
    from conduit.host.client import MCPCodebaseClient, conduit_server_params

    (repo / "src" / "answers.txt").write_text("x\n")
    monkeypatch.setenv("CONDUIT_DENY", "answers.txt")
    async with MCPCodebaseClient(conduit_server_params(repo)) as client:
        result = await client.call_tool("read_file", {"path": "src/answers.txt"})
    assert result.isError and "deny-list" in result.content[0].text


def test_the_conduit_cli_passes_deny_through(repo, monkeypatch, capsys):
    import sys

    from conduit.host import cli
    from conduit.host.llm.adapter import FinalAnswer, ToolCall
    from conduit.host.llm.stub import StubAdapter

    (repo / "src" / "answers.txt").write_text("x\n")
    stub = StubAdapter([ToolCall("read_file", {"path": "src/answers.txt"}), FinalAnswer("done")])
    monkeypatch.setattr(cli, "get_adapter", lambda provider: stub)
    monkeypatch.setattr(sys, "argv", ["conduit", "--repo-root", str(repo), "--deny", "answers.txt", "q"])
    with pytest.raises(SystemExit):
        cli.main()
    assert "refused by the secrets deny-list" in capsys.readouterr().out


# --- Results that don't fit in one reply ------------------------------------


async def test_list_symbols_pages_through_everything(repo):
    (repo / "src" / "many.py").write_text("".join(f"def f{i:02d}():\n    pass\n" for i in range(30)))
    server = build_server(load_config(str(repo)))
    seen, offset = [], 0
    while offset is not None:
        page = await call(server, "list_symbols", {"path": "src/many.py", "limit": 7, "offset": offset})
        assert page["total"] == 30 and page["truncated"] == page["has_more"]
        seen += [s["name"] for s in page["symbols"]]
        offset = page["next_offset"]
    assert seen == [f"f{i:02d}" for i in range(30)]


async def test_a_large_tree_is_collapsed_to_fit_not_cut_off(repo):
    for pkg in range(12):
        for mod in range(15):
            d = repo / "src" / f"package_{pkg:02d}" / "internal" / "generated"
            d.mkdir(parents=True, exist_ok=True)
            (d / f"module_with_a_long_name_{mod:02d}.py").write_text("x = 1\n")
    server = build_server(load_config(str(repo)))
    contents = await server.read_resource("repo://tree")
    data = json.loads(next(iter(contents)).content)  # whole, valid JSON

    assert len(json.dumps(data, separators=(",", ":"))) <= TREE_MAX_CHARS

    def files(node):
        if node["type"] == "file":
            return 1
        return node["file_count"] if node.get("collapsed") else sum(files(c) for c in node["children"])

    assert files(data) == 12 * 15 + 1  # every file still accounted for
    assert "src/app.py" in tree_paths(data)  # shallow files keep their names


def test_only_as_much_is_collapsed_as_needed(repo):
    """One big generated directory shouldn't hide the small ones beside it."""
    big = repo / "src" / "vendored" / "generated"
    big.mkdir(parents=True)
    for i in range(300):
        (big / f"generated_module_number_{i:03d}.py").write_text("x = 1\n")
    small = repo / "src" / "core" / "handlers"
    small.mkdir(parents=True)
    (small / "auth.py").write_text("x = 1\n")

    data = RepoIndex(repo).file_tree()
    assert len(json.dumps(data, separators=(",", ":"))) <= TREE_MAX_CHARS
    paths = tree_paths(data)
    assert "src/core/handlers/auth.py" in paths  # the small sibling keeps its names
    assert "src/vendored/generated" in paths and not any("generated_module" in p for p in paths)


def test_a_tree_too_wide_to_fit_says_what_it_left_out(repo):
    for i in range(400):
        (repo / f"top_level_file_with_a_long_name_{i:03d}.txt").write_text("x")
    data = RepoIndex(repo).file_tree()
    assert len(json.dumps(data, separators=(",", ":"))) <= TREE_MAX_CHARS
    assert data["omitted_entries"] > 0
    assert len(data["children"]) + data["omitted_entries"] == 401


async def test_a_small_tree_is_left_alone(sample_repo):
    data = await tree(build_server(load_config(str(sample_repo))))
    assert "src/payments.py" in tree_paths(data)
    assert not any(n.get("collapsed") for n in [data, *data["children"]])


# --- This repository, served for real ----------------------------------------


@pytest.mark.skipif(shutil.which("git") is None or not (ROOT / ".git").exists(), reason="needs a git checkout")
def test_serving_this_checkout_shows_only_what_git_would_track():
    index = RepoIndex(ROOT)
    index.build()
    files = sorted(index._entries)
    ignored = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"],
        input="\n".join(files), capture_output=True, text=True, cwd=ROOT,
    ).stdout.split()
    assert ignored == []  # nothing git ignores (.venv, .env, build plan, caches...)
    assert "conduit/server/indexer.py" in files and "README.md" in files
    assert len(json.dumps(index.file_tree(), separators=(",", ":"))) <= TREE_MAX_CHARS
