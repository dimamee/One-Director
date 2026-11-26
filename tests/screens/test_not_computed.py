"""Screens that cannot be computed are reported as "not computed", never as zero."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from tests.screens.helpers import config_with, flagged, injected_world, run
from tests.screens.synthetic import MarketBuilder, MarketRef

from one_director.screens import STRUCTURAL_FLAG_CODES, ScreenResult


def reasons(result: ScreenResult, trade_id: str) -> dict[str, str]:
    return {
        item.flag_code: item.reason for item in result.not_computed if item.trade_id == trade_id
    }


def world_with(seed: int = 3) -> tuple[MarketBuilder, MarketRef]:
    builder = MarketBuilder(seed)
    market = builder.clean_market("namangan", "construction")
    return builder, market


def ordinary_bids(market: MarketRef, count: int) -> list[tuple[str, Decimal | None]]:
    return [
        (inn, Decimal(1_000_000 - 10_000 * rank))
        for rank, inn in enumerate(market.firms[:count], start=1)
    ]


def test_records_are_unique_per_screen_and_lot() -> None:
    result = run(injected_world(with_bid_prices=False))
    keys = Counter((item.flag_code, item.trade_id) for item in result.not_computed)
    assert max(keys.values()) == 1


def test_missing_bid_prices_are_not_computed_not_zero() -> None:
    with_prices = run(injected_world())
    without_prices = run(injected_world(with_bid_prices=False))
    data = injected_world(with_bid_prices=False)
    cover = {
        item.trade_id: item.reason
        for item in without_prices.not_computed
        if item.flag_code == "COVER_BID_PATTERN"
    }
    assert set(cover) == {lot.trade_id for lot in data.lots}
    assert set(cover.values()) == {"bid_prices_missing"}
    assert flagged(without_prices, "COVER_BID_PATTERN") == set()
    # Screens that do not need bid prices are unaffected (scenario B).
    for flag_code in STRUCTURAL_FLAG_CODES:
        if flag_code != "COVER_BID_PATTERN":
            assert flagged(without_prices, flag_code) == flagged(with_prices, flag_code)


def test_disabled_price_block_is_not_computed() -> None:
    data = injected_world()
    result = run(data, config_with(("price_screens_enabled", False)))
    assert flagged(result, "COVER_BID_PATTERN") == set()
    cover = {item.reason for item in result.not_computed if item.flag_code == "COVER_BID_PATTERN"}
    assert cover == {"price_screens_disabled"}


def test_participants_mismatch_keeps_lot_out_of_bid_based_screens() -> None:
    """R2: 8 records in bids against participants_count = 4 (specs/agents/04-graph.md)."""
    builder, market = world_with()
    bids = ordinary_bids(market, 8)
    trade_id = builder.add_lot(
        market,
        customer=market.customers[0],
        start_cost=Decimal(1_200_000),
        bids=bids,
        winner=bids[-1][0],
        deal_date=None,
        participants_count=4,
    )
    result = run(builder.build())
    lot_reasons = reasons(result, trade_id)
    for flag_code in ("CO_BIDDING", "PERPETUAL_RUNNER_UP", "COVER_BID_PATTERN"):
        assert lot_reasons[flag_code] == "participants_mismatch"
    # The platform's own participants_count and the deal price are still usable.
    assert "LOW_DISCOUNT" not in lot_reasons
    assert "FEW_BIDDERS" not in lot_reasons
    # The winner is known even when the bid records disagree; only the date is missing.
    assert lot_reasons["WINNER_ROTATION"] == "deal_date_missing"


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"deal_cost": None}, {"LOW_DISCOUNT": "deal_cost_missing"}),
        (
            {"participants_count": None},
            {
                "SINGLE_BIDDER": "participants_count_missing",
                "FEW_BIDDERS": "participants_count_missing",
                "CO_BIDDING": "participants_mismatch",
            },
        ),
        ({"region": None}, dict.fromkeys(STRUCTURAL_FLAG_CODES, "market_undefined")),
        ({"category": ""}, dict.fromkeys(STRUCTURAL_FLAG_CODES, "market_undefined")),
        ({"procedure_type": "other"}, dict.fromkeys(STRUCTURAL_FLAG_CODES, "out_of_scope")),
        ({"procedure_type": None}, dict.fromkeys(STRUCTURAL_FLAG_CODES, "out_of_scope")),
        ({"status": "cancelled"}, dict.fromkeys(STRUCTURAL_FLAG_CODES, "out_of_scope")),
        ({"deal_cost": Decimal(2_000_000)}, {"LOW_DISCOUNT": "invalid_values"}),
        ({"participants_count": 0}, {"SINGLE_BIDDER": "invalid_values"}),
        ({"deal_date": None}, {"WINNER_ROTATION": "deal_date_missing"}),
    ],
)
def test_missing_or_invalid_inputs(override: dict[str, object], expected: dict[str, str]) -> None:
    builder, market = world_with()
    bids = ordinary_bids(market, 4)
    trade_id = builder.add_lot(
        market,
        customer=market.customers[0],
        start_cost=Decimal(1_200_000),
        bids=bids,
        winner=bids[-1][0],
        deal_date=date(2025, 6, 1),
    )
    data = builder.build()
    lots = tuple(replace(lot, **override) if lot.trade_id == trade_id else lot for lot in data.lots)
    lot_reasons = reasons(run(replace(data, lots=lots)), trade_id)
    for flag_code, reason in expected.items():
        assert lot_reasons[flag_code] == reason, flag_code


def test_lot_without_winner_or_with_two_winners() -> None:
    builder, market = world_with()
    bids = ordinary_bids(market, 4)
    no_winner = builder.add_lot(
        market,
        customer=market.customers[0],
        start_cost=Decimal(1_200_000),
        bids=bids,
        winner=None,
        deal_date=None,
        deal_cost=bids[-1][1],
    )
    data = builder.build()
    lot_reasons = reasons(run(data), no_winner)
    for flag_code in ("WINNER_ROTATION", "PERPETUAL_RUNNER_UP", "COVER_BID_PATTERN"):
        assert lot_reasons[flag_code] == "winner_ambiguous"
    # Co-bidding does not depend on who won.
    assert "CO_BIDDING" not in lot_reasons

    two_winners = tuple(
        replace(bid, is_winner=True) if bid.trade_id == no_winner else bid for bid in data.bids
    )
    result = run(replace(data, bids=two_winners))
    assert reasons(result, no_winner)["WINNER_ROTATION"] == "winner_ambiguous"
