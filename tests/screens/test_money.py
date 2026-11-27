"""Money in evidence: a string with exactly two decimals, whatever the input scale (D-42).

The same amount arrives as ``Decimal("196510000.00")`` from DuckDB
``DECIMAL(20, 2)`` and from the ``data.schema`` models, but may arrive as
``Decimal("196510000")`` from other code. ``evidence`` -- and with it the
deterministic ``flag_id`` -- must not depend on that.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from tests.screens.helpers import by_code, flagged, injected_world, json_round_trip, run

from one_director.screens import EvidenceError, ScreenResult, recompute
from one_director.screens.synthetic import MarketBuilder, MarketRef, SyntheticData, cents

MONEY_KEYS = {"start_cost", "deal_cost", "bid_price", "winner_price"}
MONEY = re.compile(r"[0-9]+\.[0-9]{2}")

# Equal amounts, other representations. DuckDB and data.schema give scale 2.
RESCALINGS: dict[str, Callable[[Decimal], Decimal]] = {
    "scale_0_when_whole": lambda d: d.quantize(Decimal(1)) if d == d.to_integral_value() else d,
    "scale_4": lambda d: d.quantize(Decimal("0.0001")),
    "exponent_form": lambda d: d.normalize(),  # 196510000.00 -> 1.9651E+8
}


def rescaled(data: SyntheticData, how: Callable[[Decimal], Decimal]) -> SyntheticData:
    lots = tuple(
        replace(
            lot,
            start_cost=how(lot.start_cost),
            deal_cost=None if lot.deal_cost is None else how(lot.deal_cost),
        )
        for lot in data.lots
    )
    bids = tuple(
        replace(bid, bid_price=None if bid.bid_price is None else how(bid.bid_price))
        for bid in data.bids
    )
    return replace(data, lots=lots, bids=bids)


def money_leaves(value: Any, key: str | None = None) -> list[Any]:
    """Values stored under the money keys anywhere in a JSON tree."""
    if isinstance(value, dict):
        return [leaf for k, item in value.items() for leaf in money_leaves(item, k)]
    if isinstance(value, list):
        return [leaf for item in value for leaf in money_leaves(item, key)]
    return [value] if key in MONEY_KEYS else []


def summary(result: ScreenResult) -> list[tuple[str, str, Any]]:
    return [(flag.flag_id, flag.object_id, flag.evidence) for flag in result.flags]


def test_generator_stores_money_with_scale_two() -> None:
    data = injected_world()
    amounts = [lot.start_cost for lot in data.lots]
    amounts += [lot.deal_cost for lot in data.lots if lot.deal_cost is not None]
    amounts += [bid.bid_price for bid in data.bids if bid.bid_price is not None]
    assert amounts
    assert {amount.as_tuple().exponent for amount in amounts} == {-2}


def test_generator_rescales_amounts_and_rejects_fractions_of_a_cent() -> None:
    assert str(cents(Decimal(196_510_000))) == "196510000.00"
    with pytest.raises(ValueError, match="two decimal places"):
        cents(Decimal("1.005"))
    builder = MarketBuilder(1)
    market = builder.clean_market("andijan", "food", lots=0, firms=3)
    builder.add_lot(
        market,
        customer=market.customers[0],
        start_cost=Decimal(1_000),
        bids=[(market.firms[0], Decimal(990))],
        winner=market.firms[0],
        deal_date=date(2025, 3, 1),
    )
    data = builder.build()
    (lot,), (bid,) = data.lots, data.bids
    assert (str(lot.start_cost), str(lot.deal_cost)) == ("1000.00", "990.00")
    assert str(bid.bid_price) == "990.00"


def test_money_in_evidence_has_exactly_two_decimals() -> None:
    result = run(injected_world())
    leaves = [leaf for flag in result.flags for leaf in money_leaves(flag.evidence)]
    codes = {flag.flag_code for flag in result.flags if money_leaves(flag.evidence)}
    assert codes == {"LOW_DISCOUNT", "COVER_BID_PATTERN"}
    assert leaves
    assert all(isinstance(leaf, str) and MONEY.fullmatch(leaf) for leaf in leaves), leaves


@pytest.mark.parametrize("how", sorted(RESCALINGS))
def test_same_amounts_in_another_scale_give_the_same_evidence_and_flag_id(how: str) -> None:
    data = injected_world()
    other = rescaled(data, RESCALINGS[how])
    # Decimal equality ignores the scale: the rows are "equal", their strings are not.
    assert other.lots == data.lots
    assert any(
        str(a.start_cost) != str(b.start_cost) for a, b in zip(data.lots, other.lots, strict=True)
    )
    expected, actual = run(data), run(other)
    assert summary(actual) == summary(expected)
    assert actual.not_computed == expected.not_computed


def _world_with_one_low_discount_lot(start_cost: Decimal) -> tuple[SyntheticData, str]:
    builder = MarketBuilder(42)
    market: MarketRef = builder.clean_market("navoi", "food")
    firms = market.firms
    trade_id = builder.add_lot(
        market,
        customer=market.customers[0],
        start_cost=Decimal("196510000.00"),
        bids=[
            (firms[0], Decimal("196000000.00")),
            (firms[1], Decimal("196300000.00")),
            (firms[2], Decimal("196400000.00")),
        ],
        winner=firms[0],
        deal_date=date(2025, 5, 5),
    )
    data = builder.build()
    lots = tuple(
        replace(lot, start_cost=start_cost) if lot.trade_id == trade_id else lot
        for lot in data.lots
    )
    return replace(data, lots=lots), trade_id


def test_the_d42_finding_low_discount_start_cost_without_cents() -> None:
    """Synthetic start_cost Decimal('196510000') vs Lot model Decimal('196510000.00')."""
    from_model, trade_id = _world_with_one_low_discount_lot(Decimal("196510000.00"))
    from_synthetic, _ = _world_with_one_low_discount_lot(Decimal("196510000"))
    (expected,) = by_code(run(from_model), "LOW_DISCOUNT")
    (actual,) = by_code(run(from_synthetic), "LOW_DISCOUNT")
    assert expected.object_id == trade_id
    assert actual.evidence == expected.evidence
    assert actual.flag_id == expected.flag_id
    assert actual.evidence["facts"]["start_cost"] == "196510000.00"
    assert actual.evidence["facts"]["deal_cost"] == "196000000.00"


@pytest.mark.parametrize(
    "value",
    ["196510000", "1.9651E+8", "196510000.000", "196510000.0", "0196510000.00", "-1.00", 196510000],
)
def test_non_canonical_money_in_evidence_is_rejected(value: object) -> None:
    result = run(injected_world())
    low = json_round_trip(by_code(result, "LOW_DISCOUNT")[0].evidence)
    low["facts"]["start_cost"] = value
    with pytest.raises(EvidenceError, match="start_cost"):
        recompute(low)
    cover = json_round_trip(by_code(result, "COVER_BID_PATTERN")[0].evidence)
    cover["facts"]["bids"][0]["bid_price"] = value
    with pytest.raises(EvidenceError, match="bid_price"):
        recompute(cover)


@pytest.mark.parametrize(
    "start_cost",
    [Decimal("1200000.005"), Decimal("1E+18"), Decimal("-1200000.00"), Decimal("NaN")],
)
def test_start_cost_outside_decimal_20_2_is_invalid(start_cost: Decimal) -> None:
    data = injected_world()
    target = sorted(data.truth["LOW_DISCOUNT"])[0]
    lots = tuple(
        replace(lot, start_cost=start_cost) if lot.trade_id == target else lot for lot in data.lots
    )
    result = run(replace(data, lots=lots))
    assert target not in flagged(result, "LOW_DISCOUNT")
    assert ("LOW_DISCOUNT", target, "invalid_values") in {
        (item.flag_code, item.trade_id, item.reason) for item in result.not_computed
    }


@pytest.mark.parametrize("bid_price", [Decimal("1000.001"), Decimal("-5.00"), Decimal(0)])
def test_bid_price_outside_decimal_20_2_is_invalid(bid_price: Decimal) -> None:
    data = injected_world()
    target = sorted(data.truth["COVER_BID_PATTERN"])[0]
    loser = next(bid for bid in data.bids if bid.trade_id == target and not bid.is_winner)
    bids = tuple(replace(bid, bid_price=bid_price) if bid == loser else bid for bid in data.bids)
    result = run(replace(data, bids=bids))
    assert target not in flagged(result, "COVER_BID_PATTERN")
    assert ("COVER_BID_PATTERN", target, "invalid_values") in {
        (item.flag_code, item.trade_id, item.reason) for item in result.not_computed
    }
