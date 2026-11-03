#!/usr/bin/env python3
"""Run the Conduit evaluation (§12) through Conduit's OWN host.

This measures exactly what the project claims: that the model-agnostic host,
driving the server's discovered tools, answers realistic codebase questions.

Grading is strict. Each question asks for a specific form (a number, a path,
True/False, an exact string), and the model must end its reply with a line
``ANSWER: <value>``. That value is compared to the expected answer exactly, after
removing only formatting (surrounding backticks, quotes, bold, a trailing full
stop, letter case). An expected "2" is not satisfied by "line 12" or "2 or 3".

``--baseline`` asks the same model the same questions with **no tools and no
repository context**. The gap between the two runs is what the server adds.

Free-tier quotas cap how many questions a day's run can execute, so results are
checkpointed to eval/results.<provider>[.baseline].json and runs resume: answered
questions are not re-asked, and a run stops as soon as the quota is exhausted.
Each checkpoint row keeps the full tool trace, so tests/test_replay.py replays
real eval runs against the live server in CI, with no model calls.

    uv run python eval/run_eval.py                      # gemini, with tools
    uv run python eval/run_eval.py --baseline           # same model, no tools
    uv run python eval/run_eval.py --questions 13 14    # a subset
    uv run python eval/run_eval.py --provider ollama    # fully local
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from conduit.host.client import MCPCodebaseClient, conduit_server_params
from conduit.host.llm.adapter import Decision, LLMAdapter, Message, get_adapter
from conduit.host.loop import run_turn

REPO_ROOT = Path(__file__).resolve().parents[1]

# Bump when grading changes. A checkpoint written under another rubric is not
# resumed: its verdicts don't mean the same thing.
RUBRIC = 2

ANSWER_INSTRUCTION = (
    " Be concise. When you are done, end your reply with a final line of the form "
    "'ANSWER: <value>', with the value in exactly the form the question asks for."
)

FOOTER = """
## How to read these numbers

The measure of an MCP server is whether a model can use it to answer real
questions it could not answer alone. The **with tools** column is the full
system: discovered tools, the repo tree as context, a step budget. The
**baseline** column is the same model and prompt with no tools and no repo, so
the gap between them is what the server contributes. Grading is exact (see the
top of eval/run_eval.py), so a verbose answer that happens to contain the right
number does not count.

Questions 13–20 are multi-step: each needs evidence from more than one file, or
reading past a misleading docstring. Every expected answer is checked against the
sample repo's code actually executing, in tests/test_eval_answers.py.

The Gemini free tier allows about 5 requests a minute and a small daily cap, so
a full run can span days. Runs resume where they stopped; *pending* rows were
never sent to the model and are not scored. Results recorded under the earlier,
lenient substring rubric are kept in eval/results.gemini.v1.json.
"""

# Captures an optional bold opener, an optional bold closer before the colon, and
# everything after the colon.
_ANSWER_LINE = re.compile(r"^[\s>]*(\*\*|__)?\s*answer\s*(\*\*|__)?\s*:(.*)$", re.IGNORECASE | re.MULTILINE)
_PAIRED = ("**", "__", "`", '"', "'")


def extract_answer(reply: str) -> str | None:
    """The value on the last 'ANSWER:' line of a reply, or None if there is none.

    Models bold the label in different places: "**ANSWER:** x" closes the bold
    after the colon, "**ANSWER: x**" around the whole line. Only that label
    markup is removed here, so asterisks belonging to the value ("*****r2") stay.
    """
    found = _ANSWER_LINE.findall(reply or "")
    if not found:
        return None
    opening, closing, value = found[-1]
    value = value.strip()
    if opening and not closing:
        if value.startswith(opening):
            value = value[len(opening):].strip()
        elif value.endswith(opening):
            value = value[: -len(opening)].strip()
    return value or None


def normalize(value: str) -> str:
    """Strip formatting, not content: wrapping markup, a final full stop, case."""
    v = " ".join(value.split())
    changed = True
    while changed:
        changed = False
        for mark in _PAIRED:
            n = len(mark)
            if len(v) > 2 * n and v.startswith(mark) and v.endswith(mark):
                v, changed = v[n:-n].strip(), True
    if v.endswith(".") and not v.endswith(".."):
        v = v[:-1].rstrip()
    return v.casefold()


def grade(expected: str, reply: str) -> tuple[bool, str | None]:
    """Exact match of the reply's ANSWER line against the expected value."""
    got = extract_answer(reply)
    return (got is not None and normalize(got) == normalize(expected)), got


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


