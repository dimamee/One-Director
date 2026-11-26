"""Edge cases, determinism and the ``flags`` row contract."""

from __future__ import annotations

import random
import re
import uuid
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import get_args

import pytest
from tests.screens.helpers import base_config, injected_world, run
from tests.screens.synthetic import MarketBuilder

from one_director.screens import (
    ALL_FLAG_CODES,
    STRUCTURAL_FLAG_CODES,
    FlagRow,
    ScreenResult,
    run_structural_screens,
    to_flag_rows,
)
from one_director.screens.results import NotComputedReason

ROOT = Path(__file__).resolve().parents[2]
CREATED_AT = datetime(2026, 12, 3, 9, 0, tzinfo=UTC)
NAIVE = datetime(2026, 12, 3, 9, 0)  # noqa: DTZ001 -- a naive timestamp on purpose
TASHKENT_TIME = datetime(2026, 12, 3, 9, 0, tzinfo=timezone(timedelta(hours=5)))
LOT_LEVEL = ("LOW_DISCOUNT", "SINGLE_BIDDER", "FEW_BIDDERS", "COVER_BID_PATTERN")


def model_card_codes() -> set[str]:
    text = (ROOT / "docs" / "model-card.md").read_text(encoding="utf-8")
    section = text.split("## 3. Признаки (screens)", 1)[1].split("\n## ", 1)[0]
    return set(re.findall(r"`([A-Z_]+)`", section))


def flags_columns() -> list[str]:
    text = (ROOT / "specs" / "schema.md").read_text(encoding="utf-8")
    section = text.split("## `flags`", 1)[1].split("\n## ", 1)[0]
    return re.findall(r"^\| `([a-z_]+)` \|", section, flags=re.MULTILINE)


def test_codes_come_from_the_model_card_catalogue() -> None:
    assert set(ALL_FLAG_CODES) == model_card_codes()
    assert set(STRUCTURAL_FLAG_CODES) < set(ALL_FLAG_CODES)


def test_empty_input() -> None:
    assert run_structural_screens([], [], base_config()) == ScreenResult(flags=(), not_computed=())


def test_single_lot_is_not_computed_instead_of_flagged() -> None:
    builder = MarketBuilder(9)
    market = builder.clean_market("surkhandarya", "construction", lots=0)
    (trade_id,) = builder.inject_single_bidder(market, count=1)
    result = run(builder.build())
    assert result.flags == ()
    lot_reasons = {item.flag_code: item.reason for item in result.not_computed}
    for flag_code in ("LOW_DISCOUNT", "SINGLE_BIDDER", "FEW_BIDDERS"):
        assert lot_reasons[flag_code] == "market_too_small"
    assert lot_reasons["COVER_BID_PATTERN"] == "too_few_bids"
    assert {item.trade_id for item in result.not_computed} == {trade_id}


def test_repeated_runs_are_identical() -> None:
    first = run(injected_world())
    second = run(injected_world())
    assert first == second
    assert [flag.flag_id for flag in first.flags] == [flag.flag_id for flag in second.flags]


def test_input_order_does_not_matter() -> None:
    data = injected_world()
    rng = random.Random(0)  # noqa: S311 -- shuffling test data
    lots, bids = list(data.lots), list(data.bids)
    rng.shuffle(lots)
    rng.shuffle(bids)
    assert run_structural_screens(lots, bids, base_config()) == run(data)


def test_flag_ids_are_unique_and_stable_uuids() -> None:
    flags = run(injected_world()).flags
    ids = [flag.flag_id for flag in flags]
    assert len(set(ids)) == len(ids)
    assert all(uuid.UUID(flag_id).version == 5 for flag_id in ids)


def test_flag_rows_match_the_flags_table() -> None:
    result = run(injected_world())
    rows = to_flag_rows(result.flags, created_at=CREATED_AT)
    assert [f.name for f in fields(FlagRow)] == flags_columns()
    assert len(rows) == len(result.flags)
    for row, flag in zip(rows, result.flags, strict=True):
        assert row.flag_id == flag.flag_id
        assert row.flag_code in STRUCTURAL_FLAG_CODES
        assert row.object_type in {"lot", "firm", "pair"}
        assert row.severity in {"low", "medium", "high"}
        assert len(row.flag_code) <= 32
        assert len(row.object_id) <= 64
        assert len(row.rule_version) <= 32
        assert row.evidence["rule_version"] == row.rule_version
        assert row.created_at == CREATED_AT


@pytest.mark.parametrize("created_at", [NAIVE, TASHKENT_TIME])
def test_created_at_must_be_utc(created_at: datetime) -> None:
    flags = run(injected_world()).flags
    with pytest.raises(ValueError, match="UTC"):
        to_flag_rows(flags, created_at=created_at)


def test_duplicate_keys_are_rejected() -> None:
    data = injected_world()
    with pytest.raises(ValueError, match="trade_id"):
        run_structural_screens([*data.lots, data.lots[0]], data.bids, base_config())
    with pytest.raises(ValueError, match="bids"):
        run_structural_screens(data.lots, [*data.bids, data.bids[0]], base_config())


def test_bids_of_unknown_lots_are_ignored() -> None:
    data = injected_world()
    stray = replace(data.bids[0], trade_id="999999999")
    assert run_structural_screens(data.lots, [*data.bids, stray], base_config()) == run(data)


def test_lot_level_screens_report_every_lot_of_a_small_world() -> None:
    builder = MarketBuilder(10)
    builder.clean_market("karakalpakstan", "construction", lots=4)
    data = builder.build()
    result = run(data)
    for flag_code in LOT_LEVEL:
        reported = {item.trade_id for item in result.not_computed if item.flag_code == flag_code}
        assert reported == {lot.trade_id for lot in data.lots}, flag_code


def test_not_computed_reasons_are_known() -> None:
    known = set(get_args(NotComputedReason))
    result = run(injected_world(with_bid_prices=False))
    assert {item.reason for item in result.not_computed} <= known


def test_zero_start_cost_is_invalid_not_a_crash() -> None:
    data = injected_world()
    target = data.lots[0].trade_id
    lots = tuple(
        replace(lot, start_cost=Decimal(0)) if lot.trade_id == target else lot for lot in data.lots
    )
    result = run(replace(data, lots=lots))
    assert ("LOW_DISCOUNT", target, "invalid_values") in {
        (item.flag_code, item.trade_id, item.reason) for item in result.not_computed
    }
