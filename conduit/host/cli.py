"""Clean CLI for the assistant demo.

Surfaces the MCP loop so it's legible: which provider is active, which tools
were discovered, which tool was called with which arguments, and — first-class —
security refusals shown as actionable errors. Provider is chosen by
``--provider`` or ``$LLM_PROVIDER`` (gemini | ollama).

Usage:
    conduit "Which file defines authenticate and what does it return on failure?"
    conduit                      # interactive REPL
    LLM_PROVIDER=ollama conduit  # fully local
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from .client import MCPCodebaseClient, conduit_server_params
from .llm.adapter import get_adapter
from .loop import LoopResult, run_turn


def _load_env() -> None:
    """Load .env from the current working directory tree (best-effort)."""
    try:
        from dotenv import find_dotenv, load_dotenv

        load_dotenv(find_dotenv(usecwd=True))
    except Exception:
        pass


def _print_result(result: LoopResult) -> None:
    for i, step in enumerate(result.steps, 1):
        status = "refused" if step.is_error else "ok"
        print(f"  [{i}] {step.name}({_fmt_args(step.arguments)}) -> {status}")
        if step.is_error:
            print(f"      {step.result_text.strip()[:200]}")
    print("\n" + result.answer.strip() + "\n")


def _fmt_args(args: dict) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in args.items())


async def _answer(provider: str, repo_root: str, question: str) -> None:
    adapter = get_adapter(provider)
    async with MCPCodebaseClient(conduit_server_params(repo_root)) as client:
        tools = await client.discover_tools()
        print(f"provider: {provider}  |  discovered tools: {', '.join(t.name for t in tools)}\n")
        try:
            result = await run_turn(client, adapter, question)
        except Exception as e:  # noqa: BLE001 — surface any provider/API error cleanly
            print(f"error from provider '{provider}': {e}")
            return
        _print_result(result)


async def _repl(provider: str, repo_root: str) -> None:
    adapter = get_adapter(provider)
    async with MCPCodebaseClient(conduit_server_params(repo_root)) as client:
        tools = await client.discover_tools()
        print(f"provider: {provider}  |  discovered tools: {', '.join(t.name for t in tools)}")
        print("Ask a question about the repo (Ctrl-D to exit).\n")
        while True:
            try:
                question = input("conduit> ").strip()
            except EOFError:
                print()
                return
            if not question:
                continue
            try:
                result = await run_turn(client, adapter, question)
            except Exception as e:  # noqa: BLE001 — keep the REPL alive on provider errors
                print(f"error from provider '{provider}': {e}\n")
                continue
            _print_result(result)


def main() -> None:
    """Entry point for the `conduit` CLI."""
    _load_env()
    parser = argparse.ArgumentParser(description="Conduit — ask questions about a codebase over MCP")
    parser.add_argument("question", nargs="*", help="Question to ask (omit for interactive mode)")
    parser.add_argument(
        "--repo-root",
        default=os.environ.get("CONDUIT_REPO_ROOT", "./sample-repo"),
        help="Repository the server serves (default: $CONDUIT_REPO_ROOT or ./sample-repo)",
    )
    parser.add_argument(
        "--provider",
        default=os.environ.get("LLM_PROVIDER", "gemini"),
        help="LLM provider: gemini | ollama (default: $LLM_PROVIDER or gemini)",
    )
    args = parser.parse_args()

    repo_root = str(Path(args.repo_root))
    if args.question:
        asyncio.run(_answer(args.provider, repo_root, " ".join(args.question)))
    else:
        asyncio.run(_repl(args.provider, repo_root))


if __name__ == "__main__":
    main()
