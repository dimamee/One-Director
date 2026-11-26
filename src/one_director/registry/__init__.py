"""Targeted registry lookups for firms that appear in flagged lots (owner: 02-registry).

Phase 0: placeholder only. Contract: ``specs/agents/02-registry.md``.

Hard rules (``docs/data-protection.md``):

* lookups ONLY for firms from lots that already carry a flag -- never a full
  registry crawl;
* names of directors/founders are pseudonymised in memory with
  ``one_director.security.pseudonymize`` before anything is written to disk;
* addresses and phones are stored as keyed hashes only;
* passport data, personal phones and home addresses are never collected.
"""
