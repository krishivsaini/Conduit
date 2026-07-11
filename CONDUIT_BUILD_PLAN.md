# Conduit — MCP Codebase Server + Model-Agnostic Assistant — Complete Build Plan

> **Audience:** A coding agent (Claude Code, Cursor, etc.) executing this build end-to-end with minimal human intervention. Also readable by Krishiv as a reference doc.
> **Goal:** Ship a real **MCP server** that exposes a code repository (search, read, symbol lookup, diff) with proper tool-schema design and hard **security boundaries**, plus a **model-agnostic host/client** that dynamically discovers the server's tools at runtime and drives them with an LLM. In 12–14 days, ~3 hours/day, ₹0 to run.
> **Headline framing:** This project's signal is **building the MCP integration layer, not using it.** Most candidates who mention MCP have *consumed* a server; you will have *built* one — with tool vs. resource design decisions, capability negotiation, transport handling, and (the differentiator) security boundaries around exposing a filesystem over a protocol. The assistant is the demo that proves the server works; the server and its security model are the resume line. Lead external artifacts with "I built an MCP server that safely exposes a codebase, plus a model-agnostic client that discovers its tools at runtime," never "an AI assistant that uses tools."
> **Reading order:** Read top to bottom once before writing any code. Source of truth throughout.

> **Standalone project (self-contained — no external docs needed):** This doc is complete on its own. Everything needed to build Conduit is in this file; there are no references to other repos or docs.

> **⚠️ Build the server by following the `mcp-builder` skill.** A skill at `/mnt/skills/examples/mcp-builder/SKILL.md` encodes current MCP-server best practices (tool naming, input/output schemas, annotations, transport selection, MCP Inspector testing, and an evaluation methodology). **Read it and follow its four-phase workflow for the server itself.** This doc layers the project-specific requirements — codebase domain, security boundaries, model-agnostic host, honest-claims discipline — on top of that skill. Where the skill and this doc agree, follow both; where this doc adds a constraint (e.g. security boundaries), this doc is additive.

---

## Table of Contents

