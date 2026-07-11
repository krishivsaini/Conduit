# Ledger — a tiny billing service (Conduit demo fixture)

This is a small, **frozen** sample codebase that the Conduit MCP server serves
during the demo and evaluation. It exists so that:

- codebase questions have **stable, verifiable answers** (the eval, §12), and
- the security deny-list can be shown **refusing real secret files** that live
  right here in the tree (`.env`, `service.key`) — see §8.

It is not a real service. The secrets are intentional fakes.

## Layout

| File | What it holds |
|---|---|
| `src/auth.py` | User authentication and role checks. |
| `src/payments.py` | Charging and refunding accounts. |
| `src/utils.py` | Shared formatting/redaction helpers. |
| `.env` | **FAKE** secrets — deny-list fixture (never exposed by the server). |
| `service.key` | **FAKE** private key — deny-list fixture. |
