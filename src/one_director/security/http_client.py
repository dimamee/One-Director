"""Polite and hardened HTTP client for data collection (Phase 1 -- stub).

Planned contract (docs/scraping-policy.md):

* Built on ``httpx.Client`` with ``verify=True`` (TLS verification is never
  disabled), HTTP/1.1, explicit timeouts (connect 5 s, read 30 s, total 60 s).
* Global rate limit: at most 1 request per second, one connection at a time.
* Retries with exponential backoff and jitter on connection errors and 5xx
  (max 5 attempts, cap 5 minutes); honours ``Retry-After``.
* Hard stop on 401/403/429: no retry, the run is aborted and a human is
  notified (a block or a limit is a signal to stop, not to evade).
* Response size limit (default 10 MB, streamed and cut off) and allowed
  content types (``application/json``).
* Allowlist of hosts: ``apietender.uzex.uz`` (the public JSON API used by the
  etender.uzex.uz site -- the only host data is actually fetched from) and the
  agreed registry source; redirects to other hosts are refused. The file host
  ``etender-fileservice.uzex.uz`` is NOT allowed (no document downloads, see
  specs/decisions.md D-29 and D-4).
* Clear ``User-Agent`` with the project name and the team contact.
* No cookies/sessions with credentials, no proxies rotation, no CAPTCHA
  solving, no header spoofing.

Tests: rate limit, stop on 429/403, size limit, host allowlist (with a mock
transport -- tests never touch the real site).
"""