class NoTools(LLMAdapter):
    """The baseline: the same model, offered no tools."""

    def __init__(self, inner: LLMAdapter) -> None:
        self.inner = inner
        self.model = getattr(inner, "model", None)

    async def decide(self, messages: list[Message], tool_schemas: list[dict[str, Any]]) -> Decision:
        return await self.inner.decide(messages, [])


def _is_rate_limit(err: str) -> bool:
    return any(t in err.lower() for t in ("429", "resource_exhausted", "quota", "rate limit"))


async def _ask(client, adapter, question: str, baseline: bool) -> dict[str, Any]:
    """One question, retrying transient errors. Returns reply, steps and error."""
    err = None
    for attempt in range(4):
        try:
            result = await run_turn(
                client, adapter, question + ANSWER_INSTRUCTION,
                max_steps=1 if baseline else 8, attach_resources=not baseline,
            )
            return {"reply": result.answer.strip(), "steps": [asdict(s) for s in result.steps], "error": None}
        except Exception as e:  # noqa: BLE001 — provider/API errors
            err = str(e)
            if _is_rate_limit(err):
                if attempt == 0:          # one cool-down, in case it's the per-minute limit
                    await asyncio.sleep(45)
                    continue
                break                     # daily quota — stop retrying
            await asyncio.sleep(3 * (attempt + 1))
    return {"reply": "", "steps": [], "error": err}


def _checkpoint_path(output: Path, provider: str, baseline: bool) -> Path:
    return output.with_name(f"results.{provider}{'.baseline' if baseline else ''}.json")


