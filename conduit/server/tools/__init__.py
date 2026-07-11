"""MCP tools (actions) exposed by the server: search_code, read_file,
list_symbols, diff. Every tool routes all path inputs through the
security boundary (conduit.server.security) before touching the filesystem."""
