"""Configuration and secrets (Phase 1 -- stub, contract only).

Planned contract:

* ``Settings`` -- a ``pydantic_settings.BaseSettings`` model read from the
  environment (and optionally a ``.env`` file whose path is given explicitly,
  preferably outside the project directory).
* Secrets are ``SecretStr`` fields: ``APP_SECRET_KEY``, ``PSEUDONYM_SALT``,
  ``ANTHROPIC_API_KEY``. Their ``repr``/``str`` never reveals the value.
* Fail fast: the application refuses to start when a required secret is empty
  or shorter than 32 bytes (``APP_SECRET_KEY``, ``PSEUDONYM_SALT`` always;
  ``ANTHROPIC_API_KEY`` only for the brief generator).
* ``DEMO_MODE`` defaults to ``True`` (safe default); ``ALLOWED_ORIGINS`` is a
  parsed list, empty means "no cross-origin access".
* ``APP_ENV`` in {``local``, ``demo``, ``pilot``}; ``debug`` is only possible
  for ``local``.
* Production thresholds/weights of the risk model are referenced by a path
  (``RISK_CONFIG_PATH``) outside the repository, never embedded in code.
* A single cached ``get_settings()`` accessor; settings objects are never
  logged, serialised into API responses or written to notebooks.

Tests: ``tests/security/test_secrets_not_leaked.py``.
"""
