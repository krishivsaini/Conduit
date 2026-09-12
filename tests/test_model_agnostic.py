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
from conduit.host.loop import LOW_BUDGET_AT, MAX_STEPS, run_turn


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


# --- Step-budget exhaustion ------------------------------------------------
# A model that wanders (e.g. re-searching for a file the deny-list hides from
# the index) used to burn the budget and get back no answer at all, discarding
# every piece of evidence it had gathered. The loop now spends one last call
# with no tools offered, which forces a text answer.


async def test_step_limit_still_produces_an_answer(sample_repo):
    """Exhausting the budget yields a real answer, not the give-up placeholder."""
    wandering = StubAdapter(
        script=[ToolCall("search_code", {"query": f"attempt-{i}"}) for i in range(MAX_STEPS)]
        + [FinalAnswer("False — the server refused to read it.")]
    )
    async with MCPCodebaseClient(conduit_server_params(sample_repo)) as client:
        result = await run_turn(client, wandering, "can you read the secret?")

    assert result.hit_step_limit is True
    assert len(result.steps) == MAX_STEPS
    assert result.answer == "False — the server refused to read it."
    assert "stopped after the maximum" not in result.answer


async def test_forced_answer_is_asked_with_no_tools(sample_repo):
    """The last call offers no tools, so the model cannot call another one."""
    wandering = StubAdapter(
        script=[ToolCall("search_code", {"query": f"attempt-{i}"}) for i in range(MAX_STEPS)]
    )
    async with MCPCodebaseClient(conduit_server_params(sample_repo)) as client:
        await run_turn(client, wandering, "can you read the secret?")

    _messages, final_schemas = wandering.calls[-1]
    assert final_schemas == []
    # Every earlier call did have the discovered tools available.
    assert all(schemas for _m, schemas in wandering.calls[:-1])


async def test_model_is_warned_before_the_budget_runs_out(sample_repo):
    """The model is told to converge while it still has calls left to spend."""
    wandering = StubAdapter(
        script=[ToolCall("search_code", {"query": f"attempt-{i}"}) for i in range(MAX_STEPS)]
    )
    async with MCPCodebaseClient(conduit_server_params(sample_repo)) as client:
        await run_turn(client, wandering, "can you read the secret?")

    # The warning lands with LOW_BUDGET_AT calls still remaining, not at the end.
    warned_at = [
        i for i, (messages, _s) in enumerate(wandering.calls)
        if any("tool calls remain" in str(m.get("content", "")) for m in messages)
    ]
    assert warned_at, "expected a low-budget warning"
    assert min(warned_at) == MAX_STEPS - LOW_BUDGET_AT
