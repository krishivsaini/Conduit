# Architecture

Conduit is two processes that talk over the **Model Context Protocol (MCP)**,
plus a swappable LLM behind a single adapter interface:

- **The server** — an MCP server (Python + FastMCP) that exposes a code
  repository through four read-only tools and one resource, behind **hard,
  tested security boundaries**. This is the headline.
- **The host** — a model-agnostic client that connects over stdio, **discovers
  the server's tools at runtime**, and drives them with an LLM (Gemini free tier
  or a fully-local Ollama model) to answer codebase questions.

> The signal is building the integration layer, not consuming it: deciding what
> is a *tool* vs. a *resource*, designing schemas and actionable errors,
> negotiating capabilities, choosing a transport, and drawing security
> boundaries around exposing a filesystem over a protocol.

---

## 1. System overview

```
┌────────────────────────────── HOST (conduit.host) ──────────────────────────────┐
│                                                                                  │
│  cli.py ──► loop.run_turn ─────────────────────────────► client.MCPCodebaseClient│
│              │  discover → decide → call → feed back        (MCP ClientSession)   │
│              ▼                                                     │              │
│        llm/adapter.LLMAdapter   (one interface)                   │              │
│          ├─ gemini.GeminiAdapter   (google-genai, default)        │              │
│          ├─ ollama.OllamaAdapter   (local, offline)               │              │
│          └─ stub.StubAdapter       (deterministic, tests)         │              │
│                                                                   │              │
└───────────────────────────────────────────────────────────────────┼────────────┘
                                                                     │
                                              MCP over  ── stdio ─────┤
                                              JSON-RPC               │
                                                                     ▼
┌───────────────────────────── SERVER (conduit.server) ────────────────────────────┐
│                                                                                  │
│  app.build_server → FastMCP("conduit_mcp")   [enforce_readonly() at build time]  │
│                                                                                  │
│  tools/                          resources/                                      │
│   ├─ search_code                  └─ repo_tree  (repo://tree)                     │
│   ├─ read_file          ┌──────────────── SECURITY BOUNDARY ─────────────────┐   │
│   ├─ list_symbols       │  boundary.resolve_within_root  (root confinement)   │   │
│   └─ diff  ─────────────►  denylist.is_denied            (secrets excluded)    │   │
│                         │  readonly.enforce_readonly     (no write/exec path)  │   │
│  access.py  ────────────┴──────────────────────┬──────────────────────────────┘   │
│  indexer.RepoIndex (lexical + ast symbols)      ▼                                 │
│  errors.ActionableError                ┌─────────────────┐                        │
│                                        │  Repo root (FS) │   read-only            │
│                                        └─────────────────┘                        │
└──────────────────────────────────────────────────────────────────────────────────┘
```

**The invariant:** every path from a tool to the filesystem flows through
`access.resolve_allowed_path` → `boundary` (confine) → `denylist` (screen)
**before** any read. There is no write/execute path anywhere in the server.

---

## 2. Request flow — dynamic discovery + the tool loop

```
1. Host starts → MCPCodebaseClient spawns the server and connects over stdio.
2. MCP capability negotiation → the client receives the tool/resource list
   FROM THE SERVER. The client hardcodes no tool names.
3. User asks a question via the CLI.
4. loop.run_turn passes the *discovered* tool schemas + the question to the
   adapter (adapter.decide).
5. The adapter (Gemini/Ollama) returns a tool_call → the client invokes it
   over MCP → the server runs it through the security boundary → structured result.
6. The result is fed back into the neutral message history; repeat 4–6.
7. The adapter returns a final answer → the CLI renders it (with the tool
   trace, so the loop is legible).
```

The client is completely generic: add or rename a tool on the server and the
unmodified client discovers and calls it. This is proven in
`tests/test_dynamic_discovery.py` by spawning an *augmented* server with an
extra tool the client has never heard of and calling it with zero client changes.

---

## 3. Tools vs. resource — the design decision

MCP distinguishes **tools** (actions the client invokes) from **resources**
(context the client reads). Conduit's split:

| Kind | Members | Why |
|---|---|---|
| **Tools** (actions) | `search_code`, `read_file`, `list_symbols`, `diff` | Each is parameterized by client input (a query, a path, a line range, two files); the result depends on the arguments. |
| **Resource** (context) | `repo_tree` (`repo://tree`) | A browsable, deny-listed view of the repo's shape for orientation — data, not an action. |

Modeling `repo_tree` as a resource rather than "one more function call" is a
deliberate signal of understanding the distinction.

