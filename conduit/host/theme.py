"""The CLI's colours: the web demo's palette, in a terminal.

Signal blue for the tool calls, hazard yellow for the boundary, grey for the
quiet parts. As on the page, a refusal gets the boldest treatment: it is the
server working, not failing.

Colour is used only on a terminal (or with FORCE_COLOR) and never when NO_COLOR
is set, so piped or redirected output stays plain text. Truecolor where the
terminal says it has it (COLORTERM), else the nearest 256- or 16-colour codes.
"""

from __future__ import annotations

import os
import re
import textwrap
from typing import TextIO

# (truecolor RGB, 256-colour index, 16-colour code). The page's signal blue
# (#1b4fd8) is too dark on a dark terminal, so the terminal uses a brighter
# step of the same hue.
_SIGNAL = ((61, 109, 255), 33, 94)
_HAZARD = ((228, 161, 27), 214, 33)
_FAINT = ((135, 141, 148), 245, 90)


def _depth(env: dict[str, str]) -> str:
    if env.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        return "24"
    if "256color" in env.get("TERM", ""):
        return "256"
    return "16"


class Style:
    """ANSI styling on a terminal (or with FORCE_COLOR), never with NO_COLOR."""

    def __init__(self, stream: TextIO, env: dict[str, str] | None = None) -> None:
        env = dict(os.environ) if env is None else env
        # FORCE_COLOR (a common convention) colours output that isn't a
        # terminal, e.g. `less -R` or a CI log; NO_COLOR always wins.
        forced = env.get("FORCE_COLOR", "") not in ("", "0")
        self.on = (stream.isatty() or forced) and "NO_COLOR" not in env
        self.depth = _depth(env)

    def _wrap(self, code: str, text: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if self.on and text else text

    def _colour(self, spec: tuple, text: str, bold: bool = False) -> str:
        rgb, c256, c16 = spec
        code = {"24": "38;2;{};{};{}".format(*rgb), "256": f"38;5;{c256}", "16": str(c16)}[self.depth]
        return self._wrap(f"1;{code}" if bold else code, text)

    def signal(self, text: str, bold: bool = False) -> str:
        return self._colour(_SIGNAL, text, bold)

    def hazard(self, text: str, bold: bool = False) -> str:
        return self._colour(_HAZARD, text, bold)

    def faint(self, text: str) -> str:
        return self._colour(_FAINT, text)

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def dim(self, text: str) -> str:
        return self.faint(text)

    def warn(self, text: str) -> str:
        return self.hazard(text)


_INLINE = re.compile(r"(\*\*[^*\n]+?\*\*|`[^`\n]+`)")


def markdown(text: str, style: Style) -> str:
    """**bold** and `code` as terminal bold and blue; the markers go either way,
    so piped output reads as plain prose rather than half-rendered Markdown."""
    out = []
    for part in _INLINE.split(text):
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            out.append(style.bold(markdown(part[2:-2], style)))
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            out.append(style.signal(part[1:-1]))
        else:
            out.append(part)
    return "".join(out)


# gpt-oss models cite sources as 【source:file†L1-L9】, a habit from their
# training that points nowhere here. Dropped from what a reader sees.
_CITATION = re.compile(r"\s*【[^】]*】")
_SPAN = re.compile(r"`[^`\n]+`")


def clean(text: str) -> str:
    return _CITATION.sub("", text)


def wrap(text: str, width: int, indent: str = "  ") -> str:
    """Wrap each line to ``width``, indented, never splitting a `code` span."""
    out = []
    for line in text.splitlines():
        if not line.strip():
            out.append("")
            continue
        protected = _SPAN.sub(lambda m: m.group(0).replace(" ", "\u00a0"), line)
        pieces = textwrap.wrap(protected, max(width - len(indent), 20),
                               break_long_words=False, break_on_hyphens=False) or [""]
        out += [indent + p.replace("\u00a0", " ") for p in pieces]
    return "\n".join(out)
