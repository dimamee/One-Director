"""Safe prompt construction and validation of LLM output (Phase 1 -- stub).

Planned contract (docs/llm-safety.md):

* ``build_messages(facts: LotFacts) -> list[dict]``: the system prompt is a
  fixed, versioned constant; lot facts are serialised as JSON and wrapped in
  ``<lot_facts>...</lot_facts>`` delimiters with the explicit instruction that
  the content is data, never instructions. Firms are referred to by
  placeholders (``P1``, ``P2``, ...); no INN, no names of firms or people, no
  free text from the source except an optional, truncated and JSON-escaped
  lot title.
* ``validate_brief(raw, facts) -> Brief``: strict pydantic schema
  (``extra="forbid"``), then semantic checks -- every number, placeholder and
  legal reference id in the text must exist in the input / the fixed legal
  catalogue; no 9-/14-digit identifiers; no forbidden accusatory phrases in
  Russian and Uzbek (e.g. "нарушение доказано", "картель" about a participant,
  "aybdor", "isbotlangan"). Any failure -> the brief is rejected and the
  deterministic template brief is used instead.
* ``render_legal_refs(ids)``: texts of ZRU-850 references come from a local
  catalogue reviewed by a lawyer, never from the model.
* Budget guard: per-call ``max_tokens``, request timeout, per-session token
  budget; a refusal (``stop_reason == "refusal"``) or budget exhaustion ->
  template brief.

Tests: ``tests/security/test_prompt_injection.py``.
"""
