"""Masking of identifiers by role and DEMO_MODE (Phase 1 -- stub).

Planned contract (docs/access-control.md, docs/data-protection.md):

* ``mask_firm(firm, role, demo_mode, unmask=False) -> MaskedFirm``.
* Sole proprietors (IP / YaTT), natural persons and firms with an unknown
  ``entity_type`` are treated as personal data: INN -> ``"*********"``, name ->
  ``"ИП ***"`` unless the role is ``supervisor`` AND an explicit, audited
  unmask was requested AND ``demo_mode`` is off.
* Legal entities: visible to ``analyst`` and above outside DEMO_MODE; masked
  for ``viewer``.
* DEMO_MODE: every firm is replaced by a stable alias ("ООО «А»", "ООО «Б»",
  ... per response) and every INN is masked, for every role, with no exception.
* Masking is applied on the server, in one place, before serialisation -- the
  UI never receives clear values it is not allowed to show.
* Fail closed: any error or unknown value leads to the masked form.

Tests: ``tests/security/test_demo_mode_masking.py``.
"""
