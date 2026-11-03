"""The Groq adapter speaks OpenAI-style tool calling correctly, offline.

OpenAI-style APIs reject a conversation whose tool results don't name the call
they answer, so the id has to survive the round trip through the loop's
provider-neutral messages.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from conduit.host.client import MCPCodebaseClient, conduit_server_params
from conduit.host.llm.adapter import FinalAnswer, ToolCall, get_adapter
from conduit.host.llm.groq import GroqAdapter, _to_messages
from conduit.host.llm.pacing import is_per_day_limit, per_minute_wait
from conduit.host.loop import run_turn


def _reply(tool_calls=None, content=None):
    message = SimpleNamespace(tool_calls=tool_calls, content=content)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _call(call_id, name, arguments):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=arguments))


class FakeCompletions:
    """Scripted Groq responses; records every request the adapter sends."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []

    async def create(self, **request):
        self.requests.append(request)
        return self.replies.pop(0)


def _adapter(replies) -> tuple[GroqAdapter, FakeCompletions]:
    adapter = GroqAdapter(api_key="dummy-not-used")
    fake = FakeCompletions(replies)
    adapter._client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
    return adapter, fake


async def test_a_full_turn_pairs_each_result_with_its_call(sample_repo):
    adapter, fake = _adapter([
        _reply([_call("call_abc", "read_file", '{"path": "src/auth.py", "end_line": 3}')]),
        _reply([_call("call_def", "read_file", '{"path": ".env"}')]),
        _reply(content="Done.\nANSWER: None"),
    ])
    async with MCPCodebaseClient(conduit_server_params(sample_repo)) as client:
        result = await run_turn(client, adapter, "q")

    assert result.answer.endswith("ANSWER: None")
    assert [s.name for s in result.steps] == ["read_file", "read_file"]
    assert result.steps[1].is_error  # the deny-list refusal reached the model as data

    last = fake.requests[-1]["messages"]
    calls = [m["tool_calls"][0]["id"] for m in last if m["role"] == "assistant"]
    results = [m["tool_call_id"] for m in last if m["role"] == "tool"]
    assert calls == results == ["call_abc", "call_def"]
    assert json.loads(last[2]["tool_calls"][0]["function"]["arguments"]) == {"path": "src/auth.py", "end_line": 3}
    assert "tools" in fake.requests[0]


async def test_no_tools_means_none_are_sent():
    adapter, fake = _adapter([_reply(content="ANSWER: 4")])
    assert await adapter.decide([{"role": "user", "content": "q"}], []) == FinalAnswer("ANSWER: 4")
    assert "tools" not in fake.requests[0]
    assert fake.requests[0]["messages"][0] == {"role": "system", "content": adapter.system_prompt}


async def test_malformed_arguments_become_an_empty_call_not_a_crash():
    adapter, _ = _adapter([_reply([_call("c1", "search_code", "{not json")])])
    decision = await adapter.decide([{"role": "user", "content": "q"}], [{"name": "search_code", "input_schema": {}}])
    assert isinstance(decision, ToolCall) and decision.arguments == {}


def test_a_recorded_call_without_an_id_still_pairs():
    """Replayed transcripts were recorded by other providers and carry no id."""
    out = _to_messages([
        {"role": "user", "content": "q"},
        {"role": "tool_call", "name": "read_file", "arguments": {"path": "a"}, "meta": None},
        {"role": "tool_result", "name": "read_file", "content": "x", "is_error": False},
    ])
    assert out[2]["tool_calls"][0]["id"] == out[3]["tool_call_id"]


def test_a_missing_key_explains_where_to_get_one(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="console.groq.com/keys"):
        get_adapter("groq")


def test_the_model_is_configurable(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "dummy-not-used")
    monkeypatch.setenv("GROQ_MODEL", "qwen/qwen3.8-27b")
    assert get_adapter("groq").model == "qwen/qwen3.8-27b"


@pytest.mark.parametrize("message, wait", [
    ("Error code: 429 - Rate limit reached for model `openai/gpt-oss-120b` on requests per "
     "minute (RPM): Limit 30, Used 30, Requested 1. Please try again in 2.5s.", 3.5),
    ("429 rate_limit_exceeded on tokens per minute (TPM): Limit 8000. Please try again in 450ms.", 1.45),
    ("429 rate_limit_exceeded on tokens per minute (TPM). Please try again in 1m3.2s.", 64.2),
])
def test_groq_per_minute_limits_are_waited_out(message, wait):
    assert per_minute_wait(message) == pytest.approx(wait)


def test_a_groq_daily_limit_is_not():
    message = ("429 rate_limit_exceeded on requests per day (RPD): Limit 1000, Used 1000. "
               "Please try again in 7m12s.")
    assert is_per_day_limit(message) and per_minute_wait(message) is None


@pytest.mark.parametrize("called, expected", [
    ("repo_browser.list_symbols", "list_symbols"),  # seen in a real gpt-oss run
    ("functions.read_file", "read_file"),
    ("read_file", "read_file"),
    ("repo_browser.delete_file", "repo_browser.delete_file"),  # unknown stays unknown
])
async def test_an_invented_namespace_is_mapped_back_to_the_real_tool(called, expected):
    adapter, _ = _adapter([_reply([_call("c1", called, "{}")])])
    schemas = [{"name": n, "input_schema": {}} for n in ("read_file", "list_symbols")]
    decision = await adapter.decide([{"role": "user", "content": "q"}], schemas)
    assert decision.name == expected
