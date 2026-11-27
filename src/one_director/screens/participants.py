"""``SINGLE_BIDDER`` / ``FEW_BIDDERS`` -- one or few participants (lot level).

Uses the platform's ``lots.participants_count`` (not recounted from ``bids``,
R2). Normalised by market: the gap ``market median participants - count`` must
reach the band, so one or two bidders in a niche market where that is the norm
are not flagged.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Final

from one_director.screens._evidence import (
    Evaluation,
    dec,
    exact,
    get_bands,
    get_dec,
    get_int,
    get_map,
    get_market_lots,
    lot_ids,
    median,
    q,
    require,
    severity_at_least,
)
from one_director.screens._prepare import (
    LotView,
    Market,
    ScreenOutput,
    make_flag,
    scope_reason,
    screen_params,
)
from one_director.screens.config import ScreensConfig
from one_director.screens.results import (
    Evidence,
    FlagCode,
    JsonValue,
    NotComputed,
    NotComputedReason,
    ScreenFlag,
)

SINGLE_BIDDER: Final[FlagCode] = "SINGLE_BIDDER"
FEW_BIDDERS: Final[FlagCode] = "FEW_BIDDERS"
RULE_VERSION: Final = "1.0.0"


def _inputs(view: LotView) -> NotComputedReason | tuple[Market, int]:
    reason = scope_reason(view)
    if reason is not None or view.market is None:
        return reason or "market_undefined"
    count = view.lot.participants_count
    if count is None:
        return "participants_count_missing"
    if count < 1:
        return "invalid_values"
    return view.market, count


def _gap(
    evidence: Mapping[str, JsonValue], params: Mapping[str, JsonValue]
) -> tuple[int, Decimal, Evidence]:
    require(len(lot_ids(evidence)) == 1, "participants evidence must name one lot")
    facts = get_map(evidence, "facts")
    count = get_int(facts, "participants_count")
    require(count >= 1, "participants_count must be positive")
    market = get_map(facts, "market")
    get_market_lots(market, params)
    market_median = get_dec(market, "median_participants")
    gap = q(market_median - count)
    return count, gap, {"gap_to_market_median": dec(gap)}


def evaluate_single(evidence: Mapping[str, JsonValue]) -> Evaluation:
    with exact():
        params = get_map(evidence, "params")
        bands = get_bands(params, "min_gap_to_market_median")
        count, gap, metrics = _gap(evidence, params)
        if count != 1:
            return Evaluation(None, metrics)
        return Evaluation(severity_at_least(gap, bands), metrics)


def evaluate_few(evidence: Mapping[str, JsonValue]) -> Evaluation:
    with exact():
        params = get_map(evidence, "params")
        max_participants = get_int(params, "max_participants")
        bands = get_bands(params, "min_gap_to_market_median")
        count, gap, metrics = _gap(evidence, params)
        # One participant is SINGLE_BIDDER, not FEW_BIDDERS.
        if not 2 <= count <= max_participants:
            return Evaluation(None, metrics)
        return Evaluation(severity_at_least(gap, bands), metrics)


def screen(views: tuple[LotView, ...], config: ScreensConfig) -> ScreenOutput:
    rule_version = config.rule_version(RULE_VERSION)
    variants = (
        (SINGLE_BIDDER, evaluate_single, screen_params(config.screens.single_bidder, config)),
        (FEW_BIDDERS, evaluate_few, screen_params(config.screens.few_bidders, config)),
    )
    not_computed: list[NotComputed] = []
    by_market: dict[Market, list[tuple[LotView, int]]] = {}
    for view in views:
        inputs = _inputs(view)
        if isinstance(inputs, str):
            not_computed += [
                NotComputed(code, view.trade_id, inputs, rule_version) for code, _, _ in variants
            ]
            continue
        market, count = inputs
        by_market.setdefault(market, []).append((view, count))

    flags: list[ScreenFlag] = []
    with exact():
        for market, items in by_market.items():
            if len(items) < config.screens.scope.min_market_lots:
                not_computed += [
                    NotComputed(code, view.trade_id, "market_too_small", rule_version)
                    for view, _ in items
                    for code, _, _ in variants
                ]
                continue
            market_median = median([Decimal(count) for _, count in items])
            market_facts: Evidence = {
                **market.as_json(),
                "lots": len(items),
                "median_participants": dec(market_median),
            }
            for view, count in items:
                for code, evaluate, params in variants:
                    evidence: Evidence = {
                        "flag_code": code,
                        "rule_version": rule_version,
                        "lot_ids": [view.trade_id],
                        "facts": {"participants_count": count, "market": market_facts},
                        "params": params,
                    }
                    flag = make_flag(code, "lot", view.trade_id, evidence, evaluate(evidence))
                    if flag is not None:
                        flags.append(flag)
    return flags, not_computed
