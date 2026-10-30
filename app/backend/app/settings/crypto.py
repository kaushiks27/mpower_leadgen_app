"""Symmetric encryption for API keys at rest (Fernet / AES-128-CBC + HMAC).

Key resolution (deterministic):
  1. `SECRETS_KEY` env — a urlsafe-base64 32-byte Fernet key (preferred; prod).
  2. else derive from `SECRET_KEY` env — SHA-256 → urlsafe-b64 (dev convenience).
  3. else raise — never silently use a default key.

Derivation lets dev/CI work with just `SECRET_KEY` (already required by
main.py), while prod can rotate a dedicated `SECRETS_KEY`. Key is read at call
time so tests can monkeypatch.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


class SecretsKeyError(RuntimeError):
    """No usable encryption key available."""


def _fernet() -> Fernet:
    raw = (os.environ.get("SECRETS_KEY") or "").strip()
    if raw:
        try:
            return Fernet(raw.encode("utf-8"))
        except (ValueError, TypeError) as e:
            raise SecretsKeyError(f"SECRETS_KEY is not a valid Fernet key: {e}") from e
    secret = (os.environ.get("SECRET_KEY") or "").strip()
    if not secret:
        raise SecretsKeyError(
            "no SECRETS_KEY and no SECRET_KEY set — cannot encrypt API keys"
        )
    derived = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(derived)


def encrypt(plaintext: str) -> str:
    """Encrypt a plaintext secret → urlsafe token string (stored in DB)."""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> str:
    """Decrypt a stored token → plaintext. Raises InvalidToken if the key
    changed or the ciphertext is corrupt."""
    return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")


__all__ = ["encrypt", "decrypt", "SecretsKeyError", "InvalidToken"]
