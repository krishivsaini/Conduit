# Image for the web demo (conduit/web). The MCP server itself needs no image —
# it is spawned as a stdio subprocess by the host, inside this container.
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

# Dependency layer first so source edits don't re-resolve the environment.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --extra web --no-install-project

COPY conduit/ ./conduit/
COPY sample-repo/ ./sample-repo/
RUN uv sync --frozen --extra web

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    CONDUIT_REPO_ROOT=/app/sample-repo \
    PORT=8000

EXPOSE 8000

# GOOGLE_API_KEY and GEMINI_MODEL are supplied by the host's environment, never
# baked into the image. Without a key the page still serves recorded runs.
CMD ["conduit-web"]
