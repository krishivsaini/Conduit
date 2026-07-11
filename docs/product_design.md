# Conduit — Product Design

> **Status:** Draft v1 · Derived from `CONDUIT_BUILD_PLAN.md` (source of truth)
> **Purpose:** The *why* and the *experience*. Positioning, the audience it's designed to convince, the product's value proposition, the demo journey, the CLI experience, and the honest-claims discipline that keeps the product defensible. The *what* (requirements) is in [requirement.md](requirement.md); the *how* in [architecture.md](architecture.md) and [implementation_plan.md](implementation_plan.md).

---

## 1. Product in one sentence

**Conduit is an MCP server that safely exposes a codebase — with tested security boundaries — plus a model-agnostic assistant that discovers the server's tools at runtime and drives them to answer codebase questions.**

The headline is deliberately *the server and its security model*, not "an AI assistant that uses tools." That framing choice is a product decision, and it is the product's reason to exist.

---

## 2. Who this is for

Conduit is a **portfolio / hiring-signal product**. Its "users" are two distinct audiences with different needs:

| Audience | What they need from the product | Where it's served |
|---|---|---|
| **A hiring engineer / interviewer** | Fast, credible evidence that the builder implemented the *integration layer* (server + security), not just consumed a tool. Wants to probe and have claims survive. | README headline, architecture doc, the live demo, tested boundaries. |
| **An LLM host (the assistant's "user" at runtime)** | Well-described tools it can discover and call to answer a real codebase question. | The tool/resource schemas, actionable errors, the eval. |
| **The builder (Krishiv), operating the demo** | A product he can *drive live* — refuse a traversal, answer a question via discovered tools, swap providers — so claims defend themselves under follow-up. | The CLI, `scripts/demo.sh`, the Loom. |

Designing for the interviewer *and* for the LLM at once is the core product tension: the tools must be genuinely useful to a model, and that usefulness must be legible to a human evaluating the work.

---

## 3. Value proposition & positioning

### 3.1 The signal
> **Building the MCP integration layer, not using it.** Most candidates who mention MCP have consumed a server; Conduit's builder has *built* one — with tool-vs-resource design decisions, capability negotiation, transport handling, and (the differentiator) security boundaries around exposing a filesystem over a protocol.

### 3.2 Three axes that must never collapse
The product loses its reason to exist if any of these degrade into the generic "agent with tools":

1. **You build the server.** Tools are an MCP server (a separate process over the protocol), not an in-process `tools/` dict.
2. **Security boundaries are the point.** Exposing a filesystem over a protocol is a real security problem; solving *and testing* it is what makes this mature rather than a demo.
3. **Discovery is dynamic.** The client learns tools from the server at runtime — the actual MCP value proposition.

If, during the build, tools become an in-process dict, security is asserted-but-not-enforced, or the client hardcodes the tool list — **stop and restore.** These are product-defining invariants, not implementation details.

### 3.3 Why MCP and not just function-calling
The honest, interview-ready answer, baked into the README and architecture doc: *function-calling wires tools into one app; MCP exposes them over a uniform interface any compliant client can discover and use — which is why the ecosystem is standardizing on it. Building the server side is what shows you understand that layer, not just the consumer side.*

---

## 4. Product principles

1. **Server-and-security-first, everywhere.** Every external artifact (README, resume bullet, Loom, outreach) leads with the server and its security model — never "an AI assistant that uses tools."
2. **Prove, don't claim.** Every security boundary has a test that *attempts a violation and asserts it fails*. Every provider-agnostic claim is validated on two providers. Numbers come from real runs.
3. **Deliberate smallness.** Read-only, one server, lexical (not semantic) search, stdio transport — each is a *scope choice with a stated rationale*, framed as maturity, not as a gap.
4. **Demoable under probing.** The product is designed to be driven live so a single follow-up question strengthens rather than collapses the claim.
5. **The model is deliberately boring.** The interesting layer is MCP; the LLM is swappable on purpose. That is a feature of the positioning, not an apology.

---

## 5. The experience: the 90-second demo (the core product moment)

The demo *is* the product's primary surface. It has three beats, in order, each proving one pillar:

```
Beat 1 — Security is real (the differentiator)
   Attempt a path traversal ("read ../../etc/passwd") → server refuses live
   with an actionable error. Attempt to read .env → denied.

Beat 2 — Discovery is real (the MCP value prop)
   Ask the assistant a genuine codebase question
   ("Which file defines the function that handles X, and what does it
    return on error?"). Watch it discover the server's tools at runtime,
   call search_code → read_file, and answer.

Beat 3 — Model-agnostic is real (the honest differentiator)
   Swap LLM_PROVIDER from gemini to ollama. Ask again.
   Same host code path, fully offline, still works.
```

Everything in the build serves this arc. If a feature doesn't strengthen one of these three beats, it is a candidate to cut before the differentiators are.

---

## 6. CLI experience

The assistant is delivered as a **clean CLI** (`host/cli.ts`); a minimal web view is an acceptable alternative but not required. The UX priorities, in order:

1. **Legibility of the MCP loop.** The CLI should make the discover → select → call → respond loop *visible* — e.g. surface which tools were discovered and which tool was called with which arguments — because the observable loop is the product's evidence.
2. **Provider transparency.** Show which provider is active (`gemini` / `ollama`) so the swap in Beat 3 is unmistakable.
3. **Refusals are first-class.** When a security boundary refuses a request, the CLI shows the *actionable error* clearly — a refusal is a feature to showcase, not an error to hide.
4. **Scriptability.** `scripts/demo.sh` runs the demo deterministically for the Loom.

Non-goals for the CLI: rich TUI, conversation memory/history features, multi-session state. The signal is the server + security, not the interface.

---

## 7. Success metrics

| Metric | Target | Why it matters |
|---|---|---|
| Security boundary tests passing | 3/3 (traversal, deny-list, read-only) | The differentiator, proven. |
| Dynamic-discovery test passing | Yes | The MCP value prop, proven. |
| Providers validated | 2 (Gemini + Ollama) | "Provider-agnostic" is only claimable if demonstrated on two. |
| Eval questions passing | Recorded real rate over ≥10 Qs | Proves the server is genuinely useful to an LLM. |
| Clean-clone reproduce time | < 10 min (incl. offline path) | Credibility of the "run it yourself" claim. |
| Demo runs live under follow-up | Yes | Claims defend themselves in an interview. |

---

## 8. Honest-claims discipline (product guardrail)

The product's credibility depends on never overclaiming. This is a design constraint, not just copywriting.

**Claimable honestly (if the build holds):** "built an MCP server exposing a codebase," "designed the tool/resource schemas and annotations," "enforced and tested security boundaries," "client dynamically discovers tools at runtime," "provider-agnostic host validated on Gemini and local Ollama," "read-only by design."

**Avoid unless literally true:** "MCP framework" (it's one server), "autonomous coding agent" (read-only, human-driven), "semantic code search" (it's lexical), "multi-server orchestration" (one server). Every number comes from a real run.

**Guiding rule:** *a precise smaller claim beats an impressive one that collapses under one follow-up.*

---

## 9. What "good" looks like (product acceptance)

The product is successful when a hiring engineer can, in a few minutes:
- Read the README and immediately understand this is a *built server with a security model*, not a consumed tool.
- Watch the 90-second demo and see all three pillars proven live.
- Open the architecture doc and find the tool-vs-resource rationale, the security model, and the honest "why MCP" answer.
- Probe any claim and have it hold, because each is backed by a test or a live demonstration.

That is the entire product goal: *a focused, secure, live-demoable MCP server that proves the builder builds the integration layer — not just consumes it.*
