"""The eval's grader is strict, and the runner records what CI needs to replay.

The previous grader was a substring check, under which an expected "2" was
satisfied by any reply containing a 2. These tests pin the strict rubric, and
run the whole runner end-to-end with a scripted model (no quota).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from conduit.host.llm.adapter import Decision, FinalAnswer, LLMAdapter, Message, ToolCall
from tests.eval_helpers import load_run_eval

ev = load_run_eval()


# --- The grader -------------------------------------------------------------

@pytest.mark.parametrize("reply, expected", [
    ("It is defined on line 15.\nANSWER: 15", "15"),
    ("ANSWER: `src/auth.py`", "src/auth.py"),
    ("ANSWER: **False**", "False"),
    ("ANSWER: false.", "False"),
    ("**ANSWER:** token::bob::*****r2", "token::bob::*****r2"),
    ("**ANSWER: False**", "False"),
    ("ANSWER: *****r2", "*****r2"),
    ("ANSWER: \"amount below minimum of $0.50\"", "amount below minimum of $0.50"),
    ("first guess\nANSWER: 3\nactually\nANSWER: 2", "2"),        # the last ANSWER line wins
])
def test_grader_accepts_the_right_value_in_any_formatting(reply, expected):
    ok, _ = ev.grade(expected, reply)
    assert ok


@pytest.mark.parametrize("reply, expected", [
    ("There are 2 functions, so ANSWER: 12", "2"),                 # would pass a substring check
    ("ANSWER: 2 or 3", "2"),
    ("The answer is 2.", "2"),                                    # no ANSWER line at all
    ("ANSWER: src/auth.py and src/utils.py", "src/auth.py"),
    ("ANSWER: *****r2", "token::bob::*****r2"),
    ("ANSWER: Truee", "True"),
])
def test_grader_rejects_answers_a_substring_check_would_pass(reply, expected):
    ok, _ = ev.grade(expected, reply)
    assert not ok


def test_normalising_keeps_meaningful_asterisks():
    assert ev.normalize("*****r2") == "*****r2"
    assert ev.normalize("**`$10.50`**") == "$10.50"


# --- The runner, end to end -------------------------------------------------

class Scripted(LLMAdapter):
    """Answers question 13 correctly using tools, and question 17 wrongly."""

    model = "scripted"

    def __init__(self) -> None:
        self.saw_tools: list[bool] = []

    async def decide(self, messages: list[Message], tool_schemas: list[dict[str, Any]]) -> Decision:
        self.saw_tools.append(bool(tool_schemas))
        question = messages[0]["content"]
        steps = sum(m["role"] == "tool_call" for m in messages)
        if "bob signs in" in question:
            if steps == 0 and tool_schemas:
                return ToolCall("read_file", {"path": "src/auth.py"})
            return FinalAnswer("He gets a token.\nANSWER: token::bob::*****r2")
        return FinalAnswer("ANSWER: bob")


def test_the_baseline_is_told_it_has_no_tools():
    """Otherwise it follows the usual 'answer from tool evidence' prompt, announces
    a search it can't run, and scores 0 for reasons unrelated to what it knows."""
    inner = Scripted()
    assert "read-only tools" in inner.system_prompt
    ev.NoTools(inner)
    assert "no tools" in inner.system_prompt and "best guess" in inner.system_prompt


async def test_runner_grades_records_traces_and_reports(sample_repo, tmp_path):
    output = tmp_path / "results.md"
    eval_file = ev.REPO_ROOT / "eval" / "evaluation.xml"
    for baseline in (False, True):
        await ev.run("stub", str(sample_repo), eval_file, output, delay=0, fresh=True,
                     baseline=baseline, only={13, 17}, adapter=Scripted())

    with_tools = json.loads((tmp_path / "results.stub.json").read_text())
    rows = {r["index"]: r for r in with_tools["results"]}
    assert with_tools["rubric"] == ev.RUBRIC
    assert rows[13]["ok"] and not rows[17]["ok"]
    # The full tool trace is kept, so CI can replay the run against the server.
    assert [s["name"] for s in rows[13]["steps"]] == ["read_file"]
    assert rows[13]["steps"][0]["result_text"]

    baseline = json.loads((tmp_path / "results.stub.baseline.json").read_text())
    assert all(r["steps"] == [] for r in baseline["results"])   # the baseline used no tools

    report = output.read_text()
    assert "With tools:** 1/2 (50%)" in report
    assert "| 13 | `token::bob::*****r2` |" in report


