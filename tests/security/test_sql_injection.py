"""SQL injection through filter, sort and path parameters is impossible.

Threat model: "Tampering / information disclosure via API" (docs/threat-model.md).
"""

import pytest

pytestmark = [
    pytest.mark.security,
    pytest.mark.skip(reason="Phase 1/2: API and DuckDB access layer are not implemented yet"),
]

PAYLOADS = [
    "' OR '1'='1",
    "1; DROP TABLE lots; --",
    "region') UNION SELECT * FROM audit_log --",
    "score_desc, (SELECT 1)",
]


def test_filter_and_sort_payloads_are_rejected() -> None:
    """Each payload in region/category/sort/q -> 400 (allowlist), never 500;
    the row count of lots and audit_log is unchanged afterwards.
    """


def test_no_string_formatting_in_sql() -> None:
    """Static check: no f-string / % / .format / + concatenation inside
    duckdb execute() calls in src/ (complements ruff S608).
    """
