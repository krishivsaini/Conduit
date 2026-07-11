# Conduit — Architecture

> **Status:** Draft v1 · Derived from `CONDUIT_BUILD_PLAN.md` (source of truth)
> **Purpose:** The *how it's structured* — components, boundaries, data flow, the security model, the schema design, and the key trade-offs. This is the planning-phase architecture; the shipped repo will also carry a root `ARCHITECTURE.md` (the hiring-facing version). The *what* is in [requirement.md](requirement.md); the *why* in [product_design.md](product_design.md); the *build order* in [implementation_plan.md](implementation_plan.md).
>
> **⚠️ Verify before building.** The MCP protocol, SDKs, and transport story change. Confirm the current spec (`https://modelcontextprotocol.io/sitemap.xml`, pages with `.md` suffix), the installed SDK API, the transport recommendation, and the current Gemini/Ollama tool-calling APIs against live docs before writing code. Follow the `mcp-builder` skill for the server. Do not build from memory.

---

## 1. System overview

Conduit is two processes that talk over the MCP protocol, plus a swappable LLM behind an adapter seam.

```
┌──────────────────────────────────────────────────────────────────────┐
│                              HOST / CLIENT                             │
│                                                                        │
│   cli.ts ──► loop.ts ──────────────────────────────► client.ts        │
│               │  discover → select → call → respond   (MCP client)     │
│               │                                            │           │
│               ▼                                            │           │
│         llm/adapter.ts  (one interface)                    │           │
│           ├─ gemini.ts   (free tier, default)              │           │
│           └─ ollama.ts   (local, offline)                  │           │
│                                                            │           │
└────────────────────────────────────────────────────────────┼─────────┘
                                                              │
                                        MCP over  ── stdio ───┤  (HTTP optional)
                                        transport             │
                                                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│                              MCP SERVER                                 │
│                                                                        │
│   index.ts  (registers tools + resources, selects transport)           │
│                                                                        │
│   tools/                         resources/                            │
│    ├─ search_code                 └─ repo_tree                          │
│    ├─ read_file                                                        │
│    ├─ list_symbols        ┌──────────── SECURITY BOUNDARY ───────────┐ │
│    └─ diff  ──────────────►  boundary.ts  (root confinement)          │ │
│                           │  denylist.ts  (secrets exclusion)         │ │
│   indexer.ts              │  readonly.ts  (no write/execute path)     │ │
│   errors.ts               └──────────────────┬───────────────────────┘ │
│                                               ▼                        │
│                                     ┌───────────────────┐              │
│                                     │  Repo root (FS)   │  read-only    │
│                                     └───────────────────┘              │
└──────────────────────────────────────────────────────────────────────┘
```

**The invariant:** every path from a tool to the filesystem passes through the security boundary *first*. There is no unchecked path to disk, and no write/execute path at all.

---

## 2. Components

### 2.1 Server (`server/`) — the headline

| Component | Responsibility |
|---|---|
| `index.ts` | Server entry: registers tools + resources, selects transport (stdio default). |
| `tools/search_code.ts` | Lexical/symbol search over the repo; paginated; returns file + line + snippet. `readOnlyHint: true`. |
| `tools/read_file.ts` | Reads a file within the root; line-range bounded. Security-checked. `readOnlyHint: true`. |
| `tools/list_symbols.ts` | Symbol index lookup for a file or query. `readOnlyHint: true`. |
| `tools/diff.ts` | Structured diff between two refs or two files. `readOnlyHint: true`. |
| `resources/repo_tree.ts` | Exposes the file tree + metadata as a resource, deny-list applied. |
| `security/boundary.ts` | Repo-root confinement + path-traversal defense (§4). |
| `security/denylist.ts` | Secret/`.env`/key exclusion (§4). |
| `security/readonly.ts` | Read-only posture enforcement (§4). |
| `indexer.ts` | Builds the lexical/symbol index over the repo. |
| `errors.ts` | Structured, actionable error helpers. |

### 2.2 Host / client (`host/`) — the model-agnostic driver

