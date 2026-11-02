#!/usr/bin/env python3
"""Test fixture: the standard Conduit server PLUS one extra tool.

This exists to prove dynamic discovery is real (§9): it registers a tool
(``reverse_text``) that the production server does not have and the client has
never heard of. test_dynamic_discovery spawns this over stdio and shows the
*unmodified* client discovers and calls the new tool — no client-side change.

Run: python tests/fixtures/augmented_server.py --repo-root <dir>
"""

from __future__ import annotations

import argparse

from mcp.types import ToolAnnotations

from conduit.server.app import build_server, load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Augmented Conduit server (adds reverse_text)")
    parser.add_argument("--repo-root", required=True)
    args = parser.parse_args()

    mcp = build_server(load_config(args.repo_root))

    # A tool that exists ONLY on this augmented server. Because the client
    # hardcodes no tool list, it will discover and be able to call this at
    # runtime with no code change.
    @mcp.tool(
        name="reverse_text",
        title="Reverse a string",
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
        ),
    )
    async def reverse_text(text: str) -> str:
        """Return the input text reversed."""
        return text[::-1]

    # Likewise a resource the host has never heard of: it should be read and
    # attached as context without any host change.
    @mcp.resource("notes://release", name="release_notes", mime_type="text/plain")
    def release_notes() -> str:
        """Release notes, only on this augmented server."""
        return "Release 2.0 renamed charge() to bill()."

    mcp.run()


if __name__ == "__main__":
    main()
