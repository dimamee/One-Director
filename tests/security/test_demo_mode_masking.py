"""DEMO_MODE: no unmasked INN / names of sole proprietors and persons in any response.

Threat model: "Personal data leak" (docs/threat-model.md, T-01).
"""

import pytest

pytestmark = [
    pytest.mark.security,
    pytest.mark.skip(reason="Phase 1: security.masking and the API are not implemented yet"),
]


def test_no_clear_identifiers_in_any_endpoint_in_demo_mode() -> None:
    """With DEMO_MODE=true and a synthetic dataset whose INNs and names are known
    canaries, call every GET endpoint as every role (incl. supervisor with
    unmask=true). Assert: no canary INN, firm name or person name in any body
    (JSON and PDF text), only aliases ("ООО «А»", "ИП ***").
    """


def test_unknown_entity_type_is_masked() -> None:
    """A firm with entity_type=unknown is masked like a sole proprietor (fail closed)."""


def test_unmask_requires_supervisor_reason_and_is_audited() -> None:
    """Outside DEMO_MODE: unmask by analyst -> 403; by supervisor without reason
    -> 400; with reason -> clear value AND an audit_log row with the reason.
    """
