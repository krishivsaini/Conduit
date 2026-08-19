"""Starlette app that renders the MCP loop in a browser.

This is a *second renderer* over the same seam the CLI uses — it calls
``conduit.host.loop.run_turn`` and streams each ToolInvocation as it lands.
Nothing about the MCP server changes to support it.

Two content paths, because the demo is public and the model quota is free-tier:

  * **Recorded runs** — real captured traces served as static JSON. No model
    call, no rate limit, works while the API is asleep. See
    scripts/record_transcripts.py.
  * **Live runs** — ``GET /api/ask`` streams a real turn over SSE, guarded by
    conduit.web.limits and a concurrency semaphore.

The repository served is fixed to the bundled ``sample-repo/``; no visitor input
reaches :func:`conduit_server_params`. The server's own confinement would refuse
an escape anyway, but the demo declines to accept the input at all.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, AsyncIterator

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from conduit.host.client import MCPCodebaseClient, conduit_server_params
from conduit.host.llm.adapter import get_adapter
from conduit.host.loop import run_turn

from .limits import RateLimiter

PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"
PROJECT_ROOT = PACKAGE_DIR.parents[1]

# The one repository this demo will ever serve.
SAMPLE_REPO = Path(os.environ.get("CONDUIT_REPO_ROOT", PROJECT_ROOT / "sample-repo"))

# A free instance has ~512MB; each turn holds one server subprocess open.
MAX_CONCURRENT_TURNS = 2

# Visitors type into this; keep it bounded before it reaches a model.
MAX_QUESTION_CHARS = 500

# Live turns get less headroom than the CLI: a confused model should give up
# fast rather than burn shared quota.
WEB_MAX_STEPS = 6


def _load_env() -> None:
    """Load .env from the working tree (best-effort), as the CLI does."""
    try:
        from dotenv import find_dotenv, load_dotenv

        load_dotenv(find_dotenv(usecwd=True))
    except Exception:
        pass


class DemoHost:
    """Runs turns against the fixed sample repo, one MCP connection per turn.

    A fresh :class:`MCPCodebaseClient` per turn (rather than one long-lived
    session) is deliberate. The stdio client's task scopes must be entered and
    exited on the same task, which a shared session spanning Starlette's
    lifespan and its request tasks cannot honour when it needs to reconnect.
    Per-turn connections make a dead subprocess a one-request problem instead of
    a permanently broken app, and the ~0.3s spawn is dwarfed by model latency.
    """

    def __init__(
        self,
        repo_root: Path,
        provider: str | None = None,
        adapter: Any = None,
    ) -> None:
        self._repo_root = repo_root
        self._provider = provider or os.environ.get("LLM_PROVIDER", "gemini")
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_TURNS)
        # Injectable so tests drive the deterministic StubAdapter (no network).
        self._adapter: Any = adapter

    @property
    def provider(self) -> str:
        return self._provider

    def _get_adapter(self) -> Any:
        """Build the adapter lazily so a missing API key disables only live runs."""
        if self._adapter is None:
            self._adapter = get_adapter(self._provider)
        return self._adapter

    def _connect(self) -> MCPCodebaseClient:
        return MCPCodebaseClient(conduit_server_params(str(self._repo_root)))

    async def discover(self) -> dict[str, Any]:
        """Discover tools and resources from the live server (nothing hardcoded)."""
        async with self._connect() as client:
            tools = await client.discover_tools()
            resources = await client.discover_resources()
        return {
            "tools": [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in tools
            ],
            "resources": [
                {"uri": r.uri, "name": r.name, "mime_type": r.mime_type} for r in resources
            ],
        }

    async def stream_turn(self, question: str) -> AsyncIterator[tuple[str, Any]]:
        """Yield ``(event, payload)`` pairs for one live turn, as they happen."""
        queue: asyncio.Queue[tuple[str, Any] | None] = asyncio.Queue()

        async def worker() -> None:
            try:
                # Built inside the try: on a deployment with no API key this is
                # where it fails, and the visitor needs to be told that in the
                # stream rather than have the response die empty.
                adapter = self._get_adapter()
                async with self._semaphore, self._connect() as client:
                    tools = await client.discover_tools()
                    queue.put_nowait(("tools", {"names": [t.name for t in tools]}))
                    result = await run_turn(
                        client,
                        adapter,
                        question,
                        max_steps=WEB_MAX_STEPS,
                        on_step=lambda inv: queue.put_nowait(("step", asdict(inv))),
                    )
                queue.put_nowait(
                    ("answer", {"text": result.answer, "hit_step_limit": result.hit_step_limit})
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — provider/transport errors reach the page
                queue.put_nowait(("error", {"message": _friendly_error(exc)}))
            finally:
                queue.put_nowait(None)

        task = asyncio.create_task(worker())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    return
                yield item
        finally:
            # The visitor closed the tab (or the response died) — stop the turn
            # rather than leaving a subprocess and a model call running.
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def _friendly_error(exc: Exception) -> str:
    """Turn a provider/transport exception into something a visitor can act on."""
    text = str(exc)
    lowered = text.lower()
    if any(t in lowered for t in ("429", "resource_exhausted", "quota", "rate limit")):
        return (
            "The free-tier model quota for today is exhausted. The recorded runs "
            "below are real captured traces and still work."
        )
    if "api key" in lowered or "api_key" in lowered or "credential" in lowered:
        return "Live questions are not configured on this deployment (no model API key)."
    return f"The model provider returned an error: {text[:200]}"


def _sse(event: str, payload: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def _client_ip(request: Request) -> str:
    """Best-effort client IP, honouring the proxy header the host sets."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# --- Routes ----------------------------------------------------------------


