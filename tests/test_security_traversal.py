"""Proves repo-root confinement: path-traversal attempts are refused (§8.1).

Implemented on Day 3.
"""

import pytest

pytestmark = pytest.mark.skip(reason="Day 3: implement boundary + this test")


def test_dotdot_traversal_is_refused(sample_repo):
    """`../../etc/passwd` must be refused with an actionable error."""
    ...


def test_absolute_path_outside_root_is_refused(sample_repo):
    """An absolute path outside the root must be refused."""
    ...


def test_symlink_escape_is_refused(sample_repo):
    """A symlink pointing outside the root must not be followed out."""
    ...
