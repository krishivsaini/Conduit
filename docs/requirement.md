# Conduit — Requirements

> **Status:** Draft v1 · Derived from `CONDUIT_BUILD_PLAN.md` (source of truth)
> **Purpose:** The contract for what must be true for Conduit to be "done." This document states *what* is required and how each requirement is verified. The *why* lives in [product_design.md](product_design.md), the *how it's structured* in [architecture.md](architecture.md), and the *how it's built* in [implementation_plan.md](implementation_plan.md).

---

## 1. Problem statement

Most portfolios that mention the Model Context Protocol (MCP) have *consumed* a pre-built server. Conduit's requirement is to demonstrate the rarer signal: **building** the MCP integration layer — a server that safely exposes a code repository over the protocol, plus a model-agnostic client that discovers and drives its tools at runtime.

The requirement is therefore split across four pillars, each of which must be **demonstrable and tested**, not merely asserted:

1. A real MCP **server** exposing a codebase (not an in-process tool dict).
2. Hard, **tested security boundaries** around what the server exposes (the differentiator).
3. **Dynamic discovery** — the client learns tools from the server at runtime.
4. A **model-agnostic** host proven on two providers.

---

## 2. Definitions

| Term | Meaning |
|---|---|
| Server | The process exposing codebase tools/resources over MCP. |
| Host / client | The LLM-powered process that connects to the server, discovers capabilities, and drives them. |
| Tool | A server-exposed *action* (`search_code`, `read_file`, `list_symbols`, `diff`) with input/output schemas. |
| Resource | Server-exposed *context* (`repo_tree`) — data, not an action. |
| Repo root | The single directory the server is permitted to serve; nothing outside is readable. |
| Deny-list | Paths/patterns refused even inside the root (`.env`, `*.key`, `*.pem`, `.git/`). |
| Security boundary | An enforced limit on server behavior (root confinement, deny-list, read-only). |
| Adapter | The seam letting the host drive Gemini or a local Ollama model behind one interface. |

---

## 3. Functional requirements

### 3.1 The MCP server

| ID | Requirement | Verification |
|---|---|---|
| FR-S1 | The server runs as a separate process communicating over the MCP protocol (not an in-process function registry). | Runs standalone; connectable via MCP Inspector. |
| FR-S2 | Exposes tool `search_code`: lexical/symbol search across the repo, paginated, returning matches with file + line + snippet. | Inspector call returns structured, paginated matches. |
| FR-S3 | Exposes tool `read_file`: reads a file within the root, supporting line ranges to bound context. | Inspector call returns bounded file content. |
| FR-S4 | Exposes tool `list_symbols`: returns symbols (functions/classes) for a file or matching a query, from a symbol index. | Inspector call returns symbol list. |
| FR-S5 | Exposes tool `diff`: structured diff between two refs or two files. | Inspector call returns structured diff. |
| FR-S6 | Exposes resource `repo_tree`: the file tree + basic metadata, with the deny-list applied. | Resource read returns tree excluding denied paths. |
| FR-S7 | Every tool has a typed input schema (Zod/Pydantic) with clear descriptions/constraints and structured output where possible. | Schema present per tool; output validates. |
| FR-S8 | Every tool declares appropriate annotations (e.g. `readOnlyHint: true`). | Annotations present in tool registration. |
| FR-S9 | Every tool returns structured, actionable errors (what went wrong + what to do) — never a raw stack trace to the client. | Bad input returns actionable error (see FR-T*). |

### 3.2 The host / client

