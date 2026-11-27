"""The synthetic generator follows ``specs/schema.md`` and stays fictional."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import fields
from pathlib import Path

from tests.screens.helpers import injected_world

from one_director.screens.synthetic import SyntheticBid, SyntheticLot

ROOT = Path(__file__).resolve().parents[2]
TECHNICAL_FIELDS = ["collected_at", "source"]


def schema_section(table: str) -> str:
    text = (ROOT / "specs" / "schema.md").read_text(encoding="utf-8")
    return text.split(f"## `{table}`", 1)[1].split("\n## ", 1)[0]


def schema_columns(table: str) -> list[str]:
    return re.findall(r"^\| `([a-z_]+)` \|", schema_section(table), flags=re.MULTILINE)


def region_whitelist() -> set[str]:
    row = next(
        line for line in schema_section("lots").splitlines() if line.startswith("| `region` |")
    )
    return set(re.findall(r"`([a-z_]+)`", row)[1:])


def test_lot_fields_match_schema() -> None:
    assert [f.name for f in fields(SyntheticLot)] == schema_columns("lots") + TECHNICAL_FIELDS


def test_bid_fields_match_schema() -> None:
    assert [f.name for f in fields(SyntheticBid)] == schema_columns("bids") + TECHNICAL_FIELDS


def test_generator_is_deterministic() -> None:
    assert injected_world(3) == injected_world(3)
    assert injected_world(3).lots != injected_world(4).lots


def test_identifiers_are_synthetic() -> None:
    data = injected_world()
    inns = {lot.customer_inn for lot in data.lots} | {bid.participant_inn for bid in data.bids}
    assert all(re.fullmatch(r"000[0-9]{6}", inn) for inn in inns)
    assert all(re.fullmatch(r"[0-9]{1,12}", lot.trade_id) for lot in data.lots)
    assert all(lot.source_url.startswith("https://example.invalid/") for lot in data.lots)
    assert {lot.region for lot in data.lots} <= region_whitelist()


def test_generated_lots_are_internally_consistent() -> None:
    data = injected_world()
    bids_by_lot = defaultdict(list)
    for bid in data.bids:
        bids_by_lot[bid.trade_id].append(bid)
    for lot in data.lots:
        bids = bids_by_lot[lot.trade_id]
        winners = [bid for bid in bids if bid.is_winner]
        assert lot.participants_count == len(bids)
        assert len(winners) == 1
        assert winners[0].bid_price == min(bid.bid_price for bid in bids)
        assert lot.deal_cost == winners[0].bid_price
        assert lot.deal_cost is not None
        assert lot.deal_cost <= lot.start_cost


def test_every_structural_scheme_is_injected() -> None:
    truth = injected_world().truth
    assert set(truth) == {
        "LOW_DISCOUNT",
        "SINGLE_BIDDER",
        "FEW_BIDDERS",
        "CO_BIDDING",
        "WINNER_ROTATION",
        "PERPETUAL_RUNNER_UP",
        "COVER_BID_PATTERN",
    }
    assert all(truth.values())
