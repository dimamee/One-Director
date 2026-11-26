"""One Director: screening of possible bid-rigging indicators in public procurement.

The system flags *indicators for review*; it never establishes a violation.
Every decision is made by an inspector of the Competition Committee.

Package map (owner agent in brackets, see ``specs/agents/``):

* ``security`` -- settings, pseudonymisation, masking, logging, HTTP client,
  LLM guard, auth, audit (humans / Phase 1).
* ``data`` -- collection of public lot and bid data (01-data).
* ``registry`` -- targeted registry lookups for flagged firms (02-registry).
* ``screens`` -- collusion indicators with reproducible evidence (03-screens).
* ``graph`` -- firm/person relationship graph (04-graph).
* ``model`` -- rules + Isolation Forest risk score with SHAP (05-model).
* ``report`` -- bilingual (uz/ru) lot briefs via a guarded LLM (06-report-llm).
* ``api`` -- FastAPI backend with roles, masking and audit (07-backend).
"""

__version__ = "0.0.0"
