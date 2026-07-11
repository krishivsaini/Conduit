"""The Conduit host — a model-agnostic MCP client that discovers the server's
tools at runtime and drives them with an LLM to answer codebase questions.

The tool list is never hardcoded; it is learned from the server via capability
negotiation (§9). The LLM sits behind one adapter interface (§10) so the same
loop runs on Gemini or a local Ollama model, selected by LLM_PROVIDER.
"""
