"""FastAPI backend: lots, firms, graph, PDF reports, auth (owner: 07-backend).

Phase 0: placeholder only. Contract: ``specs/api-contract.md`` and
``specs/agents/07-backend.md``.

Every endpoint declares its role dependency (default deny), validates all
parameters, uses parameterised DuckDB queries only, masks identifiers via
``one_director.security.masking`` and writes to ``audit_log`` where required.
"""