| ID | Requirement | Verification |
|---|---|---|
| FR-H1 | On startup the client connects to the server and **discovers** tools/resources via MCP capability negotiation. | Client lists tools it did not hardcode. |
| FR-H2 | The tool list is **not hardcoded** in the client. | Code review + FR-H5 test. |
| FR-H3 | The host loop is: receive request → present discovered tool schemas to the LLM → LLM selects tool + args → client calls tool over MCP → feed result back → LLM composes an answer (possibly iterating). | Assistant answers a codebase question end-to-end. |
| FR-H4 | A clean CLI drives the assistant demo. | `host/cli.ts` runs an interactive/scripted session. |
| FR-H5 | Adding or renaming a server tool causes the client to use it **with no client-side code change**. | `test_dynamic_discovery.ts` passes. |

### 3.3 Model-agnostic LLM layer

| ID | Requirement | Verification |
|---|---|---|
| FR-M1 | One adapter interface: given a user message + discovered tool schemas, return a tool-selection (name + args) or a final answer. | Interface defined in `host/llm/adapter.ts`. |
| FR-M2 | A Gemini adapter (free tier, default) implements the interface. | Assistant answers via Gemini. |
| FR-M3 | An Ollama adapter (local, e.g. Qwen2.5) implements the interface. | Assistant answers fully offline via Ollama. |
| FR-M4 | `LLM_PROVIDER` env var selects the provider at runtime; the host loop calls only the adapter, never a provider SDK directly. | Swapping the env var changes provider with no loop code change. |
| FR-M5 | The loop works with a deterministic stub adapter (no network). | `test_model_agnostic.ts` passes. |

### 3.4 Evaluation

| ID | Requirement | Verification |
|---|---|---|
| FR-E1 | `eval/evaluation.xml` contains **≥10** questions that require using the server's tools, are realistic, verifiable (single checkable answer), read-only, and stable. | File present with ≥10 conforming entries. |
| FR-E2 | The eval is run and per-question results (pass/fail) are recorded from a real run. | Recorded results, no placeholders. |

---

## 4. Security requirements (the differentiator — non-negotiable)

Each boundary is **enforced in code and proven by a test that attempts a violation and asserts it fails.**

| ID | Requirement | Verification |
|---|---|---|
| SR-1 | **Repo-root confinement / path-traversal defense.** Every path is resolved and checked to be inside the configured root. `../../etc/passwd`, absolute paths outside the root, and symlink escapes are refused with an actionable error. | `test_security_traversal.ts` asserts refusal. |
| SR-2 | **Deny-list.** Even inside the root, configured sensitive paths/patterns (`.env`, `*.key`, `*.pem`, `.git/`, credentials files) never appear in `repo_tree`, `search_code` results, or `read_file`. | `test_security_denylist.ts` asserts a denied file cannot be read or discovered. |
| SR-3 | **Read-only posture.** No tool mutates the filesystem or executes code; no write/execute path exists. | `test_security_readonly.ts` asserts no such tool is registered and no code path writes. |
| SR-4 | **Bounded output.** Reads are line-range-bounded and search is paginated, so a single call cannot exfiltrate the whole repo or blow context. | Reads/search enforce bounds; verified in `test_tools.ts`. |
| SR-5 | **Untrusted input.** Any client-supplied path/pattern is validated against the boundary *before* touching the filesystem. | Code review: boundary check precedes all FS access. |

---

## 5. Non-functional requirements

| ID | Requirement | Verification |
|---|---|---|
| NFR-1 | **Reproducible in < 10 minutes** from a clean clone, either fully local (Ollama path, zero external dependency) or on the Gemini free tier. | Timed clean-clone run. |
| NFR-2 | **₹0 to run** — free Gemini tier or local Ollama; no paid dependency. | Config uses only free/local providers. |
| NFR-3 | **Actionable errors everywhere** — structured `{ what, why, fix }`-style errors, never stack traces to the client. | `test_tools.ts` for bad-input paths. |
| NFR-4 | **Follows the current MCP spec + installed SDK** — protocol/transport/APIs verified against live docs, not built from memory. | Verification notes in commit history / architecture doc. |
| NFR-5 | **Repo hygiene** — `.gitignore` excludes `.env`, `node_modules`, `dist/`, `.ollama/`; no secrets in history; keys via env only; MIT license. | Repo inspection. |
| NFR-6 | **Transport:** stdio for the local case (required); streamable HTTP as a documented optional alternative. | stdio works; HTTP documented if built. |

