"""Proves the deny-list: secrets are never read, searched, or listed (§8.2).

Implemented on Day 4.
"""

import pytest

pytestmark = pytest.mark.skip(reason="Day 4: implement deny-list + this test")


def test_env_file_cannot_be_read(sample_repo):
    """read_file on sample-repo/.env must be refused."""
    ...


def test_key_file_not_in_search_results(sample_repo):
    """A secret in service.key must not appear in search_code results."""
    ...


def test_denied_files_absent_from_repo_tree(sample_repo):
    """.env / *.key must not appear in the repo_tree resource."""
    ...
