# Conduit — Implementation Plan

> **Status:** Draft v1
> **Purpose:** The *how it gets built over time* — phases, day-by-day tasks, dependencies, per-phase exit criteria, and risks. Requirements are in [requirement.md](requirement.md); the structure being built in [architecture.md](architecture.md); the positioning in [product_design.md](product_design.md).
>
> **Cadence:** 12–14 days × ~3 hours/day, ₹0 to run.
> **If time slips, cut in this order:** HTTP transport → web UI. **Never cut** the security boundaries, the dynamic-discovery test, or the model-agnostic adapter — those are the differentiators.

---

## 1. Ground rule before any code

Follow the `mcp-builder` skill (`/mnt/skills/examples/mcp-builder/SKILL.md`) for the server, and **verify live before building** (non-negotiable):
- Load the MCP spec via its sitemap (pages with `.md` suffix) and the current SDK README before writing server code.
- Confirm the current transport recommendation (stdio local / streamable HTTP remote) and the current tool/resource registration API.
- Confirm the current Gemini Flash model ID + free-tier limits and the current Ollama tool-calling API before writing adapters.
- When unsure about any protocol/SDK/provider detail, fetch docs rather than guessing.

---

## 2. Phases (grouping of the day-by-day)

| Phase | Days | Theme | Differentiator it protects |
|---|---|---|---|
| **P0 — Foundation** | 1 | Verify live docs, scaffold, pick target repo | — |
| **P1 — Minimal server** | 2 | One tool + stdio + Inspector | "Build a server, not a client" |
| **P2 — Security** | 3–4 | Boundary, deny-list, read-only (tested) | **The differentiator** |
| **P3 — Full toolset** | 5–7 | search/symbols/diff, repo_tree, actionable errors | Server quality |
| **P4 — Host + discovery** | 8–9 | MCP client, dynamic discovery, Gemini loop | **Dynamic discovery** |
| **P5 — Model-agnostic** | 10–11 | Ollama adapter, provider switch, discovery test | **Provider-agnostic** |
| **P6 — Eval & polish** | 12–14 | Eval, architecture doc, reproducibility, README + Loom | Proof & artifacts |

---

## 3. Day-by-day plan

| Day | Focus | End-of-day artifact | Exit gate |
|---|---|---|---|
| 1 | Read `mcp-builder`; fetch live MCP spec + SDK README; pick TS (or Python); scaffold repo per layout; choose the demo repo the server will serve. | Environment verified against live docs; repo skeleton; server target chosen. | Skeleton compiles; docs verified. |
| 2 | Minimal MCP server: one tool (`read_file`) + stdio transport; test with MCP Inspector. | Server runs; Inspector can call `read_file`. | Inspector round-trips a read. |
| 3 | Security boundary: repo-root confinement + path-traversal defense (`boundary.ts`). | `test_security_traversal.ts` green. | Traversal attempt refused by test. |
| 4 | Deny-list + read-only posture; wire the boundary into `read_file`. | `test_security_denylist.ts`, `test_security_readonly.ts` green. | Denied file unreadable; no write path. |
| 5 | `indexer.ts` + `search_code` (lexical/symbol), paginated, schema + annotations. | Search works via Inspector; boundary-checked. | Search returns bounded, structured matches. |
| 6 | `list_symbols` + `diff` tools; `repo_tree` resource (deny-list applied). | Full tool/resource set live. | All tools + resource callable in Inspector. |
| 7 | `errors.ts`: structured actionable errors across all tools; `test_tools.ts`. | Bad inputs return actionable errors, not stack traces. | `test_tools.ts` green (good + bad paths). |
| 8 | Host MCP client: connect + **dynamic discovery** of tools. | Client lists server tools it did not hardcode. | Client prints discovered tools, no hardcoded list. |
| 9 | `adapter.ts` + Gemini adapter; host loop (discover→select→call→respond). | Assistant answers a question by calling a tool, via Gemini. | End-to-end answer via a real tool call. |
| 10 | Ollama adapter; `LLM_PROVIDER` switch; `test_model_agnostic.ts`. | Same assistant works fully locally via Ollama. | Offline answer via Ollama; test green. |
| 11 | `test_dynamic_discovery.ts` (rename/add a tool → client uses it, no client change). | Discovery proven; MCP value prop demonstrated. | Test green with an unedited client. |
| 12 | `eval/evaluation.xml` (≥10) + run it; record results. | Eval demonstrates the server is useful to an LLM. | ≥10 conforming Qs; real results recorded. |
| 13 | ARCHITECTURE.md (diagram + security model + why-MCP); reproducibility pass (clean clone, offline Ollama path). | Clean-clone run < 10 min; offline path works. | Timed clean clone < 10 min. |
| 14 | README + Loom (traversal refused live + dynamic discovery + provider swap) + resume bullet. | All output artifacts exist. | Every §5 artifact present. |

---

## 4. Dependency graph (what blocks what)

