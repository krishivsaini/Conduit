#!/usr/bin/env python3
"""Run the Conduit evaluation (§12) through Conduit's OWN host.

Unlike a generic harness, this measures exactly what the project claims: that
the model-agnostic host, driving the server's discovered tools, can answer
realistic codebase questions. Each question is run through run_turn (default
provider: gemini), and the final answer is graded against the expected value by
case-insensitive substring match. A Markdown report is written to eval/results.md.

    uv run python eval/run_eval.py                 # gemini, sample-repo
    uv run python eval/run_eval.py --provider ollama
"""

from __future__ import annotations

import argparse
import asyncio
import time
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

from conduit.host.client import MCPCodebaseClient, conduit_server_params
from conduit.host.llm.adapter import get_adapter
from conduit.host.loop import run_turn

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_env() -> None:
    try:
        from dotenv import find_dotenv, load_dotenv

        load_dotenv(find_dotenv(usecwd=True))
    except Exception:
        pass


def parse_pairs(eval_file: Path) -> list[tuple[str, str]]:
    tree = ET.parse(eval_file)
    pairs = []
    for qa in tree.getroot().findall("qa_pair"):
        q = (qa.findtext("question") or "").strip()
        a = (qa.findtext("answer") or "").strip()
        if q and a:
            pairs.append((q, a))
    return pairs


def grade(expected: str, answer: str) -> bool:
    """Direct (lenient) string comparison: expected appears in the answer."""
    return expected.strip().lower() in (answer or "").lower()


def _is_rate_limit(err: str) -> bool:
    return any(t in err.lower() for t in ("429", "resource_exhausted", "quota", "rate limit"))


async def run(provider: str, repo_root: str, eval_file: Path, output: Path, delay: float) -> None:
    pairs = parse_pairs(eval_file)
    adapter = get_adapter(provider)
    model = getattr(adapter, "model", provider)

    rows = []
    async with MCPCodebaseClient(conduit_server_params(repo_root)) as client:
        for i, (question, expected) in enumerate(pairs, 1):
            answer, steps, err = "", 0, None
            for attempt in range(5):
                try:
                    result = await run_turn(client, adapter, question + " Be concise.")
                    answer, steps, err = result.answer.strip(), len(result.steps), None
                    break
                except Exception as e:  # noqa: BLE001 — transient provider/API errors
                    err = str(e)
                    # Free-tier rate limits need a real cool-down, not a short retry.
                    await asyncio.sleep(45 if _is_rate_limit(err) else 3 * (attempt + 1))
            ok = grade(expected, answer)
            rows.append((i, question, expected, answer, steps, ok, err))
            note = "" if not err else f"  [error: {err[:70]}]"
            print(f"[{i:2}/{len(pairs)}] {'PASS' if ok else 'FAIL'}  expected={expected!r}  ({steps} tool calls){note}")
            await asyncio.sleep(delay)  # space calls under free-tier RPM

    passed = sum(1 for r in rows if r[5])
    _write_report(output, provider, model, rows, passed)
    print(f"\nAccuracy: {passed}/{len(rows)}  ->  {output}")


def _write_report(output: Path, provider: str, model: str, rows, passed: int) -> None:
    total = len(rows)
    lines = [
        "# Conduit evaluation results",
        "",
        f"- **Date:** {date.today().isoformat()}",
        f"- **Provider / model:** {provider} / {model}",
        f"- **Server target:** sample-repo/",
        f"- **Accuracy:** {passed}/{total} ({100*passed//total if total else 0}%)",
        "",
        "Scored by eval/run_eval.py: each question is answered through Conduit's host",
        "(discovering and driving the server's tools), graded by case-insensitive",
        "substring match against the expected answer.",
        "",
        "| # | Expected | Got | Tool calls | Result |",
        "|---|---|---|---|---|",
    ]
    for i, _q, expected, answer, steps, ok, err in rows:
        got = (answer or "").replace("\n", " ").replace("|", "\\|")
        if not got and err:
            got = f"_(error: {err[:60]})_"
        if len(got) > 80:
            got = got[:77] + "…"
        lines.append(f"| {i} | `{expected}` | {got} | {steps} | {'✅' if ok else '❌'} |")
    lines.append("")
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    _load_env()
    parser = argparse.ArgumentParser(description="Run the Conduit evaluation through the host")
    parser.add_argument("--provider", default="gemini", help="gemini | ollama")
    parser.add_argument("--repo-root", default=str(REPO_ROOT / "sample-repo"))
    parser.add_argument("--eval-file", default=str(REPO_ROOT / "eval" / "evaluation.xml"))
    parser.add_argument("--output", default=str(REPO_ROOT / "eval" / "results.md"))
    parser.add_argument("--delay", type=float, default=6.0, help="Seconds between questions (free-tier spacing)")
    args = parser.parse_args()
    asyncio.run(run(args.provider, args.repo_root, Path(args.eval_file), Path(args.output), args.delay))


if __name__ == "__main__":
    main()