async def health(request: Request) -> JSONResponse:
    """Wake probe — lets the page say 'waking the server' honestly."""
    host: DemoHost = request.app.state.host
    return JSONResponse({"status": "ok", "provider": host.provider})


async def tools(request: Request) -> JSONResponse:
    """The live tool list, discovered over MCP on every call."""
    host: DemoHost = request.app.state.host
    try:
        return JSONResponse(await host.discover())
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"could not reach the MCP server: {exc}"}, status_code=503)


async def ask(request: Request) -> StreamingResponse | JSONResponse:
    """Stream one live turn as Server-Sent Events.

    GET (not POST) so the browser can use EventSource directly; the turn is
    read-only, which is what the whole server guarantees.
    """
    question = (request.query_params.get("q") or "").strip()
    if not question:
        return JSONResponse({"error": "missing question"}, status_code=400)
    if len(question) > MAX_QUESTION_CHARS:
        return JSONResponse(
            {"error": f"question is too long (max {MAX_QUESTION_CHARS} characters)"},
            status_code=413,
        )

    limiter: RateLimiter = request.app.state.limiter
    refusal = limiter.check(_client_ip(request))
    if refusal:
        return JSONResponse({"error": refusal}, status_code=429)

    host: DemoHost = request.app.state.host

    async def events() -> AsyncIterator[str]:
        async for event, payload in host.stream_turn(question):
            yield _sse(event, payload)
        yield _sse("done", {})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def create_app(repo_root: Path | None = None, host: DemoHost | None = None) -> Starlette:
    """Build the app. ``host`` is injectable so tests can drive a stub adapter."""
    # Set CONDUIT_WEB_ORIGINS to the static host's origin in production; the
    # permissive default keeps local development and tests friction-free.
    origins = [o.strip() for o in os.environ.get("CONDUIT_WEB_ORIGINS", "").split(",") if o.strip()]
    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=origins or ["*"],
            allow_methods=["GET"],
            allow_headers=["*"],
        )
    ]

    routes: list[Any] = [
        Route("/api/health", health),
        Route("/api/tools", tools),
        Route("/api/ask", ask),
    ]
    # Serving the frontend is optional: the deployed setup puts it on a static
    # host so the page paints while this service is still waking up.
    if STATIC_DIR.is_dir():
        routes.append(Mount("/", app=StaticFiles(directory=str(STATIC_DIR), html=True)))

    app = Starlette(routes=routes, middleware=middleware)
    app.state.host = host or DemoHost(repo_root or SAMPLE_REPO)
    app.state.limiter = RateLimiter()
    return app


def main() -> None:
    """Entry point for the `conduit-web` script."""
    import uvicorn

    _load_env()
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(create_app(), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
