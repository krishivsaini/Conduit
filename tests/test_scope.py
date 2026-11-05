"""The scope rule's two halves: getting into the prompt, and being recognised."""

from __future__ import annotations

import pytest

from conduit.host.llm.adapter import SYSTEM_PROMPT
from conduit.host.llm.fallback import FallbackAdapter
from conduit.host.llm.stub import StubAdapter
from conduit.host.scope import SCOPE_RULE, apply_scope, declined


@pytest.mark.parametrize("answer, reason", [
    ("OFF_TOPIC: geography isn't about this repository", "geography isn't about this repository"),
    ("**OFF_TOPIC:** not about the repo", "not about the repo"),
    ("`OFF_TOPIC`: recipes", "recipes"),
    ("I can only help with this repository.\nOFF_TOPIC: cooking", "cooking"),
    ("OFF_TOPIC", "not about this repository"),
])
def test_a_decline_is_recognised_however_it_is_formatted(answer, reason):
    assert declined(answer) == reason


@pytest.mark.parametrize("answer", [
    "src/payments.py\nANSWER: src/payments.py",
    "The marker OFF_TOPIC appears in conduit/host/scope.py",  # mentioned, not declared
    "",
])
def test_an_answer_is_not_mistaken_for_a_decline(answer):
    assert declined(answer) is None


def test_the_rule_is_added_once_and_keeps_the_original_prompt():
    adapter = StubAdapter()
    apply_scope(apply_scope(adapter))
    assert adapter.system_prompt.startswith(SYSTEM_PROMPT)
    assert adapter.system_prompt.count(SCOPE_RULE) == 1


def test_the_rule_reaches_both_providers_behind_auto():
    gemini, groq = StubAdapter(), StubAdapter()
    apply_scope(FallbackAdapter(gemini, groq))
    assert SCOPE_RULE in gemini.system_prompt and SCOPE_RULE in groq.system_prompt



@pytest.mark.parametrize("scoped, shows", [(True, "Declined: not about this repository\n  ▌ recipes"),
                                          (False, "OFF_TOPIC: recipes")])
def test_the_cli_shows_a_decline_only_when_scoped(monkeypatch, capsys, sample_repo, scoped, shows):
    import sys

    from conduit.host import cli
    from conduit.host.llm.adapter import FinalAnswer

    stub = StubAdapter([FinalAnswer("OFF_TOPIC: recipes")])
    monkeypatch.setattr(cli, "get_adapter", lambda provider: stub)
    argv = ["conduit", "--repo-root", str(sample_repo), "--provider", "ollama", "dinner ideas?"]
    monkeypatch.setattr(sys, "argv", argv + (["--scoped"] if scoped else []))
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert shows in out
    assert (SCOPE_RULE in stub.system_prompt) is scoped
