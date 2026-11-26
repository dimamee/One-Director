"""Output types of the screens: flags, "not computed" records, ``flags`` rows.

A flag is an *indicator for review* of an inspector, never a finding.
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
    "invalid_values",  # e.g. start_cost <= 0, deal_cost > start_cost, price <= 0
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
    """A screen could not be evaluated for a lot -- this is not a zero or a pass."""

    flag_code: FlagCode
    trade_id: str
    reason: NotComputedReason


@dataclass(frozen=True, slots=True)
class ScreenResult:
    flags: tuple[ScreenFlag, ...]
    not_computed: tuple[NotComputed, ...]


@dataclass(frozen=True, slots=True)
class FlagRow:
    """One row of the ``flags`` table (``specs/schema.md``).

    Temporary: replaced by ``one_director.data.schema.Flag`` once 01-data
    ships the shared models (D-7).
    """

    flag_id: str
    object_type: ObjectType
    object_id: str
    flag_code: FlagCode
    severity: Severity
    evidence: Evidence
    rule_version: str
    created_at: datetime
