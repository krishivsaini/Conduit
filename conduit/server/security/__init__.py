"""Security boundaries — the differentiator (§8 of the build plan).

Each boundary is enforced here and proven by a test in tests/ that attempts
a violation and asserts it fails:

  - boundary.py  → repo-root confinement / path-traversal defense
  - denylist.py  → secrets / .env / key exclusion
  - readonly.py  → provably read-only posture

Enforcement ordering (an architectural invariant): every client-supplied path
passes through boundary → denylist BEFORE any filesystem access. There is no
write/execute path anywhere in the server.
"""
