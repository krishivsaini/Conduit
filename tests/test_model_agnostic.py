"""Proves the loop is provider-independent: it runs on a deterministic stub
adapter (no network), and both real adapters conform to the interface (§10).

Implemented on Day 10.
"""

import pytest

pytestmark = pytest.mark.skip(reason="Day 10: implement adapters + this test")


def test_loop_runs_with_stub_adapter():
    """The host loop answers a question via the no-network stub adapter."""
    ...


def test_real_adapters_conform_to_interface():
    """GeminiAdapter and OllamaAdapter both satisfy the LLMAdapter contract."""
    ...
