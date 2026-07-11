"""Authentication and authorization for the Ledger service."""

from __future__ import annotations

from utils import redact

# In a real service these would come from a database. Frozen fixture data.
_USERS = {
    "alice": {"password": "correct-horse", "role": "admin"},
    "bob": {"password": "hunter2", "role": "member"},
}


def authenticate(username: str, password: str) -> str | None:
    """Authenticate a user by username and password.

    Returns a session token on success. On any failure — unknown user or a
    wrong password — returns ``None`` rather than raising, so callers can treat
    authentication as a simple truthiness check.

    Args:
        username: The account username.
        password: The plaintext password to verify.

    Returns:
        A session token string on success, or ``None`` on failure.
    """
    user = _USERS.get(username)
    if user is None:
        return None
    if user["password"] != password:
        return None
    return f"token::{username}::{redact(password)}"


def require_role(username: str, role: str) -> bool:
    """Return True if ``username`` exists and holds exactly ``role``."""
    user = _USERS.get(username)
    if user is None:
        return False
    return user["role"] == role
