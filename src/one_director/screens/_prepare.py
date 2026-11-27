"""Joins ``bids`` to ``lots`` once and derives what every screen needs."""

from __future__ import annotations

import copy
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import NamedTuple

from pydantic import BaseModel

from one_director.screens._evidence import Evaluation
from one_director.screens.config import ScopeConfig, ScreensConfig
from one_director.screens.inputs import BidLike, LotLike
from one_director.screens.results import (
    Evidence,
    FlagCode,
    JsonValue,
    NotComputed,
    NotComputedReason,
    ObjectType,
    ScreenFlag,
)


class Market(NamedTuple):
    """Normalisation unit: region x category (``docs/model-card.md`` §7)."""

    region: str
    category: str

    def as_json(self) -> dict[str, JsonValue]:
        return {"region": self.region, "category": self.category}


@dataclass(frozen=True, slots=True)
class LotView:
    lot: LotLike
    bids: tuple[BidLike, ...]  # sorted by participant_inn
    market: Market | None
    in_scope: bool

    @property
    def trade_id(self) -> str:
        return self.lot.trade_id

    @property
    def consistent(self) -> bool:
        """R2: bid records agree with the platform's ``participants_count``.

        Until ``bids.participant_status`` is defined (UZEX/RTAM), a lot whose
        record count differs is kept out of every screen that relies on the
        list of participants (same rule as ``specs/agents/04-graph.md``).
        """
        return self.lot.participants_count == len(self.bids)

    @property
    def winner_inns(self) -> tuple[str, ...]:
        return tuple(bid.participant_inn for bid in self.bids if bid.is_winner)


type ScreenOutput = tuple[list[ScreenFlag], list[NotComputed]]
type Screen = Callable[[tuple[LotView, ...], ScreensConfig], ScreenOutput]


def trade_sort_key(trade_id: str) -> tuple[int, int, str]:
    """Numeric order for numeric ``trade_id`` (D-9), text order otherwise."""
    if trade_id.isascii() and trade_id.isdigit():
        return (0, int(trade_id), trade_id)
    return (1, 0, trade_id)


def prepare(
    lots: Iterable[LotLike], bids: Iterable[BidLike], scope: ScopeConfig
) -> tuple[LotView, ...]:
    """Index bids by lot; reject duplicate keys; bids of unknown lots are ignored."""
    by_lot: defaultdict[str, list[BidLike]] = defaultdict(list)
    seen_bids: set[tuple[str, str]] = set()
    for bid in bids:
        key = (bid.trade_id, bid.participant_inn)
        if key in seen_bids:
            raise ValueError("duplicate (trade_id, participant_inn) in bids")
        seen_bids.add(key)
        by_lot[bid.trade_id].append(bid)

    views: list[LotView] = []
    seen_lots: set[str] = set()
    for lot in lots:
        if lot.trade_id in seen_lots:
            raise ValueError("duplicate trade_id in lots")
        seen_lots.add(lot.trade_id)
        market = Market(lot.region, lot.category) if lot.region and lot.category else None
        in_scope = lot.procedure_type in scope.procedure_types and lot.status in scope.statuses
        lot_bids = tuple(sorted(by_lot.get(lot.trade_id, ()), key=lambda b: b.participant_inn))
        views.append(LotView(lot=lot, bids=lot_bids, market=market, in_scope=in_scope))
    return tuple(sorted(views, key=lambda view: trade_sort_key(view.trade_id)))


def screen_params(section: BaseModel, config: ScreensConfig) -> Evidence:
    """``evidence.params``: the screen's thresholds plus the market-size gate (D-46)."""
    params: Evidence = section.model_dump(mode="json")
    params["min_market_lots"] = config.screens.scope.min_market_lots
    return params


def scope_reason(view: LotView) -> NotComputedReason | None:
    """Reasons shared by every screen."""
    if not view.in_scope:
        return "out_of_scope"
    if view.market is None:
        return "market_undefined"
    return None


def single_winner(view: LotView) -> str | None:
    winners = view.winner_inns
    return winners[0] if len(winners) == 1 else None


def make_flag(
    flag_code: FlagCode,
    object_type: ObjectType,
    object_id: str,
    evidence: Evidence,
    evaluation: Evaluation,
) -> ScreenFlag | None:
    """A flag if the evaluation raised one; evidence is copied (flags share no dicts)."""
    if evaluation.severity is None:
        return None
    return ScreenFlag(
        flag_code=flag_code,
        object_type=object_type,
        object_id=object_id,
        severity=evaluation.severity,
        rule_version=str(evidence["rule_version"]),
        evidence=copy.deepcopy({**evidence, "metrics": evaluation.metrics}),
    )
