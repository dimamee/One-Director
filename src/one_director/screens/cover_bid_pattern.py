"""``COVER_BID_PATTERN`` -- losing bids evenly spaced above the winner (lot level).

Only when bid prices exist and the price block is enabled
(``price_screens_enabled``, D-6); otherwise every lot is "not computed".

With all prices sorted ascending (the winner first), ``gaps`` are the
differences between neighbours and ``gap_cv`` is their coefficient of variation
(population standard deviation / mean). Cover bids placed at fixed steps above
the winner give ``gap_cv`` close to 0; independent bids do not. The flag needs:
the winner is the lowest bid and the nearest loser is at least ``min_markup``
above it; ``gap_cv`` within the band; and ``gap_cv`` at least
``min_gap_to_market_median`` below the median of its market (region x category)
-- normalisation for markets where prices follow a formula.

Lots with fewer than ``min_losers`` losing bids are not computed (the spacing is
undefined). Bid records must agree with ``participants_count`` (R2). Bid prices
enter evidence in their canonical form, ``"196510000.00"`` (D-42).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from itertools import pairwise
from typing import Final

from one_director.screens._evidence import (
    Evaluation,
    as_money,
    dec,
    exact,
    get_bands,
    get_bool,
    get_dec,
    get_int,
    get_map,
    get_maps,
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
    single_winner,
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

FLAG_CODE: Final[FlagCode] = "COVER_BID_PATTERN"
RULE_VERSION: Final = "1.0.0"

type _Priced = tuple[str, Decimal, bool]  # participant_inn, bid_price, is_winner


def gap_cv(prices: Sequence[Decimal]) -> Decimal:
    """Coefficient of variation of the gaps between sorted prices (needs >= 2 gaps)."""
    ordered = sorted(prices)
    gaps = [after - before for before, after in pairwise(ordered)]
    mean = sum(gaps, Decimal(0)) / len(gaps)
    variance = sum(((gap - mean) ** 2 for gap in gaps), Decimal(0)) / len(gaps)
    return q(variance.sqrt() / mean)


def _inputs(view: LotView, min_losers: int) -> NotComputedReason | tuple[Market, list[_Priced]]:
    reason = scope_reason(view)
    if reason is not None or view.market is None:
        return reason or "market_undefined"
    if not view.consistent:
        return "participants_mismatch"
    if any(bid.bid_price is None for bid in view.bids):
        return "bid_prices_missing"
    priced: list[_Priced] = []
    for bid in view.bids:
        price = None if bid.bid_price is None else as_money(bid.bid_price)
        if price is None or price == 0:
            return "invalid_values"
        priced.append((bid.participant_inn, price, bid.is_winner))
    if single_winner(view) is None:
        return "winner_ambiguous"
    if len(priced) - 1 < min_losers:
        return "too_few_bids"
    if len({price for _, price, _ in priced}) == 1:
        return "degenerate_prices"
    return view.market, sorted(priced, key=lambda item: (item[1], item[0]))


def evaluate(evidence: Mapping[str, JsonValue]) -> Evaluation:
    with exact():
        require(len(lot_ids(evidence)) == 1, "COVER_BID_PATTERN evidence must name one lot")
        params = get_map(evidence, "params")
        min_losers = get_int(params, "min_losers")
        min_markup = get_dec(params, "min_markup")
        min_gap = get_dec(params, "min_gap_to_market_median")
        bands = get_bands(params, "max_gap_cv")
        facts = get_map(evidence, "facts")
        get_str(facts, "currency")
        market = get_map(facts, "market")
        get_market_lots(market, params)
        market_median = get_dec(market, "median_gap_cv")

        bids = get_maps(facts, "bids")
        for bid in bids:
            get_str(bid, "participant_inn")
        prices = [get_money(bid, "bid_price") for bid in bids]
        winners = [get_money(bid, "bid_price") for bid in bids if get_bool(bid, "is_winner")]
        require(len(winners) == 1, "exactly one bid must be the winner")
        require(all(price > 0 for price in prices), "bid prices must be positive")
        require(len(set(prices)) > 1, "bid prices must not all be equal")
        winner_price = winners[0]
        losers = sorted(prices)
        losers.remove(winner_price)
        require(len(losers) >= 2, "at least two losing bids are needed")

        cv = gap_cv(prices)
        markup = q((losers[0] - winner_price) / winner_price)
        gap = q(market_median - cv)
        metrics: Evidence = {
            "losers": len(losers),
            "winner_price": money(winner_price),
            "nearest_loser_markup": dec(markup),
            "gap_cv": dec(cv),
            "gap_to_market_median": dec(gap),
        }
        if len(losers) < min_losers or markup < min_markup or gap < min_gap:
            return Evaluation(None, metrics)
        return Evaluation(severity_at_most(cv, bands), metrics)


def screen(views: tuple[LotView, ...], config: ScreensConfig) -> ScreenOutput:
    settings = config.screens.cover_bid_pattern
    rule_version = config.rule_version(RULE_VERSION)
    not_computed: list[NotComputed] = []
    if not config.price_screens_enabled:
        for view in views:
            reason = scope_reason(view) or "price_screens_disabled"
            not_computed.append(NotComputed(FLAG_CODE, view.trade_id, reason, rule_version))
        return [], not_computed

    params = screen_params(settings, config)
    by_market: dict[Market, list[tuple[LotView, list[_Priced]]]] = {}
    for view in views:
        inputs = _inputs(view, settings.min_losers)
        if isinstance(inputs, str):
            not_computed.append(NotComputed(FLAG_CODE, view.trade_id, inputs, rule_version))
            continue
        market, priced = inputs
        by_market.setdefault(market, []).append((view, priced))

    flags: list[ScreenFlag] = []
    with exact():
        for market, items in by_market.items():
            if len(items) < config.screens.scope.min_market_lots:
                not_computed += [
                    NotComputed(FLAG_CODE, v.trade_id, "market_too_small", rule_version)
                    for v, _ in items
                ]
                continue
            market_median = median([gap_cv([p for _, p, _ in priced]) for _, priced in items])
            market_facts: Evidence = {
                **market.as_json(),
                "lots": len(items),
                "median_gap_cv": dec(market_median),
            }
            for view, priced in items:
                evidence: Evidence = {
                    "flag_code": FLAG_CODE,
                    "rule_version": rule_version,
                    "lot_ids": [view.trade_id],
                    "facts": {
                        "currency": view.lot.currency,
                        "bids": [
                            {"participant_inn": inn, "bid_price": money(price), "is_winner": won}
                            for inn, price, won in priced
                        ],
                        "market": market_facts,
                    },
                    "params": params,
                }
                flag = make_flag(FLAG_CODE, "lot", view.trade_id, evidence, evaluate(evidence))
                if flag is not None:
                    flags.append(flag)
    return flags, not_computed
