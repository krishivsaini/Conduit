"""Clean CLI for the assistant demo.

Surfaces the MCP loop so it's legible: which provider is active, which tools
were discovered, which tool was called with which arguments — printed as each
call lands, not after the turn ends — and, first-class, security refusals named
by the boundary that fired. Provider is chosen by ``--provider`` or
``$LLM_PROVIDER`` (gemini | ollama).

Usage:
    conduit "Which file defines authenticate and what does it return on failure?"
    conduit                      # interactive REPL
    conduit --provider ollama    # fully local

Configuration problems (no API key, a missing repo, Ollama not running) print a
one-line fix and exit non-zero instead of a traceback.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, TextIO

from .client import MCPCodebaseClient, conduit_server_params
from .llm.adapter import LLMAdapter, get_adapter
from .loop import LoopResult, ToolInvocation, run_turn

PROVIDERS = ("gemini", "ollama")

# A refusal only means something if it says which guarantee fired. Same naming
# as the web demo, keyed off the server's actionable error text.
_BOUNDARIES = (
    (re.compile(r"deny-list|denylist|excluded", re.I), "secrets deny-list"),
    (re.compile(r"outside the repo root|escape|traversal", re.I), "repo-root confinement"),
)
_TOOL_ERROR_PREFIX = re.compile(r"^Error executing tool \w+:\s*")


def _load_env() -> None:
    """Load .env from the current working directory tree (best-effort)."""
    try:
        from dotenv import find_dotenv, load_dotenv

        load_dotenv(find_dotenv(usecwd=True))
    except Exception:
        pass


class _Style:
    """ANSI styling on a terminal only, and never when NO_COLOR is set."""

    def __init__(self, stream: TextIO) -> None:
        self.on = stream.isatty() and "NO_COLOR" not in os.environ

    def _wrap(self, code: str, text: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if self.on else text

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def warn(self, text: str) -> str:
        return self._wrap("33", text)


class _Spinner:
    """A one-line 'thinking' indicator on stderr while the model works.

    A single turn can take 5-20s of model latency; with nothing on screen that
    reads as a hang. Terminal only — piped or redirected output stays free of
    control characters.
    """

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self) -> None:
        self.enabled = sys.stderr.isatty()
        self._task: asyncio.Task[None] | None = None
        self._t0 = 0.0

    async def _spin(self) -> None:
        i = 0
        while True:
            elapsed = int(time.monotonic() - self._t0)
            sys.stderr.write(f"\r{self.FRAMES[i % len(self.FRAMES)]} thinking… {elapsed}s")
            sys.stderr.flush()
            i += 1
            await asyncio.sleep(0.1)

    def start(self) -> None:
        if self.enabled and self._task is None:
            self._t0 = time.monotonic()
            self._task = asyncio.create_task(self._spin())

    def clear(self) -> None:
        """Erase the spinner line so the next print starts clean."""
        if self.enabled:
            sys.stderr.write("\r\x1b[K")
            sys.stderr.flush()

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self.clear()


def _fmt_args(args: dict[str, Any]) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in args.items())


def _boundary(detail: str) -> str | None:
    for pattern, name in _BOUNDARIES:
        if pattern.search(detail):
            return name
    return None


def _print_step(index: int, step: ToolInvocation, style: _Style) -> None:
    call = f"  [{index}] {step.name}({_fmt_args(step.arguments)})"
    if not step.is_error:
        print(f"{call} -> ok", flush=True)
        return
    detail = _TOOL_ERROR_PREFIX.sub("", step.result_text.strip())
    boundary = _boundary(detail)
    status = f"refused by the {boundary}" if boundary else "refused"
    print(f"{call} -> {style.warn(status)}", flush=True)
    print(style.dim(f"      {detail[:200]}"), flush=True)


def _print_answer(result: LoopResult, style: _Style) -> None:
    print("\n" + result.answer.strip())
    if result.hit_step_limit:
        print(style.dim("\n(used the full tool budget, then answered from the evidence gathered)"))
    print(flush=True)


def _explain(provider: str, exc: Exception) -> str:
    """Turn a provider failure into the thing the user should do about it."""
    text = str(exc)
    lowered = text.lower()
    if any(t in lowered for t in ("429", "resource_exhausted", "quota", "rate limit")):
        return (
            "the Gemini free tier is rate limited (5 requests a minute, plus a daily "
            "cap). Wait a minute and retry, or use --provider ollama."
        )
    if provider == "ollama":
        if "not found" in lowered and ("model" in lowered or "404" in lowered):
            model = os.environ.get("OLLAMA_MODEL", "mistral")
            return f"the Ollama model '{model}' isn't pulled. Run: ollama pull {model}"
        if "connect" in lowered or "connection" in lowered:
            host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
            return f"could not reach Ollama at {host}. Start it with: ollama serve"
    return f"the {provider} provider returned an error: {text[:300]}"


async def _ask(
    client: MCPCodebaseClient, adapter: LLMAdapter, provider: str, question: str, style: _Style
) -> bool:
    """Run one turn, printing each tool call the moment it lands. True on success."""
    spinner = _Spinner()
    count = 0

    def on_step(step: ToolInvocation) -> None:
        nonlocal count
        count += 1
        spinner.clear()
        _print_step(count, step, style)

    spinner.start()
    try:
        result = await run_turn(client, adapter, question, on_step=on_step)
    except Exception as exc:  # noqa: BLE001 — a provider failure is a message, not a crash
        await spinner.stop()
        print(style.warn(f"\n{_explain(provider, exc)}\n"), file=sys.stderr)
        return False
    await spinner.stop()
    _print_answer(result, style)
    return True


async def _run(
    provider: str, adapter: LLMAdapter, repo_root: Path, question: str | None
) -> int:
    """Answer one question (exit status 1 if it failed), or run the REPL."""
    style = _Style(sys.stdout)
    async with MCPCodebaseClient(conduit_server_params(str(repo_root))) as client:
        tools = await client.discover_tools()
        names = ", ".join(t.name for t in tools)
        print(style.dim(f"provider: {provider} · tools discovered from the server: {names}"), flush=True)

        if question is not None:
            print(flush=True)
            return 0 if await _ask(client, adapter, provider, question, style) else 1

        print(style.dim("Ask a question about the repo. Ctrl-D to exit.") + "\n")
        while True:
            try:
                line = input(style.bold("conduit> ")).strip()
            except EOFError:
                print()
                return 0
            if line:
                await _ask(client, adapter, provider, line, style)


def _fail(message: str) -> None:
    print(f"conduit: {message}", file=sys.stderr)
    raise SystemExit(2)


def main() -> None:
    """Entry point for the `conduit` CLI."""
    _load_env()
    parser = argparse.ArgumentParser(
        prog="conduit", description="Ask questions about a codebase over MCP."
    )
    parser.add_argument("question", nargs="*", help="Question to ask (omit for interactive mode)")
    parser.add_argument(
        "--repo-root",
        default=os.environ.get("CONDUIT_REPO_ROOT", "./sample-repo"),
        help="Repository the server serves (default: $CONDUIT_REPO_ROOT or ./sample-repo)",
    )
    parser.add_argument(
        "--provider",
        choices=PROVIDERS,
        default=os.environ.get("LLM_PROVIDER", "gemini"),
        help="LLM provider (default: $LLM_PROVIDER or gemini)",
    )
    args = parser.parse_args()

    # Check the cheap things before spawning a server. A typo'd path used to
    # start one over a nonexistent directory and answer as if the repo were empty.
    repo_root = Path(args.repo_root).expanduser()
    if not repo_root.is_dir():
        _fail(
            f"repository not found: {repo_root}\n"
            "  Point --repo-root (or CONDUIT_REPO_ROOT) at a directory to serve."
        )
    # argparse validates --provider but not the $LLM_PROVIDER default, and a
    # missing API key surfaces here too; both deserve a sentence, not a traceback.
    try:
        adapter = get_adapter(args.provider)
    except (RuntimeError, ValueError) as exc:
        _fail(str(exc))

    question = " ".join(args.question) if args.question else None
    try:
        status = asyncio.run(_run(args.provider, adapter, repo_root, question))
    except KeyboardInterrupt:
        print(file=sys.stderr)
        raise SystemExit(130)
    raise SystemExit(status)


if __name__ == "__main__":
    main()
