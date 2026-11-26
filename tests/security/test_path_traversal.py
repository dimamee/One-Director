"""Path traversal through /reports/{trade_id}.pdf is impossible.

Threat model: "Information disclosure via file access" (docs/threat-model.md).
"""

import pytest

pytestmark = [
    pytest.mark.security,
    pytest.mark.skip(reason="Phase 2: PDF export endpoint is not implemented yet"),
]

PAYLOADS = [
    "../../etc/passwd",
    "..%2F..%2F.env",
    "%2e%2e%2fsecrets",
    "123/../../data/raw/x",
    "123\x00.pdf",
]


def test_traversal_payloads_are_rejected() -> None:
    """Each payload -> 400/404 with a generic body; nothing outside the reports
    directory is read (checked with a canary file).
    """


def test_file_names_are_generated_by_the_server() -> None:
    """The PDF is built in memory or under a server-generated name; the
    Content-Disposition file name contains only [0-9A-Za-z_.-].
    """
