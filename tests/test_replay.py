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
STATIC = ROOT / "conduit" / "web" / "static"
TRANSCRIPTS = json.loads((STATIC / "transcripts.json").read_text())["transcripts"]
# Recorded against Conduit itself at one commit, with some paths denied.
CONDUIT = json.loads((STATIC / "transcripts.conduit.json").read_text())


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


@pytest.fixture(scope="module")
def conduit_snapshot(tmp_path_factory):
    """This repository exactly as it was when the demo's Conduit runs were recorded."""
    from tests.eval_helpers import load_repo_snapshot

    snapshot = load_repo_snapshot()
    try:
        return snapshot.extract(CONDUIT["commit"], tmp_path_factory.mktemp("conduit") / "repo")
    except (LookupError, FileNotFoundError) as exc:  # no git, or a shallow clone
        pytest.skip(f"can't extract the recorded commit: {exc}")


@pytest.mark.parametrize("transcript", CONDUIT["transcripts"], ids=lambda t: f"conduit-q{t['index']}")
async def test_a_recorded_run_on_conduit_replays_against_its_commit(conduit_snapshot, transcript):
    params = conduit_server_params(conduit_snapshot, deny=CONDUIT["deny"])
    async with MCPCodebaseClient(params) as client:
        result = await run_turn(client, ReplayAdapter(transcript), transcript["question"])
    assert [(s.name, s.arguments) for s in result.steps] == [
        (s["name"], s["arguments"]) for s in transcript["steps"]
    ]
    assert result.answer == transcript["answer"]


def test_the_conduit_recordings_are_pinned_and_keep_the_answer_key_hidden():
    assert len(CONDUIT["commit"]) == 40 and "eval/" in CONDUIT["deny"]
    # The snapshot is tracked files only; nothing in it was ever a local secret.
    refused = [s for t in CONDUIT["transcripts"] for s in t["steps"] if s["is_error"]]
    assert any("deny-list" in s["result_text"] and "eval/" in str(s["arguments"]) for s in refused)


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


def test_a_snapshot_holds_tracked_files_only(conduit_snapshot):
    """A recording must never have seen a local .env, untracked notes, or the
    gitignored build plan: git archive only writes what the commit tracks."""
    names = {p.relative_to(conduit_snapshot).as_posix() for p in conduit_snapshot.rglob("*")}
    assert "conduit/server/indexer.py" in names and "README.md" in names
    assert not {".env", "CONDUIT_BUILD_PLAN.md", ".venv", ".kilo", ".learn", ".git"} & names
    assert not any(n.startswith(("brag-output", ".kilo/", ".learn/")) for n in names)


def test_the_file_count_on_the_page_is_the_snapshots(conduit_snapshot):
    assert CONDUIT["files"] == sum(1 for p in conduit_snapshot.rglob("*") if p.is_file())
