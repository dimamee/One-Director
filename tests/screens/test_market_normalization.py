"""Screens are normalised by market (region x category), docs/model-card.md §7."""

from __future__ import annotations

from tests.screens.helpers import by_code, flagged, run

from one_director.screens.synthetic import MarketBuilder


def test_low_discount_depends_on_the_market() -> None:
    """A 0.1-0.4 % discount is unusual where discounts are 5-25 %, not where they are 0.1-0.5 %."""
    builder = MarketBuilder(21)
    competitive = builder.clean_market("bukhara", "construction")
    regulated = builder.clean_market("bukhara", "food", discount_bp=(10, 50))
    in_competitive = builder.inject_low_discount(competitive)
    builder.inject_low_discount(regulated)
    result = run(builder.build())
    assert flagged(result, "LOW_DISCOUNT") == set(in_competitive)


def test_few_bidders_depends_on_the_market() -> None:
    """Two bidders are few where 3-7 is usual, not in a niche market of 2-3 bidders."""
    builder = MarketBuilder(22)
    competitive = builder.clean_market("jizzakh", "construction")
    niche = builder.clean_market("jizzakh", "it_services", participants=(2, 3))
    in_competitive = builder.inject_few_bidders(competitive)
    builder.inject_few_bidders(niche)
    result = run(builder.build())
    assert flagged(result, "FEW_BIDDERS") == set(in_competitive)


def test_co_bidding_is_measured_against_expected_overlap() -> None:
    """In a 3-firm market every pair always bids together: that is the market, not a pattern."""
    builder = MarketBuilder(23)
    builder.clean_market("navoi", "construction", firms=3, participants=(3, 3))
    result = run(builder.build())
    assert flagged(result, "CO_BIDDING") == set()


def test_same_region_other_category_is_another_market() -> None:
    builder = MarketBuilder(24)
    first = builder.clean_market("khorezm", "construction")
    builder.clean_market("khorezm", "food")
    injected = builder.inject_single_bidder(first)
    flags = by_code(run(builder.build()), "SINGLE_BIDDER")
    assert {flag.object_id for flag in flags} == set(injected)
    for flag in flags:
        market = flag.evidence["facts"]["market"]
        assert (market["region"], market["category"]) == ("khorezm", "construction")
        assert market["lots"] == 60 + len(injected)


def test_too_small_market_is_not_computed() -> None:
    builder = MarketBuilder(25)
    small = builder.clean_market("syrdarya", "construction", lots=5)
    injected = builder.inject_low_discount(small, count=2)
    result = run(builder.build())
    assert flagged(result, "LOW_DISCOUNT") == set()
    reasons = {
        item.reason
        for item in result.not_computed
        if item.flag_code == "LOW_DISCOUNT" and item.trade_id in injected
    }
    assert reasons == {"market_too_small"}
