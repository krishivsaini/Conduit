# Conduit evaluation results

- **Updated:** 2026-11-03 · **Provider / model:** groq / openai/gpt-oss-120b
- **Questions:** 10 (each asks about a behaviour, so the code has to be found) · **Server target:** this repository (Conduit itself, `eval/` denied)
- **With tools:** 9/10 (90%)
- **Baseline (same model, no tools):** 2/10 (20%)
- **Mean tool calls per answered question:** 4.5

Graded strictly: the reply's `ANSWER:` line must equal the expected value exactly, ignoring only formatting. ⏳ = not yet sent to the model (quota).

| # | Expected | With tools | Calls | ✓ | Baseline | ✓ |
|---|---|---|---|---|---|---|
| 1 | `8` | _(no ANSWER line)_ | 8 | ❌ | 5 | ❌ |
| 2 | `ReplayDivergence` | ReplayDivergence | 2 | ✅ | ToolOutputMismatchError | ❌ |
| 3 | `conduit/server/security/boundary.py` | conduit/server/security/boundary.py | 3 | ✅ | src/util.c | ❌ |
| 4 | `1000000` | 1000000 | 4 | ✅ | 1000000 | ✅ |
| 5 | `CONDUIT_CLIENT_IP_HEADER` | CONDUIT_CLIENT_IP_HEADER | 3 | ✅ | REAL_IP_HEADER | ❌ |
| 6 | `7` | 7 | 8 | ✅ | 6 | ❌ |
| 7 | `8000` | 8000 | 3 | ✅ | 2000 | ❌ |
| 8 | `.git/` | .git/ | 3 | ✅ | /.git/ | ❌ |
| 9 | `4` | 4 | 3 | ✅ | 2 | ❌ |
| 10 | `429` | 429 | 8 | ✅ | 429 | ✅ |

## How to read these numbers

This suite serves a real repository, this one, instead of the frozen sample:
a common term matches hundreds of lines, there are hundreds of symbols, and the
repo tree only just fits its size budget (larger repos get it collapsed). `eval/` is on the server's deny-list for
the run, so the answer key can't be read. Columns mean the same as in
eval/results.md.

Conduit changes with every commit, so these traces aren't replayed in CI (the
sample suite's are). Instead tests/test_eval_answers.py recomputes every expected
answer from the code, so a change that alters an answer fails CI until the key
is updated.
