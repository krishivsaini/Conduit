#!/usr/bin/env python3
"""Capture real host runs as JSON, for the web demo to replay instantly.

The public demo runs on a free-tier model quota, so it cannot afford to call a
model for every visitor. Instead the preset questions replay traces recorded
here — genuine `run_turn` output (tool calls, arguments, refusals, final
answer), captured once and committed. The page labels them as recorded; nothing
is hand-written or simulated.

Questions come from the existing evaluation corpus (eval/evaluation.xml) rather
than a separate demo script, so what the page shows is the same thing the eval
grades. Selection defaults to a curated subset that exercises each tool and ends
on the security refusal.

Free-tier quotas are per-model and per-day (a small daily cap; one question
costs several requests), so recording **resumes** like eval/run_eval.py
does: questions already captured are kept and skipped, and a quota failure stops
the run with whatever it got. Top the set up on a later day, or from another
model's quota, and the file fills in. Each transcript records the model that
produced it.

    uv run python scripts/record_transcripts.py                # gemini, curated subset
    uv run python scripts/record_transcripts.py --provider ollama
    uv run python scripts/record_transcripts.py --questions 1 4 11
    uv run python scripts/record_transcripts.py --redo 5       # re-record one, keep the rest
    uv run python scripts/record_transcripts.py --fresh        # re-record everything
    uv run python scripts/record_transcripts.py --repo conduit --provider groq
        # Conduit itself, at HEAD: extracted with git archive (tracked files only),
        # eval/ denied; the commit is stored so CI replays against the same tree
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

from conduit.host.client import MCPCodebaseClient, conduit_server_params
from conduit.host.llm.adapter import get_adapter
from conduit.host.loop import run_turn

import repo_snapshot  # noqa: E402 — scripts/ is on sys.path when run as a script

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC = PROJECT_ROOT / "conduit" / "web" / "static"


@dataclass(frozen=True)
class Target:
    """A repository the demo shows recorded runs for."""

    eval_file: Path
    output: Path
    default_questions: list[int]
    captions: dict[int, str]
    deny: tuple[str, ...] = ()
    snapshot: bool = False  # record against an extracted commit of this repo
    label: str = "sample-repo/"
    repo_root: Path = field(default=PROJECT_ROOT / "sample-repo")


TARGETS = {
    # The frozen sample repo. Chosen so the set covers search_code, read_file
    # and list_symbols, includes one multi-hop question, and ends on the
    # deny-list refusal — which is the point of the whole project.
    "sample": Target(
        PROJECT_ROOT / "eval" / "evaluation.xml", STATIC / "transcripts.json", [2, 4, 5, 11, 12],
        {
            2: "Finds a definition it was never told the location of",
            4: "Reads a specific value out of the source",
            5: "Uses the AST symbol index, not a text match",
            11: "Follows an import across two files",
            12: "Asks for a secret — and the deny-list refuses",
        },
    ),
    # Conduit itself, pinned to one commit. eval/ is denied as it is in the
    # eval's conduit suite, so the answer key can't be read.
    "conduit": Target(
        PROJECT_ROOT / "eval" / "evaluation.conduit.xml", STATIC / "transcripts.conduit.json", [5, 2, 9, 11],
        {
            5: "Finds a setting by what it does, in a real codebase",
            2: "Traces a behaviour to the exception it raises",
            9: "Counts across a package, for one exact answer",
            11: "Asks for the eval answer key — and a deny rule added for this deployment refuses",
        },
        deny=("eval/",), snapshot=True, label="Conduit (this repository)",
    ),
}


def _load_env() -> None:
    try:
        from dotenv import find_dotenv, load_dotenv

        load_dotenv(find_dotenv(usecwd=True))
    except Exception:
        pass


@lru_cache(maxsize=1)
def _run_eval():
    """The eval runner, so recordings parse and grade exactly as the eval does.

    eval/ has no __init__.py (and `eval` shadows a builtin), so load it by path.
    """
    spec = importlib.util.spec_from_file_location("_run_eval", PROJECT_ROOT / "eval" / "run_eval.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


async def record(
    provider: str, target: Target, indices: list[int], delay: float, fresh: bool, redo: list[int],
    commit: str = "HEAD",
) -> None:
    ev = _run_eval()
    pairs = ev.parse_pairs(target.eval_file)
    adapter = get_adapter(provider)
    model = getattr(adapter, "model", provider)
    output = target.output

    indices = list(dict.fromkeys([*indices, *redo]))
    selected = []
    for i in indices:
        if not 1 <= i <= len(pairs):
            raise SystemExit(f"question {i} is out of range (1..{len(pairs)})")
        selected.append((i, *pairs[i - 1]))

    # Keep anything already captured; a day's quota rarely covers the whole set.
    sha = None
    if target.snapshot:
        sha = repo_snapshot.resolve(commit)
        if not repo_snapshot.is_pushed(sha):
            print(f"warning: {sha[:7]} isn't on a remote branch yet; the page's link to it won't work until it is\n")

    existing: dict[int, dict] = {}
    if not fresh and output.exists():
        previous = json.loads(output.read_text())
        if previous.get("commit") != sha:
            # Recordings against another commit can't be replayed against this one.
            print(f"recorded against {str(previous.get('commit'))[:7]} before; re-recording all against {sha[:7]}\n")
        else:
            existing = {t["index"]: t for t in previous["transcripts"]}
            existing = {i: t for i, t in existing.items() if i not in redo}
        if existing:
            print(f"resuming: {len(existing)} transcript(s) already recorded\n")

    transcripts: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="conduit-snapshot-") as tmp:
        root = repo_snapshot.extract(sha, Path(tmp) / "repo") if sha else target.repo_root
        files = sum(1 for p in root.rglob("*") if p.is_file())
        tool_names = await _record_into(
            transcripts, adapter, provider, model, root, target, selected, existing, delay, ev
        )

    merged = {**existing, **{t["index"]: t for t in transcripts}}
    if not merged:
        raise SystemExit("\nNothing recorded — not writing an empty transcripts file.")

    # Keep transcripts outside this run's selection too: recording one question
    # must not drop the others.
    ordered = [merged[i] for i in indices if i in merged]
    ordered += [merged[i] for i in sorted(merged) if i not in indices]
    missing = [i for i in indices if i not in merged]

    payload: dict = {
        "recorded": date.today().isoformat(),
        "provider": provider,
        "repo": target.label,
        "discovered_tools": tool_names,
    }
    if sha:
        payload |= {"commit": sha, "deny": list(target.deny), "files": files}
    payload["transcripts"] = ordered
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tail = f"  ({len(missing)} still missing: {missing} — re-run to fill in)" if missing else ""
    print(f"\nWrote {len(ordered)} transcript(s) -> {output.relative_to(PROJECT_ROOT)}{tail}")


async def _record_into(transcripts, adapter, provider, model, root, target, selected, existing, delay, ev):
    async with MCPCodebaseClient(conduit_server_params(root, deny=target.deny)) as client:
        discovered = await client.discover_tools()
        tool_names = [t.name for t in discovered]
        print(f"provider: {provider} ({model})  |  serving: {target.label}  |  discovered: {', '.join(tool_names)}\n")

        for n, (index, question, expected) in enumerate(selected, 1):
            if index in existing:
                print(f"[{n}/{len(selected)}] Q{index}: kept (recorded by {existing[index].get('model', '?')})")
                continue
            print(f"[{n}/{len(selected)}] Q{index}: {question[:70]}...")
            try:
                result = await run_turn(client, adapter, question + ev.ANSWER_INSTRUCTION)
            except Exception as exc:  # noqa: BLE001 — quota/provider errors are expected
                print(f"      FAILED: {str(exc)[:120]}")
                print("      (stopping; re-run when the quota resets to finish the set)")
                break

            steps = [asdict(s) for s in result.steps]
            ok, _ = ev.grade(expected, result.answer)  # the eval's exact-match rubric
            transcripts.append(
                {
                    "index": index,
                    "question": question,
                    "caption": target.captions.get(index, ""),
                    "expected": expected,
                    "answer": result.answer.strip(),
                    "correct": ok,
                    "steps": steps,
                    "hit_step_limit": result.hit_step_limit,
                    # Per-transcript: the set may be filled in across days, and
                    # across models' separate free-tier quota buckets.
                    "model": model,
                    "recorded": date.today().isoformat(),
                }
            )
            marks = "".join("x" if s["is_error"] else "." for s in steps)
            print(f"      {len(steps)} tool call(s) [{marks}]  ->  {'PASS' if ok else 'FAIL'}")
            await asyncio.sleep(delay)
    return tool_names


def main() -> None:
    _load_env()
    parser = argparse.ArgumentParser(description="Record real host runs for the web demo")
    parser.add_argument("--provider", default="gemini", help="gemini | groq | ollama | auto")
    parser.add_argument("--repo", choices=sorted(TARGETS), default="sample",
                        help="sample: the bundled sample repo; conduit: this repository at --commit")
    parser.add_argument("--commit", default="HEAD", help="With --repo conduit: the commit to record against")
    parser.add_argument(
        "--questions",
        type=int,
        nargs="*",
        default=None,
        help="1-based indices into the target's question file (default: its curated set)",
    )
    parser.add_argument("--delay", type=float, default=6.0, help="Seconds between questions")
    parser.add_argument("--fresh", action="store_true", help="Re-record everything, ignoring what exists")
    parser.add_argument(
        "--redo",
        type=int,
        nargs="+",
        default=[],
        metavar="N",
        help="Re-record just these questions, keeping the rest (e.g. after a server change)",
    )
    args = parser.parse_args()
    target = TARGETS[args.repo]
    questions = args.questions if args.questions is not None else target.default_questions
    asyncio.run(record(args.provider, target, questions, args.delay, args.fresh, args.redo, args.commit))


if __name__ == "__main__":
    main()