```
Day 1 (verify + scaffold)
   │
Day 2 (minimal server + stdio) ──────────────┐
   │                                          │
Day 3 (boundary) → Day 4 (denylist+readonly)  │
   │                                          │
Day 5 (search) → Day 6 (symbols/diff/tree) → Day 7 (errors)
                                                 │
Day 8 (client + discovery) ──────────────────────┤
   │                                              │
Day 9 (Gemini loop) → Day 10 (Ollama + switch) → Day 11 (discovery test)
                                                     │
Day 12 (eval) → Day 13 (architecture + reproduce) → Day 14 (README + Loom)
```

Critical rule: **the security work (Days 3–4) gates the full toolset (Days 5–7)** — every new tool wires through the already-tested boundary, so the boundary is built and proven first.

---

## 5. Output artifacts checklist (Definition of Done)

| # | Artifact | Location | Proves |
|---|---|---|---|
| 1 | Public GitHub repo `conduit` | `github.com/<user>/conduit` | Resume link. |
| 2 | Server-and-security-first README | repo root | Recruiter first impression. |
| 3 | `ARCHITECTURE.md` + diagram + security model | repo root | Engineering depth. |
| 4 | Passing security tests (traversal, denylist, readonly) | `tests/` (+ CI) | **The differentiator, proven.** |
| 5 | Passing `test_dynamic_discovery.ts` | `tests/` | MCP value prop, proven. |
| 6 | Passing `test_model_agnostic.ts` + both adapters | `tests/` + `host/llm/` | Provider-agnostic claim, proven. |
| 7 | `eval/evaluation.xml` (≥10) + recorded results | `eval/` | Server usefulness. |
| 8 | 90-second Loom (traversal → discovery → provider swap) | Loom link | Outreach. |
| 9 | "Why MCP / server-vs-resource / why-not-function-calling" rationale | README + ARCHITECTURE.md | Judgment signal. |
| 10 | Resume bullet with honest, demoable claims | resume | Linked from outreach. |

---

## 6. Risks & mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Building from memory on a changed protocol/SDK | Broken/outdated server | Day-1 live verification is a hard gate; re-check when anything feels off. |
| Tools drift into an in-process dict | Loses the whole signal | Invariant check every phase: is this still a server over the protocol? If not, stop and restore. |
| Security asserted but not tested | "Security theater," differentiator gone | No boundary is "done" until a violation-attempt test is green (Days 3–4 gate the rest). |
| Client hardcodes the tool list | Discovery becomes decorative | `test_dynamic_discovery.ts` (Day 11) must pass with an unedited client. |
| Provider SDK called from the loop | Breaks model-agnosticism | Loop calls only `adapter.decide()`; enforced by the stub-adapter test. |
| Gemini free-tier limits / model-ID churn | Adapter fails at demo time | Confirm model ID + limits live; Ollama offline path is the zero-dependency fallback. |
| Time slips | Miss the deadline | Cut HTTP transport, then web UI. Never cut the three differentiators. |
| Scope creep (write tools, semantic search, multi-server) | Reverts to a generic agent | Treated as explicit non-goals; noted as future work only. |

---

## 7. Testing strategy (built alongside, not after)

| Test | Introduced | Asserts |
|---|---|---|
| `test_security_traversal.ts` | Day 3 | `../../etc/passwd` / absolute / symlink escapes refused. |
| `test_security_denylist.ts` | Day 4 | `.env` / key files never read or discovered. |
| `test_security_readonly.ts` | Day 4 | No write/execute tool registered; no code path writes. |
| `test_tools.ts` | Day 7 | Each tool: valid input → structured output; bad input → actionable error. |
| `test_dynamic_discovery.ts` | Day 11 | Client uses a newly added/renamed tool with no client change. |
| `test_model_agnostic.ts` | Day 10 | Loop works via stub adapter; both real adapters conform. |
| MCP Inspector (manual) | Days 2–6 | Manual round-trip of each tool/resource as it lands. |
| `eval/evaluation.xml` run | Day 12 | ≥10 realistic, verifiable, read-only questions; real pass results. |

---

## 8. Common failure modes to avoid (from the build plan)

1. Don't build tools as an in-process dict — it must be an MCP server over the protocol.
2. Don't assert security without a violation-attempt test.
3. Don't hardcode the tool list in the client.
4. Don't call a provider SDK from the host loop — only the adapter interface.
5. Don't let a client-supplied path reach the filesystem unchecked — boundary first, always.
6. Don't add write/execute tools — read-only is the security-surface decision.
7. Don't build semantic/vector search — lexical + symbol index only.
8. Don't build from memory — verify against live docs and the `mcp-builder` skill.
9. Don't overclaim — precise, tested claims only.
10. Don't write README placeholders — real eval results, real refused-traversal capture, real provider-swap demo.

---

## 9. Definition of done (roll-up)

The build is complete when every checkbox in [requirement.md §8](requirement.md) holds and every artifact in §5 above exists — i.e. a secure, live-demoable MCP codebase server with tested boundaries, real dynamic discovery, and provider-agnostic driving, reproducible from a clean clone in under 10 minutes.