async def test_a_checkpoint_from_another_rubric_is_not_resumed(tmp_path):
    old = tmp_path / "results.stub.json"
    old.write_text(json.dumps({"provider": "stub", "results": [{"question": "q", "ok": True}]}))
    assert ev.load_checkpoint(old) == {}


class KeyHunter(LLMAdapter):
    """A model that goes looking for the answer key instead of the code."""

    model = "key-hunter"

    async def decide(self, messages: list[Message], tool_schemas: list[dict[str, Any]]) -> Decision:
        tried = sum(m["role"] == "tool_call" for m in messages)
        hunts = [("read_file", {"path": "eval/evaluation.conduit.xml"}),
                 ("search_code", {"query": "<answer>"})]
        if tried < len(hunts):
            return ToolCall(*hunts[tried])
        return FinalAnswer("ANSWER: 8")


async def test_the_conduit_suite_hides_its_own_answer_key(tmp_path):
    suite = ev.SUITES["conduit"]
    output = tmp_path / "results.conduit.md"
    await ev.run("stub", str(suite.repo_root), suite.eval_file, output, delay=0, fresh=True,
                 baseline=False, only={1}, adapter=KeyHunter(), suite=suite)

    (row,) = json.loads((tmp_path / "results.conduit.stub.json").read_text())["results"]
    read, search = row["steps"]
    assert read["is_error"] and "deny-list" in read["result_text"]
    found = [m["path"] for m in json.loads(search["result_text"])["matches"]]
    assert not [p for p in found if p.startswith("eval/")]  # (this test file matches its own query)
    assert "this repository" in output.read_text()


# --- Pacing under a requests-per-minute limit ---------------------------------

PER_MINUTE = ("429 RESOURCE_EXHAUSTED. {'error': {'details': [{'quotaId': "
              "'GenerateRequestsPerMinutePerProjectPerModel-FreeTier'}, {'retryDelay': '15s'}]}}")
PER_DAY = ("429 RESOURCE_EXHAUSTED. {'error': {'details': [{'quotaId': "
           "'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}]}}")


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(round(seconds, 1))
        self.now += seconds


class Flaky(LLMAdapter):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        self.calls = 0

    async def decide(self, messages, tool_schemas):
        self.calls += 1
        if self.errors:
            raise RuntimeError(self.errors.pop(0))
        return FinalAnswer("ANSWER: ok")


async def test_model_calls_are_spaced_to_the_rpm_limit():
    t = FakeTime()
    paced = ev.Paced(Flaky([]), rpm=5, sleep=t.sleep, clock=t.clock)
    for _ in range(3):
        await paced.decide([], [])
    assert t.slept == [12.0, 12.0]  # 60 s / 5 requests, none before the first


async def test_a_per_minute_limit_is_waited_out_not_treated_as_the_end_of_the_day():
    t = FakeTime()
    inner = Flaky([PER_MINUTE, PER_MINUTE])
    paced = ev.Paced(inner, rpm=0, sleep=t.sleep, clock=t.clock)
    assert isinstance(await paced.decide([], []), FinalAnswer)
    assert inner.calls == 3 and t.slept == [17.0, 17.0]  # Gemini's retryDelay + 2 s


async def test_a_per_day_limit_stops_immediately():
    t = FakeTime()
    paced = ev.Paced(Flaky([PER_DAY]), rpm=0, sleep=t.sleep, clock=t.clock)
    with pytest.raises(RuntimeError, match="PerDay"):
        await paced.decide([], [])
    assert t.slept == []
