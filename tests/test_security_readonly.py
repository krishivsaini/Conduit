"""Proves the read-only posture: no write/execute tool exists (§8.3).

Implemented on Day 4.
"""

import pytest

pytestmark = pytest.mark.skip(reason="Day 4: implement read-only assertion + this test")


def test_only_readonly_tools_registered():
    """Every registered tool is in the read-only allow-set."""
    ...


def test_no_code_path_opens_files_for_writing():
    """No server module opens a file in a write mode."""
    ...
