"""Proves each tool: valid input → valid structured output; bad input →
actionable error (not a stack trace).

Implemented on Day 7.
"""

import pytest

pytestmark = pytest.mark.skip(reason="Day 7: implement tools + this test")


def test_read_file_valid_input_returns_content(sample_repo):
    ...


def test_read_file_bad_path_returns_actionable_error(sample_repo):
    ...


def test_search_code_returns_paginated_matches(sample_repo):
    ...
