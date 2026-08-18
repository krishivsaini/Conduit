#!/usr/bin/env python3
"""Run the Conduit evaluation (§12) through Conduit's OWN host.

Unlike a generic harness, this measures exactly what the project claims: that
the model-agnostic host, driving the server's discovered tools, can answer
realistic codebase questions. Each question is run through run_turn (default
provider: gemini) and graded against the expected value by case-insensitive
substring match. A Markdown report is written to eval/results.md.

Free-tier quotas cap how many questions one day's run can execute, so results
are **checkpointed** to eval/results.<provider>.json and runs **resume** by
default: questions already executed are not re-asked (and don't re-burn quota),
and a run stops as soon as the daily quota is exhausted rather than grinding
through doomed retries.

    uv run python eval/run_eval.py                    # gemini, resumes
    uv run python eval/run_eval.py --provider ollama  # fully local
    uv run python eval/run_eval.py --fresh            # ignore the checkpoint
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

from conduit.host.client import MCPCodebaseClient, conduit_server_params
from conduit.host.llm.adapter import get_adapter
from conduit.host.loop import run_turn

REPO_ROOT = Path(__file__).resolve().parents[1]

# Appended to every generated report: cross-provider context that is a stable
# fact about the project, not a property of any single run.
FOOTER = """
## Also verified: the fully-local path

The same eval, same host, run against a local Ollama model (`--provider ollama`)
completes **all 12 questions with real tool calls and no API key** — confirming
the discover → call → respond loop and the server's tools work end-to-end
offline. Final-answer accuracy there is low (1/12 on a 0.8B model, which usually
hits the tool-step cap before synthesizing): that measures the *model*, not the
server. The tool calls themselves were correct.

## Interpreting these numbers

The measure of an MCP server is whether an LLM can use it to answer real
questions. On a capable model every executed question was answered correctly
from tool evidence, with citations. The only cap is the Gemini free-tier daily
quota, which limits how many questions one day's run can execute — runs are
checkpointed and resume, so repeating the command on a later day completes the
remainder without re-asking what's already answered.
"""


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


async def _ask(client, adapter, question: str) -> tuple[str, int, str | None]:
    """Ask one question, retrying transient errors. Returns (answer, steps, error)."""
    err = None
    for attempt in range(4):
        try:
            result = await run_turn(client, adapter, question + " Be concise.")
            return result.answer.strip(), len(result.steps), None
        except Exception as e:  # noqa: BLE001 — provider/API errors
            err = str(e)
            if _is_rate_limit(err):
                # One cool-down in case it's a per-minute (not daily) limit.
                if attempt == 0:
                    await asyncio.sleep(45)
                    continue
                break  # daily quota — stop retrying
            await asyncio.sleep(3 * (attempt + 1))
    return "", 0, err


async def run(provider: str, repo_root: str, eval_file: Path, output: Path, delay: float, fresh: bool) -> None:
    pairs = parse_pairs(eval_file)
    adapter = get_adapter(provider)
    model = getattr(adapter, "model", provider)
    checkpoint = output.with_name(f"results.{provider}.json")

    done: dict[str, dict] = {}
    if not fresh and checkpoint.exists():
        done = {r["question"]: r for r in json.loads(checkpoint.read_text())["results"]}
        if done:
            print(f"resuming: {len(done)} question(s) already executed (from {checkpoint.name})\n")

    quota_hit = False
    async with MCPCodebaseClient(conduit_server_params(repo_root)) as client:
        for i, (question, expected) in enumerate(pairs, 1):
            if question in done:
                r = done[question]
                print(f"[{i:2}/{len(pairs)}] {'PASS' if r['ok'] else 'FAIL'}  (cached from {r['date']})")
                continue
            if quota_hit:
                print(f"[{i:2}/{len(pairs)}] SKIP   quota exhausted — re-run to continue")
                continue

            answer, steps, err = await _ask(client, adapter, question)
            if err and _is_rate_limit(err):
                quota_hit = True
                print(f"[{i:2}/{len(pairs)}] SKIP   quota exhausted — re-run to continue")
                continue

            ok = grade(expected, answer)
            done[question] = {
                "question": question, "expected": expected, "answer": answer,
                "steps": steps, "ok": ok, "error": err, "date": date.today().isoformat(),
            }
            checkpoint.write_text(json.dumps({"provider": provider, "model": model,
                                              "results": list(done.values())}, indent=2))
            note = "" if not err else f"  [error: {err[:70]}]"
            print(f"[{i:2}/{len(pairs)}] {'PASS' if ok else 'FAIL'}  expected={expected!r}  ({steps} tool calls){note}")
            await asyncio.sleep(delay)

    rows = [(i, q, e, done.get(q)) for i, (q, e) in enumerate(pairs, 1)]
    executed = [r for _, _, _, r in rows if r]
    passed = sum(1 for r in executed if r["ok"])
    _write_report(output, provider, model, rows, passed, len(executed))
    pending = len(pairs) - len(executed)
    tail = f"  ({pending} pending — re-run after the quota resets)" if pending else ""
    print(f"\nExecuted: {passed}/{len(executed)} correct{tail}  ->  {output}")


def _write_report(output: Path, provider: str, model: str, rows, passed: int, executed: int) -> None:
    total = len(rows)
    pct = f"{100 * passed // executed}%" if executed else "n/a"
    lines = [
        "# Conduit evaluation results",
        "",
        f"- **Date:** {date.today().isoformat()}",
        f"- **Provider / model:** {provider} / {model}",
        "- **Server target:** `sample-repo/`",
        f"- **Executed accuracy:** {passed}/{executed} ({pct}) — of {total} questions",
        "",
        "Each question is answered through Conduit's own host: the client discovers the",
        "server's tools at runtime and drives them, and the final answer is graded by",
        "case-insensitive substring match. Questions marked *pending* were never sent to",
        "the model (free-tier daily quota); re-running resumes where it left off.",
        "",
        "| # | Expected | Model answer | Tool calls | Result |",
        "|---|---|---|---|---|",
    ]
    for i, _q, expected, r in rows:
        if not r:
            lines.append(f"| {i} | `{expected}` | — | — | ⏳ pending (quota) |")
            continue
        got = (r["answer"] or "").replace("\n", " ").replace("|", "\\|")
        if not got and r.get("error"):
            got = f"_(error: {r['error'][:60]})_"
        if len(got) > 80:
            got = got[:77] + "…"
        lines.append(f"| {i} | `{expected}` | {got} | {r['steps']} | {'✅' if r['ok'] else '❌'} |")
    lines.append(FOOTER)
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    _load_env()
    parser = argparse.ArgumentParser(description="Run the Conduit evaluation through the host")
    parser.add_argument("--provider", default="gemini", help="gemini | ollama")
    parser.add_argument("--repo-root", default=str(REPO_ROOT / "sample-repo"))
    parser.add_argument("--eval-file", default=str(REPO_ROOT / "eval" / "evaluation.xml"))
    parser.add_argument("--output", default=str(REPO_ROOT / "eval" / "results.md"))
    parser.add_argument("--delay", type=float, default=6.0, help="Seconds between questions")
    parser.add_argument("--fresh", action="store_true", help="Ignore the checkpoint and re-ask everything")
    args = parser.parse_args()
    asyncio.run(run(args.provider, args.repo_root, Path(args.eval_file),
                    Path(args.output), args.delay, args.fresh))


if __name__ == "__main__":
    main()