---

## 6. Scope

### 6.1 In scope
- One MCP server exposing a codebase (search, read, symbol lookup, diff) + a `repo_tree` resource.
- Tested security boundaries (root confinement, deny-list, read-only, bounded output).
- A model-agnostic host with runtime tool discovery over stdio.
- Two LLM adapters (Gemini free tier + local Ollama) behind one interface.
- ≥10-question MCP-style evaluation with recorded results.
- README, architecture doc, and a 90-second demo.

### 6.2 Out of scope (deliberate)
| Excluded | Reason |
|---|---|
| Write / destructive / shell-execution tools | Keeps the security surface tractable and the demo safe. Read-only by design. Noted as future work with implications. |
| Multi-server orchestration | One server built deeply; composing third-party servers is a different, more overlapping project. |
| Semantic / vector (RAG) code search | Search is lexical + symbolic. Semantic search is documented future work. |
| Fine-tuning / agent-orchestration frameworks | The host is a minimal discover→select→call→respond loop. |
| Fancy frontend | A clean CLI (or minimal web view) suffices; the signal is server + security, not UI. |

---

## 7. Constraints & assumptions

- **Language:** TypeScript with the official MCP TS SDK is recommended (strongest ecosystem support); Python + FastMCP is an acceptable alternative if the whole build mirrors it.
- **Schemas:** Zod (TS) or Pydantic (Python).
- **Default model:** Gemini Flash free tier (confirm the exact current model ID and rate limits against live docs before building); alternative local Ollama model (e.g. Qwen2.5).
- **Search:** lexical (ripgrep-style) + a lightweight symbol index; **no embeddings**.
- **Manual testing:** MCP Inspector (`npx @modelcontextprotocol/inspector`).
- The server is pointed at a **target repo to serve** (chosen during Day 1).

---

## 8. Acceptance criteria (Definition of Done)

Conduit is done when **all** hold:

- [ ] **Server:** real MCP server exposing `search_code`, `read_file`, `list_symbols`, `diff`, and the `repo_tree` resource; typed schemas, structured output, annotations, actionable errors; Inspector-testable. *(FR-S1–S9)*
- [ ] **Security:** `test_security_traversal.ts`, `test_security_denylist.ts`, `test_security_readonly.ts` all green; bounded output enforced. *(SR-1–5)*
- [ ] **Dynamic discovery:** client discovers tools at runtime; `test_dynamic_discovery.ts` proves it uses a newly added/renamed tool with no client change. *(FR-H1–H5)*
- [ ] **Model-agnostic:** host runs on Gemini and local Ollama via one adapter selected by `LLM_PROVIDER`; `test_model_agnostic.ts` passes. *(FR-M1–M5)*
- [ ] **Evaluation:** `eval/evaluation.xml` with ≥10 conforming questions + recorded real results. *(FR-E1–E2)*
- [ ] **Docs & demo:** server-and-security-first README; architecture doc with security model + "why MCP" rationale; limitations & reproducing sections; 90-second demo (traversal refused → discovery → provider swap). *(§6.6/6.9 of build plan)*
- [ ] **Reproducibility & hygiene:** clean-clone run < 10 min including the offline Ollama path; `.gitignore`/secrets/LICENSE hygiene met. *(NFR-1, NFR-5)*

---

## 9. Traceability

Every requirement above maps back to the build plan sections it derives from: mission & non-negotiables (§1), scope (§1.3, §2), server tools (§7), security (§8), discovery (§9), model-agnostic layer (§10), transport (§11), evaluation (§12), and acceptance criteria (§14). If a requirement here and the build plan ever diverge, the build plan wins and this document must be corrected.
