"""Load eval/run_eval.py and scripts/repo_snapshot.py (scripts, not packages) for tests."""

from __future__ import annotations

import importlib.util
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_EVAL = ROOT / "eval" / "run_eval.py"


@lru_cache(maxsize=None)
def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


def load_run_eval():
    return _load(RUN_EVAL, "run_eval")


def load_repo_snapshot():
    """scripts/repo_snapshot.py: extract one commit of this repo with git archive."""
    return _load(ROOT / "scripts" / "repo_snapshot.py", "repo_snapshot")
