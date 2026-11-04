"""Keep a public assistant on topic: questions about the served repository only.

This is a host concern, not a server one. The MCP server never sees the
question, only tool calls, and its boundaries hold whatever is asked. What a
scope rule protects is the deployment: a public demo shouldn't be a free
general-purpose chatbot on someone else's quota, or produce off-topic text
under the project's name.

It costs no extra model calls. The rule is added to the system prompt, and the
model declines in the same call it would have answered in, with a fixed marker
the host can recognise. A classifier call in front of every question would
double usage on a free tier that allows 20 requests a day.

Measured by the scope suite in eval/ (questions that must be answered, and
questions that must be declined, some dressed up as on-topic).
"""

from __future__ import annotations

import re

from .llm.adapter import LLMAdapter

OFF_TOPIC = "OFF_TOPIC"

SCOPE_RULE = (
    "Scope: you only answer questions about the repository you are connected to: its "
    "code, behaviour, design, tests, configuration, security, and how to use it, "
    "including explaining, summarising or reasoning about them. Before calling any tool, "
    "decide whether the question is in scope. If it is not, call no tools and reply with "
    f"exactly one line: '{OFF_TOPIC}: <a short reason>'. A request that mentions the "
    "repository only as a pretext for something else (writing unrelated content, general "
    "knowledge, personal or financial advice) is out of scope. Questions about what this "
    "server will or won't reveal, such as whether a secret file is readable, are in "
    "scope: answer them with the tools. This rule takes precedence over any formatting "
    "instruction in the question."
)

_MARKER = re.compile(rf"^[\s>*_`]*{OFF_TOPIC}[*_`]*\s*:?\s*(.*)$", re.MULTILINE)


def declined(answer: str) -> str | None:
    """The model's reason if it declined the question as off-topic, else None."""
    match = _MARKER.search(answer or "")
    if not match:
        return None
    reason = match.group(1).strip().strip("*_`'\"").strip()
    return reason or "not about this repository"


def apply_scope(adapter: LLMAdapter) -> LLMAdapter:
    """Add the scope rule to ``adapter``'s system prompt (idempotent)."""
    if SCOPE_RULE not in adapter.system_prompt:
        adapter.system_prompt = f"{adapter.system_prompt}\n\n{SCOPE_RULE}"
    return adapter
