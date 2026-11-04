"""Every expected answer in eval/evaluation.xml is what the code actually does.

An eval is only as good as its answer key, and a hand-typed key can be wrong.
Here each expected answer is recomputed by importing the sample repo and running
it, so a typo in the key, or a change to the sample repo, fails CI instead of
quietly mis-grading a model.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import os
import pkgutil
import re
import sys
import textwrap
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


# --- The conduit suite: questions about this repository ----------------------
#
# Conduit changes with every commit, so these answers can go stale; computing
# them from the code means a change that alters one fails here, naming the
# question, instead of silently mis-grading a model.

CONDUIT_PAIRS = load_run_eval().parse_pairs(ROOT / "eval" / "evaluation.conduit.xml")


def _class_methods(module, class_name: str) -> int:
    tree = ast.parse(inspect.getsource(module))
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == class_name)
    return sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in cls.body)


def _raised_in(fn) -> str:
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    (name,) = {n.exc.func.id for n in ast.walk(tree) if isinstance(n, ast.Raise) and n.exc}
    return name


def _ip_header_variable() -> str:
    """Find the variable by behaviour: set each os.environ name the web app
    reads, and see which one decides the trusted header."""
    from conduit.web import app as web

    names = re.findall(r'os\.environ\.get\("([A-Z_]+)"', inspect.getsource(web))
    (hit,) = [n for n in names if _with_env(n, "x-probe", lambda: web.create_app(ROOT / "sample-repo"))
              .state.client_ip_header == "x-probe"]
    return hit


def _with_env(name, value, fn):
    old = os.environ.get(name)
    os.environ[name] = value
    try:
        return fn()
    finally:
        os.environ.pop(name) if old is None else os.environ.__setitem__(name, old)


def _over_the_limit_status() -> int:
    from starlette.testclient import TestClient

    from conduit.host.llm.stub import StubAdapter
    from conduit.web.app import DemoHost, create_app
    from conduit.web.limits import RateLimiter

    app = create_app(host=DemoHost(ROOT / "sample-repo", provider="stub", adapter=StubAdapter([])))
    app.state.limiter = RateLimiter(per_ip=1, per_ip_window=60, global_daily=100)
    client = TestClient(app)
    client.get("/api/ask", params={"q": "one"})
    return client.get("/api/ask", params={"q": "two"}).status_code


def _conduit_truth() -> dict[int, object]:
    from conduit.host import loop
    from conduit.host.llm import replay
    from conduit.server import indexer, tools
    from conduit.server.security import boundary
    from conduit.server.security.denylist import DEFAULT_DENY_PATTERNS

    (dir_pattern,) = [p for p in DEFAULT_DENY_PATTERNS if p.endswith("/")]
    tool_modules = [importlib.import_module(f"{tools.__name__}.{m.name}")
                    for m in pkgutil.iter_modules(tools.__path__)]
    return {
        1: loop.MAX_STEPS,
        2: _raised_in(replay.ReplayAdapter._check),
        3: Path(inspect.getsourcefile(boundary.resolve_within_root)).relative_to(ROOT).as_posix(),
        4: indexer.MAX_FILE_BYTES,
        5: _ip_header_variable(),
        6: _class_methods(indexer, "RepoIndex"),
        7: loop.MAX_RESOURCE_CHARS,
        8: dir_pattern,
        9: sum(inspect.isfunction(getattr(m, "register", None)) for m in tool_modules),
        10: _over_the_limit_status(),
    }


@pytest.fixture(scope="module")
def conduit_truth():
    return _conduit_truth()


def test_every_conduit_question_has_a_computed_answer(conduit_truth):
    assert set(conduit_truth) == set(range(1, len(CONDUIT_PAIRS) + 1))


@pytest.mark.parametrize("index", range(1, len(CONDUIT_PAIRS) + 1))
def test_conduit_answer_matches_the_code(conduit_truth, index):
    question, expected = CONDUIT_PAIRS[index - 1]
    actual = str(conduit_truth[index])
    assert actual == expected, f"Q{index}: key says {expected!r}, code says {actual!r}\n  {question}"



# --- The scope suite's on-topic questions ------------------------------------

SCOPE_FILE = ROOT / "eval" / "evaluation.scope.xml"


def test_scope_on_topic_answers_match_the_code(repo):
    auth, payments, utils = repo["auth"], repo["payments"], repo["utils"]

    def refund_rejects(cents):
        try:
            payments.refund("acct", cents)
        except payments.PaymentError:
            return True
        return False

    truth = {
        1: _rel(payments.charge),
        2: payments.MIN_CHARGE_CENTS,
        3: refund_rejects(10),
        # 4 asks whether the server reads .env: a server property, proven by
        # tests/test_security_denylist.py.
        5: next(u for u, d in auth._USERS.items() if d["role"] == "admin"),
        6: utils.format_currency(1050),
        7: auth.authenticate("alice", "definitely-wrong"),
        8: utils.redact.__name__,
    }
    pairs = load_run_eval().parse_pairs(SCOPE_FILE)
    kinds = load_run_eval().parse_kinds(SCOPE_FILE)
    on_topic = [i for i, k in enumerate(kinds, 1) if k == "on-topic"]
    assert set(truth) | {4} == set(on_topic)
    for i, value in truth.items():
        assert str(value) == pairs[i - 1][1], f"scope Q{i}: key {pairs[i - 1][1]!r}, code {value!r}"
