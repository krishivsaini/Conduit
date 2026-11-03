"""auto: Gemini's free tier first, Groq when Gemini is rate limited.

Fake providers and a fake clock, so no quota is spent and no time passes.
"""

from __future__ import annotations

import sys

import pytest

from conduit.host.llm.adapter import FinalAnswer, LLMAdapter, ToolCall, get_adapter
from conduit.host.llm.fallback import PER_DAY_COOLDOWN, PER_MINUTE_COOLDOWN, FallbackAdapter
from conduit.host.llm.gemini import GeminiAdapter
from conduit.host.llm.groq import GroqAdapter
from conduit.host.llm.stub import StubAdapter

PER_DAY = "429 RESOURCE_EXHAUSTED 'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'"
PER_MINUTE = "429 RESOURCE_EXHAUSTED 'quotaId': 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier'"


class Provider(LLMAdapter):
    """Answers with its own name, or raises the next scripted error."""

    def __init__(self, model: str, errors: list[str] | None = None) -> None:
        self.model = model
        self.errors = list(errors or [])
        self.calls = 0

    async def decide(self, messages, tool_schemas):
        self.calls += 1
        if self.errors:
            raise RuntimeError(self.errors.pop(0))
        return FinalAnswer(self.model)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def turn() -> list[dict]:
    return [{"role": "user", "content": "q"}]


async def test_a_spent_daily_quota_moves_the_question_to_the_fallback():
    switched = []
    gemini, groq = Provider("gemini", [PER_DAY]), Provider("groq")
    auto = FallbackAdapter(gemini, groq, clock=Clock(), on_switch=switched.append)
    assert await auto.decide(turn(), []) == FinalAnswer("groq")
    assert auto.model == "groq" and switched == ["daily quota used up"]


async def test_the_primary_is_left_alone_until_its_cooldown_ends():
    clock = Clock()
    gemini, groq = Provider("gemini", [PER_DAY]), Provider("groq")
    auto = FallbackAdapter(gemini, groq, clock=clock)
    await auto.decide(turn(), [])
    clock.now = PER_DAY_COOLDOWN - 1
    assert await auto.decide(turn(), []) == FinalAnswer("groq")
    assert gemini.calls == 1  # not asked again inside the cooldown
    clock.now = PER_DAY_COOLDOWN
    assert await auto.decide(turn(), []) == FinalAnswer("gemini")
    assert auto.model == "gemini"


async def test_a_per_minute_limit_has_a_short_cooldown():
    clock = Clock()
    auto = FallbackAdapter(Provider("gemini", [PER_MINUTE]), Provider("groq"), clock=clock)
    assert await auto.decide(turn(), []) == FinalAnswer("groq")
    clock.now = PER_MINUTE_COOLDOWN
    assert await auto.decide(turn(), []) == FinalAnswer("gemini")


async def test_a_switched_question_finishes_on_the_fallback():
    """Gemini 3 can't continue tool calls another model made, so switching
    back waits for the next question even if the cooldown has ended."""
    clock = Clock()
    gemini, groq = Provider("gemini", [PER_MINUTE]), Provider("groq")
    auto = FallbackAdapter(gemini, groq, clock=clock)
    messages = turn()
    await auto.decide(messages, [])
    messages += [{"role": "tool_call", "name": "read_file", "arguments": {}},
                 {"role": "tool_result", "name": "read_file", "content": "x", "is_error": False}]
    clock.now = PER_MINUTE_COOLDOWN * 10
    assert await auto.decide(messages, []) == FinalAnswer("groq")
    assert gemini.calls == 1
    assert await auto.decide(turn(), []) == FinalAnswer("gemini")  # the next question


async def test_other_errors_are_not_hidden_by_a_switch():
    groq = Provider("groq")
    auto = FallbackAdapter(Provider("gemini", ["400 INVALID_ARGUMENT: bad schema"]), groq, clock=Clock())
    with pytest.raises(RuntimeError, match="INVALID_ARGUMENT"):
        await auto.decide(turn(), [])
    assert groq.calls == 0


async def test_when_both_are_limited_the_fallbacks_error_surfaces():
    auto = FallbackAdapter(Provider("gemini", [PER_DAY]), Provider("groq", ["429 rate_limit_exceeded"]),
                           clock=Clock())
    with pytest.raises(RuntimeError, match="rate_limit_exceeded"):
        await auto.decide(turn(), [])


def test_setting_the_system_prompt_reaches_both():
    """The eval's baseline sets a no-tools prompt; it must apply whichever answers."""
    gemini, groq = Provider("gemini"), Provider("groq")
    auto = FallbackAdapter(gemini, groq)
    auto.system_prompt = "no tools"
    assert gemini.system_prompt == groq.system_prompt == auto.system_prompt == "no tools"


# --- Which providers auto uses, by the keys that are set ---------------------


@pytest.mark.parametrize("keys, expected", [
    ({"GOOGLE_API_KEY", "GROQ_API_KEY"}, FallbackAdapter),
    ({"GOOGLE_API_KEY"}, GeminiAdapter),  # a fresh clone with a free key: as before
    ({"GROQ_API_KEY"}, GroqAdapter),
])
def test_auto_uses_the_keys_that_are_set(monkeypatch, keys, expected):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    for k in ("GOOGLE_API_KEY", "GROQ_API_KEY"):
        if k in keys:
            monkeypatch.setenv(k, "dummy-not-used")
        else:
            monkeypatch.delenv(k, raising=False)
    adapter = get_adapter()  # auto is the default
    assert type(adapter) is expected
    if expected is FallbackAdapter:
        assert isinstance(adapter.primary, GeminiAdapter) and isinstance(adapter.fallback, GroqAdapter)


def test_auto_with_no_keys_names_both_options(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY .* GROQ_API_KEY"):
        get_adapter("auto")


def test_naming_a_provider_still_means_only_that_one(monkeypatch):
    """The eval names its provider, so its results never mix models."""
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy-not-used")
    monkeypatch.setenv("GROQ_API_KEY", "dummy-not-used")
    assert type(get_adapter("gemini")) is GeminiAdapter


# --- The CLI says when it switched --------------------------------------------


def test_the_cli_says_when_it_moves_to_groq(monkeypatch, capsys, sample_repo):
    from conduit.host import cli

    class SpentGemini(StubAdapter):
        model = "gemini-3.6-flash"

        async def decide(self, messages, tool_schemas):
            raise RuntimeError(PER_DAY)

    groq = StubAdapter([ToolCall("read_file", {"path": "src/auth.py", "end_line": 2}), FinalAnswer("from groq")])
    groq.model = "openai/gpt-oss-120b"
    monkeypatch.setattr(cli, "get_adapter", lambda provider: FallbackAdapter(SpentGemini(), groq))
    monkeypatch.setattr(sys, "argv", ["conduit", "--repo-root", str(sample_repo), "q"])
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    out = capsys.readouterr()
    assert exit_info.value.code == 0
    assert "Gemini daily quota used up: continuing on Groq, openai/gpt-oss-120b" in out.err
    assert out.err.count("continuing on Groq") == 1  # once per switch, not per step
    assert "auto (gemini, then groq" in out.out and out.out.rstrip().endswith("from groq")
