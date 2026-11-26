"""Append-only audit log (Phase 1 -- stub).

Planned contract (docs/access-control.md, specs/schema.md ``audit_log``):

* ``record(event: AuditEvent) -> None``: inserts one row with ``ts`` (UTC),
  ``user_id``, ``role``, ``action``, ``object_type``, ``object_id``,
  ``ip_hash``, ``request_id``, optional ``reason`` (mandatory for ``unmask``).
* Append-only: the module exposes no update/delete; rows are hash-chained
  (``record_hash = SHA-256(prev_hash || canonical_json(row))``) so that any
  modification or deletion is detectable by ``verify_chain()``.
* Audited actions: login success/failure, view of a lot card, view of a firm
  card, graph view, unmask, PDF export, brief (re)generation, user changes.
* Writing the audit row is part of the request: if it fails, the response
  with data is not returned (fail closed).
* Audit rows contain identifiers, never the returned data itself.

Tests: chain verification, failure of the writer blocks the response.
"""
