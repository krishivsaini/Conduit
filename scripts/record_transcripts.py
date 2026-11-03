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
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

from conduit.host.client import MCPCodebaseClient, conduit_server_params
from conduit.host.llm.adapter import get_adapter
from conduit.host.loop import run_turn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVAL_FILE = PROJECT_ROOT / "eval" / "evaluation.xml"
OUTPUT = PROJECT_ROOT / "conduit" / "web" / "static" / "transcripts.json"

# 1-based indices into evaluation.xml. Chosen so the set covers search_code,
# read_file and list_symbols, includes one multi-hop question, and ends on the
# deny-list refusal — which is the point of the whole project.
DEFAULT_QUESTIONS = [2, 4, 5, 11, 12]

# Shown above each preset so a visitor knows what to watch for.
CAPTIONS = {
    2: "Finds a definition it was never told the location of",
    4: "Reads a specific value out of the source",
    5: "Uses the AST symbol index, not a text match",
    11: "Follows an import across two files",
    12: "Asks for a secret — and the deny-list refuses",
}


def _load_env() -> None:
    try:
        from dotenv import find_dotenv, load_dotenv

        load_dotenv(find_dotenv(usecwd=True))
    except Exception:
        pass


def _parse_pairs(eval_file: Path) -> list[tuple[str, str]]:
    """Reuse the eval runner's parser so both read the corpus identically.

    eval/ has no __init__.py (and `eval` shadows a builtin), so load it by path.
    """
    spec = importlib.util.spec_from_file_location("_run_eval", PROJECT_ROOT / "eval" / "run_eval.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module.parse_pairs(eval_file)


async def record(
    provider: str, repo_root: str, indices: list[int], delay: float, fresh: bool, redo: list[int]
) -> None:
    pairs = _parse_pairs(EVAL_FILE)
    adapter = get_adapter(provider)
    model = getattr(adapter, "model", provider)

    indices = list(dict.fromkeys([*indices, *redo]))
    selected = []
    for i in indices:
        if not 1 <= i <= len(pairs):
            raise SystemExit(f"question {i} is out of range (1..{len(pairs)})")
        selected.append((i, *pairs[i - 1]))

    # Keep anything already captured; a day's quota rarely covers the whole set.
    existing: dict[int, dict] = {}
    if not fresh and OUTPUT.exists():
        existing = {t["index"]: t for t in json.loads(OUTPUT.read_text())["transcripts"]}
        existing = {i: t for i, t in existing.items() if i not in redo}
        if existing:
            print(f"resuming: {len(existing)} transcript(s) already recorded\n")

    transcripts = []
    async with MCPCodebaseClient(conduit_server_params(repo_root)) as client:
        discovered = await client.discover_tools()
        tool_names = [t.name for t in discovered]
        print(f"provider: {provider} ({model})  |  discovered: {', '.join(tool_names)}\n")

        for n, (index, question, expected) in enumerate(selected, 1):
            if index in existing:
                print(f"[{n}/{len(selected)}] Q{index}: kept (recorded by {existing[index].get('model', '?')})")
                continue
            print(f"[{n}/{len(selected)}] Q{index}: {question[:70]}...")
            try:
                result = await run_turn(client, adapter, question + " Be concise.")
            except Exception as exc:  # noqa: BLE001 — quota/provider errors are expected
                print(f"      FAILED: {str(exc)[:120]}")
                print("      (stopping; re-run when the quota resets to finish the set)")
                break

            steps = [asdict(s) for s in result.steps]
            ok = expected.strip().lower() in result.answer.lower()
            transcripts.append(
                {
                    "index": index,
                    "question": question,
                    "caption": CAPTIONS.get(index, ""),
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

    merged = {**existing, **{t["index"]: t for t in transcripts}}
    if not merged:
        raise SystemExit("\nNothing recorded — not writing an empty transcripts file.")

    # Keep transcripts outside this run's selection too: recording one question
    # must not drop the others.
    ordered = [merged[i] for i in indices if i in merged]
    ordered += [merged[i] for i in sorted(merged) if i not in indices]
    missing = [i for i in indices if i not in merged]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(
            {
                "recorded": date.today().isoformat(),
                "provider": provider,
                "repo": "sample-repo/",
                "discovered_tools": tool_names,
                "transcripts": ordered,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    tail = f"  ({len(missing)} still missing: {missing} — re-run to fill in)" if missing else ""
    print(f"\nWrote {len(ordered)} transcript(s) -> {OUTPUT.relative_to(PROJECT_ROOT)}{tail}")


def main() -> None:
    _load_env()
    parser = argparse.ArgumentParser(description="Record real host runs for the web demo")
    parser.add_argument("--provider", default="gemini", help="gemini | ollama")
    parser.add_argument("--repo-root", default=str(PROJECT_ROOT / "sample-repo"))
    parser.add_argument(
        "--questions",
        type=int,
        nargs="*",
        default=DEFAULT_QUESTIONS,
        help="1-based indices into eval/evaluation.xml",
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
    asyncio.run(record(args.provider, args.repo_root, args.questions, args.delay, args.fresh, args.redo))


if __name__ == "__main__":
    main()
