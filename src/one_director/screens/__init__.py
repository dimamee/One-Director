"""Collusion screens: reproducible indicators per lot, firm and pair (owner: 03-screens).

Contract: ``specs/agents/03-screens.md``; codes: ``docs/model-card.md`` §3.

A flag is an *indicator for review* by an inspector, never a finding. Each
flag stores ``evidence`` -- exact JSON with the lots, values, applied
parameters and ``rule_version`` (conventions in :mod:`.results`) -- and
:func:`recompute` decides it again from that evidence alone. Thresholds come
from configuration (:func:`load_config` for ``RISK_CONFIG_PATH``,
:func:`load_demo_config` for the demo file), never from constants in public code.

Pass 1 (D-48): structural screens from ``lots`` and ``bids`` --
``LOW_DISCOUNT``, ``SINGLE_BIDDER``, ``FEW_BIDDERS``, ``CO_BIDDING``,
``WINNER_ROTATION``, ``PERPETUAL_RUNNER_UP`` and, when bid prices exist and the
price block is enabled, ``COVER_BID_PATTERN``. Screens that cannot be
evaluated for a lot are returned as :class:`NotComputed`, never as zero; they
become ``screen_coverage`` rows (D-45). Pass 2 (registry links, ``SHARED_*``)
is not implemented yet.

The synthetic market generator (D-27) is :mod:`one_director.screens.synthetic`;
it is test data, is not imported here and no screen uses it.
"""

from one_director.screens._evidence import Evaluation, EvidenceError
from one_director.screens.config import ConfigError, ScreensConfig, load_config, load_demo_config
from one_director.screens.inputs import BidLike, LotLike
from one_director.screens.results import (
    ALL_FLAG_CODES,
    STRUCTURAL_FLAG_CODES,
    CoverageRow,
    FlagRow,
    NotComputed,
    ScreenFlag,
    ScreenResult,
)
from one_director.screens.run import (
    recompute,
    run_structural_screens,
    to_coverage_rows,
    to_flag_rows,
)

__all__ = [
    "ALL_FLAG_CODES",
    "STRUCTURAL_FLAG_CODES",
    "BidLike",
    "ConfigError",
    "CoverageRow",
    "Evaluation",
    "EvidenceError",
    "FlagRow",
    "LotLike",
    "NotComputed",
    "ScreenFlag",
    "ScreenResult",
    "ScreensConfig",
    "load_config",
    "load_demo_config",
    "recompute",
    "run_structural_screens",
    "to_coverage_rows",
    "to_flag_rows",
]
