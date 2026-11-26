"""Risk score 0-100 per lot and firm: rules + Isolation Forest + SHAP (owner: 05-model).

Phase 0: placeholder only. Contract: ``specs/agents/05-model.md``,
documentation: ``docs/model-card.md``.

Every score carries ``model_version`` and the top-3 reasons. Production weights
and thresholds are loaded from configuration outside the public repository.
Metrics on synthetic data and on real cases are never mixed.
"""
