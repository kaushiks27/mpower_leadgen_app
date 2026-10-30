"""Argon2 password hashing for the auth feature.

Single PasswordHasher with default parameters, a module-level DUMMY_HASH for
timing-safe equality on unknown emails (login always verifies against
*something* so wall time does not leak whether an email exists), and explicit
hash/verify helpers.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerifyMismatchError

_HASHER = PasswordHasher()

# Pre-computed hash of a fixed dummy password — consumes CPU when the login
# flow must verify "something" against an unknown email so response time stays
# symmetric and cannot be used to enumerate accounts.
DUMMY_HASH = _HASHER.hash("__dummy_for_timing_safety__")

MIN_PASSWORD_LEN = 8


def hash_password(plain: str) -> str:
    return _HASHER.hash(plain)


def verify_password(plain: str, stored_hash: str) -> bool:
    """Return True iff `plain` matches `stored_hash`. Never raises."""
    try:
        _HASHER.verify(stored_hash, plain)
        return True
    except (VerifyMismatchError, InvalidHash, Exception):
        return False
