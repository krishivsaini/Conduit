# Conduit

**An MCP server that safely exposes a codebase, plus a model-agnostic assistant that discovers its tools at runtime.**

The server exposes code search, file read, symbol lookup, and diff over the
[Model Context Protocol](https://modelcontextprotocol.io), with hard security
boundaries — **repo-root confinement, a secrets deny-list, and a provably
read-only posture, each proven by a test that attempts a violation and asserts
it fails.** A model-agnostic host (Gemini free tier or a fully-local Ollama
model) discovers the server's tools at runtime and drives them to answer
codebase questions.

> The signal here is **building the MCP integration layer, not consuming it** —
> tool-vs-resource design, capability negotiation, transport, and (the
> differentiator) security boundaries around exposing a filesystem over a
> protocol.

---

## 🚧 Status: in development

Scaffolded on **Day 1** of a 12–14 day build. The architecture is in place; each
capability is implemented and tested on its scheduled day. Progress:

- [x] **Day 1** — environment verified against live MCP/SDK docs; repo skeleton; sample repo chosen
- [ ] **Day 2** — minimal MCP server: `read_file` over stdio, testable in MCP Inspector
- [ ] **Days 3–4** — security boundaries: traversal defense, deny-list, read-only (tested)
- [ ] **Days 5–7** — `search_code`, `list_symbols`, `diff`, `repo_tree`; actionable errors
- [ ] **Days 8–9** — host client with **dynamic discovery**; Gemini adapter + loop
- [ ] **Days 10–11** — Ollama adapter + provider switch; dynamic-discovery proof
- [ ] **Days 12–14** — evaluation (≥10 Q); architecture doc; README + demo

Planning docs: [requirements](docs/requirement.md) ·
[product design](docs/product_design.md) ·
[architecture](docs/architecture.md) ·
[implementation plan](docs/implementation_plan.md) ·
[full build plan](CONDUIT_BUILD_PLAN.md).

---

## Why MCP (and not just function-calling)?

Function-calling wires tools into one app; MCP exposes them over a uniform
interface any compliant client can **discover** and use — which is why the
ecosystem is standardizing on it. Building the *server* side is what shows you
understand that layer, not just the consumer side.

## Security model (the differentiator)

The server confines all access to the repo root, enforces a secrets deny-list,
and is provably read-only. Each boundary has a test that attempts a violation
and asserts it fails:

| Boundary | Enforced in | Proven by |
|---|---|---|
| Repo-root confinement / path-traversal defense | `conduit/server/security/boundary.py` | `tests/test_security_traversal.py` |
| Secrets deny-list (`.env`, `*.key`, `*.pem`, `.git/`) | `conduit/server/security/denylist.py` | `tests/test_security_denylist.py` |
| Read-only posture (no write/execute path) | `conduit/server/security/readonly.py` | `tests/test_security_readonly.py` |

The bundled [`sample-repo/`](sample-repo/) contains **intentionally fake**
secrets (`.env`, `service.key`) so the deny-list can be shown refusing them live.

## Quickstart (target — lands over the build)

```bash
# 1. Install (fully local path needs no API key)
uv sync

# 2. Run the MCP server over stdio, serving the sample repo
uv run conduit-server --repo-root ./sample-repo

# 3. Or test it manually with the MCP Inspector
npx @modelcontextprotocol/inspector uv run conduit-server --repo-root ./sample-repo

# 4. Ask the assistant a codebase question (Gemini or fully-local Ollama)
cp .env.example .env      # set LLM_PROVIDER=gemini|ollama
uv run conduit
```

## Limitations (deliberate scope choices)

- **Read-only** — no write/refactor/exec tools, by design (keeps the security surface tractable).
- **Single server** — one server built deeply, not a multi-server hub.
- **Lexical + symbolic search** — no semantic/vector RAG.
- **stdio transport** — streamable HTTP is a documented optional alternative.

## License

MIT — see [LICENSE](LICENSE).
