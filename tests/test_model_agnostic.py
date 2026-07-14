"""The host loop is provider-independent (§10).

Proven hermetically (no network): the same loop that runs on Gemini and Ollama
also runs on a deterministic stub adapter, and all three adapters conform to the
one LLMAdapter interface. The live Gemini/Ollama runs are demonstrated
separately; this suite stays offline and fast.
"""

from __future__ import annotations

import pytest

from conduit.host.client import MCPCodebaseClient, conduit_server_params
from conduit.host.llm.adapter import FinalAnswer, LLMAdapter, ToolCall, get_adapter
from conduit.host.llm.gemini import GeminiAdapter
from conduit.host.llm.ollama import OllamaAdapter
from conduit.host.llm.stub import StubAdapter
from conduit.host.loop import run_turn


async def test_loop_runs_with_stub_adapter(sample_repo):
    """The same host loop answers via a no-network stub, making real tool calls."""
    stub = StubAdapter(
        script=[
            ToolCall("search_code", {"query": "authenticate"}),
            ToolCall("read_file", {"path": "src/auth.py", "start_line": 14, "end_line": 32}),
            FinalAnswer("authenticate is in src/auth.py and returns None on failure."),
        ]
    )
    async with MCPCodebaseClient(conduit_server_params(sample_repo)) as client:
        result = await run_turn(client, stub, "where is authenticate?")

    assert result.answer.startswith("authenticate is in src/auth.py")
    assert [s.name for s in result.steps] == ["search_code", "read_file"]
    assert all(not s.is_error for s in result.steps)

    # The loop passed the runtime-discovered tool schemas to the adapter.
    _messages, schemas = stub.calls[0]
    assert {s["name"] for s in schemas} == {"read_file", "search_code", "list_symbols", "diff"}


def test_all_adapters_conform_to_the_interface():
    """Gemini, Ollama, and the stub all implement the one LLMAdapter contract,
    and construct without any network call."""
    for cls in (GeminiAdapter, OllamaAdapter, StubAdapter):
        assert issubclass(cls, LLMAdapter)

    adapters = [
        GeminiAdapter(api_key="dummy-not-used"),
        OllamaAdapter(model="mistral"),
        StubAdapter(),
    ]
    for adapter in adapters:
        assert isinstance(adapter, LLMAdapter)


def test_get_adapter_selects_provider_by_name(monkeypatch):
    """LLM_PROVIDER (or the arg) selects the provider; unknown names are rejected."""
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy-not-used")
    assert isinstance(get_adapter("gemini"), GeminiAdapter)
    assert isinstance(get_adapter("ollama"), OllamaAdapter)
    with pytest.raises(ValueError):
        get_adapter("nonsense")
