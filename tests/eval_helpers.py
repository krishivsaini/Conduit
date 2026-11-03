"""Load eval/run_eval.py (a script, not a package) for tests."""

from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path

RUN_EVAL = Path(__file__).resolve().parents[1] / "eval" / "run_eval.py"


@lru_cache(maxsize=1)
def load_run_eval():
    spec = importlib.util.spec_from_file_location("run_eval", RUN_EVAL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
