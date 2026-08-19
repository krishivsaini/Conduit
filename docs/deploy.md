# Deploying the demo

The web demo (`conduit/web/`) is a second renderer over `host.loop.run_turn` —
the same seam the CLI uses. The MCP server is unchanged by it and still runs
over stdio, spawned as a subprocess by the host inside the container.

## What gets deployed where

Two pieces, deliberately split so the page never waits on a cold start:

| Piece | Where | Why |
|---|---|---|
| `conduit/web/static/` (HTML, CSS, JS, `transcripts.json`) | any static host / CDN | Paints instantly and replays real recorded runs with the API asleep or absent. |
| The Starlette API (`conduit-web`) | Render free tier, via `Dockerfile` | Only needed for *live* questions. Free instances spin down after ~15 min idle and take ~30s to wake. |

The frontend degrades on its own: if `/api/tools` is unreachable it shows the
tool names from the last recording, marks the server as asleep, and tells the
visitor a live question will take ~30s to wake it. Recorded runs keep working.

## The quota constraint (read this first)

The Gemini free tier allows **20 `generate_content` requests per day, per model,
per project**. One question costs one request per loop step — 2–4 in practice.
So a free-tier deployment supports roughly **5–8 live questions per day in
total**, across every visitor.

That is the reason the demo is recorded-first. `conduit/web/limits.py` caps live
runs at 3/hour/IP and 8/day globally so the budget cannot be drained by one
visitor, and an exhausted quota renders as a plain message pointing at the
recorded runs rather than a provider stack trace.

Quota is **per model**, so `gemini-3.5-flash-lite` and `gemini-3.1-flash-lite`
draw on separate buckets — useful when recording transcripts.

## Recording the transcripts

The preset questions replay genuine captured runs. Record them before deploying:

```bash
GEMINI_MODEL=gemini-3.5-flash-lite uv run python scripts/record_transcripts.py
```

Questions come from `eval/evaluation.xml`, so the page shows the same runs the
eval grades. The script **resumes**: already-captured questions are kept, and a
quota failure stops the run with whatever it got. Re-run on a later day, or
against another model's quota, to fill in the rest:

```bash
GEMINI_MODEL=gemini-3.1-flash-lite uv run python scripts/record_transcripts.py
```

Each transcript records the model and date that produced it, and the page shows
both. Commit `conduit/web/static/transcripts.json` — it is demo content, and it
means the deploy has no build-time model dependency.

## API on Render

`render.yaml` is a working blueprint. Either point Render at the repo and let it
read the blueprint, or create a Docker web service manually with:

- **Dockerfile path** `./Dockerfile`
- **Health check path** `/api/health`
- **Environment**: `GOOGLE_API_KEY` (secret, set in the dashboard — never
  committed), `GEMINI_MODEL=gemini-3.5-flash-lite`, `CONDUIT_REPO_ROOT=/app/sample-repo`

Without `GOOGLE_API_KEY` the service still runs and serves recorded runs; live
questions return *"Live questions are not configured on this deployment."*

## Frontend on a static host

Publish `conduit/web/static/` as-is — there is no build step. Then wire the two
halves together:

1. In `index.html`, set the API origin: `<body data-api="https://your-api.onrender.com">`
2. On the API, set `CONDUIT_WEB_ORIGINS` to the static site's origin, which
   narrows CORS from the permissive local-development default.

Serving both from one origin also works (`uv run conduit-web` mounts the static
directory at `/`), at the cost of the cold start applying to the whole page.

## Running it locally

```bash
uv sync --extra web
uv run conduit-web          # http://localhost:8000
```

## Verifying a deployment

```bash
curl -s https://your-api.onrender.com/api/health
curl -s https://your-api.onrender.com/api/tools        # live MCP discovery
curl -sN 'https://your-api.onrender.com/api/ask?q=Which+file+defines+authenticate%3F'
```

Then, on the page itself, run the **"Asks for a secret"** preset and confirm the
deny-list refusal renders as a named boundary with a link to the test that
proves it. That is the demo working.