**Schema design:** every tool has a flat, typed input schema (Pydantic via
`Annotated[..., Field(...)]`), structured output (a Pydantic return type →
generated `outputSchema` + `structuredContent`), tool annotations
(`readOnlyHint=True`, …), and actionable errors. All path inputs pass through the
security boundary before touching disk.

---

## 4. Security model — the differentiator

Every boundary is **enforced in code and proven by a test that attempts a
violation and asserts it fails.** Client-supplied paths are untrusted.

| Boundary | Enforced in | Proven by |
|---|---|---|
| **Repo-root confinement / path traversal** — resolve `..` *and* symlinks, then check containment by path ancestry (not string prefix) | `security/boundary.py` | `tests/test_security_traversal.py` (14 cases: `../`, absolute, symlink escape, sibling-prefix refused; valid/nested/in-root-symlink allowed) |
| **Secrets deny-list** — case-insensitive, per-component glob (`.env`, `.env.*`, `*.key`, `*.pem`, `.git/`, `id_rsa`, …); checked on the *resolved* path so a symlink-to-secret is caught | `security/denylist.py` | `tests/test_security_denylist.py` (denied from read, search, and the tree) |
| **Read-only posture** — no tool mutates the FS or executes code; the server refuses to build if a non-allow-listed tool, or one without `readOnlyHint`, is registered | `security/readonly.py` | `tests/test_security_readonly.py` (incl. an **AST scan** proving no server code path writes/deletes/`subprocess`/`shutil`) |
| **Bounded output** — reads are line-range capped (`MAX_LINES`), search is paginated | `read_file`, `search_code` | `tests/test_tools.py` |

**Enforcement ordering (an architectural invariant):**

```
client path ──► boundary.resolve_within_root ──► denylist.is_denied ──► filesystem (read-only)
```

No tool reaches disk before both checks pass. A consequence worth calling out:
`diff` operates on **two files, not two git refs** — diffing refs would require
executing `git` as a subprocess, which the read-only/no-exec posture forbids
(and the AST scan would fail). That is a principled scope choice, not a shortcut.

---

## 5. Model-agnostic LLM layer

The host loop depends only on one interface and never imports a provider SDK:

```
adapter.decide(messages, tool_schemas) -> ToolCall(name, arguments) | FinalAnswer(text)
```

- `GeminiAdapter` and `OllamaAdapter` implement it; `LLM_PROVIDER` selects at
  runtime via `get_adapter`. A `StubAdapter` (deterministic, no network) proves
  the loop is provider-independent in tests.
- The loop keeps a **provider-neutral** message list; each adapter translates it
  to its own SDK format. Provider-specific data that must round-trip (e.g.
  Gemini 3.x **thought signatures**) rides along in an opaque `provider_meta`
  blob that the loop propagates verbatim and never interprets — so the
  abstraction stays clean.
- Proven on two providers: Gemini (free tier) and a fully-local Ollama model,
  plus the stub. See `tests/test_model_agnostic.py` and `eval/results.md`.

---

## 6. Transport

**stdio** (local): the client spawns the server as a subprocess and speaks
MCP/JSON-RPC over its stdin/stdout — the simplest correct choice for a codebase
server on the same machine. FastMCP logs to stderr, keeping stdout clean for the
protocol. Streamable HTTP is a documented future option; it is not needed for
the demo.

---

## 7. Why MCP, not just function-calling?

Function-calling wires tools into one application. MCP exposes them over a
uniform interface that *any* compliant client can **discover** and use at
runtime — which is why the ecosystem is standardizing on it. Building the
*server* side is what demonstrates understanding of that integration layer,
rather than only the consumer side. Conduit is deliberately on the building
side, and its client proves the discovery property rather than asserting it.

---

## 8. Technology & key trade-offs

| Concern | Choice | Rationale |
|---|---|---|
| Language / SDK | Python + MCP SDK **v1.x** (FastMCP) | v2 was pre-release ("do not use in production"); pinned the stable line. |
| Schemas | Pydantic (`Annotated` params → flat input schema) | A single model param nests under `params`; flat schemas are better for tool-calling. |
| Search | Pure-Python lexical + stdlib-`ast` symbols | No ripgrep binary, no embeddings → the offline/clean-clone path has zero external deps. |
| Diff | `difflib` file-vs-file | Ref diffing needs `git` exec, which the read-only posture forbids. |
| LLM | Gemini free tier / local Ollama behind one adapter | The model is deliberately swappable; the MCP layer is the interesting part. |
| Transport | stdio | Correct and simplest for a local codebase server. |

**Deliberate non-goals:** write/execute tools, multi-server orchestration,
semantic/vector search, conversation memory. Each is a stated scope choice that
keeps the security surface tractable and the project focused.
