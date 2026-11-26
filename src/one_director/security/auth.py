"""Authentication and role-based access control (Phase 1 -- stub).

Planned contract (docs/access-control.md):

* Roles (ordered): ``viewer`` < ``analyst`` < ``supervisor``; ``admin`` is a
  separate role for user management and does not imply data access.
* ``issue_token(user) -> str``: JWT (HS256) signed with ``APP_SECRET_KEY``;
  claims ``sub``, ``role``, ``iat``, ``nbf``, ``exp`` (TTL 30 min, max 60),
  ``jti``, ``iss``, ``aud``. No refresh tokens in the hackathon build.
* ``decode_token(token)``: algorithm allowlist ``["HS256"]`` (never ``none``),
  required claims, audience/issuer check, 30 s leeway.
* Passwords: argon2id via ``argon2.PasswordHasher``; constant-time verify; a
  dummy hash is verified for unknown users to avoid user enumeration by timing.
* ``require_role(*roles)``: FastAPI dependency used by EVERY endpoint except
  ``/health`` and ``/auth/token``; a test enumerates all routes and fails if a
  route has no role dependency (default deny).
* Login throttling: per IP and per account; generic error messages.

Tests: ``tests/security/test_authz.py``.
"""
