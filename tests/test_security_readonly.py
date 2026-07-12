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


# --- Proof 2: no server code path writes / deletes / executes --------------

# Method names that are inherently write/delete/exec regardless of receiver.
ALWAYS_FORBIDDEN_METHODS = {
    "write_text", "write_bytes", "unlink", "mkdir", "rmdir", "makedirs",
    "rmtree", "symlink_to", "touch",
}
# Dangerous os.* calls (receiver must be the `os` module).
OS_FORBIDDEN = {
    "system", "popen", "remove", "removedirs", "rename", "renames", "replace",
    "unlink", "rmdir", "mkdir", "makedirs", "execv", "execve", "execvp",
    "execvpe", "spawnv", "spawnl", "spawnve", "chmod", "chown", "truncate",
}
FORBIDDEN_MODULES = {"subprocess", "shutil"}
_WRITE_MODE_CHARS = set("wax+")


def _mode_is_write(node: ast.Call) -> bool:
    """True if an open() call uses a write/append/create mode."""
    mode = None
    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
        mode = node.args[1].value
    for kw in node.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            mode = kw.value.value
    return isinstance(mode, str) and bool(set(mode) & _WRITE_MODE_CHARS)


def _scan_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []

    for node in ast.walk(tree):
        # Forbidden module imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_MODULES:
                    violations.append(f"{path.name}:{node.lineno} import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in FORBIDDEN_MODULES:
                violations.append(f"{path.name}:{node.lineno} from {node.module} import ...")
        # Dangerous calls
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "open" and _mode_is_write(node):
                violations.append(f"{path.name}:{node.lineno} open(..., write mode)")
            elif isinstance(func, ast.Attribute):
                if func.attr in ALWAYS_FORBIDDEN_METHODS:
                    violations.append(f"{path.name}:{node.lineno} .{func.attr}()")
                elif isinstance(func.value, ast.Name):
                    if func.value.id == "os" and func.attr in OS_FORBIDDEN:
                        violations.append(f"{path.name}:{node.lineno} os.{func.attr}()")
                    elif func.value.id in FORBIDDEN_MODULES:
                        violations.append(f"{path.name}:{node.lineno} {func.value.id}.{func.attr}()")
    return violations


def test_no_server_code_path_writes_or_executes():
    all_violations: list[str] = []
    py_files = sorted(SERVER_DIR.rglob("*.py"))
    assert py_files, "expected to scan server source files"
    for f in py_files:
        all_violations.extend(_scan_file(f))
    assert not all_violations, f"read-only violation(s) in server code: {all_violations}"
