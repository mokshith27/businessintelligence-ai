"""JWT authentication for BusinessIntelligence.ai.

Closes the enterprise-readiness gap: role filtering was previously
application-level only. This module adds real authentication:

- ``POST /api/auth/login`` issues a signed JWT (HS256) with a role claim
- ``GET /api/auth/me`` validates the bearer token
- Write/LLM endpoints require a valid token (configurable)

Design constraints:
- No external user store needed for the demo: demo users are seeded
  in-code with PBKDF2-hashed passwords (never plaintext).
- ``AUTH_DISABLED=1`` in ``.env`` turns enforcement off for local dev,
  so the existing demo flow keeps working unchanged.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path
from typing import Any, Optional

import jwt

# ============================================================
# CONFIGURATION
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_env_file() -> None:
    """Minimal .env loader (mirrors llm/story_generator.py behaviour)."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_env_file()

JWT_SECRET = os.environ.get("JWT_SECRET", "") or secrets.token_urlsafe(48)
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "480"))
AUTH_DISABLED = os.environ.get("AUTH_DISABLED", "0").strip() == "1"

# ============================================================
# DEMO USER STORE (PBKDF2-hashed, never plaintext)
# ============================================================

_PBKDF2_ITERATIONS = 120_000


def _hash_password(password: str, salt: Optional[bytes] = None) -> str:
    if salt is None:
        salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _PBKDF2_ITERATIONS,
    )
    return f"pbkdf2${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split("$")
        if scheme != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            _PBKDF2_ITERATIONS,
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def _seed_user(username: str, password: str, role: str, full_name: str) -> dict:
    return {
        "username": username,
        "password_hash": _hash_password(password),
        "role": role,
        "full_name": full_name,
    }


# Demo users — one per persona used by the role filter.
# Passwords are documented in README (demo only; production would
# use an identity provider / SSO).
DEMO_USERS: dict[str, dict[str, Any]] = {
    user["username"]: user
    for user in [
        _seed_user(
            "maria.exec",
            "demo-exec-2026",
            "executive",
            "Maria Silva - Head of Marketplace Operations",
        ),
        _seed_user(
            "joao.ops",
            "demo-ops-2026",
            "operations",
            "Joao Costa - Marketplace Ops Team Lead",
        ),
        _seed_user(
            "ana.analyst",
            "demo-analyst-2026",
            "analyst",
            "Ana Souza - Business / Data Analyst",
        ),
    ]
}


# ============================================================
# AUTHENTICATION
# ============================================================


class AuthenticationError(Exception):
    """Raised when credentials are invalid."""


class AuthorizationError(Exception):
    """Raised when the token's role is insufficient."""


def authenticate(username: str, password: str) -> dict[str, Any]:
    """Validate credentials and return the user record."""
    user = DEMO_USERS.get((username or "").strip().lower())
    if user is None or not _verify_password(password or "", user["password_hash"]):
        raise AuthenticationError("Invalid username or password")
    return user


def create_token(user: dict[str, Any]) -> str:
    """Issue a signed JWT with role + identity claims."""
    now = int(time.time())
    payload = {
        "sub": user["username"],
        "role": user["role"],
        "name": user["full_name"],
        "iat": now,
        "exp": now + JWT_EXPIRE_MINUTES * 60,
        "iss": "businessintelligence-ai",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Decode + validate a JWT. Raises on expiry, signature, or format."""
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            issuer="businessintelligence-ai",
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid token") from exc

    if not payload.get("sub") or not payload.get("role"):
        raise AuthenticationError("Token missing required claims")
    return payload


def authorize(
    token: Optional[str],
    required_roles: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Full check: token validity + role allowance.

    Returns the decoded payload. Raises AuthenticationError /
    AuthorizationError. When ``AUTH_DISABLED`` is set, returns an
    anonymous executive identity (local dev / judge demo mode).
    """
    if AUTH_DISABLED:
        return {
            "sub": "anonymous",
            "role": "executive",
            "name": "Anonymous (auth disabled)",
        }

    if not token:
        raise AuthenticationError("Missing bearer token")

    payload = decode_token(token.strip())

    if required_roles and payload["role"] not in required_roles:
        raise AuthorizationError(
            f"Role '{payload['role']}' is not authorized. "
            f"Required: {', '.join(required_roles)}"
        )
    return payload


def extract_bearer(authorization_header: Optional[str]) -> Optional[str]:
    """Pull the token out of an 'Authorization: Bearer <token>' header."""
    if not authorization_header:
        return None
    parts = authorization_header.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None
