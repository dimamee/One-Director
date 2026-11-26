"""Security building blocks shared by all modules (owner: humans, Phase 1).

Phase 0 contains only module stubs with their contracts in docstrings; the code
is written in Phase 1 (TASK.md, section 4) after the organisers confirm the
rules on pre-written code. Changes to this package require review by the
security owner (CLAUDE.md, "Security -- non-negotiable").

Modules:

* ``settings`` -- configuration and secrets via pydantic-settings, fail fast.
* ``pseudonymize`` -- HMAC pseudonyms for people, hashes of addresses/phones.
* ``masking`` -- masking of INN and names by role and ``DEMO_MODE``.
* ``logging`` -- JSON logs with a secret/personal-data redaction filter.
* ``http_client`` -- polite, hardened httpx client for the scraper.
* ``llm_guard`` -- safe prompt construction and LLM output validation.
* ``auth`` -- JWT, roles, FastAPI role dependency.
* ``audit`` -- append-only, hash-chained ``audit_log`` writer.
"""
