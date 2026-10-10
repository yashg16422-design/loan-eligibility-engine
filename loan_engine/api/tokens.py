"""Signed dashboard tokens: a borrower opens their dashboard without an account or password.

A token says "this is user X until time T", signed with HMAC-SHA256 under a key kept in
Secrets Manager. The server stores nothing per token: verifying is recomputing the signature.
Format (URL-safe, no padding): ``<user_id hex>.<expiry unix seconds>.<signature>``.

Pure functions: the key and the clock are passed in, so tests need no AWS and no sleeping.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import uuid

VERSION = b"v1"  # part of the signed message: a future format can't be confused with this one
CHECK_TTL_SECONDS = 24 * 3600  # instant check: the visitor came to the site
EMAIL_TTL_SECONDS = 14 * 24 * 3600  # link in the notification email: read days later


class InvalidTokenError(ValueError):
    """Malformed, forged or expired token (always answered with HTTP 401)."""


def _signature(user_hex: str, expires_at: int, key: bytes) -> str:
    message = b".".join([VERSION, user_hex.encode(), str(expires_at).encode()])
    digest = hmac.new(key, message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def sign(user_id: uuid.UUID, expires_at: int, key: bytes) -> str:
    """Token for `user_id`, valid until the unix time `expires_at`."""
    if len(key) < 32:
        raise ValueError("token key must be at least 32 bytes")
    return f"{user_id.hex}.{expires_at}.{_signature(user_id.hex, expires_at, key)}"


def verify(token: str, key: bytes, now: int) -> uuid.UUID:
    """The user id inside a genuine, unexpired token.

    Raises:
        InvalidTokenError: for anything else (the reason is for logs, never for the client).
    """
    parts = token.split(".") if isinstance(token, str) else []
    if len(parts) != 3 or len(token) > 200:
        raise InvalidTokenError("malformed token")
    user_hex, expiry, signature = parts
    try:
        user_id = uuid.UUID(hex=user_hex)
        expires_at = int(expiry)
    except ValueError:
        raise InvalidTokenError("malformed token") from None
    # Constant-time comparison: timing must not reveal how much of a forgery was right.
    if not hmac.compare_digest(signature, _signature(user_hex, expires_at, key)):
        raise InvalidTokenError("bad signature")
    if now >= expires_at:
        raise InvalidTokenError("expired token")
    return user_id


def bearer(headers: dict[str, str] | None) -> str:
    """The token from an ``Authorization: Bearer <token>`` header ('' when absent)."""
    value = (headers or {}).get("authorization", "")
    scheme, _, token = value.partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""
