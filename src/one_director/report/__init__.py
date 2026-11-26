"""Bilingual (uz/ru) lot briefs written by an LLM under strict guards (owner: 06-report-llm).

Phase 0: placeholder only. Contract: ``specs/agents/06-report-llm.md``,
rules: ``docs/llm-safety.md``.

The LLM receives only aggregated, non-personal facts as JSON inside explicit
delimiters, has no tools, network or DB access, and its output is a strict
pydantic schema that is validated against the input before use. Legal
references come from a fixed local catalogue, never from the model.
"""
