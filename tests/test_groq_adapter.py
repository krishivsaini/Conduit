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



# --- Groq refusing an invalid tool call -----------------------------------------
# Seen in a real demo run: gpt-oss called search_code(query=""), Groq checked it
# against the schema (minLength 1) and refused the whole response with a 400.

REJECTED = ("Error code: 400 - {'error': {'message': 'Tool call validation failed: tool call validation "
            "failed: parameters for tool search_code did not match schema: errors: [`/query`: minLength: "
            "got 0, want 1]', 'type': 'invalid_request_error', 'code': 'tool_use_failed'}}")


class Rejecting(FakeCompletions):
    def __init__(self, failures, replies):
        super().__init__(replies)
        self.failures = failures

    async def create(self, **request):
        self.requests.append(request)
        if self.failures:
            self.failures -= 1
            raise RuntimeError(REJECTED)
        return self.replies.pop(0)


def _rejecting_adapter(failures, replies):
    adapter = GroqAdapter(api_key="dummy-not-used")
    fake = Rejecting(failures, replies)
    adapter._client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
    return adapter, fake


async def test_a_rejected_tool_call_is_explained_to_the_model_and_retried():
    adapter, fake = _rejecting_adapter(1, [_reply([_call("c1", "search_code", '{"query": "deny"}')])])
    decision = await adapter.decide([{"role": "user", "content": "q"}], [{"name": "search_code", "input_schema": {}}])
    assert decision == ToolCall("search_code", {"query": "deny"}, {"tool_call_id": "c1"})
    retry = fake.requests[1]["messages"][-1]
    assert retry["role"] == "user" and "search_code" in retry["content"] and "minLength" in retry["content"]
    assert len(fake.requests[0]["messages"]) == 2  # the first attempt wasn't altered


async def test_it_gives_up_after_two_retries():
    adapter, fake = _rejecting_adapter(5, [])
    with pytest.raises(RuntimeError, match="tool_use_failed"):
        await adapter.decide([{"role": "user", "content": "q"}], [{"name": "search_code", "input_schema": {}}])
    assert len(fake.requests) == 3


async def test_other_errors_are_not_retried():
    class Down(FakeCompletions):
        async def create(self, **request):
            self.requests.append(request)
            raise RuntimeError("503 Service Unavailable")

    adapter = GroqAdapter(api_key="dummy-not-used")
    fake = Down([])
    adapter._client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
    with pytest.raises(RuntimeError, match="503"):
        await adapter.decide([{"role": "user", "content": "q"}], [])
    assert len(fake.requests) == 1


def test_a_visitor_gets_a_sentence_not_the_providers_400():
    from conduit.web.app import _friendly_error

    message = _friendly_error(RuntimeError(REJECTED))
    assert "Try rephrasing" in message and "Error code" not in message and "minLength" not in message



# --- Argument names the model reorders ------------------------------------------

READ_FILE = {"name": "read_file", "input_schema": {"properties": {
    "path": {}, "start_line": {}, "end_line": {}}}}


@pytest.mark.parametrize("sent, expected", [
    ({"path": "a.py", "line_start": 1, "line_end": 9}, {"path": "a.py", "start_line": 1, "end_line": 9}),
    ({"path": "a.py", "start_line": 1}, {"path": "a.py", "start_line": 1}),            # already right
    ({"path": "a.py", "max_lines": 9}, {"path": "a.py", "max_lines": 9}),              # not a reordering: left for the server
    ({"path": "a.py", "line_start": 1, "start_line": 2}, {"path": "a.py", "line_start": 1, "start_line": 2}),  # ambiguous
])
async def test_a_reordered_argument_name_is_mapped_back(sent, expected):
    import json as _json

    adapter, _ = _adapter([_reply([_call("c1", "read_file", _json.dumps(sent))])])
    decision = await adapter.decide([{"role": "user", "content": "q"}], [READ_FILE])
    assert decision.arguments == expected


async def test_the_mapped_call_is_one_the_server_accepts(sample_repo):
    """End to end: line_start/line_end reach the server as start_line/end_line,
    and come back as the asked-for range, not a refusal."""
    adapter, _ = _adapter([
        _reply([_call("c1", "read_file", '{"path": "src/auth.py", "line_start": 1, "line_end": 3}')]),
        _reply(content="ANSWER: ok"),
    ])
    async with MCPCodebaseClient(conduit_server_params(sample_repo)) as client:
        result = await run_turn(client, adapter, "q")
    (step,) = result.steps
    assert not step.is_error and '"end_line": 3' in step.result_text
