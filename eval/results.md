# Conduit evaluation results

- **Updated:** 2026-11-02 · **Provider / model:** gemini / gemini-3.5-flash
- **Questions:** 20 (1–12 single-step, 13–20 multi-step) · **Server target:** `sample-repo/`
- **With tools:** 5/5 (100%) of questions answered so far
- **Baseline (same model, no tools):** not run
- **Mean tool calls per answered question:** 1.6

Graded strictly: the reply's `ANSWER:` line must equal the expected value exactly, ignoring only formatting. ⏳ = not yet sent to the model (quota).

| # | Expected | With tools | Calls | ✓ | Baseline | ✓ |
|---|---|---|---|---|---|---|
| 1 | `None` | — | — | ⏳ | — | ⏳ |
| 2 | `src/auth.py` | — | — | ⏳ | — | ⏳ |
| 3 | `PaymentError` | — | — | ⏳ | — | ⏳ |
| 4 | `50` | — | — | ⏳ | — | ⏳ |
| 5 | `2` | — | — | ⏳ | — | ⏳ |
| 6 | `2` | — | — | ⏳ | — | ⏳ |
| 7 | `src/utils.py` | — | — | ⏳ | — | ⏳ |
| 8 | `member` | — | — | ⏳ | — | ⏳ |
| 9 | `$` | — | — | ⏳ | — | ⏳ |
| 10 | `15` | — | — | ⏳ | — | ⏳ |
| 11 | `redact` | — | — | ⏳ | — | ⏳ |
| 12 | `False` | — | — | ⏳ | — | ⏳ |
| 13 | `token::bob::*****r2` | token::bob::*****r2 | 2 | ✅ | — | ⏳ |
| 14 | `amount below minimum of $0.50` | amount below minimum of $0.50 | 2 | ✅ | — | ⏳ |
| 15 | `$10.50` | $10.50 | 2 | ✅ | — | ⏳ |
| 16 | `False` | False | 1 | ✅ | — | ⏳ |
| 17 | `alice` | alice | 1 | ✅ | — | ⏳ |
| 18 | `False` | — | — | ⏳ | — | ⏳ |
| 19 | `3` | — | — | ⏳ | — | ⏳ |
| 20 | `5` | — | — | ⏳ | — | ⏳ |

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
