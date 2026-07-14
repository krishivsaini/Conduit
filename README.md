# Conduit

**An MCP server that safely exposes a codebase, plus a model-agnostic assistant that discovers its tools at runtime.**

Conduit is a [Model Context Protocol](https://modelcontextprotocol.io) server
(Python + FastMCP) that exposes a code repository through four read-only tools —
**search, read, symbol lookup, and diff** — and one resource, behind **hard
security boundaries: repo-root confinement, a secrets deny-list, and a provably
read-only posture, each proven by a test that attempts a violation and asserts
it fails.** A model-agnostic host (Gemini free tier **or** a fully-local Ollama
model) discovers the server's tools at runtime and drives them to answer
codebase questions.

> The signal is **building the MCP integration layer, not consuming it** —
> tool-vs-resource design, capability negotiation, transport, and (the
> differentiator) security boundaries around exposing a filesystem over a protocol.

`62 tests, 0 skipped` · `Python 3.10+` · `MIT`

**[Architecture & security model →](ARCHITECTURE.md)** · **[Evaluation results →](eval/results.md)**

---

## Quickstart

```bash
uv sync                       # install (the fully-local path needs no API key)

# Ask the assistant a question about the bundled sample repo:
uv run conduit "Which file defines the authenticate function, and what does it return on failure?"

# Fully local, no API key (needs `ollama serve` + a tool-capable model pulled):
LLM_PROVIDER=ollama OLLAMA_MODEL=<your-model> uv run conduit "List the functions in src/payments.py"

# For Gemini (free tier): put GOOGLE_API_KEY in .env (see .env.example), then run `uv run conduit`.
```

The server also runs standalone over stdio and works with the MCP Inspector:

```bash
uv run conduit-server --repo-root ./sample-repo
npx @modelcontextprotocol/inspector uv run conduit-server --repo-root ./sample-repo
```

## Security model (the differentiator)

Every boundary is enforced in code and **proven by a test that attempts a
violation and asserts it fails** — security tested, not asserted.

| Boundary | What it guarantees | Proven by |
|---|---|---|
| **Repo-root confinement** | resolves `..` *and* symlinks, then refuses anything outside the root | `tests/test_security_traversal.py` — 14 cases incl. symlink escape |
| **Secrets deny-list** | `.env`, `*.key`, `*.pem`, `.git/`, `id_rsa`, … never read, searched, or listed | `tests/test_security_denylist.py` |
| **Read-only posture** | no tool writes or executes; the server refuses to build if a non-read-only tool is registered | `tests/test_security_readonly.py` — incl. an AST scan for writes / `subprocess` |
| **Bounded output** | reads are line-range capped; search is paginated | `tests/test_tools.py` |

The bundled [`sample-repo/`](sample-repo/) ships **intentionally fake** secrets
(`.env`, `service.key`) so the deny-list can be shown refusing them live. All
client-supplied paths flow through confine → deny-list **before** any read; there
is no write/execute path anywhere in the server.

## Dynamic discovery

The host hardcodes no tool list — it learns the server's tools at runtime via MCP
capability negotiation. [`tests/test_dynamic_discovery.py`](tests/test_dynamic_discovery.py)
proves it: an *augmented* server registers a tool the client has never heard of,
and the **unmodified** client discovers and calls it. That is the MCP value
proposition demonstrated, not asserted.

## Model-agnostic

The host loop calls **one adapter interface** and never a provider SDK.
`LLM_PROVIDER` selects Gemini (`gemini-3.5-flash`, free tier) or a local Ollama
model; a deterministic stub proves the loop is provider-independent in tests.
Swapping providers changes one env var, no loop code.

## Evaluation

[`eval/evaluation.xml`](eval/evaluation.xml) holds 12 realistic, verifiable,
read-only questions answered by driving the server's tools. Run through
Conduit's own host, **a capable model (Gemini) answered every question it
executed correctly** (6/6 before the free-tier daily quota capped that day's run),
and the whole discover→call→respond loop runs **fully offline** via a local model.
Methodology + full table: [`eval/results.md`](eval/results.md). Re-run any time:

```bash
uv run python eval/run_eval.py                    # gemini
uv run python eval/run_eval.py --provider ollama  # fully local
```

## Reproducing

```bash
git clone https://github.com/krishivsaini/Conduit.git && cd Conduit
uv sync --extra dev
uv run pytest                                     # 62 passed
uv run conduit-server --repo-root ./sample-repo   # the MCP server over stdio
```

Clean clone to green tests runs in well under the 10-minute target. The Ollama
path needs no network and no API key.

## Why MCP, not just function-calling?

Function-calling wires tools into one app; MCP exposes them over a uniform
interface any compliant client can **discover** and use at runtime — which is why
the ecosystem is standardizing on it. Building the *server* side is what shows
you understand that integration layer, not just the consumer side.
See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design and the
tool-vs-resource rationale.

## Limitations (deliberate scope choices)

- **Read-only** — no write / refactor / exec tools, by design (keeps the security surface tractable).
- **Single server** — one server built deeply, not a multi-server hub.
- **Lexical + symbolic search** — no semantic / vector RAG.
- **`diff` is file-vs-file** — diffing git refs would require executing `git` as a subprocess, which the read-only/no-exec posture forbids.
- **stdio transport** — streamable HTTP is a documented future option.

## Project layout

```
conduit/server/   MCP server: tools/, resources/, security/, indexer, access, errors
conduit/host/     model-agnostic client: client, loop, cli, llm/ (adapter, gemini, ollama, stub)
tests/            security (traversal/denylist/readonly), discovery, model-agnostic, tools
eval/             evaluation.xml + run_eval.py + results.md
sample-repo/      the bundled demo target (with fake secrets for the deny-list demo)
```

Design docs: [requirements](docs/requirement.md) · [product design](docs/product_design.md) ·
[architecture](docs/architecture.md) · [implementation plan](docs/implementation_plan.md) ·
[full build plan](CONDUIT_BUILD_PLAN.md).

## License

MIT — see [LICENSE](LICENSE).
