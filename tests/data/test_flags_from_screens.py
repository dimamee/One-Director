"""Contract 01-data <-> 03-screens: every ``flags`` row 03 builds is a valid ``Flag``.

03-screens writes ``flags`` from wave 1 and keeps a temporary copy of the
columns (``FlagRow``, "временно, D-43") until it switches to
``one_director.data.schema.Flag``. These tests run pass 1 of 03 on its shared
synthetic markets (D-27), read through our ``Lot`` / ``Bid`` models as the
pipeline will read the tables, and check that every row 03 would write is
accepted by ``Flag`` unchanged -- as Python objects and after the JSON column.

Only the stable public API of ``one_director.screens`` is used
(``run_structural_screens``, ``to_flag_rows``, ``load_demo_config``,
``STRUCTURAL_FLAG_CODES``, ``synthetic``), and :func:`row_values` reads both
a ``FlagRow`` and a ``Flag``: the tests keep working, unchanged, after 03
replaces its copy with ``Flag``. Thresholds are the demo file's
("DEMO — не для продакшна"). No network.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from one_director.data.schema import FLAG_OBJECT_TYPES, Bid, Flag, Lot
from one_director.screens import (
    STRUCTURAL_FLAG_CODES,
    ScreensConfig,
    load_demo_config,
    run_structural_screens,
    to_flag_rows,
)
from one_director.screens.synthetic import SyntheticData, injected_world

CREATED_AT = datetime(2026, 11, 28, 12, 0, tzinfo=UTC)


@dataclasses.dataclass(frozen=True)
class Written:
    """What 03 would write into ``flags`` for one synthetic world."""

    with_bid_prices: bool
    data: SyntheticData
    rows: list[Any]


def row_values(row: object) -> dict[str, Any]:
    """Column values of a row of ``to_flag_rows``: ``FlagRow`` now, ``Flag`` after D-43."""
    if isinstance(row, Flag):
        return row.model_dump()
    assert dataclasses.is_dataclass(row)
    assert not isinstance(row, type)
    return dataclasses.asdict(row)


def demo_config_with_price_screens() -> ScreensConfig:
    # The price block on (D-6), so that COVER_BID_PATTERN is written as well.
    return load_demo_config().model_copy(update={"price_screens_enabled": True})


def as_models(data: SyntheticData) -> tuple[list[Lot], list[Bid]]:
    lots = [Lot.model_validate(dataclasses.asdict(lot)) for lot in data.lots]
    bids = [Bid.model_validate(dataclasses.asdict(bid)) for bid in data.bids]
    return lots, bids


@pytest.fixture(scope="module", params=[True, False], ids=["with_bid_prices", "without_bid_prices"])
def written(request: pytest.FixtureRequest) -> Written:
    with_bid_prices: bool = request.param
    data = injected_world(with_bid_prices=with_bid_prices)
    lots, bids = as_models(data)
    result = run_structural_screens(lots, bids, demo_config_with_price_screens())
    return Written(with_bid_prices, data, to_flag_rows(result.flags, created_at=CREATED_AT))


def test_every_pass_1_code_is_written(written: Written) -> None:
    expected = set(STRUCTURAL_FLAG_CODES)
    if not written.with_bid_prices:
        expected -= {"COVER_BID_PATTERN"}  # not computed without bid prices
    assert {row.flag_code for row in written.rows} == expected
    assert {row.object_type for row in written.rows} == {"lot", "firm", "pair"}


def test_rows_have_exactly_the_flag_columns(written: Written) -> None:
    for row in written.rows:
        assert list(row_values(row)) == list(Flag.model_fields)


def test_every_row_is_a_valid_flag(written: Written) -> None:
    for row in written.rows:
        values = row_values(row)
        flag = Flag.model_validate(values)
        assert flag.model_dump() == values, row.flag_code
        assert flag.object_type == FLAG_OBJECT_TYPES[flag.flag_code]


def test_every_row_survives_the_json_column(written: Written) -> None:
    for row in written.rows:
        values = row_values(row)
        # The pipeline writes evidence as JSON text; a reader parses it back.
        text = json.dumps(
            values["evidence"], sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
        flag = Flag.model_validate({**values, "evidence": json.loads(text)})
        assert flag.evidence == values["evidence"], row.flag_code
        assert Flag.model_validate_json(flag.model_dump_json()) == flag, row.flag_code


def test_rows_from_the_models_equal_rows_from_the_synthetic_data(written: Written) -> None:
    # D-42: Lot / Bid keep money with scale 2, so evidence -- and the
    # deterministic flag_id -- is the same as on 03's own synthetic rows.
    result = run_structural_screens(
        written.data.lots, written.data.bids, demo_config_with_price_screens()
    )
    rows = to_flag_rows(result.flags, created_at=CREATED_AT)
    assert [row_values(row) for row in rows] == [row_values(row) for row in written.rows]


def test_row_values_reads_a_flag_as_well(written: Written) -> None:
    # After D-43, to_flag_rows returns Flag rows: the helper must read them the same.
    for row in written.rows:
        flag = Flag.model_validate(row_values(row))
        assert row_values(flag) == row_values(row)
