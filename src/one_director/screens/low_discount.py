"""``LOW_DISCOUNT`` -- the deal price is close to the start price (lot level).

``discount = (start_cost - deal_cost) / start_cost``. Normalised by market: the
lot is flagged only if its discount is below the band *and* at least
``min_gap_to_market_median`` below the median discount of its market
(region x category), so markets where small discounts are normal are not
flagged wholesale.

Amounts enter evidence in their canonical form, ``"196510000.00"`` (D-42), so
the evidence and ``flag_id`` do not depend on the scale of the input ``Decimal``.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Final

from one_director.screens._evidence import (
    Evaluation,
    as_money,
    dec,
    exact,
    get_bands,
    get_dec,
    get_map,
    get_market_lots,
    get_money,
    get_str,
    lot_ids,
    median,
    money,
    q,
    require,
    severity_at_most,
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

FLAG_CODE: Final[FlagCode] = "LOW_DISCOUNT"
RULE_VERSION: Final = "1.0.0"


def discount_of(start_cost: Decimal, deal_cost: Decimal) -> Decimal:
    return q((start_cost - deal_cost) / start_cost)


def _inputs(view: LotView) -> NotComputedReason | tuple[Market, Decimal, Decimal]:
    reason = scope_reason(view)
    if reason is not None or view.market is None:
        return reason or "market_undefined"
    if view.lot.deal_cost is None:
        return "deal_cost_missing"
    start, deal = as_money(view.lot.start_cost), as_money(view.lot.deal_cost)
    if start is None or deal is None or start == 0 or deal > start:
        return "invalid_values"
    return view.market, start, deal


def evaluate(evidence: Mapping[str, JsonValue]) -> Evaluation:
    with exact():
        require(len(lot_ids(evidence)) == 1, "LOW_DISCOUNT evidence must name one lot")
        params = get_map(evidence, "params")
        min_gap = get_dec(params, "min_gap_to_market_median")
        bands = get_bands(params, "max_discount")
        facts = get_map(evidence, "facts")
        start, deal = get_money(facts, "start_cost"), get_money(facts, "deal_cost")
        get_str(facts, "currency")
        require(start > 0 and deal <= start, "need 0 < start_cost and deal_cost <= start_cost")
        market = get_map(facts, "market")
        get_market_lots(market, params)
        market_median = get_dec(market, "median_discount")

        discount = discount_of(start, deal)
        gap = q(market_median - discount)
        metrics: Evidence = {"discount": dec(discount), "gap_to_market_median": dec(gap)}
        if gap < min_gap:
            return Evaluation(None, metrics)
        return Evaluation(severity_at_most(discount, bands), metrics)


def screen(views: tuple[LotView, ...], config: ScreensConfig) -> ScreenOutput:
    params = screen_params(config.screens.low_discount, config)
    rule_version = config.rule_version(RULE_VERSION)
    not_computed: list[NotComputed] = []
    by_market: dict[Market, list[tuple[LotView, Decimal, Decimal]]] = {}
    for view in views:
        inputs = _inputs(view)
        if isinstance(inputs, str):
            not_computed.append(NotComputed(FLAG_CODE, view.trade_id, inputs, rule_version))
            continue
        market, start, deal = inputs
        by_market.setdefault(market, []).append((view, start, deal))

    flags: list[ScreenFlag] = []
    with exact():
        for market, items in by_market.items():
            if len(items) < config.screens.scope.min_market_lots:
                not_computed += [
                    NotComputed(FLAG_CODE, view.trade_id, "market_too_small", rule_version)
                    for view, _, _ in items
                ]
                continue
            market_median = median([discount_of(start, deal) for _, start, deal in items])
            market_facts: Evidence = {
                **market.as_json(),
                "lots": len(items),
                "median_discount": dec(market_median),
            }
            for view, start, deal in items:
                evidence: Evidence = {
                    "flag_code": FLAG_CODE,
                    "rule_version": rule_version,
                    "lot_ids": [view.trade_id],
                    "facts": {
                        "start_cost": money(start),
                        "deal_cost": money(deal),
                        "currency": view.lot.currency,
                        "market": market_facts,
                    },
                    "params": params,
                }
                flag = make_flag(FLAG_CODE, "lot", view.trade_id, evidence, evaluate(evidence))
                if flag is not None:
                    flags.append(flag)
    return flags, not_computed
