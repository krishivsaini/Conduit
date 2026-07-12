"""Conduit MCP server entry point.

Constructs the FastMCP server, wires the served repo root through the security
boundary, registers tools + resources, and runs over stdio (the local
transport; streamable HTTP is a documented optional alternative — §11).

Registration is intentionally incremental per the build plan:
  Day 2 → read_file      Day 5 → search_code
  Day 6 → list_symbols, diff, repo_tree

Run:
    conduit-server --repo-root ./sample-repo
    # or, for manual testing:  npx @modelcontextprotocol/inspector conduit-server ...
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

from mcp.server.fastmcp import FastMCP


@dataclass(frozen=True)
class ServerConfig:
    """Resolved configuration for a server instance."""

    repo_root: Path


def load_config(repo_root: str | None = None) -> ServerConfig:
    """Resolve server config from an explicit arg or ``CONDUIT_REPO_ROOT``."""
    root = repo_root or os.environ.get("CONDUIT_REPO_ROOT", "./sample-repo")
    return ServerConfig(repo_root=Path(root).resolve())


def build_server(config: ServerConfig) -> FastMCP:
    """Create the FastMCP server and register the (currently empty) tool set.

    Tools and resources are registered here as the build progresses. Each
    registration passes ``config`` so tools can route path inputs through the
    security boundary before touching the filesystem.
    """
    mcp = FastMCP("conduit_mcp")

    # --- Registration wired in over Days 2-6 (see module docstring) ---
    from .tools import read_file

    read_file.register(mcp, config)

    # Day 5-6: search_code, list_symbols, diff, repo_tree

    # Read-only posture (§8.3): refuse to start if any non-read-only tool was
    # registered. This is enforcement, not decoration.
    from .security.readonly import enforce_readonly

    enforce_readonly(mcp)
    return mcp


def main() -> None:
    """CLI entry point: parse ``--repo-root`` and run the server over stdio."""
    parser = argparse.ArgumentParser(description="Conduit MCP codebase server")
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Directory to serve (defaults to $CONDUIT_REPO_ROOT or ./sample-repo)",
    )
    args = parser.parse_args()

    config = load_config(args.repo_root)
    server = build_server(config)
    server.run()  # stdio transport (FastMCP default)


if __name__ == "__main__":
    main()
