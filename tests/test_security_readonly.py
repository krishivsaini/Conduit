"""Proves the read-only posture: no write/execute tool exists (§8.3).

Two independent proofs:
  1. The registered tool set is allow-listed and every tool declares
     readOnlyHint=True (and the guard actually rejects a would-be write tool).
  2. A static scan asserts no server code path opens a file for writing,
     deletes/moves files, or shells out.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from mcp.server.fastmcp import FastMCP

from conduit.server.app import build_server, load_config
from conduit.server.security.readonly import (
    ALLOWED_READONLY_TOOLS,
    ReadOnlyViolationError,
    assert_readonly_toolset,
    enforce_readonly,
)

SERVER_DIR = Path(__file__).resolve().parents[1] / "conduit" / "server"


# --- Proof 1: only read-only tools are registered --------------------------


def test_only_readonly_tools_registered(sample_repo):
    mcp = build_server(load_config(str(sample_repo)))
    tools = mcp._tool_manager.list_tools()
    names = {t.name for t in tools}
    assert names <= ALLOWED_READONLY_TOOLS
    assert all(t.annotations and t.annotations.readOnlyHint for t in tools)


def test_guard_rejects_a_write_tool():
    """Attempt a violation: a non-allow-listed tool must be rejected."""
    with pytest.raises(ReadOnlyViolationError):
        assert_readonly_toolset(frozenset({"read_file", "delete_file"}))


def test_enforce_rejects_tool_missing_readonly_hint():
    """An allow-listed tool without readOnlyHint=True is still rejected."""
    mcp = FastMCP("probe")

    @mcp.tool(name="search_code")  # allow-listed name, but no annotations
    async def search_code(query: str) -> str:
        return query

    with pytest.raises(ReadOnlyViolationError):
        enforce_readonly(mcp)


def test_the_real_server_refuses_to_build_with_a_write_tool(sample_repo, monkeypatch):
    """The guards above are only enforcement if build_server actually runs
    them. Smuggle a write tool into a real registration and the server must
    refuse to start."""
    from mcp.types import ToolAnnotations

    from conduit.server.tools import diff

    real_register = diff.register

    def register_with_a_write_tool(mcp, config):
        real_register(mcp, config)

        @mcp.tool(name="delete_file", annotations=ToolAnnotations(readOnlyHint=False))
        async def delete_file(path: str) -> str:
            return path

    monkeypatch.setattr(diff, "register", register_with_a_write_tool)
    with pytest.raises(ReadOnlyViolationError):
        build_server(load_config(str(sample_repo)))


# --- Proof 2: no server code path writes / deletes / executes --------------
# A static scan is a strong check, not a proof: it reads the code as written,
# so it cannot see through getattr(), strings built at runtime, or a dependency
# that writes on our behalf. It covers the ways code ordinarily reaches the
# filesystem or a shell, and the scanner is itself tested (bottom of file)
# against each pattern it must catch.

# Method names that are inherently write/delete/exec regardless of receiver.
ALWAYS_FORBIDDEN_METHODS = {
    "write_text", "write_bytes", "unlink", "mkdir", "rmdir", "makedirs",
    "rmtree", "symlink_to", "hardlink_to", "touch", "rename", "chmod", "lchmod",
}
# Dangerous os.* calls (receiver must be the `os` module).
OS_FORBIDDEN = {
    "system", "popen", "remove", "removedirs", "rename", "renames", "replace",
    "unlink", "rmdir", "mkdir", "makedirs", "execv", "execve", "execvp",
    "execvpe", "spawnv", "spawnl", "spawnve", "chmod", "chown", "truncate",
}
FORBIDDEN_MODULES = {"subprocess", "shutil"}
# os.open() flags that write or create. Any reference to one is a violation.
OS_WRITE_FLAGS = {"O_WRONLY", "O_RDWR", "O_CREAT", "O_APPEND", "O_TRUNC"}
# Modules whose .open(file, mode) takes the mode second, like the builtin.
# Any other receiver's .open(mode) is treated as Path.open, mode first.
OPEN_MODE_SECOND = {"io", "builtins", "codecs", "gzip", "bz2", "lzma"}
_WRITE_MODE_CHARS = set("wax+")


def _const_str(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _mode_is_write(node: ast.Call, mode_index: int) -> bool:
    """True if an open-style call passes a write/append/create mode."""
    mode = _const_str(node.args[mode_index]) if len(node.args) > mode_index else None
    for kw in node.keywords:
        if kw.arg == "mode":
            mode = _const_str(kw.value)
    return mode is not None and bool(set(mode) & _WRITE_MODE_CHARS)


def _scan_source(source: str, name: str) -> list[str]:
    tree = ast.parse(source, filename=name)
    violations: list[str] = []

    def flag(node: ast.AST, what: str) -> None:
        violations.append(f"{name}:{node.lineno} {what}")

    # `import os as o` makes `o.system(...)` the same call, so collect aliases first.
    os_names = {"os"} | {
        a.asname for n in ast.walk(tree) if isinstance(n, ast.Import)
        for a in n.names if a.name == "os" and a.asname
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_MODULES:
                    flag(node, f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            if module in FORBIDDEN_MODULES:
                flag(node, f"from {node.module} import ...")
            elif module == "os":
                # `from os import system` dodges every os.<name> check below.
                for alias in node.names:
                    if alias.name == "*" or alias.name in OS_FORBIDDEN | OS_WRITE_FLAGS:
                        flag(node, f"from os import {alias.name}")
        elif isinstance(node, ast.Attribute):
            if node.attr in OS_WRITE_FLAGS:
                flag(node, f"os.{node.attr} (a write flag for os.open)")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                if func.id == "open" and _mode_is_write(node, 1):
                    flag(node, "open(..., write mode)")
                elif func.id in ("eval", "exec"):
                    flag(node, f"{func.id}()")
                elif func.id == "__import__" and (_const_str(node.args[0]) if node.args else None):
                    if _const_str(node.args[0]).split(".")[0] in FORBIDDEN_MODULES:
                        flag(node, f"__import__({node.args[0].value!r})")
            elif isinstance(func, ast.Attribute):
                receiver = func.value.id if isinstance(func.value, ast.Name) else None
                if func.attr in ALWAYS_FORBIDDEN_METHODS:
                    flag(node, f".{func.attr}()")
                elif func.attr == "open" and receiver not in os_names:
                    if _mode_is_write(node, 1 if receiver in OPEN_MODE_SECOND else 0):
                        flag(node, f"{receiver or '<path>'}.open(..., write mode)")
                elif func.attr == "import_module" and node.args:
                    target = _const_str(node.args[0])
                    if target and target.split(".")[0] in FORBIDDEN_MODULES:
                        flag(node, f"import_module({target!r})")
                elif receiver in os_names and func.attr in OS_FORBIDDEN:
                    flag(node, f"os.{func.attr}()")
                elif receiver in FORBIDDEN_MODULES:
                    flag(node, f"{receiver}.{func.attr}()")
    return violations


def _scan_file(path: Path) -> list[str]:
    return _scan_source(path.read_text(encoding="utf-8"), path.name)


def test_no_server_code_path_writes_or_executes():
    all_violations: list[str] = []
    py_files = sorted(SERVER_DIR.rglob("*.py"))
    assert py_files, "expected to scan server source files"
    for f in py_files:
        all_violations.extend(_scan_file(f))
    assert not all_violations, f"read-only violation(s) in server code: {all_violations}"


# --- The scanner itself is tested ------------------------------------------
# A scan that silently misses a pattern is worse than no scan. Each snippet is
# a real way to write a file or start a process; the scanner must flag all of
# them, and must not flag ordinary reads.

MUST_FLAG = [
    'open("f", "w")',
    'open("f", mode="a")',
    'from pathlib import Path\nPath("f").open("w")',
    'from pathlib import Path\nPath("f").open(mode="x")',
    'import io\nio.open("f", "w+")',
    'from pathlib import Path\nPath("f").write_text("x")',
    'from pathlib import Path\nPath("a").rename("b")',
    'import os\nos.system("ls")',
    'import os as o\no.remove("f")',
    'from os import system\nsystem("ls")',
    'from os import remove',
    'from os import *',
    'import os\nos.open("f", os.O_WRONLY)',
    'import os\nos.open("f", os.O_CREAT | os.O_RDONLY)',
    'import subprocess',
    'from shutil import rmtree',
    '__import__("subprocess").run(["ls"])',
    'import importlib\nimportlib.import_module("shutil")',
    'eval("1")',
    'exec("x = 1")',
]

MUST_ALLOW = [
    'open("f")',
    'open("f", "r")',
    'from pathlib import Path\nPath("f").read_text()',
    'from pathlib import Path\nPath("f").open()',
    'from pathlib import Path\nPath("f").open("rb")',
    'import os\nos.environ.get("X")',
    'import os\nos.open("f", os.O_RDONLY)',
    '"a b".replace(" ", "")',
]


@pytest.mark.parametrize("source", MUST_FLAG)
def test_scanner_catches(source):
    assert _scan_source(source, "snippet.py"), f"scanner missed: {source!r}"


@pytest.mark.parametrize("source", MUST_ALLOW)
def test_scanner_allows_ordinary_reads(source):
    assert _scan_source(source, "snippet.py") == []
