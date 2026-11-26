"""Rate limiting per user and per IP.

Threat model: "Denial of service / scraping of our API, brute force" (docs/threat-model.md).
"""

import pytest

pytestmark = [
    pytest.mark.security,
    pytest.mark.skip(reason="Phase 2: API rate limiting is not implemented yet"),
]


def test_login_is_throttled() -> None:
    """More than the allowed POST /auth/token attempts per minute from one IP ->
    429 with Retry-After; the account is locked after repeated failures.
    """


def test_api_limits_per_user_and_ip() -> None:
    """Exceeding the per-user limit on /lots -> 429; another user from another
    IP is not affected.
    """
