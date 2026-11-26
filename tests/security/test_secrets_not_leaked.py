"""Secrets never appear in logs, API responses, exceptions or reprs.

Threat model: "API key compromise" (docs/threat-model.md, T-06).
"""

import pytest

pytestmark = [
    pytest.mark.security,
    pytest.mark.skip(reason="Phase 1: security.settings / security.logging not implemented yet"),
]


def test_settings_repr_hides_secrets() -> None:
    """repr()/str()/model_dump_json() of Settings never contain secret values.

    Setup: monkeypatch APP_SECRET_KEY, PSEUDONYM_SALT, ANTHROPIC_API_KEY with
    random canary strings. Assert: no canary in repr, str, JSON dump.
    """


def test_app_refuses_to_start_with_empty_required_secret() -> None:
    """Empty or short APP_SECRET_KEY / PSEUDONYM_SALT -> start-up error.

    The error message names the variable, never its value.
    """


def test_log_records_are_redacted() -> None:
    """Canary secrets, a fake JWT, a 9-digit INN and a 14-digit PINFL passed to the
    logger (message, args, extra, exception) are replaced by placeholders in the
    emitted JSON.
    """


def test_error_responses_contain_no_secrets_or_traces() -> None:
    """An endpoint forced to raise returns the generic error body: no canary,
    no stack trace, no file paths, no library names.
    """
