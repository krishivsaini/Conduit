"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_REPO = REPO_ROOT / "sample-repo"


@pytest.fixture
def sample_repo() -> Path:
    """Absolute path to the bundled sample repo the server serves in tests."""
    return SAMPLE_REPO
