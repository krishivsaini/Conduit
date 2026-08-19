"""Proves the web demo renders the loop faithfully and stays within its limits.

The web layer is a second consumer of run_turn, so the things worth testing are
the ones the CLI never exercised: that steps stream out as they happen, that a
refusal reaches the browser intact, that the visitor cannot choose which
repository is served, and that live model calls are actually bounded.

Every test here drives the deterministic StubAdapter against the real MCP
server over stdio — no network, no API key, no model.
"""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from conduit.host.client import MCPCodebaseClient, conduit_server_params
from conduit.host.llm.adapter import FinalAnswer, ToolCall
from conduit.host.llm.stub import StubAdapter
from conduit.host.loop import run_turn
from conduit.web.app import MAX_QUESTION_CHARS, DemoHost, create_app
from conduit.web.limits import RateLimiter


def _client(sample_repo, script) -> TestClient:
    """An app whose model decisions are scripted, so runs are deterministic."""
    host = DemoHost(sample_repo, provider="stub", adapter=StubAdapter(script))
    return TestClient(create_app(host=host))


def _events(response) -> list[tuple[str, dict]]:
    """Parse an SSE body into (event, payload) pairs."""
    parsed = []
    for frame in response.text.split("\n\n"):
        if not frame.strip():
            continue
        event, data = "message", ""
        for line in frame.split("\n"):
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data += line[5:].strip()
        if data:
            parsed.append((event, json.loads(data)))
    return parsed


# --- The loop still behaves exactly as it did -------------------------------


async def test_run_turn_without_on_step_is_unchanged(sample_repo):
    """The callback is additive: omitting it must not alter the result."""
    script = [ToolCall(name="read_file", arguments={"path": "src/auth.py"}), FinalAnswer(text="ok")]
    async with MCPCodebaseClient(conduit_server_params(str(sample_repo))) as client:
        result = await run_turn(client, StubAdapter(list(script)), "q")

    assert result.answer == "ok"
    assert [s.name for s in result.steps] == ["read_file"]
    assert result.hit_step_limit is False


async def test_on_step_fires_once_per_step_in_order(sample_repo):
    """What the callback sees must match what the result records."""
    script = [
        ToolCall(name="read_file", arguments={"path": "src/auth.py"}),
        ToolCall(name="read_file", arguments={"path": "src/utils.py"}),
        FinalAnswer(text="done"),
    ]
    seen = []
    async with MCPCodebaseClient(conduit_server_params(str(sample_repo))) as client:
        result = await run_turn(client, StubAdapter(script), "q", on_step=seen.append)

    assert [s.name for s in seen] == ["read_file", "read_file"]
    assert [s.arguments["path"] for s in seen] == ["src/auth.py", "src/utils.py"]
    assert seen == result.steps


# --- Discovery reaches the page ---------------------------------------------


def test_tools_endpoint_reports_what_the_server_advertises(sample_repo):
    client = _client(sample_repo, [])
    body = client.get("/api/tools").json()

    assert {t["name"] for t in body["tools"]} == {"search_code", "read_file", "list_symbols", "diff"}
    assert [r["uri"] for r in body["resources"]] == ["repo://tree"]
    # Schemas travel too — the page shows them as tooltips.
    assert all(t["input_schema"]["type"] == "object" for t in body["tools"])


def test_health_reports_the_active_provider(sample_repo):
    body = _client(sample_repo, []).get("/api/health").json()
    assert body == {"status": "ok", "provider": "stub"}


# --- Streaming a turn --------------------------------------------------------


def test_ask_streams_tools_then_steps_then_answer(sample_repo):
    script = [
        ToolCall(name="search_code", arguments={"query": "authenticate"}),
        FinalAnswer(text="src/auth.py defines it."),
    ]
    response = _client(sample_repo, script).get("/api/ask", params={"q": "where is authenticate?"})
    assert response.status_code == 200

    events = _events(response)
    assert [e for e, _ in events] == ["tools", "step", "answer", "done"]

    _, tools = events[0]
    assert "search_code" in tools["names"]

    _, step = events[1]
    assert step["name"] == "search_code"
    assert step["arguments"] == {"query": "authenticate"}
    assert step["is_error"] is False

    _, answer = events[2]
    assert answer == {"text": "src/auth.py defines it.", "hit_step_limit": False}


def test_a_refused_call_reaches_the_browser_as_a_step(sample_repo):
    """The refusal is the demo's whole point; it must not be swallowed."""
    script = [
        ToolCall(name="read_file", arguments={"path": "service.key"}),
        FinalAnswer(text="False."),
    ]
    response = _client(sample_repo, script).get("/api/ask", params={"q": "read the key"})

    steps = [payload for event, payload in _events(response) if event == "step"]
    assert len(steps) == 1
    assert steps[0]["is_error"] is True
    # The page names the boundary by matching this text — keep them in step.
    assert "deny-list" in steps[0]["result_text"]


def test_traversal_refusal_reaches_the_browser(sample_repo):
    script = [
        ToolCall(name="read_file", arguments={"path": "../pyproject.toml"}),
        FinalAnswer(text="Refused."),
    ]
    response = _client(sample_repo, script).get("/api/ask", params={"q": "escape the root"})

    steps = [p for e, p in _events(response) if e == "step"]
    assert steps[0]["is_error"] is True
    assert "outside the repo root" in steps[0]["result_text"]


