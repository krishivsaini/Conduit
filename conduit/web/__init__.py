"""The deployable web demo — a thin renderer over the host loop.

This package lives outside ``conduit/server/`` deliberately. The read-only
proof in tests/test_security_readonly.py statically scans the server tree for
writes and process spawning; a web server there would fail that scan and, more
importantly, would blur the boundary the project is about. The MCP server is
untouched by anything in here — this package is just another consumer of
``conduit.host.loop.run_turn``, exactly like the CLI.
"""
