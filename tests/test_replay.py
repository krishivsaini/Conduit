"""Real recorded model runs, replayed against the live server — no model calls.

Each transcript in the web demo was produced by a real model (Gemini) driving
the real host. Replaying its decisions through today's loop and server checks
that every tool still returns exactly what the model saw, so the server can't
change behaviour silently, and the demo's recorded runs can't drift from what
the server really does. Runs offline, so it runs in CI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conduit.host.client import MCPCodebaseClient, conduit_server_params
from conduit.host.llm.replay import ReplayAdapter, ReplayDivergence
from conduit.host.loop import run_turn

TRANSCRIPTS = json.loads(
    (Path(__file__).resolve().parents[1] / "conduit" / "web" / "static" / "transcripts.json").read_text()
)["transcripts"]


@pytest.mark.parametrize("transcript", TRANSCRIPTS, ids=lambda t: f"eval-q{t['index']}")
async def test_recorded_run_replays_identically(sample_repo, transcript):
    async with MCPCodebaseClient(conduit_server_params(sample_repo)) as client:
        result = await run_turn(client, ReplayAdapter(transcript), transcript["question"])

    assert [(s.name, s.arguments) for s in result.steps] == [
        (s["name"], s["arguments"]) for s in transcript["steps"]
    ]
    assert result.answer == transcript["answer"]
    assert transcript["expected"].lower() in result.answer.lower()


async def test_replay_notices_when_the_server_changes(sample_repo, tmp_path):
    """The check must actually bite: serve a repo where one recorded file has
    changed, and the replay must stop at the first step whose result differs."""
    transcript = next(t for t in TRANSCRIPTS if any(s["name"] == "read_file" for s in t["steps"]))
    changed = tmp_path / "repo"
    changed.mkdir()
    for path in sample_repo.rglob("*"):
        if path.is_file():
            dest = changed / path.relative_to(sample_repo)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(path.read_text() + "\n# edited after the recording\n")

    with pytest.raises(ReplayDivergence, match="diverged from the recording"):
        async with MCPCodebaseClient(conduit_server_params(changed)) as client:
            await run_turn(client, ReplayAdapter(transcript), transcript["question"])
