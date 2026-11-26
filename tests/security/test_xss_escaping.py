"""Strings from the data (firm names, lot titles) are escaped in the dashboard and PDF.

Threat model: "XSS via scraped data" (docs/threat-model.md).
"""

import pytest

pytestmark = [
    pytest.mark.security,
    pytest.mark.skip(reason="Phase 2: dashboard and PDF export are not implemented yet"),
]

PAYLOADS = [
    "<script>alert(1)</script>",
    '"><img src=x onerror=alert(1)>',
    "javascript:alert(1)",
    "<a href='https://example.invalid'>click</a>",
]


def test_graph_labels_are_escaped() -> None:
    """pyvis HTML generated for a firm named with each payload contains only the
    escaped form (&lt;script&gt;...), no executable tag or handler.
    """


def test_dashboard_never_renders_raw_html_from_data() -> None:
    """Static check over app/: no unsafe HTML rendering flags, no components.html
    with data-derived strings.
    """


def test_pdf_contains_escaped_text_and_no_external_resources() -> None:
    """The PDF for a lot with payload strings renders them as literal text and
    references no external URL, font or image.
    """
