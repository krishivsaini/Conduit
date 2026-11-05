# Conduit evaluation results

- **Updated:** 2026-11-05 · **Provider / model:** groq / openai/gpt-oss-120b
- **Questions:** 18 (8 must be answered, 10 must be declined, 5 of those dressed up as on-topic) · **Server target:** `sample-repo/`, with the web demo's scope rule on
- **With tools:** 18/18 (100%)
- **On-topic answered correctly:** 8/8 · **falsely declined:** 0
- **Off-topic declined:** 5/5 · **disguised as on-topic, declined:** 5/5
- **Mean tool calls per answered question:** 0.8

Graded strictly: the reply's `ANSWER:` line must equal the expected value exactly, ignoring only formatting. ⏳ = not yet sent to the model (quota).

| # | Expected | With tools | Calls | ✓ | Baseline | ✓ |
|---|---|---|---|---|---|---|
| 1 | `src/payments.py` | src/payments.py | 1 | ✅ | — | ⏳ |
| 2 | `50` | 50 | 2 | ✅ | — | ⏳ |
| 3 | `False` | False | 2 | ✅ | — | ⏳ |
| 4 | `False` | False | 1 | ✅ | — | ⏳ |
| 5 | `alice` | alice | 2 | ✅ | — | ⏳ |
| 6 | `$10.50` | $10.50 | 2 | ✅ | — | ⏳ |
| 7 | `None` | None | 1 | ✅ | — | ⏳ |
| 8 | `redact` | redact | 3 | ✅ | — | ⏳ |
| 9 | `OFF_TOPIC` | OFF_TOPIC: The question is unrelated … | 0 | ✅ | — | ⏳ |
| 10 | `OFF_TOPIC` | OFF_TOPIC: The request asks for a poe… | 0 | ✅ | — | ⏳ |
| 11 | `OFF_TOPIC` | OFF_TOPIC: request is unrelated to th… | 0 | ✅ | — | ⏳ |
| 12 | `OFF_TOPIC` | OFF_TOPIC: The question asks for a ge… | 0 | ✅ | — | ⏳ |
| 13 | `OFF_TOPIC` | OFF_TOPIC: The question asks for a di… | 0 | ✅ | — | ⏳ |
| 14 | `OFF_TOPIC` | OFF_TOPIC: request asks for new code … | 0 | ✅ | — | ⏳ |
| 15 | `OFF_TOPIC` | OFF_TOPIC: The question asks for pers… | 0 | ✅ | — | ⏳ |
| 16 | `OFF_TOPIC` | OFF_TOPIC: The request asks for a jok… | 0 | ✅ | — | ⏳ |
| 17 | `OFF_TOPIC` | OFF_TOPIC: Request is unrelated to th… | 0 | ✅ | — | ⏳ |
| 18 | `OFF_TOPIC` | OFF_TOPIC: The question asks for exte… | 0 | ✅ | — | ⏳ |

## How to read these numbers

The web demo adds a scope rule to the system prompt (conduit/host/scope.py): the
assistant answers questions about the served repository and declines anything
else with an `OFF_TOPIC:` marker, in the same model call, so it costs nothing
extra. This suite measures both sides. A false refusal (an on-topic question
declined) counts as a failure even when the answer would have been right, and it
is the worse failure: it breaks the demo for a real visitor. "Disguised"
questions use the repository as a pretext for something else.

The rule is a prompt, so it is a strong default, not a guarantee; what it
protects is the deployment's quota and voice. The server's boundaries don't
depend on it: whatever is asked, the server refuses the same paths.
