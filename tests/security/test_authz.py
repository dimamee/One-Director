"""Authentication and role checks: no token -> 401, insufficient role -> 403.

Threat model: "Elevation of privilege" (docs/threat-model.md, docs/access-control.md).
"""

import pytest

pytestmark = [
    pytest.mark.security,
    pytest.mark.skip(reason="Phase 1/2: security.auth and the API are not implemented yet"),
]


def test_every_route_declares_a_role_dependency() -> None:
    """Enumerate app.routes: every route except /health and /auth/token has a
    require_role dependency (default deny).
    """


def test_missing_or_invalid_token_returns_401() -> None:
    """No token, expired token, wrong signature, alg=none, wrong audience -> 401
    with a generic body and WWW-Authenticate header.
    """


def test_role_matrix_is_enforced() -> None:
    """Parametrised over the matrix in docs/access-control.md: each role x
    endpoint pair returns the expected 2xx or 403.
    """