| Component | Responsibility |
|---|---|
| `client.ts` | MCP client: connect, **discover** tools/resources, call tools. No hardcoded tool list. |
| `loop.ts` | The orchestration loop: discover → LLM selects tool → call → feed result → respond. |
| `llm/adapter.ts` | The provider-agnostic interface (§5). |
| `llm/gemini.ts` | Gemini free-tier implementation of the adapter. |
| `llm/ollama.ts` | Local Ollama implementation of the adapter. |
| `cli.ts` | Clean CLI for the assistant demo; surfaces discovered tools, active provider, and refusals. |

### 2.3 Supporting

| Component | Responsibility |
|---|---|
| `tests/` | Security (traversal, deny-list, read-only), dynamic discovery, tool I/O, model-agnostic. |
| `eval/evaluation.xml` | ≥10 realistic, verifiable, read-only Q/A (MCP-style). |
| `scripts/demo.sh` | Deterministic scripted demo for the Loom. |

---

## 3. Tool vs. resource — the design decision

MCP distinguishes **tools** (actions the client invokes) from **resources** (context the client reads). Conduit's split:

- **Tools** — `search_code`, `read_file`, `list_symbols`, `diff`. Each is an *action* with parameters the LLM chooses (a query, a path, a line range, two refs). The result depends on arguments.
- **Resource** — `repo_tree`. It is *ambient context* for orientation: the file tree and metadata, with the deny-list applied. The client reads it to understand the repo's shape without invoking an action.

**Rationale (goes in the shipped README/ARCHITECTURE):** an action parameterized by client input is a tool; a browsable, relatively static view of what's available is a resource. Putting `repo_tree` behind a resource (not a tool) signals understanding of the distinction rather than modeling everything as a function call.

### 3.1 Schema design rules (per the `mcp-builder` skill)
- Every tool has a typed input schema (Zod/Pydantic) with clear descriptions and constraints.
- Structured output / `structuredContent` wherever possible.
- Action-oriented, consistent tool names.
- All path inputs pass through the security boundary (§4) **before** touching the filesystem.
- Errors are structured and actionable, e.g. *"path X is outside the repo root; provide a path relative to the root."*

---

## 4. Security model (the differentiator)

Every boundary is **enforced in code and proven by a test that attempts a violation and asserts it fails.** Treat every client-supplied path/pattern as untrusted; validate before use.

### 4.1 Repo-root confinement / path-traversal defense (`boundary.ts`)
- Resolve every incoming path to an absolute, canonical form (resolving `..` and symlinks).
- Assert the resolved path is inside the configured repo root; otherwise refuse with an actionable error.
- Defends against `../../etc/passwd`, absolute paths outside the root, and symlink escapes.
- **Proof:** `test_security_traversal.ts`.

### 4.2 Deny-list (`denylist.ts`)
- Configured sensitive patterns (`.env`, `*.key`, `*.pem`, `.git/`, credential files) are never exposed — not in `repo_tree`, not in `search_code` results, not via `read_file`.
- Applied uniformly at every exposure point, not just at read time.
- **Proof:** `test_security_denylist.ts`.

### 4.3 Read-only posture (`readonly.ts`)
- No tool mutates the filesystem or executes code; there is no write/execute code path.
- Enforced structurally (no write API is reachable) and asserted by test.
- **Proof:** `test_security_readonly.ts`.

### 4.4 Bounded output
- `read_file` is line-range bounded; `search_code` is paginated.
- Prevents single-call exfiltration of the whole repo and context blow-up — a resource/abuse boundary.

### 4.5 Enforcement ordering (critical)
```
client-supplied path ──► boundary.ts (resolve + confine)
                     ──► denylist.ts (reject sensitive)
                     ──► filesystem (read-only)
```
No tool reaches the filesystem before both checks pass. This ordering is an architectural invariant, not a per-tool convenience.

---

## 5. Model-agnostic LLM layer

The host loop depends only on a single adapter interface, never on a provider SDK.

```
adapter.decide(userMessage, discoveredToolSchemas)
    → { kind: "tool_call", name, arguments }   // select a discovered tool
    | { kind: "final", text }                   // compose the answer
```

