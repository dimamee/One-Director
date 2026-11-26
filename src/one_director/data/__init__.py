"""Collection of public lot and bid data from etender.uzex.uz (owner: 01-data).

Phase 0: placeholder only, no business logic. Contract: ``specs/agents/01-data.md``,
table layout: ``specs/schema.md`` (``lots``, ``bids``).

Hard rules (``docs/scraping-policy.md``):

* public, unauthenticated endpoints only; at most 1 request per second;
* every request goes through ``one_director.security.http_client``;
* responses are validated by pydantic models; unknown fields are logged, not fatal;
* no bulk download of documents or contracts;
* raw responses go to ``data/raw/`` and are deleted after successful processing.
"""
