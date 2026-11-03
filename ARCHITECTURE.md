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
│          ├─ groq.GroqAdapter       (OpenAI-style, paid limits)    │              │
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
4. loop.run_turn reads every resource the server advertises (repo://tree) and
   puts it ahead of the question as context, then passes that plus the
   *discovered* tool schemas to the adapter (adapter.decide).
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
Resources work the same way: the augmented server also adds a resource, and the
unmodified host reads it and hands it to the model.

---

## 3. Tools vs. resource — the design decision

MCP distinguishes **tools** (actions the client invokes) from **resources**
(context the client reads). Conduit's split:

| Kind | Members | Why |
|---|---|---|
| **Tools** (actions) | `search_code`, `read_file`, `list_symbols`, `diff` | Each is parameterized by client input (a query, a path, a line range, two files); the result depends on the arguments. |
| **Resource** (context) | `repo_tree` (`repo://tree`) | A browsable, deny-listed view of the repo's shape for orientation — data, not an action. |

Modeling `repo_tree` as a resource rather than "one more function call" is a
deliberate signal of understanding the distinction. The host uses it the way MCP
intends: it reads the resource once per turn and gives it to the model as
context (compacted, capped at 8,000 characters), so the model can go straight to
a file instead of spending tool calls finding it. Deny-listed files are absent
from it, so the tree never hints at where a secret lives.

### The index, on a real repository

`search_code`, `list_symbols` and `repo://tree` share one `indexer.RepoIndex`,
built once when the server starts. It stays current: before each query it
re-stats the walk and re-reads only files whose size or mtime changed, so an edit
made while the server runs is searchable straight away, not only readable.
Measured on 2,700 files / 730k lines: a cold build takes ~2 s and the
per-query freshness check ~0.1 s, which is why there is no on-disk cache (a
cache would also be the server's first write to disk).

What the server serves, in order: the deny-list (secrets), no symlinks in the
walk, the repo's own `.gitignore` files (nested ones and `.git/info/exclude`
too), then vendor directories such as `node_modules`. It presents **one view**:
a file the walk leaves out is also refused by `read_file`, `diff` and
`list_symbols` (`indexer.hidden_reason`), so no file is readable without being
listed. That matters because `.gitignore` is itself served and names the files a
repo keeps private; "not listed but readable by exact path" would hand a model
that list. The deny-list is still checked first and can't be undone by a
`.gitignore` (`!.env` re-includes nothing).

Both result lists page (`offset` / `next_offset`). The tree is meant to be read
in one go, so past 6,000 characters it collapses directories to a `file_count`:
deepest level first, biggest first within a level, stopping as soon as it fits.
It always stays whole, valid JSON. Before this, the
host cut it off at 8,000 characters, mid-JSON, on any real repo.

Proven by `tests/test_real_repo.py`, which also serves this checkout and checks,
with `git check-ignore`, that nothing git ignores is indexed.

**Schema design:** every tool has a flat, typed input schema (Pydantic via
`Annotated[..., Field(...)]`), structured output (a Pydantic return type →
generated `outputSchema` + `structuredContent`), tool annotations
(`readOnlyHint=True`, …), and actionable errors. All path inputs pass through the
security boundary before touching disk. An argument a tool doesn't take is
refused with the right names (`ConduitMCP.call_tool`): FastMCP's default is to
ignore it, which turned a model's `read_file(line_start=1, line_end=3)` into a
silent whole-file read. `search_code` and `list_symbols` take an optional file
or directory `path`, resolved through the same boundary as `read_file`.

---

## 4. Security model — the differentiator

Every boundary is **enforced in code and proven by a test that attempts a
violation and asserts it fails.** Client-supplied paths are untrusted.

| Boundary | Enforced in | Proven by |
|---|---|---|
| **Repo-root confinement / path traversal** — resolve `..` *and* symlinks, then check containment by path ancestry (not string prefix) | `security/boundary.py` | `tests/test_security_traversal.py` (14 cases: `../`, absolute, symlink escape, sibling-prefix refused; valid/nested/in-root-symlink allowed) |
| **Secrets deny-list** — case-insensitive, per-component glob (`.env`, `.env.*`, `*.key`, `*.pem`, `.git/`, `id_rsa`, …); checked on the *resolved* path so a symlink-to-secret is caught. A deployment can add patterns (`--deny`, `CONDUIT_DENY`) but not remove the defaults. Matches names, not file contents | `security/denylist.py` | `tests/test_security_denylist.py` (denied from read, search, and the tree; file and directory symlinks to secrets refused) |
| **Read-only posture** — no tool mutates the FS or executes code; the server refuses to build if a non-allow-listed tool, or one without `readOnlyHint`, is registered | `security/readonly.py` | `tests/test_security_readonly.py` (a guard test smuggles a write tool into `build_server` and expects refusal; an **AST scan** checks no server code writes, deletes or starts a process, and is itself tested against 20 such patterns — a strong check, not a proof) |
| **Bounded output** — reads are line-range capped (`MAX_LINES`), search and symbol listings page, the tree collapses to fit | `read_file`, `indexer.py` | `tests/test_tools.py`, `tests/test_real_repo.py` |

**Enforcement ordering (an architectural invariant):**

```
client path ──► boundary.resolve_within_root ──► denylist.is_denied ──► indexer.hidden_reason ──► filesystem (read-only)
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

- `GeminiAdapter`, `GroqAdapter` and `OllamaAdapter` implement it; `LLM_PROVIDER` selects at
  runtime via `get_adapter`. A `StubAdapter` (deterministic, no network) proves
  the loop is provider-independent in tests.
- The loop keeps a **provider-neutral** message list; each adapter translates it
  to its own SDK format. Provider-specific data that must round-trip (e.g.
  Gemini 3.x **thought signatures**, or the OpenAI-style tool-call id Groq needs
  to pair a result with its call) rides along in an opaque `provider_meta` blob
  that the loop propagates verbatim and never interprets — so the abstraction
  stays clean.
- Adding Groq took one module and one branch in `get_adapter`; no loop, server or
  client code changed. Proven on three providers (Gemini, Groq, a fully-local
  Ollama model) plus the stub. See `tests/test_model_agnostic.py`,
  `tests/test_groq_adapter.py` and `eval/results.md`.
- `pacing.Paced` wraps any adapter to live with per-minute rate limits: it waits
  out a per-minute 429 for the delay the provider names, and re-raises a per-day
  one. A multi-step question makes several calls back to back, so without it a
  5-a-minute free tier failed questions halfway through.

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
