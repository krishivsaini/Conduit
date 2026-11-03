"""Every expected answer in eval/evaluation.xml is what the code actually does.

An eval is only as good as its answer key, and a hand-typed key can be wrong.
Here each expected answer is recomputed by importing the sample repo and running
it, so a typo in the key, or a change to the sample repo, fails CI instead of
quietly mis-grading a model.
"""

from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path

import pytest

from tests.eval_helpers import load_run_eval

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "sample-repo" / "src"
PAIRS = load_run_eval().parse_pairs(ROOT / "eval" / "evaluation.xml")


@pytest.fixture(scope="module")
def repo():
    """The sample repo's modules, imported for real (they import each other)."""
    names = ("auth", "payments", "utils")
    # Don't leave __pycache__ inside the served repo: the server would never
    # index it, but it is not ours to write into.
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(SRC))
    try:
        mods = {n: importlib.import_module(n) for n in names}
        yield mods
    finally:
        sys.path.remove(str(SRC))
        sys.dont_write_bytecode = saved
        for n in names:
            sys.modules.pop(n, None)


def _rel(fn) -> str:
    return Path(inspect.getsourcefile(fn)).relative_to(ROOT / "sample-repo").as_posix()


def _raises(fn, *args) -> BaseException:
    try:
        fn(*args)
    except BaseException as exc:  # noqa: BLE001
        return exc
    raise AssertionError(f"{fn.__name__}{args} did not raise")


def _ground_truth(m) -> dict[int, object]:
    auth, payments, utils = m["auth"], m["payments"], m["utils"]
    own_functions = lambda mod: [  # noqa: E731
        fn for _, fn in inspect.getmembers(mod, inspect.isfunction) if fn.__module__ == mod.__name__
    ]
    masked = utils.redact("abcdefgh")
    return {
        1: auth.authenticate("alice", "definitely-wrong"),
        2: _rel(auth.authenticate),
        3: type(_raises(payments.charge, "acct", payments.MIN_CHARGE_CENTS - 1)).__name__,
        4: payments.MIN_CHARGE_CENTS,
        5: len(own_functions(payments)),
        6: len(masked) - masked.count("*"),
        7: _rel(utils.redact),
        8: next(d["role"] for d in auth._USERS.values() if d["role"] != "admin"),
        9: utils.format_currency(100)[0],
        10: inspect.getsourcelines(payments.charge)[1],
        11: next(n for n in ("redact", "format_currency") if n in inspect.getsource(auth.authenticate)),
        # 12 asks whether the server will read a secret: that is a property of
        # the server, proven by tests/test_security_denylist.py, not of this code.
        13: auth.authenticate("bob", auth._USERS["bob"]["password"]),
        14: str(_raises(payments.charge, "acct", 49)),
        15: payments.charge("acct", 1050)["amount"],
        16: _enforces_minimum(payments.refund, payments),
        17: next(u for u, d in auth._USERS.items() if d["role"] == "admin"),
        18: auth.require_role("no-such-user", "admin"),
        19: sum("amount_cents" in inspect.signature(fn).parameters
                for mod in (auth, payments, utils) for fn in own_functions(mod)),
        20: utils.redact("x" * 7).count("*"),
    }


def _enforces_minimum(fn, payments) -> bool:
    try:
        fn("acct", payments.MIN_CHARGE_CENTS - 1)
    except payments.PaymentError:
        return True
    return False


def test_every_question_has_a_computed_answer(repo):
    covered = set(_ground_truth(repo)) | {12}
    assert covered == set(range(1, len(PAIRS) + 1))


@pytest.mark.parametrize("index", [i for i in range(1, len(PAIRS) + 1) if i != 12])
def test_expected_answer_matches_the_code(repo, index):
    question, expected = PAIRS[index - 1]
    actual = str(_ground_truth(repo)[index])
    assert actual == expected, f"Q{index}: key says {expected!r}, code says {actual!r}\n  {question}"
