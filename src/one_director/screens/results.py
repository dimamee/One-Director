"""Output types of the screens: flags, "not computed" records, table rows.

A flag is an *indicator for review* of an inspector, never a finding.

Conventions of ``flags.evidence`` (consumers rely on them; ``specs/schema.md``):

* **INNs only under keys ending with ``_inn`` or ``_inns``** (D-46) -- a string
  (or ``null``) and a list of strings: ``firm_inn``, ``winner_inn``,
  ``customer_inn``, ``participant_inn``, ``firm_inns``, ``group_inns``. 07-backend
  masks evidence by these key suffixes, so an INN under any other key would
  leak. Persons never appear (no names, no ``person_id``); lot titles, firm and
  customer names are never copied.
* **Applied thresholds only under ``params``** (D-46): the screen's section of the
  configuration plus ``min_market_lots``. ``params`` never leaves the pipeline
  (API, PDF, LLM); it is kept so that :func:`~one_director.screens.recompute`
  can decide the flag again from the evidence alone.
* Top-level keys: ``flag_code``, ``rule_version``, ``lot_ids``, ``facts`` (inputs),
  ``params``, ``metrics`` (derived values).
* Exact JSON: no floats. Money is a string with exactly two decimals
  (``"196510000.00"``, D-42), derived values have six decimals; neither depends
  on the scale of the input ``Decimal``, and neither does ``flag_id``.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal, get_args

type JsonValue = str | int | bool | list[JsonValue] | dict[str, JsonValue] | None
"""Evidence is exact JSON: decimals are strings, there are no floats."""

type Evidence = dict[str, JsonValue]

FlagCode = Literal[
    "LOW_DISCOUNT",
    "SINGLE_BIDDER",
    "FEW_BIDDERS",
    "CO_BIDDING",
    "WINNER_ROTATION",
    "PERPETUAL_RUNNER_UP",
    "SHARED_FOUNDER",
    "SHARED_DIRECTOR",
    "SHARED_ADDRESS",
    "SHARED_PHONE",
    "COVER_BID_PATTERN",
]
"""Codes of ``docs/model-card.md`` §3 (new codes need a PR there and in the glossary)."""

ALL_FLAG_CODES: Final[tuple[FlagCode, ...]] = get_args(FlagCode)

STRUCTURAL_FLAG_CODES: Final[tuple[FlagCode, ...]] = (
    "LOW_DISCOUNT",
    "SINGLE_BIDDER",
    "FEW_BIDDERS",
    "CO_BIDDING",
    "WINNER_ROTATION",
    "PERPETUAL_RUNNER_UP",
    "COVER_BID_PATTERN",
)
"""Pass 1: screens computed from ``lots`` and ``bids`` only (no registry data)."""

Severity = Literal["low", "medium", "high"]
ObjectType = Literal["lot", "firm", "pair"]

# Whitelist of screen_coverage.reason (specs/schema.md, D-45). "invalid_values" is
# not in the schema's copy of this list yet (a PR to specs/schema.md is proposed).
NotComputedReason = Literal[
    "out_of_scope",  # procedure type or status outside the configured scope (R3)
    "market_undefined",  # region or category is missing
    "market_too_small",  # fewer computable lots in the market than min_market_lots
    "deal_cost_missing",
    "participants_count_missing",
    "participants_mismatch",  # bids rows != lots.participants_count (R2)
    "winner_ambiguous",  # not exactly one bid with is_winner
    "deal_date_missing",
    "price_screens_disabled",  # price_screens_enabled = false (D-6)
    "bid_prices_missing",
    "too_few_bids",
    "degenerate_prices",  # all bid prices equal: spacing is undefined
    # start_cost = 0, deal_cost > start_cost, bid price = 0, participants_count = 0,
    # or an amount that DECIMAL(20, 2) cannot hold (negative, sub-cent, too large).
    "invalid_values",
]

_FLAG_ID_NAMESPACE: Final = uuid.uuid5(uuid.NAMESPACE_DNS, "flags.one-director.invalid")


def canonical_json(value: JsonValue) -> str:
    """Stable serialisation used for identifiers and digests."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class ScreenFlag:
    """One raised indicator with the evidence it was decided on."""

    flag_code: FlagCode
    object_type: ObjectType
    object_id: str
    severity: Severity
    rule_version: str
    evidence: Evidence

    @property
    def flag_id(self) -> str:
        """Deterministic UUID: the same inputs and configuration give the same id."""
        name = canonical_json(
            {
                "flag_code": self.flag_code,
                "object_type": self.object_type,
                "object_id": self.object_id,
                "rule_version": self.rule_version,
                "evidence": self.evidence,
            }
        )
        return str(uuid.uuid5(_FLAG_ID_NAMESPACE, name))


@dataclass(frozen=True, slots=True)
class NotComputed:
    """A screen could not be evaluated for a lot -- this is not a zero or a pass.

    One record per (lot, screen); becomes a row of ``screen_coverage`` (D-45).
    """

    flag_code: FlagCode
    trade_id: str
    reason: NotComputedReason
    rule_version: str


@dataclass(frozen=True, slots=True)
class ScreenResult:
    flags: tuple[ScreenFlag, ...]
    not_computed: tuple[NotComputed, ...]


@dataclass(frozen=True, slots=True)
class FlagRow:
    """One row of the ``flags`` table (``specs/schema.md``).

    Временно, D-43: a copy of the ``flags`` columns until 01-data ships
    ``one_director.data.schema.Flag`` (D-7); removed by a separate PR right
    after that model is in ``main``.
    """

    flag_id: str
    object_type: ObjectType
    object_id: str
    flag_code: FlagCode
    severity: Severity
    evidence: Evidence
    rule_version: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CoverageRow:
    """One row of the ``screen_coverage`` table (``specs/schema.md``, D-45).

    Временно, D-43: a copy of the ``screen_coverage`` columns until 01-data ships
    ``one_director.data.schema.ScreenCoverage``; removed by a separate PR right
    after that model is in ``main``.
    """

    trade_id: str
    flag_code: FlagCode
    reason: NotComputedReason
    rule_version: str
    created_at: datetime
