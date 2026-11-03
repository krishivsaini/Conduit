# Conduit evaluation results

- **Updated:** 2026-11-03 · **Provider / model:** groq / openai/gpt-oss-120b
- **Questions:** 20 (1–12 single-step, 13–20 multi-step) · **Server target:** `sample-repo/`
- **With tools:** 20/20 (100%)
- **Baseline (same model, no tools):** 5/20 (25%)
- **Mean tool calls per answered question:** 3.2

Graded strictly: the reply's `ANSWER:` line must equal the expected value exactly, ignoring only formatting. ⏳ = not yet sent to the model (quota).

| # | Expected | With tools | Calls | ✓ | Baseline | ✓ |
|---|---|---|---|---|---|---|
| 1 | `None` | None | 4 | ✅ | false | ❌ |
| 2 | `src/auth.py` | src/auth.py | 3 | ✅ | src/auth/auth_service.py | ❌ |
| 3 | `PaymentError` | PaymentError | 3 | ✅ | InvalidAmountException | ❌ |
| 4 | `50` | 50 | 1 | ✅ | 1 | ❌ |
| 5 | `2` | 2 | 1 | ✅ | 7 | ❌ |
| 6 | `2` | 2 | 5 | ✅ | 4 | ❌ |
| 7 | `src/utils.py` | src/utils.py | 4 | ✅ | src/utils/secret.py | ❌ |
| 8 | `member` | member | 3 | ✅ | user | ❌ |
| 9 | `$` | $ | 4 | ✅ | $ | ✅ |
| 10 | `15` | 15 | 1 | ✅ | 27 | ❌ |
| 11 | `redact` | redact | 3 | ✅ | signJwt | ❌ |
| 12 | `False` | False | 3 | ✅ | False | ✅ |
| 13 | `token::bob::*****r2` | token::bob::*****r2 | 5 | ✅ | abcd1234efgh5678ijkl9012mnop3456 | ❌ |
| 14 | `amount below minimum of $0.50` | amount below minimum of $0.50 | 3 | ✅ | Amount must be at least 50 cents | ❌ |
| 15 | `$10.50` | $10.50 | 4 | ✅ | 10.50 | ❌ |
| 16 | `False` | False | 3 | ✅ | False | ✅ |
| 17 | `alice` | alice | 1 | ✅ | admin | ❌ |
| 18 | `False` | False | 2 | ✅ | False | ✅ |
| 19 | `3` | 3 | 6 | ✅ | 3 | ✅ |
| 20 | `5` | 5 | 6 | ✅ | 7 | ❌ |

## How to read these numbers

The measure of an MCP server is whether a model can use it to answer real
questions it could not answer alone. The **with tools** column is the full
system: discovered tools, the repo tree as context, a step budget. The
**baseline** column is the same model and prompt with no tools and no repo, so
the gap between them is what the server contributes. Grading is exact (see the
top of eval/run_eval.py), so a verbose answer that happens to contain the right
number does not count.

Questions 13–20 are multi-step: each needs evidence from more than one file, or
reading past a misleading docstring. Every expected answer is checked against the
sample repo's code actually executing, in tests/test_eval_answers.py.

The Gemini free tier allows about 5 requests a minute and a small daily cap, so
a full run can span days. Runs resume where they stopped; *pending* rows were
never sent to the model and are not scored. Results recorded under the earlier,
lenient substring rubric are kept in eval/results.gemini.v1.json.
