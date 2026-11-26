"""Structured JSON logging with redaction (Phase 1 -- stub).

Planned contract (docs/data-protection.md, "Logs"):

* ``configure_logging(level)`` installs a JSON formatter on the root logger:
  ``ts`` (UTC ISO 8601), ``level``, ``logger``, ``event``, ``request_id`` and
  structured ``extra`` fields. No free-form f-string messages with data.
* A redaction filter runs on every record (message, args, extra, exception
  text) and replaces: values of known secrets from settings, anything that looks
  like an API key or JWT, 9-digit INN and 14-digit PINFL sequences, e-mail
  addresses and phone numbers. IP addresses are replaced by ``ip_hash``.
* Exceptions are logged with type and a redacted message; stack traces only in
  ``APP_ENV=local``.
* The uvicorn access log is disabled in containers (paths such as
  ``/firms/{inn}`` contain identifiers); request logging is done by the API
  middleware with redacted paths.

Note: this module intentionally shadows the stdlib name inside the package only;
always ``import logging`` absolutely.

Tests: ``tests/security/test_secrets_not_leaked.py``.
"""
