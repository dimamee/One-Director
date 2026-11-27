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
from tests.screens.helpers import base_config, config_with, injected_world, run

from one_director.screens import (
    ALL_FLAG_CODES,
    STRUCTURAL_FLAG_CODES,
    CoverageRow,
    FlagRow,
    ScreenResult,
    cover_bid_pattern,
    run_structural_screens,
    to_coverage_rows,
    to_flag_rows,
)
from one_director.screens.results import NotComputedReason
from one_director.screens.synthetic import MarketBuilder

ROOT = Path(__file__).resolve().parents[2]
CREATED_AT = datetime(2026, 12, 3, 9, 0, tzinfo=UTC)
NAIVE = datetime(2026, 12, 3, 9, 0)  # noqa: DTZ001 -- a naive timestamp on purpose
TASHKENT_TIME = datetime(2026, 12, 3, 9, 0, tzinfo=timezone(timedelta(hours=5)))
LOT_LEVEL = ("LOW_DISCOUNT", "SINGLE_BIDDER", "FEW_BIDDERS", "COVER_BID_PATTERN")


def model_card_codes() -> set[str]:
    text = (ROOT / "docs" / "model-card.md").read_text(encoding="utf-8")
    section = text.split("## 3. Признаки (screens)", 1)[1].split("\n## ", 1)[0]
    return set(re.findall(r"`([A-Z_]+)`", section))


def schema_section(table: str) -> str:
    text = (ROOT / "specs" / "schema.md").read_text(encoding="utf-8")
    return text.split(f"## `{table}`", 1)[1].split("\n## ", 1)[0]


def table_columns(table: str) -> list[str]:
    return re.findall(r"^\| `([a-z_]+)` \|", schema_section(table), flags=re.MULTILINE)


def flags_columns() -> list[str]:
    return table_columns("flags")


def coverage_reason_whitelist() -> set[str]:
    row = next(
        line
        for line in schema_section("screen_coverage").splitlines()
        if line.startswith("| `reason` |")
    )
    return set(re.findall(r"`([a-z_]+)`", row.split("белый список:", 1)[1]))


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


# -- screen_coverage (D-45) --------------------------------------------------------


def test_not_computed_reasons_match_the_screen_coverage_whitelist() -> None:
    # Strict both ways: a new reason goes into the code and into specs/schema.md
    # in the same change (the schema says "новые значения — PR в этот файл").
    whitelist = coverage_reason_whitelist()
    reasons = set(get_args(NotComputedReason))
    assert len(whitelist) >= 10  # the parser found the list
    assert reasons == whitelist, (
        f"only in NotComputedReason: {sorted(reasons - whitelist)}; "
        f"only in specs/schema.md: {sorted(whitelist - reasons)}"
    )


def test_not_computed_records_carry_the_rule_version_of_their_screen() -> None:
    result = run(injected_world())
    flag_versions = {flag.flag_code: flag.rule_version for flag in result.flags}
    assert result.not_computed
    for item in result.not_computed:
        assert item.rule_version == flag_versions[item.flag_code]
    # A disabled price block is still recorded under the version of the config used.
    disabled_config = config_with(("price_screens_enabled", False))
    disabled = run(injected_world(), disabled_config)
    cover = {
        item.rule_version for item in disabled.not_computed if item.flag_code == "COVER_BID_PATTERN"
    }
    assert cover == {disabled_config.rule_version(cover_bid_pattern.RULE_VERSION)}
    assert cover != {flag_versions["COVER_BID_PATTERN"]}


def test_coverage_rows_match_the_screen_coverage_table() -> None:
    result = run(injected_world(with_bid_prices=False))
    rows = to_coverage_rows(result.not_computed, created_at=CREATED_AT)
    assert [f.name for f in fields(CoverageRow)] == table_columns("screen_coverage")
    assert len(rows) == len(result.not_computed)
    keys = {(row.trade_id, row.flag_code, row.rule_version) for row in rows}
    assert len(keys) == len(rows)  # PK (trade_id, flag_code, rule_version)
    for row, item in zip(rows, result.not_computed, strict=True):
        assert (row.trade_id, row.flag_code, row.reason) == (
            item.trade_id,
            item.flag_code,
            item.reason,
        )
        assert row.reason in coverage_reason_whitelist()
        assert len(row.reason) <= 32
        assert len(row.rule_version) <= 32
        assert row.created_at == CREATED_AT


@pytest.mark.parametrize("created_at", [NAIVE, TASHKENT_TIME])
def test_coverage_created_at_must_be_utc(created_at: datetime) -> None:
    result = run(injected_world(with_bid_prices=False))
    with pytest.raises(ValueError, match="UTC"):
        to_coverage_rows(result.not_computed, created_at=created_at)
