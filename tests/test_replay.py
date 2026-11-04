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

ROOT = Path(__file__).resolve().parents[1]
TRANSCRIPTS = json.loads((ROOT / "conduit" / "web" / "static" / "transcripts.json").read_text())["transcripts"]


def _eval_runs() -> list[tuple[str, dict]]:
    """Real eval runs on the frozen sample repo that recorded a trace, from every
    provider (eval/results[.scope].<provider>.json). Baselines have no trace; the
    conduit suite serves this repo, which changes every commit, so it isn't
    replayable."""
    from tests.eval_helpers import load_run_eval

    ev = load_run_eval()
    runs = []
    for path in sorted((ROOT / "eval").glob("results.*.json")):
        label = ".".join(path.name.split(".")[1:-1])  # gemini, groq, scope.groq, ...
        if label.startswith("conduit") or label.endswith("baseline"):
            continue
        rows = ev.load_checkpoint(path).values()  # other rubrics load as empty
        runs += [(label, r) for r in rows if r.get("reply") and not r.get("error")]
    return runs


# The demo's recorded runs, plus every real eval run that kept its tool trace.
CASES = [pytest.param(t, id=f"demo-q{t['index']}") for t in TRANSCRIPTS] + [
    pytest.param({"question": r["question"], "steps": r["steps"], "answer": r["reply"]},
                 id=f"eval-{provider}-q{r['index']}")
    for provider, r in _eval_runs()
]


@pytest.mark.parametrize("transcript", CASES)
async def test_recorded_run_replays_identically(sample_repo, transcript):
    async with MCPCodebaseClient(conduit_server_params(sample_repo)) as client:
        result = await run_turn(client, ReplayAdapter(transcript), transcript["question"])

    assert [(s.name, s.arguments) for s in result.steps] == [
        (s["name"], s["arguments"]) for s in transcript["steps"]
    ]
    assert result.answer == transcript["answer"]
    if "expected" in transcript:  # the demo labels its runs as matching the key
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
            data = path.read_bytes()
            if path.suffix in {".py", ".md"}:
                data += b"\n# edited after the recording\n"
            dest.write_bytes(data)

    with pytest.raises(ReplayDivergence, match="diverged from the recording"):
        async with MCPCodebaseClient(conduit_server_params(changed)) as client:
            await run_turn(client, ReplayAdapter(transcript), transcript["question"])