- `gemini.ts` and `ollama.ts` both implement `decide(...)`. `LLM_PROVIDER` selects at runtime.
- The loop calls only `adapter.decide(...)`; swapping providers changes one env var, no loop code.
- A deterministic **stub adapter** (no network) is used in tests to prove the loop is provider-independent.
- **Proof:** `test_model_agnostic.ts` (loop works via stub; both real adapters conform to the interface contract).

**Model note:** default is Gemini Flash free tier (confirm the exact current model ID and rate limits live); the local alternative is an Ollama model (e.g. Qwen2.5) for a zero-external-dependency path. The LLM's only job is tool-selection; the project depends on no single provider.

---

## 6. Dynamic discovery — the data flow

```
1. Host starts → client.ts connects to server over stdio.
2. MCP capability negotiation → client receives the tool/resource list
   FROM THE SERVER (not hardcoded).
3. User asks a question via cli.ts.
4. loop.ts passes the *discovered* tool schemas + the question to adapter.decide().
5. Adapter returns a tool_call → client.ts invokes it over MCP.
6. Server runs the tool (through the security boundary) → returns structured result.
7. loop.ts feeds the result back to the adapter; repeat 4–6 as needed.
8. Adapter returns final → cli.ts renders the answer.
```

**The proof of "real" discovery (`test_dynamic_discovery.ts`):** add or rename a tool on the server and the client uses it with **no client-side code change**, because it learned the tool at runtime in step 2. If the client had to be edited to see the new tool, discovery would be decorative — the test guards against exactly that.

---

## 7. Transport

- **stdio** (default): the client spawns/connects to the server as a local process. Correct and simplest for a codebase server on the same machine.
- **Streamable HTTP** (optional, if time allows): documented alternative for the remote case. Not required for the demo.
- Confirm the current transport APIs against the live SDK before building. The choice + rationale is documented here and in the shipped ARCHITECTURE.md.

---

## 8. Technology stack

| Concern | Choice | Notes |
|---|---|---|
| Language | TypeScript (recommended) | Strongest MCP SDK/ecosystem support; Python + FastMCP is a valid mirror. |
| MCP | Official MCP TypeScript SDK | Verify version/API live before building. |
| Schemas | Zod (TS) / Pydantic (Python) | Typed input + structured output. |
| Search/index | Lexical (ripgrep-style) + lightweight symbol index | **No embeddings.** |
| LLM (default) | Gemini Flash free tier | Confirm model ID + limits live. |
| LLM (local) | Ollama (e.g. Qwen2.5) | Zero-external-dependency, offline path. |
| Manual testing | MCP Inspector (`npx @modelcontextprotocol/inspector`) | Per the `mcp-builder` skill. |
| Transport | stdio (default), streamable HTTP (optional) | Verify live. |

---

## 9. Key architectural trade-offs

| Decision | Alternative rejected | Rationale |
|---|---|---|
| Separate MCP server process | In-process `tools/` dict | The in-process dict is a generic agent; the separate server over the protocol is the rare, defensible signal. |
| Read-only server | Write/refactor tools | Keeps the security surface tractable and the demo safe. Write tools noted as future work with implications. |
| Lexical + symbol search | Semantic / vector RAG | Simple, fast, no embeddings; keeps scope focused. Semantic search is documented future work. |
| One server, built deeply | Multi-server orchestration | Depth over breadth; composing third-party servers overlaps generic projects. |
| stdio transport | HTTP-first | Simplest correct choice for a local codebase server; HTTP is optional. |
| Provider-agnostic adapter | Single-vendor SDK in the loop | Makes the model deliberately swappable; the MCP layer is the interesting part, not the model. |

---

## 10. Non-goals (architectural)

- No write/execute/shell path anywhere in the server.
- No multi-server hub or orchestration framework.
- No embeddings / vector store.
- No conversation-memory or multi-session state in the host — a minimal discover→select→call→respond loop only.

Every non-goal is a stated scope choice, echoed in [requirement.md §6.2](requirement.md) and framed in the README's "Limitations" as deliberate maturity, not gaps.
