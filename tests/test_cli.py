"""The CLI's user-facing behaviour.

The CLI is the README's first command, so its failure modes are the first thing
a new user meets. Configuration problems must be one-line messages with a
non-zero exit status (never a traceback), tool calls must print as they land
rather than after the turn ends, and refusals must name the boundary that fired.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys

import pytest

from conduit.host import cli
from conduit.host.llm.adapter import FinalAnswer, ToolCall
from conduit.host.llm.stub import StubAdapter
from conduit.host.loop import ToolInvocation


def run_cli(*args: str, cwd, drop: tuple[str, ...] = (), **env: str) -> subprocess.CompletedProcess:
    """Run the real entry point in a subprocess, as a user would."""
    environ = {k: v for k, v in os.environ.items() if k not in drop}
    environ.update(env)
    return subprocess.run(
        [sys.executable, "-m", "conduit.host.cli", *args],
        cwd=cwd, env=environ, capture_output=True, text=True, timeout=60,
    )


def assert_no_traceback(proc: subprocess.CompletedProcess) -> None:
    assert "Traceback" not in proc.stdout + proc.stderr


# --- Configuration problems: a sentence and an exit status, not a traceback --


def test_missing_api_key_explains_how_to_get_one(tmp_path, sample_repo):
    # cwd=tmp_path so no project .env is found, as on a fresh clone.
    proc = run_cli("--repo-root", str(sample_repo), "hi",
                   cwd=tmp_path, drop=("GOOGLE_API_KEY", "LLM_PROVIDER"))
    assert proc.returncode == 2
    assert "GOOGLE_API_KEY is not set" in proc.stderr
    assert "aistudio.google.com" in proc.stderr
    assert_no_traceback(proc)


def test_unknown_provider_flag_is_rejected_up_front(tmp_path):
    proc = run_cli("--provider", "openai", "hi", cwd=tmp_path)
    assert proc.returncode == 2
    assert "invalid choice: 'openai'" in proc.stderr
    assert_no_traceback(proc)


def test_unknown_provider_from_the_environment_is_a_message(tmp_path, sample_repo):
    # argparse checks the flag but not the $LLM_PROVIDER default.
    proc = run_cli("--repo-root", str(sample_repo), "hi", cwd=tmp_path, LLM_PROVIDER="openai")
    assert proc.returncode == 2
    assert "unknown LLM_PROVIDER 'openai'" in proc.stderr
    assert "stub" not in proc.stderr  # a test-only detail has no place in a user message
    assert_no_traceback(proc)


def test_missing_repository_fails_before_anything_else(tmp_path):
    # No API key either: the repo check must run first, so this reports the
    # path — the problem the user can see — rather than the key.
    proc = run_cli("--repo-root", str(tmp_path / "nope"), "hi",
                   cwd=tmp_path, drop=("GOOGLE_API_KEY", "LLM_PROVIDER"))
    assert proc.returncode == 2
    assert "repository not found" in proc.stderr
    assert "GOOGLE_API_KEY" not in proc.stderr
    assert_no_traceback(proc)


# --- A turn: streamed, with refusals named ---------------------------------


class RecordingStub(StubAdapter):
    """A stub that logs each model call, so the test can see what was printed
    between calls."""

    def __init__(self, script, events):
        super().__init__(script)
        self.events = events

    async def decide(self, messages, tool_schemas):
        self.events.append("model")
        return await super().decide(messages, tool_schemas)


def test_tool_calls_print_as_they_land_not_after_the_turn(monkeypatch, capsys, sample_repo):
    events: list[str] = []
    stub = RecordingStub(
        [
            ToolCall("search_code", {"query": "authenticate"}),
            ToolCall("read_file", {"path": ".env"}),
            FinalAnswer("False — the server refused to read it."),
        ],
        events,
    )
    real_print_step = cli._print_step

    def recording_print_step(index, step, style):
        events.append(f"print step {index}")
        real_print_step(index, step, style)

    monkeypatch.setattr(cli, "get_adapter", lambda provider: stub)
    monkeypatch.setattr(cli, "_print_step", recording_print_step)
    monkeypatch.setattr(sys, "argv", ["conduit", "--repo-root", str(sample_repo), "can you read .env?"])

    with pytest.raises(SystemExit) as exit_info:
        cli.main()

    assert exit_info.value.code == 0
    # Each step is on screen before the next model call starts — streamed, not
    # batched at the end of the turn.
    assert events == ["model", "print step 1", "model", "print step 2", "model"]

    out = capsys.readouterr().out
    assert "refused by the secrets deny-list" in out
    assert out.rstrip().endswith("False — the server refused to read it.")


def test_a_failed_turn_exits_non_zero_with_a_fix(monkeypatch, capsys, sample_repo):
    class Exhausted(StubAdapter):
        async def decide(self, messages, tool_schemas):
            raise RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded")

    monkeypatch.setattr(cli, "get_adapter", lambda provider: Exhausted())
    monkeypatch.setattr(sys, "argv", ["conduit", "--repo-root", str(sample_repo), "hi"])

    with pytest.raises(SystemExit) as exit_info:
        cli.main()

    assert exit_info.value.code == 1
    err = capsys.readouterr().err
    assert "rate limited" in err and "--provider ollama" in err


# --- The pieces -------------------------------------------------------------


@pytest.mark.parametrize(
    "server_text, boundary",
    [
        ("Error executing tool read_file: path '.env' is excluded by the server's "
         "secrets deny-list and cannot be accessed.", "secrets deny-list"),
        ("Error executing tool read_file: path '../../etc/passwd' is outside the "
         "repo root.", "repo-root confinement"),
    ],
)
def test_refusals_name_the_boundary_that_fired(capsys, server_text, boundary):
    step = ToolInvocation("read_file", {"path": "x"}, server_text, is_error=True)
    cli._print_step(1, step, cli._Style(io.StringIO()))
    out = capsys.readouterr().out
    assert f"refused by the {boundary}" in out
    assert "Error executing tool" not in out  # transport prefix is noise to a reader


def test_provider_errors_become_the_next_thing_to_do(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "tiny:1b")
    assert "ollama pull tiny:1b" in cli._explain(
        "ollama", Exception("model 'tiny:1b' not found (status code: 404)"))
    assert "ollama serve" in cli._explain(
        "ollama", ConnectionError("Failed to connect to Ollama."))
    assert "--provider ollama" in cli._explain(
        "gemini", Exception("429 RESOURCE_EXHAUSTED"))


class FakeTerminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_colour_only_on_a_terminal_and_never_with_no_color(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert cli._Style(io.StringIO()).warn("x") == "x"          # piped: plain
    assert "\x1b[" in cli._Style(FakeTerminal()).warn("x")      # terminal: styled
    monkeypatch.setenv("NO_COLOR", "1")
    assert cli._Style(FakeTerminal()).warn("x") == "x"          # NO_COLOR wins