1. [Mission & Non-Negotiables](#1-mission--non-negotiables)
2. [Scope Boundary: What This Project Is Not](#2-scope-boundary)
3. [Why This Is Not Just "An Agent With Tools"](#3-why-not-just-an-agent)
4. [Glossary](#4-glossary)
5. [Repository Layout](#5-repository-layout)
6. [Environment, SDK & Model-Agnostic Design](#6-environment)
7. [The MCP Server: Tools & Resources](#7-the-mcp-server)
8. [Security Boundaries (The Differentiator)](#8-security-boundaries)
9. [The Host/Client: Dynamic Discovery](#9-the-host-client)
10. [Model-Agnostic LLM Layer](#10-model-agnostic-layer)
11. [Transport](#11-transport)
12. [Evaluation (MCP-style)](#12-evaluation)
13. [Day-by-Day Execution Plan](#13-day-by-day-execution-plan)
14. [Acceptance Criteria (Definition of Done)](#14-acceptance-criteria)
15. [Common Failure Modes for the Coding Agent](#15-common-failure-modes)
16. [Honest Claims Discipline (Read This Twice)](#16-honest-claims-discipline)
17. [Output Artifacts Checklist](#17-output-artifacts-checklist)

---

## 1. Mission & Non-Negotiables

### 1.1 What we are building

Two halves of the MCP protocol, built to be defensible from both sides:

- **The server (headline)** — an MCP server exposing a code repository through well-designed tools (search by text/symbol/name, read file, list symbols, structured diff) and resources (repo tree, file metadata). Proper input/output schemas, tool annotations, actionable errors, and — the differentiator — **hard security boundaries** (§8).
- **Security boundaries (the differentiator)** — the server must not read outside the repo root (path-traversal defense), must respect a configured deny-list (secrets, `.env`, key files), and must enforce a read-only posture where declared. These are tested, not just asserted.
- **The host/client** — a client that connects to the server, **discovers its tools at runtime** via MCP capability negotiation, and an LLM decides which tool to call for a user request. The "dynamic discovery" is real: the client does not hardcode the tool list; it learns it from the server.
- **Model-agnostic LLM layer** — the host's decision-maker works with either Gemini (free tier, default) or a local Ollama model, selected by config. The LLM's only job is tool-selection; the project does not depend on any one provider (§10).

### 1.2 Non-negotiables

1. **Build a server, not just a client.** The rare signal is implementing the MCP server with real schema/design decisions. A project that only consumes existing servers does not qualify (§3).
2. **Security boundaries are tested, not claimed.** Path-traversal defense, deny-list enforcement, and read-only posture each have a test that proves the boundary holds against an attempted violation (§8). This is the differentiator; it is non-negotiable.
3. **Dynamic discovery is real.** The client discovers tools at runtime from the server; the tool list is not hardcoded in the client (§9). A test proves the client uses a tool the server advertised without the client having prior knowledge of it.
4. **Model-agnostic, and proven.** The host runs on at least two providers (Gemini + local Ollama), selected by config, validated by the same host code path (§10). "Provider-agnostic" is only claimable if demonstrated on two.
5. **Follow the current MCP spec and SDK.** The protocol, SDKs, and transport story change. Verify against the live spec and the installed SDK version before building — do not build from memory or old tutorials (§6, and the `mcp-builder` skill).
6. **Actionable errors.** Every tool returns structured, actionable errors (what went wrong, what to do) — never a raw stack trace into the client (per `mcp-builder`).
7. **MCP-style evaluation.** ≥10 realistic, verifiable questions the assistant answers by using the server's tools, per the `mcp-builder` evaluation methodology (§12).
8. **Reproducible in <10 minutes from a clean clone**, running fully locally with the Ollama path (zero external dependency) or on the Gemini free tier.

### 1.3 Scope cuts (explicitly out of scope)

- **No write/destructive operations on the codebase.** Read-only server: search, read, symbol lookup, diff. No file editing, no shell execution. This keeps the security surface tractable and the demo safe. (Note write-tools as a documented future extension with the security implications called out.)
- **No multi-server orchestration.** One server you build, deeply, plus a client. Composing many third-party servers is a different (and more overlapping) project — out of scope.
- **No production RAG / embeddings for search.** Code search is lexical/symbolic (ripgrep-style + a symbol index), not semantic vector search. Keep it simple and fast; semantic code search is a documented future extension.
- **No fine-tuning, no agent orchestration framework.** The host is a simple discover→select→call→respond loop. Complex multi-agent orchestration is a different project.
- **No fancy frontend.** A clean CLI or a minimal web view for the assistant is plenty. The signal is the server + security, not the UI.

---

## 2. Scope Boundary

Conduit is an **MCP infrastructure** project. Its signal is a well-designed, secure MCP server and a client that discovers and drives it — not the assistant's conversational quality.

**What this project is:** an MCP server exposing a codebase through schema-designed tools and resources with tested security boundaries, plus a model-agnostic host that dynamically discovers and orchestrates those tools.

**What this project is deliberately not:**
- Not a general AI agent / assistant framework — the host is a minimal discover-select-call loop.
- Not a semantic code-search / RAG system — search is lexical + symbolic.
- Not a write/refactor tool — read-only, by design (security surface).
- Not a multi-server hub — one server, built well.

**Why MCP is the right frame (stands on its own):** the Model Context Protocol is the emerging standard for connecting LLMs to tools and data through a uniform interface. Building a server — deciding what is a *tool* (an action) versus a *resource* (exposable context), designing input/output schemas, negotiating capabilities, choosing a transport, and drawing security boundaries around what the server exposes — demonstrates understanding of the integration layer that products like coding assistants are built on. Consuming a pre-built server demonstrates far less. This project is deliberately on the building side.

---

## 3. Why This Is Not Just "An Agent With Tools"

This section exists because the easy version of this project — "an LLM that calls some tools" — is indistinguishable from a dozen other portfolios and overlaps a generic agent project. Conduit is different on three specific axes; protect all three or the project loses its reason to exist.

1. **You build the server.** The tools are not a Python `tools/` dict wired into an agent loop. They are an **MCP server** — a separate process exposing capabilities over the protocol, with schema, annotations, transport, and negotiation. That is the integration layer, and building it is the rare signal.
2. **Security boundaries are the point.** Exposing a filesystem over a protocol is a real security problem (path traversal, secret leakage, scope). Solving it — and *testing* that you solved it — is what makes this mature rather than a demo (§8).
3. **Discovery is dynamic.** The client learns the tools from the server at runtime, not from hardcoded knowledge. That is the actual MCP value proposition — a uniform interface — and demonstrating it is the difference between "I used MCP" and "I understand MCP."

If during the build any of these three collapses (tools become an in-process dict; security is asserted but not enforced; the client hardcodes the tool list), the project reverts to a generic agent-with-tools and its distinctiveness is gone. Stop and restore.

---

## 4. Glossary

| Term | Definition |
|---|---|
| **MCP** | Model Context Protocol — a standard for exposing tools, resources, and prompts to LLM clients over a uniform interface. |
| **Server** | The process exposing capabilities (here: codebase tools/resources) over MCP. |
| **Host / client** | The process that connects to a server, discovers its capabilities, and drives them (here: the LLM-powered assistant). |
| **Tool** | An action the server exposes (e.g. `search_code`, `read_file`), with an input schema and (ideally) an output schema. |
| **Resource** | Exposable context the server offers (e.g. the repo file tree, file metadata) — data, not an action. |
| **Capability negotiation** | The MCP handshake where the client learns what tools/resources the server offers. |
| **Transport** | How client and server communicate — stdio (local) or streamable HTTP (remote). |
| **Dynamic discovery** | The client obtaining the tool list from the server at runtime rather than hardcoding it. |
| **Security boundary** | An enforced limit on what the server will do (repo-root confinement, deny-list, read-only). |
| **Repo root** | The single directory the server is allowed to serve; nothing outside it is readable. |
| **Deny-list** | Paths/patterns the server refuses to expose even inside the root (e.g. `.env`, `*.key`, `.git/`). |
| **Host adapter** | The seam that lets the host use Gemini or a local model behind one interface (§10). |

---

## 5. Repository Layout

> Language: **TypeScript recommended** (the `mcp-builder` skill and the MCP ecosystem have the strongest TS SDK support; also plays to existing TS/Node strength). Python/FastMCP is a valid alternative if preferred — follow the skill's Python guide instead. The layout below assumes TS; mirror it for Python.

```
conduit/                                       # repo root
├── README.md                              # server-and-security-first; the hiring-decision artifact (§14)
├── LICENSE                                # MIT
├── .gitignore                             # .env, node_modules, dist/, *.log, .ollama/
├── .env.example                           # LLM_PROVIDER=gemini|ollama, GOOGLE_API_KEY=, OLLAMA_MODEL=
├── package.json / tsconfig.json           # (or pyproject.toml for Python)
├── ARCHITECTURE.md                        # diagram: server ⇄ transport ⇄ host; tool-vs-resource rationale; security model; why-not-Send/why-MCP
│
├── server/                                # THE MCP SERVER (the headline)
│   ├── index.ts                           # server entry: registers tools + resources, chooses transport
│   ├── tools/
│   │   ├── search_code.ts                 # lexical/symbol search over the repo (schema + annotations)
│   │   ├── read_file.ts                   # read a file within the root (schema + annotations)
│   │   ├── list_symbols.ts                # symbol index lookup
│   │   └── diff.ts                        # structured diff between refs/files
│   ├── resources/
│   │   └── repo_tree.ts                   # exposes the file tree / metadata as a resource
│   ├── security/
│   │   ├── boundary.ts                    # repo-root confinement + path-traversal defense (§8)
│   │   ├── denylist.ts                    # secret/`.env`/key exclusion (§8)
│   │   └── readonly.ts                    # read-only posture enforcement (§8)
│   ├── indexer.ts                         # builds the symbol/search index over the repo
│   └── errors.ts                          # structured, actionable error helpers
│
├── host/                                  # THE MODEL-AGNOSTIC CLIENT
│   ├── client.ts                          # MCP client: connect, discover tools, call tools
│   ├── loop.ts                            # discover → LLM selects tool → call → respond
│   ├── llm/
│   │   ├── adapter.ts                     # the provider-agnostic interface (§10)
│   │   ├── gemini.ts                      # Gemini free-tier implementation
│   │   └── ollama.ts                      # local Ollama implementation
│   └── cli.ts                             # a clean CLI for the assistant demo
│
├── tests/
│   ├── test_security_traversal.ts         # `../../etc/passwd` style attempts are refused (§8)
│   ├── test_security_denylist.ts          # `.env` / key files are never readable (§8)
│   ├── test_security_readonly.ts          # no write/destructive path exists
│   ├── test_dynamic_discovery.ts          # client uses a server-advertised tool w/o hardcoding it (§9)
│   ├── test_tools.ts                      # each tool: valid input → valid structured output; bad input → actionable error
│   └── test_model_agnostic.ts             # host loop works via the adapter with a stub provider; both real adapters conform
│
├── eval/
│   └── evaluation.xml                     # ≥10 realistic verifiable Q/A per mcp-builder (§12)
│
└── scripts/
    └── demo.sh                            # scripted demo run for the Loom
```

---

## 6. Environment, SDK & Model-Agnostic Design

- **Language/SDK:** TypeScript with the official MCP TypeScript SDK (recommended), or Python with the MCP Python SDK / FastMCP. Zod (TS) or Pydantic (Python) for schemas.
- **LLM:** model-agnostic (§10). Default **Gemini 3.5 Flash free tier**; alternative **local Ollama** model (e.g. Qwen2.5) for a zero-external-dependency path. The host reads `LLM_PROVIDER` from env.
- **Search/index:** a lexical search (ripgrep-style) plus a lightweight symbol index. No embeddings.
- **Testing:** the MCP Inspector (`npx @modelcontextprotocol/inspector`) for manual server testing, plus the automated tests above.

> **⚠️ §6 note to coding agent — verify live before building, this is non-negotiable:**
> - **Follow `/mnt/skills/examples/mcp-builder/SKILL.md`** for the server. Load the MCP spec via its sitemap (`https://modelcontextprotocol.io/sitemap.xml`, fetch pages with `.md` suffix) and the current SDK README (`https://raw.githubusercontent.com/modelcontextprotocol/typescript-sdk/main/README.md` or the Python equivalent) **before writing server code**. The protocol and SDK APIs change; do not rely on memory.
> - **Confirm the current transport recommendation** (stdio for local, streamable HTTP for remote) and the current tool/resource registration API from the live SDK docs.
> - **Confirm the current Gemini Flash model ID and free-tier limits** (`https://ai.google.dev/gemini-api/docs/rate-limits`) and the current Ollama tool-calling API before writing the adapters.
> - When unsure about any protocol/SDK/provider detail, fetch docs rather than guessing.

---

## 7. The MCP Server: Tools & Resources

Follow the `mcp-builder` skill's Phase 2 for each tool (input schema, output schema, description, annotations, actionable errors). Project-specific set:

**Tools (actions):**
- `search_code` — lexical/symbol search across the repo; paginated; returns matches with file + line + snippet. Annotations: `readOnlyHint: true`.
- `read_file` — read a file *within the root* (security-checked, §8); supports line ranges to bound context. `readOnlyHint: true`.
- `list_symbols` — return symbols (functions/classes) for a file or matching a query, from the symbol index. `readOnlyHint: true`.
- `diff` — structured diff between two refs or two files. `readOnlyHint: true`.

**Resources (context):**
- `repo_tree` — the file tree (deny-list applied) and basic metadata, exposed as a resource the client can read for orientation.

Design rules (from the skill + this project):
- Every tool has a Zod/Pydantic input schema with clear descriptions and constraints, and an output schema / `structuredContent` where possible.
- Every tool passes all path inputs through the security boundary (§8) *before* touching the filesystem.
- Errors are structured and actionable ("path X is outside the repo root; provide a path relative to the root").
- Tool names are action-oriented and consistently prefixed if helpful.

---

## 8. Security Boundaries (The Differentiator)

This is what makes Conduit mature rather than a demo, and it's the rarest part of the resume line. Each boundary is **enforced in code and proven by a test that attempts a violation and asserts it fails.**

1. **Repo-root confinement / path-traversal defense (`security/boundary.ts`).** Every path the server touches is resolved and checked to be inside the configured repo root. Attempts like `../../etc/passwd`, absolute paths outside the root, or symlink escapes are refused with an actionable error. `test_security_traversal.ts` proves a traversal attempt is refused.
2. **Deny-list (`security/denylist.ts`).** Even inside the root, configured sensitive paths/patterns are never exposed: `.env`, `*.key`, `*.pem`, `.git/`, credentials files. They don't appear in `repo_tree`, `search_code` results, or `read_file`. `test_security_denylist.ts` proves a denied file cannot be read or discovered.
3. **Read-only posture (`security/readonly.ts`).** The server exposes no write/execute path. There is no tool that mutates the filesystem or runs code. `test_security_readonly.ts` asserts no such tool is registered and no code path writes.
4. **Bounded output.** Reads are line-range-bounded and search is paginated so a single call can't exfiltrate the whole repo in one shot or blow the context — a mild resource/abuse boundary worth noting.

> The README's security section is a hiring asset: "the server confines all access to the repo root, enforces a secrets deny-list, and is provably read-only — each boundary has a test that attempts a violation and asserts it fails." That sentence is rare in a fresher portfolio and directly signals production/security maturity.

> **§8 note:** treat any path or pattern arriving from the client as untrusted input — validate against the boundary before use. Never let a client-supplied path reach the filesystem unchecked.

---

## 9. The Host/Client: Dynamic Discovery

- On startup, the client connects to the server and **discovers** its tools and resources via MCP capability negotiation. The tool list is *not* hardcoded in the client.
- The host loop (`loop.ts`): receive user request → present the *discovered* tool schemas to the LLM → LLM selects a tool + arguments → client calls the tool via MCP → feed the result back → LLM composes a response (possibly calling more tools).
- `test_dynamic_discovery.ts` proves the point: add or rename a tool on the server, and the client uses it **without any client-side code change** — because it discovered it at runtime. This test is the evidence that discovery is real, not decorative.

---

## 10. Model-Agnostic LLM Layer

- `host/llm/adapter.ts` defines one interface: given a user message + the discovered tool schemas, return a tool-selection (tool name + arguments) or a final answer.
- `gemini.ts` and `ollama.ts` both implement it. `LLM_PROVIDER` selects at runtime.
- The host loop calls only the adapter interface — never a provider SDK directly. Swapping providers changes one env var, no loop code.
- `test_model_agnostic.ts`: the loop works with a stub adapter (deterministic, no network), and both real adapters conform to the interface contract.

> **The resume claim this earns (honest):** "provider-agnostic LLM integration — the assistant runs on Gemini (free tier) or a fully-local Ollama model behind one adapter interface, validated on both." This is a stronger line than any single vendor name, and it's the honest answer to "why is the model interesting here?" — it isn't; the MCP layer is, and the model is deliberately swappable. Because it's genuinely built and tested on two providers, the claim survives probing.

---

## 11. Transport

- **stdio** for the local case (client spawns/connects to the server as a local process) — simplest, and correct for a codebase server running on the same machine.
- Optionally expose **streamable HTTP** as a documented alternative for the remote case, if time allows — but stdio is sufficient for the demo. Confirm the current transport APIs against the live SDK (§6).
- Document the transport choice and rationale in ARCHITECTURE.md.

---

## 12. Evaluation (MCP-style)

Follow the `mcp-builder` evaluation guide (its Phase 4). Produce `eval/evaluation.xml` with **≥10 questions** that:
- require the assistant to actually use the server's tools (search → read → reason),
- are realistic (things someone navigating a codebase would ask),
- are verifiable (a single checkable answer),
- are read-only and stable.

Example shape: *"Which file defines the function that handles X, and what does it return on error?"* — answerable only by searching + reading via the server. Record whether the assistant answered each correctly. This demonstrates the server is actually *useful to an LLM*, which is the real measure of an MCP server's quality.

---

## 13. Day-by-Day Execution Plan

12–14 days × ~3 hours. If something slips, **cut the HTTP transport and the web UI — never the security boundaries, the dynamic-discovery test, or the model-agnostic adapter**, which are the differentiators.

| Day | Focus | End-of-day artifact |
|---|---|---|
| 1 | Read `mcp-builder` skill; fetch live MCP spec + SDK README; pick TS/Python; scaffold repo; choose the demo repo the server will serve | Environment verified against live docs; repo skeleton; server target chosen |
| 2 | Minimal MCP server: one tool (`read_file`) + stdio transport; test with MCP Inspector | Server runs; Inspector can call `read_file` |
| 3 | Security boundary: repo-root confinement + path-traversal defense (`boundary.ts`) | `test_security_traversal.ts` green |
| 4 | Deny-list + read-only posture; wire boundary into `read_file` | `test_security_denylist.ts`, `test_security_readonly.ts` green |
| 5 | `indexer.ts` + `search_code` tool (lexical/symbol), paginated, schema + annotations | Search works via Inspector; boundary-checked |
| 6 | `list_symbols` + `diff` tools; `repo_tree` resource (deny-list applied) | Full tool/resource set live |
| 7 | `errors.ts`: structured actionable errors across all tools; `test_tools.ts` | Bad inputs return actionable errors, not stack traces |
| 8 | Host MCP client: connect + **dynamic discovery** of tools | Client lists server tools it did not hardcode |
| 9 | `adapter.ts` + Gemini adapter; host loop (discover→select→call→respond) | Assistant answers a question by calling a tool, via Gemini |
| 10 | Ollama adapter; `LLM_PROVIDER` switch; `test_model_agnostic.ts` | Same assistant works fully locally via Ollama |
| 11 | `test_dynamic_discovery.ts` (rename/add a tool → client uses it, no client change) | Discovery proven; the MCP value prop demonstrated |
| 12 | `eval/evaluation.xml` (≥10) + run it; record results | Eval demonstrates the server is useful to an LLM |
| 13 | ARCHITECTURE.md (diagram + security model + why-MCP); reproducibility pass (clean clone, Ollama path offline) | Clean-clone run <10 min; offline path works |
| 14 | README + Loom (security boundary refused live + dynamic discovery + provider swap) + resume bullet | All §17 artifacts exist |

---

## 14. Acceptance Criteria (Definition of Done)

### 14.1 The server
- [ ] A real MCP server (separate process, over the protocol) exposing `search_code`, `read_file`, `list_symbols`, `diff`, and a `repo_tree` resource.
- [ ] Every tool has a typed input schema, structured output where possible, annotations, and actionable errors.
- [ ] Testable with the MCP Inspector.

### 14.2 Security (the differentiator)
- [ ] Repo-root confinement refuses path-traversal attempts; `test_security_traversal.ts` proves it.
- [ ] Deny-list hides secrets from read, search, and tree; `test_security_denylist.ts` proves it.
- [ ] Read-only posture: no write/execute tool exists; `test_security_readonly.ts` proves it.

### 14.3 Dynamic discovery
- [ ] The client discovers tools at runtime; the tool list is not hardcoded.
- [ ] `test_dynamic_discovery.ts` proves the client uses a newly added/renamed server tool with no client-side change.

### 14.4 Model-agnostic
- [ ] Host runs on Gemini and on local Ollama via one adapter interface; `LLM_PROVIDER` selects.
- [ ] `test_model_agnostic.ts` proves the loop is provider-independent; both adapters conform.

### 14.5 Evaluation
- [ ] `eval/evaluation.xml` with ≥10 realistic, verifiable, read-only questions; results recorded.

### 14.6 README + Loom
- [ ] README opens with the server-and-security headline, not "AI assistant that uses tools":

> **Conduit: an MCP server that safely exposes a codebase, plus a model-agnostic assistant that discovers its tools at runtime.**
>
> The server exposes code search, file read, symbol lookup, and diff over the Model Context Protocol, with hard security boundaries — repo-root confinement, a secrets deny-list, and a provably read-only posture, each proven by a test that attempts a violation and asserts it fails. A model-agnostic host (Gemini free tier or a fully-local Ollama model) discovers the server's tools at runtime and drives them to answer codebase questions.
>
> [Loom →] [Architecture + security model →]

- [ ] "Why MCP / server vs. resource" rationale in README + ARCHITECTURE.md.
- [ ] Security section with the "each boundary has a violation test" framing.
- [ ] "Limitations" section: read-only, single server, lexical (not semantic) search, stdio transport. Framed as deliberate scope choices.
- [ ] "Reproducing" section with literal commands, including the fully-offline Ollama path.
- [ ] 90-second Loom: show a path-traversal attempt refused live → the assistant answering a codebase question via discovered tools → swapping `LLM_PROVIDER` from Gemini to Ollama and it still working.

### 14.7 Repo hygiene
- [ ] `.gitignore` excludes `.env`, `node_modules`, `dist/`, `.ollama/`.
- [ ] No secrets in history; keys via env only.
- [ ] Clean-clone build/run succeeds; LICENSE is MIT.

---

## 15. Common Failure Modes for the Coding Agent

1. **Do not build tools as an in-process dict.** They must be an MCP server over the protocol (§3.1). An in-process tool registry is a generic agent, not an MCP project.
2. **Do not assert security without testing it.** Each boundary needs a test that attempts a violation and asserts failure (§8). Untested security is theater.
3. **Do not hardcode the tool list in the client.** Discovery is runtime; `test_dynamic_discovery.ts` must pass (§9).
4. **Do not call a provider SDK from the host loop.** Only the adapter interface (§10). A direct SDK call breaks model-agnosticism.
5. **Do not let a client-supplied path reach the filesystem unchecked.** Boundary first, always (§8).
6. **Do not add write/execute tools.** Read-only is the security surface decision (§1.3). Note them as future work with implications, don't build them.
7. **Do not build semantic/vector code search.** Lexical + symbol index only (§1.3).
8. **Do not build from memory.** Verify the MCP spec, SDK, transport, and model APIs against live docs and the `mcp-builder` skill (§6).
9. **Do not overclaim.** "Built an MCP server with security boundaries + model-agnostic discovery" — not "MCP framework" or "autonomous coding agent" (§16).
10. **Do not write README placeholders.** Real eval results, a real refused-traversal screenshot, a real provider-swap demo.

---

## 16. Honest Claims Discipline (Read This Twice)

MCP is current and interviewers will probe whether you *built* or *used* it. Protect the claims:

**Claimable honestly if the build holds:** *"built an MCP server exposing a codebase," "designed the tool/resource schemas and annotations," "enforced and tested security boundaries (repo-root confinement, secrets deny-list, read-only)," "client dynamically discovers tools at runtime," "provider-agnostic host validated on Gemini and local Ollama," "read-only by design."*

**Avoid unless literally true:** *"MCP framework"* (you built one server, not a framework), *"autonomous coding agent"* (it's read-only and human-driven), *"semantic code search"* (it's lexical), *"multi-server orchestration"* (one server). And every number (eval pass rate, tool count) must come from real runs.

**The interview asset:** you can *drive this live* — attempt a path traversal and watch it refused, ask the assistant a codebase question and watch it discover and call tools, then swap the provider and watch it still work. Build toward that demo and the claims defend themselves. As always, a precise smaller claim beats an impressive one that collapses under one follow-up.

**On "why MCP and not just function-calling?"** — you will be asked. The honest answer: function-calling wires tools into one app; MCP exposes them over a uniform interface any compliant client can discover and use, which is why the ecosystem is standardizing on it — and building the server side is what shows you understand that layer, not just the consumer side.

---

## 17. Output Artifacts Checklist

| # | Artifact | Location | Required for |
|---|---|---|---|
| 1 | Public GitHub repo `conduit` | `github.com/<user>/conduit` | Resume link, outreach |
| 2 | Server-and-security-first README | repo root | Recruiter first impression |
| 3 | `ARCHITECTURE.md` + diagram (server ⇄ transport ⇄ host) + security model | repo root | Engineering depth signal |
| 4 | Passing security tests (traversal, denylist, readonly) | `tests/` + CI | The differentiator, proven |
| 5 | Passing `test_dynamic_discovery.ts` | `tests/` | MCP value prop, proven |
| 6 | Passing `test_model_agnostic.ts` + both adapters | `tests/` + `host/llm/` | Provider-agnostic claim, proven |
| 7 | `eval/evaluation.xml` (≥10) + recorded results | `eval/` | Server usefulness demonstrated |
| 8 | 90-second Loom (traversal refused → discovery → provider swap) | Loom link | LinkedIn, outreach |
| 9 | "Why MCP / server-vs-resource / why-not-function-calling" rationale | README + ARCHITECTURE.md | The judgment signal |
| 10 | Resume bullet with honest, demoable MCP + security claims | resume file | Linked from outreach |

When all exist, this is a complete, defensible MCP infrastructure project: a secure codebase server plus a model-agnostic client that discovers and drives it — demonstrating the integration layer that modern AI tooling is built on, from the building side, not the consuming side.

---

## Final note to the coding agent executing this

This document is the source of truth, layered on top of the `mcp-builder` skill for the server implementation. When the agent's instinct conflicts with this document, this document wins. When the agent thinks "it would be simpler to make the tools an in-process dict / assert security without a test / hardcode the tool list / call the provider SDK directly," it should stop — those are exactly the shortcuts that turn this from a real MCP infrastructure project into a generic agent-with-tools that collapses the distinctiveness under one interview question.

The goal is not the most capable coding assistant. The goal is a focused, secure, *live-demoable* MCP server — with tested security boundaries, real dynamic discovery, and provider-agnostic driving — that proves you build the integration layer, not just consume it. Optimize for that.

Good build, Krishiv.
