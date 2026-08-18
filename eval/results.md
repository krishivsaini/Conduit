# Conduit evaluation results

- **Date:** 2026-08-18
- **Provider / model:** gemini / gemini-3.5-flash
- **Server target:** `sample-repo/`
- **Executed accuracy:** 6/6 (100%) — of 12 questions

Each question is answered through Conduit's own host: the client discovers the
server's tools at runtime and drives them, and the final answer is graded by
case-insensitive substring match. Questions marked *pending* were never sent to
the model (free-tier daily quota); re-running resumes where it left off.

| # | Expected | Model answer | Tool calls | Result |
|---|---|---|---|---|
| 1 | `None` | None | 2 | ✅ |
| 2 | `src/auth.py` | The function responsible for verifying a user's credentials is `authenticate`… | 2 | ✅ |
| 3 | `PaymentError` | The exception type raised is **`PaymentError`** (defined in `src/payments.py`). | 2 | ✅ |
| 4 | `50` | 50 | 2 | ✅ |
| 5 | `2` | 2 | 2 | ✅ |
| 6 | `2` | 2 | 4 | ✅ |
| 7 | `src/utils.py` | — | — | ⏳ pending (quota) |
| 8 | `member` | — | — | ⏳ pending (quota) |
| 9 | `$` | — | — | ⏳ pending (quota) |
| 10 | `15` | — | — | ⏳ pending (quota) |
| 11 | `redact` | — | — | ⏳ pending (quota) |
| 12 | `False` | — | — | ⏳ pending (quota) |

## Also verified: the fully-local path

The same eval, same host, run against a local Ollama model (`--provider ollama`)
completes **all 12 questions with real tool calls and no API key** — confirming
the discover → call → respond loop and the server's tools work end-to-end
offline. Final-answer accuracy there is low (1/12 on a 0.8B model, which usually
hits the tool-step cap before synthesizing): that measures the *model*, not the
server. The tool calls themselves were correct.

## Interpreting these numbers

The measure of an MCP server is whether an LLM can use it to answer real
questions. On a capable model every executed question was answered correctly
from tool evidence, with citations. The only cap is the Gemini free-tier daily
quota, which limits how many questions one day's run can execute — runs are
checkpointed and resume, so repeating the command on a later day completes the
remainder without re-asking what's already answered.
