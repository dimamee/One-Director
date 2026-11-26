"""Pseudonymisation of people and hashing of contact data (Phase 1 -- stub).

Planned contract (docs/data-protection.md, section "Pseudonymisation"):

* ``person_id(full_name) -> str``: ``HMAC-SHA256(PSEUDONYM_SALT, "person:" +
  normalize_name(full_name))``, hex encoded. The clear name is never stored.
* ``normalize_name(name) -> str``: Unicode NFKC, casefold, unify Uzbek/Russian
  Cyrillic and Latin spellings to one Latin form (e.g. Cyrillic "sh"/"ch"/"o'"/
  "g'" letters, the apostrophe variants), drop punctuation and repeated spaces,
  sort name tokens so that "surname name" == "name surname". The exact
  transliteration table is specified and unit-tested in Phase 1.
* ``address_hash(addr)`` / ``phone_hash(phone)``: same HMAC with the domain
  prefixes ``"addr:"`` / ``"phone:"`` over normalised values (phones in E.164).
* ``ip_hash(ip)``: HMAC with the prefix ``"ip:"`` for logs and ``audit_log``.
* Domain prefixes guarantee that a hash from one domain never matches another.
* Matching is done ONLY by comparing hashes. A name match alone is weak
  evidence (namesakes) and must be labelled as such by the screens.

Tests: deterministic output, Latin/Cyrillic equivalence, no clear text in output.
"""
