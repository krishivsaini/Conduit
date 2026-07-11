"""Model-agnostic LLM layer (§10).

One interface (adapter.py); three implementations — gemini.py (free tier,
default), ollama.py (local, offline), and stub.py (deterministic, for tests).
LLM_PROVIDER selects at runtime. The host loop calls only the adapter."""