def load_checkpoint(path: Path) -> dict[str, dict]:
    """Rows by question, from a checkpoint written under the current rubric."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if data.get("rubric") != RUBRIC:
        return {}
    return {r["question"]: r for r in data["results"]}


async def run(
    provider: str, repo_root: str, eval_file: Path, output: Path, delay: float,
    fresh: bool, baseline: bool, only: set[int] | None, adapter: LLMAdapter | None = None,
) -> None:
    pairs = parse_pairs(eval_file)
    base = adapter or get_adapter(provider)
    model = getattr(base, "model", provider)
    runner = NoTools(base) if baseline else base
    checkpoint = _checkpoint_path(output, provider, baseline)

    done = {} if fresh else load_checkpoint(checkpoint)
    if done:
        print(f"resuming: {len(done)} question(s) already answered (from {checkpoint.name})\n")

    quota_hit = False
    async with MCPCodebaseClient(conduit_server_params(repo_root)) as client:
        for i, (question, expected) in enumerate(pairs, 1):
            if only and i not in only:
                continue
            if question in done:
                print(f"[{i:2}] {'PASS' if done[question]['ok'] else 'FAIL'}  (cached from {done[question]['date']})")
                continue
            if quota_hit:
                print(f"[{i:2}] SKIP  quota exhausted — re-run to continue")
                continue

            r = await _ask(client, runner, question, baseline)
            if r["error"] and _is_rate_limit(r["error"]):
                quota_hit = True
                print(f"[{i:2}] SKIP  quota exhausted — re-run to continue")
                continue

            ok, got = grade(expected, r["reply"])
            done[question] = {
                "index": i, "question": question, "expected": expected, "answer": got,
                "reply": r["reply"], "steps": r["steps"], "ok": ok, "error": r["error"],
                "model": model, "date": date.today().isoformat(),
            }
            checkpoint.write_text(json.dumps(
                {"provider": provider, "model": model, "rubric": RUBRIC, "baseline": baseline,
                 "results": list(done.values())}, indent=2))
            note = f"  [error: {r['error'][:70]}]" if r["error"] else ""
            print(f"[{i:2}] {'PASS' if ok else 'FAIL'}  expected={expected!r} got={got!r} "
                  f"({len(r['steps'])} tool calls){note}")
            await asyncio.sleep(delay)

    write_report(output, provider, eval_file)


def write_report(output: Path, provider: str, eval_file: Path) -> None:
    """Rebuild results.md from both checkpoints (with tools, and baseline)."""
    pairs = parse_pairs(eval_file)
    tools = load_checkpoint(_checkpoint_path(output, provider, False))
    base = load_checkpoint(_checkpoint_path(output, provider, True))

    def score(rows: dict[str, dict]) -> str:
        if not rows:
            return "not run"
        ok = sum(r["ok"] for r in rows.values())
        return f"{ok}/{len(rows)} ({100 * ok // len(rows)}%)"

    def cell(r: dict | None) -> str:
        if r is None:
            return "⏳"
        if r.get("error") and not r.get("reply"):
            return "⚠️ error"
        return "✅" if r["ok"] else "❌"

    def shown(r: dict | None) -> str:
        if r is None:
            return "—"
        v = (r.get("answer") or "_(no ANSWER line)_").replace("|", "\\|")
        return v if len(v) <= 40 else v[:37] + "…"

    models = sorted({r["model"] for r in [*tools.values(), *base.values()] if r.get("model")})
    calls = [len(r["steps"]) for r in tools.values() if r.get("reply")]
    lines = [
        "# Conduit evaluation results",
        "",
        f"- **Updated:** {date.today().isoformat()} · **Provider / model:** {provider} / {', '.join(models) or '—'}",
        f"- **Questions:** {len(pairs)} (1–12 single-step, 13–20 multi-step) · **Server target:** `sample-repo/`",
        f"- **With tools:** {score(tools)} of questions answered so far",
        f"- **Baseline (same model, no tools):** {score(base)}",
        f"- **Mean tool calls per answered question:** {sum(calls) / len(calls):.1f}" if calls else
        "- **Mean tool calls per answered question:** —",
        "",
        "Graded strictly: the reply's `ANSWER:` line must equal the expected value exactly, "
        "ignoring only formatting. ⏳ = not yet sent to the model (quota).",
        "",
        "| # | Expected | With tools | Calls | ✓ | Baseline | ✓ |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, (q, expected) in enumerate(pairs, 1):
        t, b = tools.get(q), base.get(q)
        n = str(len(t["steps"])) if t and t.get("reply") else "—"
        lines.append(f"| {i} | `{expected}` | {shown(t)} | {n} | {cell(t)} | {shown(b)} | {cell(b)} |")
    lines.append(FOOTER)
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nwith tools: {score(tools)} · baseline: {score(base)}  ->  {output}")


def main() -> None:
    _load_env()
    parser = argparse.ArgumentParser(description="Run the Conduit evaluation through the host")
    parser.add_argument("--provider", default="gemini", help="gemini | ollama")
    parser.add_argument("--baseline", action="store_true", help="Same model, no tools, no repo context")
    parser.add_argument("--questions", type=int, nargs="+", help="Only these question numbers")
    parser.add_argument("--repo-root", default=str(REPO_ROOT / "sample-repo"))
    parser.add_argument("--eval-file", default=str(REPO_ROOT / "eval" / "evaluation.xml"))
    parser.add_argument("--output", default=str(REPO_ROOT / "eval" / "results.md"))
    parser.add_argument("--delay", type=float, default=13.0,
                        help="Seconds between questions (the free tier allows ~5 requests a minute)")
    parser.add_argument("--fresh", action="store_true", help="Ignore the checkpoint and re-ask everything")
    parser.add_argument("--report-only", action="store_true", help="Rebuild results.md from checkpoints")
    args = parser.parse_args()
    if args.report_only:
        write_report(Path(args.output), args.provider, Path(args.eval_file))
        return
    asyncio.run(run(args.provider, args.repo_root, Path(args.eval_file), Path(args.output),
                    args.delay, args.fresh, args.baseline, set(args.questions or []) or None))


if __name__ == "__main__":
    main()
