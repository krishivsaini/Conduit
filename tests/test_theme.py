"""The CLI's palette: the web demo's colours, only where colour belongs."""

from __future__ import annotations

import io

import pytest

from conduit.host.theme import Style, markdown


class Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_piped_output_is_plain_text():
    style = Style(io.StringIO(), env={"COLORTERM": "truecolor"})
    assert style.hazard("refused", bold=True) == "refused" and style.signal("01") == "01"


def test_no_color_wins_even_over_force_color():
    assert not Style(Tty(), env={"NO_COLOR": "1"}).on
    assert not Style(io.StringIO(), env={"NO_COLOR": "1", "FORCE_COLOR": "1"}).on
    assert Style(io.StringIO(), env={"FORCE_COLOR": "1"}).on
    assert not Style(io.StringIO(), env={"FORCE_COLOR": "0"}).on


@pytest.mark.parametrize("env, code", [
    ({"COLORTERM": "truecolor"}, "38;2;228;161;27"),   # the page's hazard yellow, exactly
    ({"TERM": "xterm-256color"}, "38;5;214"),
    ({"TERM": "xterm"}, "33"),
])
def test_the_palette_degrades_to_what_the_terminal_supports(env, code):
    assert Style(Tty(), env=env).hazard("x") == f"\x1b[{code}mx\x1b[0m"


def test_markdown_renders_on_a_terminal_and_reads_as_prose_when_piped():
    text = "It is **`resolve_within_root`** in `boundary.py`."
    assert markdown(text, Style(io.StringIO(), env={})) == "It is resolve_within_root in boundary.py."
    coloured = markdown(text, Style(Tty(), env={"COLORTERM": "truecolor"}))
    assert "\x1b[1m" in coloured and "38;2;61;109;255" in coloured and "**" not in coloured



def test_model_citation_tags_are_dropped():
    from conduit.host.theme import clean

    assert clean("It is in boundary.py 【source:conduit/server/security/boundary.py†L1-L74】.") == "It is in boundary.py."


def test_wrapping_keeps_the_indent_and_never_splits_a_code_span():
    from conduit.host.theme import wrap

    text = "The function " + "word " * 20 + "`requested against repo_root` and more words to wrap here"
    lines = wrap(text, 40).splitlines()
    assert all(line.startswith("  ") and len(line) <= 40 or "`" in line for line in lines)
    assert any("`requested against repo_root`" in line for line in lines)
    assert wrap("a\n\nb", 40) == "  a\n\n  b"
