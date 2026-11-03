"""Replay adapter — plays back a recorded real-model run against the live server.

The free-tier model quota makes live runs scarce, so tests should not need them.
This adapter replays the decisions a real model made (from a transcript
recorded by scripts/record_transcripts.py) through the real host loop and the
real MCP server, and checks that each tool result the server returns today is
byte-for-byte the one the model saw when the run was recorded.

That gives two things without a single model call:
  * a regression test for the server: if a tool's output changes, the replay
    diverges and says exactly where;
  * a guarantee that the web demo's recorded runs still show what the server
    really returns, since the page replays those same transcripts.
"""

from __future__ import annotations

from typing import Any

from .adapter import Decision, FinalAnswer, LLMAdapter, Message, ToolCall


class ReplayDivergence(AssertionError):
    """The live server answered a recorded tool call differently."""


class ReplayAdapter(LLMAdapter):
    """Replays one recorded transcript's decisions, verifying each tool result.

    Args:
        transcript: A transcript dict as written by record_transcripts.py, with
            ``steps`` (each ``name``, ``arguments``, ``result_text``,
            ``is_error``) and the final ``answer``.
    """

    def __init__(self, transcript: dict[str, Any]) -> None:
        self._transcript = transcript
        self._steps = transcript["steps"]
        self._answer = transcript["answer"]
        self._turn = 0

    async def decide(self, messages: list[Message], tool_schemas: list[dict[str, Any]]) -> Decision:
        if self._turn > 0:
            self._check(self._turn - 1, messages)
        if self._turn < len(self._steps):
            step = self._steps[self._turn]
            self._turn += 1
            return ToolCall(name=step["name"], arguments=dict(step["arguments"]))
        self._turn += 1
        return FinalAnswer(text=self._answer)

    def _check(self, index: int, messages: list[Message]) -> None:
        """Compare the live result of recorded step ``index`` to the recording."""
        recorded = self._steps[index]
        results = [m for m in messages if m["role"] == "tool_result"]
        if len(results) <= index:
            raise ReplayDivergence(f"step {index + 1} ({recorded['name']}) produced no result")
        live = results[index]
        if live["is_error"] != recorded["is_error"] or live["content"] != recorded["result_text"]:
            raise ReplayDivergence(
                f"step {index + 1} {recorded['name']}({recorded['arguments']}) diverged from the "
                f"recording.\n  recorded: {recorded['result_text'][:300]!r}\n"
                f"  live:     {live['content'][:300]!r}\n"
                + self._rerecord_hint()
            )

    def _rerecord_hint(self) -> str:
        index = self._transcript.get("index")
        if "caption" in self._transcript and index is not None:  # a web-demo transcript
            return ("If the change is intended, re-record this run: "
                    f"uv run python scripts/record_transcripts.py --redo {index}")
        return "If the change is intended, re-record this run with the tool that produced it."