def test_missing_api_key_streams_a_message_rather_than_an_empty_body(sample_repo, monkeypatch):
    """A deployment without a key must still explain itself, not die mid-stream.

    The adapter is constructed lazily inside the streaming worker for exactly
    this reason: the response status is already sent by then, so the failure has
    to arrive as an event.
    """
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    host = DemoHost(sample_repo, provider="gemini")  # no adapter injected
    response = TestClient(create_app(host=host)).get("/api/ask", params={"q": "hi"})

    assert response.status_code == 200
    events = _events(response)
    assert [e for e, _ in events] == ["error", "done"]
    assert "not configured" in events[0][1]["message"]


def test_provider_failure_becomes_an_error_event_not_a_crash(sample_repo):
    class Exploding(StubAdapter):
        async def decide(self, messages, tool_schemas):
            raise RuntimeError("429 RESOURCE_EXHAUSTED quota")

    host = DemoHost(sample_repo, provider="stub", adapter=Exploding())
    response = TestClient(create_app(host=host)).get("/api/ask", params={"q": "hi"})

    assert response.status_code == 200
    errors = [p for e, p in _events(response) if e == "error"]
    assert len(errors) == 1
    assert "quota" in errors[0]["message"].lower()


# --- Input the visitor controls ---------------------------------------------


def test_empty_and_oversized_questions_are_refused(sample_repo):
    client = _client(sample_repo, [])
    assert client.get("/api/ask", params={"q": "   "}).status_code == 400
    assert client.get("/api/ask").status_code == 400
    assert client.get("/api/ask", params={"q": "x" * (MAX_QUESTION_CHARS + 1)}).status_code == 413


def test_the_visitor_cannot_choose_which_repository_is_served(sample_repo, tmp_path):
    """No query parameter may influence the repo root reaching the MCP server."""
    secret = tmp_path / "elsewhere"
    secret.mkdir()
    (secret / "loot.txt").write_text("should never be served")

    host = DemoHost(sample_repo, provider="stub", adapter=StubAdapter([]))
    client = TestClient(create_app(host=host))

    captured = []
    original = host._connect

    def spy():
        captured.append(host._repo_root)
        return original()

    host._connect = spy
    client.get("/api/tools", params={"repo_root": str(secret), "path": str(secret)})

    assert captured == [sample_repo]


# --- Rate limiting -----------------------------------------------------------


def test_per_ip_limit_refuses_the_next_request():
    clock = [1000.0]
    limiter = RateLimiter(per_ip=3, per_ip_window=60, global_daily=100, clock=lambda: clock[0])

    assert [limiter.check("1.1.1.1") for _ in range(3)] == [None, None, None]
    refusal = limiter.check("1.1.1.1")
    assert refusal is not None and "per hour" in refusal

    # A different visitor is unaffected...
    assert limiter.check("2.2.2.2") is None
    # ...and the window slides.
    clock[0] += 61
    assert limiter.check("1.1.1.1") is None


def test_global_daily_ceiling_applies_across_visitors():
    clock = [0.0]
    limiter = RateLimiter(per_ip=10, per_ip_window=60, global_daily=4, clock=lambda: clock[0])

    for i in range(4):
        assert limiter.check(f"10.0.0.{i}") is None
    refusal = limiter.check("10.0.0.99")
    assert refusal is not None and "daily budget" in refusal


def test_ask_returns_429_once_the_limit_is_reached(sample_repo):
    app = create_app(host=DemoHost(sample_repo, provider="stub", adapter=StubAdapter([])))
    app.state.limiter = RateLimiter(per_ip=1, per_ip_window=60, global_daily=10)
    client = TestClient(app)

    assert client.get("/api/ask", params={"q": "first"}).status_code == 200
    blocked = client.get("/api/ask", params={"q": "second"})
    assert blocked.status_code == 429
    assert "error" in blocked.json()


def test_recorded_transcripts_are_not_rate_limited(sample_repo):
    """The static path must survive the live budget running out."""
    app = create_app(host=DemoHost(sample_repo, provider="stub", adapter=StubAdapter([])))
    app.state.limiter = RateLimiter(per_ip=0, per_ip_window=60, global_daily=0)
    client = TestClient(app)

    assert client.get("/api/ask", params={"q": "anything"}).status_code == 429
    assert client.get("/transcripts.json").status_code == 200


# --- The recorded transcripts the page ships with ---------------------------


def test_shipped_transcripts_are_well_formed_and_include_a_refusal():
    from conduit.web.app import STATIC_DIR

    path = STATIC_DIR / "transcripts.json"
    if not path.exists():
        pytest.skip("no transcripts recorded yet (scripts/record_transcripts.py)")

    data = json.loads(path.read_text())
    assert data["transcripts"], "an empty transcript set would render an empty page"

    for t in data["transcripts"]:
        assert {"question", "answer", "steps", "expected", "model"} <= set(t)
        for step in t["steps"]:
            assert {"name", "arguments", "result_text", "is_error"} <= set(step)

    # The security question is the reason the demo exists.
    refusals = [s for t in data["transcripts"] for s in t["steps"] if s["is_error"]]
    assert refusals, "the recorded set must show the boundary refusing something"
