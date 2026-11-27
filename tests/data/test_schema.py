"""Tests for the row models ``Lot``, ``Bid``, ``Flag`` (``one_director.data.schema``).

Layers:

* contract tests read the column tables straight from ``specs/schema.md`` and
  check that the models have exactly those columns (plus the technical
  ``collected_at`` / ``source`` for tables filled from a source), the same
  nullability and the same type limits -- a model cannot silently drift from
  the spec or grow invented fields;
* domain tests pin the value rules: identifier patterns, white lists, money as
  ``Decimal`` (never float) with the column scale of 2, UTC timestamps (and a
  ``ValidationError``, not a crash, for values outside the UTC range),
  strictness and which error renderings do and do not echo input values;
* JSON input tests pin what ``model_validate_json`` accepts: money only as a
  string with exactly 2 places, never a JSON number (D-42); timestamps only as
  RFC 3339 strings, never unix time (review 09, N4);
* D-51 tests pin the behaviour that stays until the open gaps are answered;
* ``flags`` tests pin the white lists against the spec and ``docs/model-card.md``
  §3 (codes and their level), the ``object_id`` format of each ``object_type``
  and the ``evidence`` conventions (D-42, D-46, weak-signal ``match_basis``).
  The rows 03-screens builds are checked in ``test_flags_from_screens.py``.

All data is synthetic (``tests/fixtures/README.md``): INNs start with ``000``,
URLs point to ``example.invalid``. No network.
"""

from __future__ import annotations

import enum
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any, Literal, get_args, overload

import pytest
from pydantic import ValidationError

from one_director.data.schema import (
    EVIDENCE_MAX_DEPTH,
    FLAG_OBJECT_TYPES,
    Bid,
    Flag,
    FlagCode,
    FlagObjectType,
    Lot,
    LotStatus,
    MatchBasis,
    ProcedureType,
    Region,
    Severity,
    Source,
    _to_column_scale,
)

SCHEMA_MD = Path(__file__).resolve().parents[2] / "specs" / "schema.md"
MODEL_CARD_MD = Path(__file__).resolve().parents[2] / "docs" / "model-card.md"

# specs/schema.md, "Общие правила": every table filled from a source carries
# `collected_at TIMESTAMPTZ` and `source`; they are not repeated in the tables.
TECHNICAL_COLUMNS = ("collected_at", "source")
# The values of `source` that mean "filled from a source" (not `computed`).
SOURCE_VALUES = ("etender", "registry", "committee")

MODELS: dict[str, type[Lot] | type[Bid] | type[Flag]] = {"lots": Lot, "bids": Bid, "flags": Flag}

COLLECTED_AT = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
CREATED_AT = datetime(2026, 11, 26, 13, 0, tzinfo=UTC)


def lot_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "trade_id": "100001",
        "display_no": "ТЕСТ-100001",
        "title": "Тестовый лот: поставка канцелярских товаров",
        "procedure_type": "best_offer",
        "category": "test_category",
        "customer_inn": "000000001",
        "customer_name": "ГУ Тест-1",
        "start_cost": Decimal("1000000.00"),
        "deal_cost": Decimal("950000.00"),
        "currency": "UZS",
        "deal_date": date(2026, 5, 14),
        "region": "tashkent_city",
        "participants_count": 3,
        "status": "completed",
        "source_url": "https://example.invalid/lot/100001",
        "collected_at": COLLECTED_AT,
        "source": "etender",
    }
    data.update(overrides)
    return data


def bid_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "trade_id": "100001",
        "participant_inn": "000000002",
        "participant_name": "ООО Тест-2",
        "is_winner": True,
        "bid_price": Decimal("950000.00"),
        "submitted_at": datetime(2026, 5, 10, 9, 30, tzinfo=UTC),
        "participant_status": None,
        "collected_at": COLLECTED_AT,
        "source": "etender",
    }
    data.update(overrides)
    return data


def evidence_data(**overrides: Any) -> dict[str, Any]:
    """Evidence in the shape 03-screens writes (``screens/results.py``): exact JSON."""
    data: dict[str, Any] = {
        "flag_code": "LOW_DISCOUNT",
        "rule_version": "1.0.0+demo.0123abcd",
        "lot_ids": ["100001"],
        "facts": {
            "start_cost": "1000000.00",  # money: a string with 2 places (D-42)
            "deal_cost": "998000.00",
            "currency": "UZS",
            "customer_inn": "000000001",  # INNs only under *_inn / *_inns (D-46)
            "market": {"region": "tashkent_city", "category": "test_category", "lots": 60},
        },
        "params": {"max_discount": {"low": "0.5", "medium": "0.4", "high": "0.3"}},  # D-46
        "metrics": {"discount": "0.002000", "bidders": 3, "complete": True, "note": None},
    }
    data.update(overrides)
    return data


def flag_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "flag_id": "99254cd4-4de8-50b2-9a26-96847fad7597",
        "object_type": "lot",
        "object_id": "100001",
        "flag_code": "LOW_DISCOUNT",
        "severity": "high",
        "evidence": evidence_data(),
        "rule_version": "1.0.0+demo.0123abcd",
        "created_at": CREATED_AT,
    }
    data.update(overrides)
    return data


VALID: dict[str, Any] = {"lots": lot_data, "bids": bid_data, "flags": flag_data}


@overload
def build(table: Literal["lots"], **overrides: Any) -> Lot: ...
@overload
def build(table: Literal["bids"], **overrides: Any) -> Bid: ...
@overload
def build(table: Literal["flags"], **overrides: Any) -> Flag: ...
@overload
def build(table: str, **overrides: Any) -> Lot | Bid | Flag: ...
def build(table: str, **overrides: Any) -> Lot | Bid | Flag:
    return MODELS[table].model_validate(VALID[table](**overrides))


# ---------------------------------------------------------------------------
# Reading the column tables from specs/schema.md
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpecColumn:
    table: str
    name: str
    sql_type: str
    nullable: bool
    source: str = field(default="computed", compare=False)
    description: str = field(default="", compare=False)

    @property
    def varchar_length(self) -> int | None:
        match = re.fullmatch(r"VARCHAR\((\d+)\)", self.sql_type)
        return int(match.group(1)) if match else None


# "| `name` | TYPE(n) | nullable | source | class | description |" -- one column
# row of a spec table.
_ROW = re.compile(
    r"^\| `(?P<name>[a-z_]+)` "
    r"\| (?P<type>[A-Z]+(?:\([0-9, ]+\))?(?:\[\])?) "
    r"\| (?P<null>[^|]+) "
    r"\| (?P<source>[^|]+) "
    r"\| (?P<cls>[^|]+) "
    r"\|(?P<description>.*)\|$"  # may be empty
)


def spec_columns(table: str) -> list[SpecColumn]:
    text = SCHEMA_MD.read_text(encoding="utf-8")
    heading = re.search(rf"^## `{table}`.*$", text, flags=re.MULTILINE)
    assert heading, f"section for `{table}` not found in specs/schema.md"
    rest = text[heading.end() :]
    next_heading = re.search(r"^#{2,3} ", rest, flags=re.MULTILINE)
    section = rest[: next_heading.start()] if next_heading else rest
    columns = []
    for line in section.splitlines():
        row = _ROW.match(line)
        if row:
            nullable = row["null"].replace("*", "").strip().startswith("да")
            columns.append(
                SpecColumn(
                    table,
                    row["name"],
                    row["type"],
                    nullable,
                    source=row["source"].strip(),
                    description=row["description"].strip(),
                )
            )
    assert columns, f"no columns parsed for `{table}`"
    return columns


def technical_columns(table: str) -> tuple[str, ...]:
    """``collected_at`` / ``source`` only for a table filled from a source.

    A table whose columns are all ``computed`` (``flags``) is not filled from a
    source ("Общие правила"), so it has no technical columns.
    """
    filled = any(
        value in column.source for column in spec_columns(table) for value in SOURCE_VALUES
    )
    return TECHNICAL_COLUMNS if filled else ()


SOURCE_TABLES = [table for table in MODELS if technical_columns(table)]


def spec_values(table: str, name: str) -> list[str]:
    """Backticked values in the description of a spec column (``lot`` / ``firm``)."""
    (column,) = [c for c in spec_columns(table) if c.name == name]
    return re.findall(r"`([a-z_]+)`", column.description)


ALL_COLUMNS = [column for table in MODELS for column in spec_columns(table)]


def columns_of_type(prefix: str) -> list[SpecColumn]:
    return [column for column in ALL_COLUMNS if column.sql_type.startswith(prefix)]


def column_id(column: SpecColumn) -> str:
    return f"{column.table}.{column.name}"


# ---------------------------------------------------------------------------
# Contract: models == specs/schema.md
# ---------------------------------------------------------------------------


def test_spec_parser_sees_known_columns() -> None:
    names = {column_id(column) for column in ALL_COLUMNS}
    assert {"lots.trade_id", "lots.source_url", "bids.participant_status"} <= names
    assert {"flags.flag_id", "flags.evidence", "flags.created_at"} <= names
    assert len(spec_columns("lots")) == 15
    assert len(spec_columns("bids")) == 7
    assert len(spec_columns("flags")) == 8


def test_only_tables_filled_from_a_source_have_technical_columns() -> None:
    assert SOURCE_TABLES == ["lots", "bids"]
    assert technical_columns("flags") == ()
    assert {column.source for column in spec_columns("flags")} == {"computed"}


@pytest.mark.parametrize("table", MODELS)
def test_model_columns_are_exactly_the_spec_columns(table: str) -> None:
    expected = [column.name for column in spec_columns(table)] + list(technical_columns(table))
    assert list(MODELS[table].model_fields) == expected


@pytest.mark.parametrize("table", MODELS)
def test_sample_rows_are_valid(table: str) -> None:
    row = build(table)
    assert row.model_dump() == VALID[table]()


@pytest.mark.parametrize("column", ALL_COLUMNS, ids=column_id)
def test_nullability_matches_spec(column: SpecColumn) -> None:
    model = MODELS[column.table]
    data = VALID[column.table](**{column.name: None})
    if column.nullable:
        assert getattr(model.model_validate(data), column.name) is None
    else:
        with pytest.raises(ValidationError) as exc:
            model.model_validate(data)
        assert [error["loc"] for error in exc.value.errors()] == [(column.name,)]


@pytest.mark.parametrize("column", ALL_COLUMNS, ids=column_id)
def test_missing_column(column: SpecColumn) -> None:
    model = MODELS[column.table]
    data = VALID[column.table]()
    del data[column.name]
    if column.nullable:
        assert getattr(model.model_validate(data), column.name) is None
    else:
        with pytest.raises(ValidationError) as exc:
            model.model_validate(data)
        errors = exc.value.errors()
        assert [(error["type"], error["loc"]) for error in errors] == [("missing", (column.name,))]


@pytest.mark.parametrize("table", SOURCE_TABLES)
@pytest.mark.parametrize("name", TECHNICAL_COLUMNS)
def test_technical_columns_are_required(table: str, name: str) -> None:
    data = VALID[table]()
    del data[name]
    with pytest.raises(ValidationError):
        MODELS[table].model_validate(data)


@pytest.mark.parametrize(("name", "value"), [("collected_at", COLLECTED_AT), ("source", "etender")])
def test_computed_table_has_no_technical_columns(name: str, value: object) -> None:
    with pytest.raises(ValidationError) as exc:
        Flag.model_validate(flag_data(**{name: value}))
    assert [(e["type"], e["loc"]) for e in exc.value.errors()] == [("extra_forbidden", (name,))]


@pytest.mark.parametrize("column", [c for c in ALL_COLUMNS if c.varchar_length], ids=column_id)
def test_varchar_longer_than_spec_is_rejected(column: SpecColumn) -> None:
    length = column.varchar_length
    assert length is not None
    base = str(VALID[column.table]()[column.name] or "x")
    too_long = (base * (length + 1))[: length + 1]
    with pytest.raises(ValidationError):
        MODELS[column.table].model_validate(VALID[column.table](**{column.name: too_long}))


FREE_TEXT_COLUMNS = {
    ("lots", "display_no"): "Т",
    ("lots", "title"): "Т",
    ("lots", "category"): "c",
    ("lots", "customer_name"): "Т",
    ("bids", "participant_name"): "Т",
}


@pytest.mark.parametrize(("table", "name"), FREE_TEXT_COLUMNS)
def test_free_text_accepts_full_spec_length(table: str, name: str) -> None:
    (length,) = [c.varchar_length for c in spec_columns(table) if c.name == name]
    assert length is not None
    value = FREE_TEXT_COLUMNS[(table, name)] * length
    assert getattr(build(table, **{name: value}), name) == value


def test_source_url_accepts_full_spec_length() -> None:
    (length,) = [c.varchar_length for c in spec_columns("lots") if c.name == "source_url"]
    assert length is not None
    prefix = "https://example.invalid/lot/"
    url = prefix + "1" * (length - len(prefix))
    assert build("lots", source_url=url).source_url == url


# ---------------------------------------------------------------------------
# Money: DECIMAL(20, 2), never float, >= 0
# ---------------------------------------------------------------------------

MONEY_COLUMNS = columns_of_type("DECIMAL")


def test_all_money_columns_are_decimal_20_2() -> None:
    assert {column_id(c) for c in MONEY_COLUMNS} == {
        "lots.start_cost",
        "lots.deal_cost",
        "bids.bid_price",
    }
    assert {c.sql_type for c in MONEY_COLUMNS} == {"DECIMAL(20,2)"}


@pytest.mark.parametrize("column", MONEY_COLUMNS, ids=column_id)
@pytest.mark.parametrize(
    "value",
    [
        Decimal("0"),
        Decimal("0.01"),
        Decimal("1.5"),
        Decimal("1.500"),  # same value as 1.50
        Decimal("999999999999999999.99"),  # 20 digits, 2 after the point
    ],
)
def test_money_accepts_decimal_within_precision(column: SpecColumn, value: Decimal) -> None:
    row = build(column.table, **{column.name: value})
    assert getattr(row, column.name) == value


@pytest.mark.parametrize("column", MONEY_COLUMNS, ids=column_id)
@pytest.mark.parametrize(
    "value",
    [
        Decimal("-0.01"),  # prices >= 0 (specs/agents/01-data.md)
        Decimal("1.001"),  # more than 2 decimal places
        Decimal("1000000000000000000.00"),  # 21 digits
        Decimal("NaN"),
        Decimal("Infinity"),
        1000000.0,  # float is never used for money (specs/schema.md)
        "1000000.00",  # no silent coercion from text
        True,
    ],
    ids=repr,
)
def test_money_rejects_invalid(column: SpecColumn, value: object) -> None:
    with pytest.raises(ValidationError):
        build(column.table, **{column.name: value})


@pytest.mark.parametrize("column", MONEY_COLUMNS, ids=column_id)
@pytest.mark.parametrize(
    ("value", "canonical"),
    [
        (Decimal("1.5"), "1.50"),
        (Decimal("1.500"), "1.50"),
        (Decimal("1E+5"), "100000.00"),
        (Decimal("0"), "0.00"),
        (Decimal("0E-10"), "0.00"),
        (Decimal("-0"), "0.00"),  # -0 == 0 passes ge=0, but must not keep its sign
        (Decimal("-0.00"), "0.00"),
        (Decimal("999999999999999999.99"), "999999999999999999.99"),
    ],
    ids=str,
)
def test_money_is_stored_with_the_column_scale(
    column: SpecColumn, value: Decimal, canonical: str
) -> None:
    # DECIMAL(20, 2) has a fixed scale: DuckDB returns every one of these values
    # with exactly two decimal places. The row must already look like that, or
    # the same lot would give a different canonical JSON (facts_hash, evidence)
    # before and after a trip through the table.
    row = build(column.table, **{column.name: value})
    money = getattr(row, column.name)
    assert money == value
    assert str(money) == canonical
    assert money.as_tuple().exponent == -2
    assert f'"{column.name}":"{canonical}"' in row.model_dump_json()


def test_money_scale_does_not_depend_on_the_global_decimal_context() -> None:
    with localcontext(prec=5):
        lot = Lot.model_validate(lot_data(start_cost=Decimal("999999999999999999.99")))
    assert str(lot.start_cost) == "999999999999999999.99"


def test_money_survives_json_round_trip_exactly() -> None:
    lot = Lot.model_validate(lot_data(start_cost=Decimal("123456789012345678.99")))
    dumped = lot.model_dump_json()
    assert '"start_cost":"123456789012345678.99"' in dumped
    restored = Lot.model_validate_json(dumped)
    assert restored == lot
    assert restored.start_cost == Decimal("123456789012345678.99")


_RAW = "__raw_json_token__"


def json_with(table: str, name: str, raw: str) -> str:
    """A valid row as JSON text, with the value of ``name`` replaced by the raw token ``raw``.

    The token is spliced into the text, so JSON numbers that a float cannot hold
    (``123456789012345678.99``, ``1e-400``) reach the parser exactly as written.
    """
    data = build(table).model_dump(mode="json")
    data[name] = _RAW
    return json.dumps(data, ensure_ascii=False).replace(json.dumps(_RAW), raw)


def from_json(table: str, name: str, raw: str) -> Lot | Bid:
    return MODELS[table].model_validate_json(json_with(table, name, raw))


def json_error(table: str, name: str, raw: str) -> ValidationError:
    with pytest.raises(ValidationError) as exc:
        from_json(table, name, raw)
    assert [e["loc"] for e in exc.value.errors()] == [(name,)]
    return exc.value


# D-42 (specs/schema.md, "Общие правила"): outside the DB, money is a string with
# exactly 2 places after the point, as DuckDB returns DECIMAL(20, 2). A JSON
# number is never accepted: it is read through float, which silently changes
# the amount (the first three cases below are what used to happen).
JSON_NUMBERS = [
    "123456789012345678.99",  # was read as 123456789012345680.00
    "1e-400",  # was read as 0.00
    "999999999999999999.99",  # valid amount, was rejected as 21 digits
    "0.1",
    "196510000",
    "196510000.00",
    "0",
    "1e5",
    "-0.0",
]


@pytest.mark.parametrize("column", MONEY_COLUMNS, ids=column_id)
@pytest.mark.parametrize("raw", JSON_NUMBERS)
def test_json_number_for_money_is_rejected(column: SpecColumn, raw: str) -> None:
    error = json_error(column.table, column.name, raw)
    (detail,) = error.errors(include_input=False, include_url=False)
    assert detail["type"] == "value_error"
    assert "exactly 2 decimal places" in detail["msg"]


@pytest.mark.parametrize("column", MONEY_COLUMNS, ids=column_id)
@pytest.mark.parametrize("raw", ["true", "false", "[]", "{}"])
def test_json_non_string_for_money_is_rejected(column: SpecColumn, raw: str) -> None:
    json_error(column.table, column.name, raw)


@pytest.mark.parametrize("column", MONEY_COLUMNS, ids=column_id)
@pytest.mark.parametrize(
    "text",
    [
        "0.00",
        "0.01",
        "0.50",
        "196510000.00",
        "123456789012345678.99",
        "999999999999999999.99",  # 20 digits, the DECIMAL(20, 2) maximum
    ],
)
def test_money_json_string_is_read_exactly(column: SpecColumn, text: str) -> None:
    row = from_json(column.table, column.name, f'"{text}"')
    money = getattr(row, column.name)
    assert money == Decimal(text)
    assert str(money) == text
    assert f'"{column.name}":"{text}"' in row.model_dump_json()


@pytest.mark.parametrize("column", MONEY_COLUMNS, ids=column_id)
@pytest.mark.parametrize(
    "text",
    [
        "196510000",  # D-42: no places -- the case that broke evidence / flag_id
        "1.5",
        "1.500",
        "1.",
        ".50",
        "01.00",  # DuckDB never writes leading zeros
        "00.00",
        "-0.00",
        "-1.00",
        "+1.00",
        "1e5",
        "1E+5",
        "1.00e0",
        " 1.00",
        "1.00 ",
        "1.00\n",
        "1_000.00",  # Decimal() accepts underscores
        "1 000.00",
        "1,00",
        "١.٠٠",  # Arabic-Indic digits: Decimal() accepts them
        "１.００",  # full-width digits
        "NaN",
        "Infinity",
        "",
        "1000000000000000000.00",  # 21 digits
    ],
    ids=repr,
)
def test_money_json_string_must_have_the_canonical_form(column: SpecColumn, text: str) -> None:
    json_error(column.table, column.name, json.dumps(text, ensure_ascii=False))


@pytest.mark.parametrize("column", MONEY_COLUMNS, ids=column_id)
def test_money_json_null_follows_nullability(column: SpecColumn) -> None:
    if column.nullable:
        row = from_json(column.table, column.name, "null")
        assert getattr(row, column.name) is None
    else:
        json_error(column.table, column.name, "null")


@pytest.mark.parametrize("value", [Decimal("1.5"), Decimal("-1.5"), Decimal("-0.01")])
def test_column_scale_never_changes_the_sign_of_a_non_zero_amount(value: Decimal) -> None:
    # Review 09, N3: -0 must become 0.00, but the helper must not rely on ge=0
    # to keep -1.50 negative (copy_abs() would silently turn it into 1.50).
    scaled = _to_column_scale(value)
    assert scaled == value
    assert scaled.is_signed() == value.is_signed()


@pytest.mark.parametrize(
    "value", [Decimal("-0"), Decimal("-0.00"), Decimal("-0E+3"), Decimal("0E-10")]
)
def test_column_scale_writes_zero_without_a_sign(value: Decimal) -> None:
    scaled = _to_column_scale(value)
    assert str(scaled) == "0.00"
    assert not scaled.is_signed()


# ---------------------------------------------------------------------------
# Time: TIMESTAMPTZ in UTC, DATE as date
# ---------------------------------------------------------------------------

TIMESTAMP_COLUMNS = [
    *columns_of_type("TIMESTAMPTZ"),
    *(SpecColumn(table, "collected_at", "TIMESTAMPTZ", nullable=False) for table in SOURCE_TABLES),
]


def test_timestamp_columns() -> None:
    assert {column_id(c) for c in TIMESTAMP_COLUMNS} == {
        "bids.submitted_at",
        "flags.created_at",
        "lots.collected_at",
        "bids.collected_at",
    }


@pytest.mark.parametrize("column", TIMESTAMP_COLUMNS, ids=column_id)
def test_timestamps_reject_naive_datetime(column: SpecColumn) -> None:
    naive = datetime(2026, 5, 10, 9, 30)  # noqa: DTZ001 -- naive on purpose: must be rejected
    with pytest.raises(ValidationError):
        build(column.table, **{column.name: naive})


@pytest.mark.parametrize("column", TIMESTAMP_COLUMNS, ids=column_id)
def test_timestamps_are_normalised_to_utc(column: SpecColumn) -> None:
    tashkent = timezone(timedelta(hours=5))
    row = build(column.table, **{column.name: datetime(2026, 5, 10, 14, 30, tzinfo=tashkent)})
    value = getattr(row, column.name)
    assert value == datetime(2026, 5, 10, 9, 30, tzinfo=UTC)
    assert value.utcoffset() == timedelta(0)
    assert value.tzinfo is UTC


# Aware timestamps that `datetime` cannot express in UTC (astimezone raises
# OverflowError). The source is untrusted and 0001-01-01 is a common placeholder
# (.NET DateTime.MinValue): such a row must fail with a ValidationError, so it is
# quarantined like any other bad row, never with a bare OverflowError that
# aborts the parse of the whole response.
OUT_OF_UTC_RANGE = [
    datetime(9999, 12, 31, 23, 0, tzinfo=timezone(timedelta(hours=-5))),
    datetime(1, 1, 1, 1, 0, tzinfo=timezone(timedelta(hours=5))),
]


def assert_out_of_utc_range_error(error: ValidationError, name: str, raw: str) -> None:
    assert [(e["type"], e["loc"]) for e in error.errors()] == [("value_error", (name,))]
    for rendering in (str(error), error.json(include_input=False)):
        assert raw not in rendering
        assert raw[:10] not in rendering  # not even the date part


@pytest.mark.parametrize("column", TIMESTAMP_COLUMNS, ids=column_id)
@pytest.mark.parametrize("value", OUT_OF_UTC_RANGE, ids=datetime.isoformat)
def test_timestamp_outside_utc_range_is_a_validation_error(
    column: SpecColumn, value: datetime
) -> None:
    with pytest.raises(ValidationError) as exc:
        build(column.table, **{column.name: value})
    assert_out_of_utc_range_error(exc.value, column.name, value.isoformat())


@pytest.mark.parametrize("column", TIMESTAMP_COLUMNS, ids=column_id)
@pytest.mark.parametrize("value", OUT_OF_UTC_RANGE, ids=datetime.isoformat)
def test_timestamp_outside_utc_range_in_json_is_a_validation_error(
    column: SpecColumn, value: datetime
) -> None:
    data = build(column.table).model_dump(mode="json")
    data[column.name] = value.isoformat()
    with pytest.raises(ValidationError) as exc:
        MODELS[column.table].model_validate_json(json.dumps(data))
    assert_out_of_utc_range_error(exc.value, column.name, value.isoformat())


# Review 09, N4: in JSON, pydantic reads a string of digits as unix time
# ("1700000000" -> 2023-11-14T22:13:20Z), so a misplaced number or a counter
# would become a plausible timestamp. JSON timestamps must be RFC 3339 strings
# with seconds and an explicit offset -- the form model_dump_json() writes.
@pytest.mark.parametrize("column", TIMESTAMP_COLUMNS, ids=column_id)
@pytest.mark.parametrize(
    "raw",
    [
        '"1700000000"',
        '"1700000000000"',
        '"1700000000.5"',
        '"0"',
        "1700000000",
        "1700000000.5",
        "true",
    ],
)
def test_timestamp_json_rejects_unix_time(column: SpecColumn, raw: str) -> None:
    json_error(column.table, column.name, raw)


@pytest.mark.parametrize("column", TIMESTAMP_COLUMNS, ids=column_id)
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('"2026-05-10T09:30:00Z"', datetime(2026, 5, 10, 9, 30, tzinfo=UTC)),
        ('"2026-05-10T14:30:00+05:00"', datetime(2026, 5, 10, 9, 30, tzinfo=UTC)),
        ('"2026-05-10T04:30:00-05:00"', datetime(2026, 5, 10, 9, 30, tzinfo=UTC)),
        ('"2026-05-10T09:30:00.5Z"', datetime(2026, 5, 10, 9, 30, 0, 500000, tzinfo=UTC)),
        ('"2026-05-10T09:30:00.123456Z"', datetime(2026, 5, 10, 9, 30, 0, 123456, tzinfo=UTC)),
    ],
)
def test_timestamp_json_accepts_rfc3339(column: SpecColumn, raw: str, expected: datetime) -> None:
    row = from_json(column.table, column.name, raw)
    value = getattr(row, column.name)
    assert value == expected
    assert value.tzinfo is UTC


@pytest.mark.parametrize("column", TIMESTAMP_COLUMNS, ids=column_id)
@pytest.mark.parametrize(
    "text",
    [
        "2026-05-10T09:30:00",  # no offset
        "2026-05-10",
        "2026-05-10T09:30Z",  # no seconds
        "2026-05-10 09:30:00Z",
        "2026-05-10t09:30:00z",
        "2026-05-10T09:30:00.1234567Z",  # more than microseconds: would be truncated
        "2026-05-10T09:30:00+0500",
        "2026-05-10T09:30:00+05",
        "20260510T093000Z",
        "2026-05-10T09:30:00Z\n",
        " 2026-05-10T09:30:00Z",
        "２０２６-05-10T09:30:00Z",  # full-width digits
        "2026-02-30T09:30:00Z",
        "2026-05-10T24:00:00Z",
        "2026-05-10T23:59:60Z",
        "",
    ],
    ids=repr,
)
def test_timestamp_json_rejects_other_forms(column: SpecColumn, text: str) -> None:
    error = json_error(column.table, column.name, json.dumps(text, ensure_ascii=False))
    if text.strip():
        assert text.strip() not in str(error)
        assert text.strip() not in error.json(include_input=False)


@pytest.mark.parametrize("column", TIMESTAMP_COLUMNS, ids=column_id)
def test_timestamp_json_null_follows_nullability(column: SpecColumn) -> None:
    if column.nullable:
        row = from_json(column.table, column.name, "null")
        assert getattr(row, column.name) is None
    else:
        json_error(column.table, column.name, "null")


@pytest.mark.parametrize(
    "raw",
    [
        '"1700000000"',
        '"19675"',
        "1699920000",
        '"2026-05-14T00:00:00Z"',
        '"20260514"',
        '"2026-5-14"',
        '"2026-05-14\\n"',
    ],
)
def test_deal_date_json_is_only_an_iso_date(raw: str) -> None:
    # pydantic's strict JSON rules already do this for `date` (unlike for
    # `datetime`, N4); the test catches a change on a pydantic upgrade.
    assert from_json("lots", "deal_date", '"2026-05-14"').deal_date == date(2026, 5, 14)
    json_error("lots", "deal_date", raw)


def test_validate_strings_follows_the_json_rules() -> None:
    # The schema docstring promises it; model_validate_strings is the other
    # non-Python input mode of pydantic.
    data = {
        key: str(value)
        for key, value in Lot.model_validate(lot_data()).model_dump(mode="json").items()
        if value is not None
    }
    lot = Lot.model_validate_strings(data)
    assert lot == Lot.model_validate(lot_data())
    for name, value in [("start_cost", "1000000"), ("collected_at", "1700000000")]:
        with pytest.raises(ValidationError) as exc:
            Lot.model_validate_strings({**data, name: value})
        assert [e["loc"] for e in exc.value.errors()] == [(name,)]


def test_deal_date_is_a_date_not_a_datetime() -> None:
    assert columns_of_type("DATE") == [SpecColumn("lots", "deal_date", "DATE", nullable=True)]
    with pytest.raises(ValidationError):
        Lot.model_validate(lot_data(deal_date=datetime(2026, 5, 14, tzinfo=UTC)))
    with pytest.raises(ValidationError):
        Lot.model_validate(lot_data(deal_date="2026-05-14"))


def test_json_round_trip_keeps_dates_and_times() -> None:
    lot = Lot.model_validate(lot_data())
    bid = Bid.model_validate(bid_data())
    flag = Flag.model_validate(flag_data())
    assert Lot.model_validate_json(lot.model_dump_json()) == lot
    assert Bid.model_validate_json(bid.model_dump_json()) == bid
    assert Flag.model_validate_json(flag.model_dump_json()) == flag


# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------

TRADE_ID_COLUMNS = [("lots", "trade_id"), ("bids", "trade_id")]
INN_COLUMNS = [("lots", "customer_inn"), ("bids", "participant_inn")]


@pytest.mark.parametrize(("table", "name"), TRADE_ID_COLUMNS)
@pytest.mark.parametrize("value", ["524614", "0", "1" * 12])
def test_trade_id_accepts_platform_integers(table: str, name: str, value: str) -> None:
    assert getattr(build(table, **{name: value}), name) == value


@pytest.mark.parametrize(("table", "name"), TRADE_ID_COLUMNS)
@pytest.mark.parametrize(
    "value",
    [
        "",
        "1" * 13,
        "52461a",
        "-1",
        " 524614",
        "524614\n",
        "../../etc/passwd",
        "٥٢٤٦١٤",  # Arabic-Indic digits are not ASCII 0-9
        524614,  # stored as VARCHAR: the parser converts, the row model does not
    ],
    ids=repr,
)
def test_trade_id_rejects_non_matching(table: str, name: str, value: object) -> None:
    with pytest.raises(ValidationError):
        build(table, **{name: value})


@pytest.mark.parametrize(("table", "name"), INN_COLUMNS)
@pytest.mark.parametrize(
    "value",
    [
        "00000001",
        "0000000001",
        "00000000X",
        "000 000 01",
        "000000001\n",
        "٠٠٠٠٠٠٠٠١",  # Arabic-Indic digits
        "０００００００００",  # full-width digits
        1,
    ],
    ids=repr,
)
def test_inn_must_be_exactly_nine_ascii_digits(table: str, name: str, value: object) -> None:
    with pytest.raises(ValidationError):
        build(table, **{name: value})


# ---------------------------------------------------------------------------
# White lists
# ---------------------------------------------------------------------------

REGION_CODES = (
    "tashkent_city",
    "tashkent_region",
    "andijan",
    "bukhara",
    "fergana",
    "jizzakh",
    "khorezm",
    "namangan",
    "navoi",
    "kashkadarya",
    "samarkand",
    "syrdarya",
    "surkhandarya",
    "karakalpakstan",
)


def test_white_lists_match_spec() -> None:
    assert set(get_args(Region)) == set(REGION_CODES)
    assert set(get_args(ProcedureType)) == {"best_offer", "tender", "auction", "other"}
    assert set(get_args(LotStatus)) == {"completed", "cancelled", "failed", "other"}
    assert set(get_args(Source)) == {"etender", "registry", "committee"}


@pytest.mark.parametrize("code", REGION_CODES)
def test_every_region_code_is_accepted(code: str) -> None:
    assert Lot.model_validate(lot_data(region=code)).region == code


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("region", "Tashkent"),
        ("region", "Toshkent shahri"),
        ("region", "TASHKENT_CITY"),
        ("procedure_type", "Eng yaxshi takliflarni tanlash"),  # raw type_name, not normalised
        ("procedure_type", "BEST_OFFER"),
        ("status", "Состоялся"),
        ("status", "COMPLETED"),
        ("source", "computed"),
        ("source", "other"),
        ("currency", "uzs"),
        ("currency", "UZ"),
        ("currency", "USDT"),
        ("currency", "86O"),
        ("currency", ""),
    ],
)
def test_lot_rejects_values_outside_white_lists(name: str, value: str) -> None:
    with pytest.raises(ValidationError):
        Lot.model_validate(lot_data(**{name: value}))


@pytest.mark.parametrize("value", ["etender", "registry", "committee"])
def test_source_values(value: str) -> None:
    assert Lot.model_validate(lot_data(source=value)).source == value
    assert Bid.model_validate(bid_data(source=value)).source == value


@pytest.mark.parametrize("value", ["UZS", "USD", "EUR"])
def test_currency_accepts_iso_4217_letter_codes(value: str) -> None:
    assert Lot.model_validate(lot_data(currency=value)).currency == value


@pytest.mark.parametrize("value", [0, 1, 32767])
def test_participants_count_fits_smallint(value: int) -> None:
    assert Lot.model_validate(lot_data(participants_count=value)).participants_count == value


@pytest.mark.parametrize("value", [-1, 32768, True, "3", 3.0], ids=repr)
def test_participants_count_rejects_invalid(value: object) -> None:
    with pytest.raises(ValidationError):
        Lot.model_validate(lot_data(participants_count=value))


@pytest.mark.parametrize("value", [1, 0, "true", "yes", None], ids=repr)
def test_is_winner_is_a_strict_boolean(value: object) -> None:
    with pytest.raises(ValidationError):
        Bid.model_validate(bid_data(is_winner=value))


def test_participant_status_stays_null_until_values_are_known() -> None:
    # specs/schema.md (D-10, D-11): values are unknown until UZEX/RTAM answer;
    # until then the column is null. A whitelist arrives with a schema PR.
    assert Bid.model_validate(bid_data()).participant_status is None
    for value in ("submitted", "отозвана", ""):
        with pytest.raises(ValidationError):
            Bid.model_validate(bid_data(participant_status=value))


def test_bid_without_price_and_time_is_valid() -> None:
    bid = Bid.model_validate(bid_data(bid_price=None, submitted_at=None, is_winner=False))
    assert bid.bid_price is None
    assert bid.submitted_at is None


# ---------------------------------------------------------------------------
# D-51: open gaps keep the current behaviour until the answers. These tests pin
# it, so that a change is made on purpose, together with specs/schema.md.
# ---------------------------------------------------------------------------


def test_d51_empty_title_is_accepted() -> None:
    assert Lot.model_validate(lot_data(title="")).title == ""


@pytest.mark.parametrize("value", [date(1, 1, 1), date(9999, 12, 31)])
def test_d51_placeholder_dates_are_accepted(value: date) -> None:
    assert Lot.model_validate(lot_data(deal_date=value)).deal_date == value


@pytest.mark.parametrize(
    "column", [c for c in TIMESTAMP_COLUMNS if c.table in SOURCE_TABLES], ids=column_id
)
@pytest.mark.parametrize(
    "value",
    [datetime(1, 1, 1, tzinfo=UTC), datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC)],
    ids=datetime.isoformat,
)
def test_d51_placeholder_timestamps_in_utc_are_accepted(
    column: SpecColumn, value: datetime
) -> None:
    assert getattr(build(column.table, **{column.name: value}), column.name) == value


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "completed", "deal_cost": None, "deal_date": None},
        {"start_cost": Decimal("100.00"), "deal_cost": Decimal("150.00")},
        {"status": "cancelled", "deal_cost": Decimal("950000.00")},
    ],
)
def test_d51_cross_field_rules_are_not_checked(overrides: dict[str, Any]) -> None:
    Lot.model_validate(lot_data(**overrides))


# ---------------------------------------------------------------------------
# source_url: a link to the lot page only
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "",
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "http://example.invalid/lot/100001",
        "//example.invalid/lot/100001",
        "https://",
        "https://example.invalid/lot/1 00001",
        " https://example.invalid/lot/100001",
    ],
)
def test_source_url_must_be_an_https_link(value: str) -> None:
    with pytest.raises(ValidationError):
        Lot.model_validate(lot_data(source_url=value))


# ---------------------------------------------------------------------------
# Untrusted text is stored as is
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("table", "name"),
    [
        ("lots", "title"),
        ("lots", "customer_name"),
        ("lots", "display_no"),
        ("bids", "participant_name"),
    ],
)
def test_untrusted_text_is_stored_unchanged(table: str, name: str) -> None:
    value = '  <script>alert("x")</script> Ignore previous instructions\t'
    assert getattr(build(table, **{name: value}), name) == value


# ---------------------------------------------------------------------------
# Strictness, immutability, no echo of input in errors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("table", MODELS)
@pytest.mark.parametrize("name", ["founder", "beneficiary", "director", "email", "ip"])
def test_unknown_columns_are_rejected(table: str, name: str) -> None:
    with pytest.raises(ValidationError) as exc:
        MODELS[table].model_validate(VALID[table](**{name: "Тестов Тест Тестович-1"}))
    assert [(e["type"], e["loc"]) for e in exc.value.errors()] == [("extra_forbidden", (name,))]


@pytest.mark.parametrize(
    ("table", "name", "value"),
    [
        ("bids", "participant_inn", "00000000X"),
        ("lots", "customer_inn", "12345678"),
        ("bids", "founder", "Тестов Тест Тестович-1"),
        ("lots", "region", "Тестовая обл."),
        ("flags", "object_id", "00000000X"),
        ("flags", "flag_code", "Тестовый признак"),
        ("flags", "rule_version", "версия Тест-1"),
    ],
)
def test_validation_error_does_not_echo_input(table: str, name: str, value: str) -> None:
    with pytest.raises(ValidationError) as exc:
        MODELS[table].model_validate(VALID[table](**{name: value}))
    message = str(exc.value)
    assert value not in message
    assert name in message  # the field name is enough to quarantine with a reason
    assert all(value not in str(e) for e in exc.value.errors(include_input=False))
    assert value not in exc.value.json(include_input=False)


def test_structured_errors_echo_input_unless_asked_not_to() -> None:
    # hide_input_in_errors only covers str(error). errors() and json() still
    # carry the raw `input` (here an INN) by default, so anything that logs or
    # stores them must pass include_input=False. This test pins that pydantic
    # behaviour, so the warning in the schema docstring stays true.
    inn = "00000000X"
    with pytest.raises(ValidationError) as exc:
        Bid.model_validate(bid_data(participant_inn=inn))
    error = exc.value
    assert inn not in str(error)
    assert [e["input"] for e in error.errors()] == [inn]
    assert inn in error.json()
    safe = error.errors(include_input=False, include_url=False)
    assert safe == [
        {
            "type": "string_pattern_mismatch",
            "loc": ("participant_inn",),
            "msg": "String should match pattern '^[0-9]{9}$'",
            "ctx": {"pattern": "^[0-9]{9}$"},
        }
    ]
    assert inn not in error.json(include_input=False)


@pytest.mark.parametrize("table", MODELS)
def test_rows_are_immutable(table: str) -> None:
    row = build(table)
    for name in MODELS[table].model_fields:
        with pytest.raises(ValidationError) as exc:
            setattr(row, name, getattr(row, name))
        assert [e["type"] for e in exc.value.errors()] == ["frozen_instance"]


@pytest.mark.parametrize(
    ("table", "name", "value"),
    [
        ("lots", "deal_date", "2026-05-14"),
        ("lots", "start_cost", "100.00"),
        ("lots", "participants_count", "3"),
        ("bids", "is_winner", "true"),
        ("bids", "submitted_at", "2026-05-10T09:30:00Z"),
        ("bids", "trade_id", 100001),
    ],
)
def test_no_silent_type_coercion_from_python_values(table: str, name: str, value: object) -> None:
    with pytest.raises(ValidationError):
        build(table, **{name: value})


# ---------------------------------------------------------------------------
# flags: white lists from specs/schema.md and docs/model-card.md §3
# ---------------------------------------------------------------------------

# docs/model-card.md §3, column "Уровень" -> flags.object_type. A group-level
# screen is written as one `firm` flag per member of the group (D-44,
# specs/schema.md -> flags); `object_type` is not extended.
MODEL_CARD_LEVELS = {"лот": "lot", "фирма": "firm", "пара фирм": "pair", "группа": "firm"}

# A valid object_id and a flag code of each object_type.
OBJECT_IDS = {"lot": "100001", "firm": "000000002", "pair": "000000002:000000003"}
CODE_OF_TYPE = {"lot": "LOW_DISCOUNT", "firm": "PERPETUAL_RUNNER_UP", "pair": "CO_BIDDING"}


def model_card_screens() -> dict[str, str]:
    """``{flag_code: level}`` from the table of ``docs/model-card.md`` §3."""
    text = MODEL_CARD_MD.read_text(encoding="utf-8")
    heading = re.search(r"^## 3\. .*$", text, flags=re.MULTILINE)
    assert heading, "section 3 not found in docs/model-card.md"
    rest = text[heading.end() :]
    next_heading = re.search(r"^## ", rest, flags=re.MULTILINE)
    section = rest[: next_heading.start()] if next_heading else rest
    screens: dict[str, str] = {}
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        for code in re.findall(r"`([A-Z_]+)`", cells[0]):
            screens[code] = cells[-1]
    assert screens, "no screens parsed from docs/model-card.md §3"
    return screens


def typed(object_type: str, **overrides: Any) -> dict[str, Any]:
    """A valid flag of ``object_type`` (matching object_id and flag_code)."""
    data = {
        "object_type": object_type,
        "object_id": OBJECT_IDS[object_type],
        "flag_code": CODE_OF_TYPE[object_type],
    }
    data.update(overrides)
    return flag_data(**data)


def flag_error(name: str, data: dict[str, Any]) -> ValidationError:
    """The single validation error of ``data``; it must point at column ``name``."""
    with pytest.raises(ValidationError) as exc:
        Flag.model_validate(data)
    assert [e["loc"] for e in exc.value.errors()] == [(name,)]
    return exc.value


def assert_no_echo(error: ValidationError, value: str) -> None:
    for rendering in (
        str(error),
        error.json(include_input=False),
        repr(error.errors(include_input=False, include_url=False)),
    ):
        assert value not in rendering


def test_flag_codes_are_the_codes_of_the_model_card() -> None:
    screens = model_card_screens()
    assert len(screens) == 11
    assert set(get_args(FlagCode)) == set(screens)


def test_object_type_of_each_code_follows_the_model_card_level() -> None:
    screens = model_card_screens()
    assert set(screens.values()) <= set(MODEL_CARD_LEVELS), "a new level needs a schema decision"
    expected = {code: MODEL_CARD_LEVELS[level] for code, level in screens.items()}
    assert dict(FLAG_OBJECT_TYPES) == expected
    assert FLAG_OBJECT_TYPES["WINNER_ROTATION"] == "firm"  # D-44


def test_flag_white_lists_match_spec() -> None:
    assert set(get_args(FlagObjectType)) == set(spec_values("flags", "object_type"))
    assert set(get_args(FlagObjectType)) == {"lot", "firm", "pair"}
    assert set(get_args(Severity)) == set(spec_values("flags", "severity"))
    assert set(get_args(Severity)) == {"low", "medium", "high"}
    # specs/schema.md -> flags: values of evidence.match_basis for weak matches.
    assert set(get_args(MatchBasis)) == {"name_hash_only", "via_intermediary"}


def test_flag_mapping_is_read_only() -> None:
    with pytest.raises(TypeError):
        FLAG_OBJECT_TYPES["LOW_DISCOUNT"] = "pair"


def test_json_column_is_evidence_only() -> None:
    assert columns_of_type("JSON") == [SpecColumn("flags", "evidence", "JSON", nullable=False)]


@pytest.mark.parametrize("code", get_args(FlagCode))
def test_every_code_is_accepted_at_its_level(code: str) -> None:
    object_type = FLAG_OBJECT_TYPES[code]
    flag = Flag.model_validate(typed(object_type, flag_code=code))
    assert (flag.flag_code, flag.object_type) == (code, object_type)


@pytest.mark.parametrize(
    ("code", "object_type"),
    [
        (code, object_type)
        for code in get_args(FlagCode)
        for object_type in OBJECT_IDS
        if object_type != FLAG_OBJECT_TYPES[code]
    ],
)
def test_code_at_another_level_is_rejected(code: str, object_type: str) -> None:
    error = flag_error("flag_code", typed(object_type, flag_code=code))
    assert error.errors()[0]["type"] == "value_error"


@pytest.mark.parametrize(
    "code",
    [
        # D-5 (🟡): price screen codes are not in docs/model-card.md §3 yet.
        "PRICE_CV_LOW",
        "PRICE_RD_HIGH",
        "PRICE_KURTOSIS_HIGH",
        "PRICE_SKEW_ABNORMAL",
        "low_discount",
        "LOW_DISCOUNT ",
        "UNKNOWN_CODE",
        "",
    ],
    ids=repr,
)
def test_codes_outside_the_model_card_are_rejected(code: str) -> None:
    flag_error("flag_code", flag_data(flag_code=code))


@pytest.mark.parametrize("value", ["group", "LOT", "Lot", "lot ", "graph", "user", ""], ids=repr)
def test_object_type_outside_the_white_list_is_rejected(value: str) -> None:
    # One error only: object_id and flag_code are not checked against an
    # object_type that is itself invalid. `group` is D-44's rejected alternative.
    flag_error("object_type", flag_data(object_type=value))


@pytest.mark.parametrize("value", ["critical", "HIGH", "High", "none", "", "high "], ids=repr)
def test_severity_outside_the_white_list_is_rejected(value: str) -> None:
    flag_error("severity", flag_data(severity=value))


# ---------------------------------------------------------------------------
# flags.object_id: trade_id, inn or "inn1:inn2" (sorted) -- by object_type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("object_type", "value"),
    [
        ("lot", "524614"),
        ("lot", "0"),
        ("lot", "1" * 12),
        ("firm", "000000001"),
        ("firm", "999999999"),
        ("pair", "000000001:000000002"),
        ("pair", "000000001:999999999"),
    ],
)
def test_object_id_has_the_format_of_its_type(object_type: str, value: str) -> None:
    assert Flag.model_validate(typed(object_type, object_id=value)).object_id == value


@pytest.mark.parametrize(
    ("object_type", "value"),
    [
        ("lot", ""),
        ("lot", "1" * 13),
        ("lot", "52461a"),
        ("lot", "-1"),
        ("lot", " 524614"),
        ("lot", "524614\n"),
        ("lot", "٥٢٤٦١٤"),  # Arabic-Indic digits
        ("lot", "000000001:000000002"),
        ("firm", ""),
        ("firm", "00000001"),
        ("firm", "0000000001"),
        ("firm", "00000000X"),
        ("firm", "000000001\n"),
        ("firm", "０００００００００"),  # full-width digits
        ("firm", "000000001:000000002"),
        ("firm", "F-0123456789abcdef"),  # firm_ref is the API id, not flags.object_id
        ("pair", "000000002:000000001"),  # not sorted
        ("pair", "000000001:000000001"),  # a firm is not a pair with itself
        ("pair", "000000001"),
        ("pair", "000000001:"),
        ("pair", ":000000001"),
        ("pair", "000000001:000000002:000000003"),
        ("pair", "000000001-000000002"),
        ("pair", "000000001,000000002"),
        ("pair", "000000001 :000000002"),
        ("pair", "000000001: 000000002"),
        ("pair", "000000001:000000002\n"),
        ("pair", "00000001:000000002"),
        ("pair", "000000001:00000000X"),
        ("pair", "1" * 64),
    ],
    ids=repr,
)
def test_object_id_of_another_format_is_rejected(object_type: str, value: str) -> None:
    error = flag_error("object_id", typed(object_type, object_id=value))
    if len(value.strip()) >= 6:  # shorter ones ("-1") can occur in the fixed message
        assert_no_echo(error, value.strip())


@pytest.mark.parametrize("value", [100001, None, b"100001"], ids=repr)
def test_object_id_is_a_string(value: object) -> None:
    flag_error("object_id", flag_data(object_id=value))


# ---------------------------------------------------------------------------
# flags.flag_id: UUID as text, VARCHAR(36)
# ---------------------------------------------------------------------------


def test_flag_id_is_a_canonical_uuid_string() -> None:
    (column,) = [c for c in spec_columns("flags") if c.name == "flag_id"]
    assert column.varchar_length == len(str(uuid.uuid4())) == 36
    for value in (
        str(uuid.uuid4()),
        str(uuid.uuid5(uuid.NAMESPACE_DNS, "flags.example.invalid")),
        "00000000-0000-0000-0000-000000000000",
    ):
        assert Flag.model_validate(flag_data(flag_id=value)).flag_id == value


@pytest.mark.parametrize(
    "value",
    [
        "99254CD4-4DE8-50B2-9A26-96847FAD7597",  # the same UUID in another case: another PK
        "{99254cd4-4de8-50b2-9a26-96847fad7597}",
        "urn:uuid:99254cd4-4de8-50b2-9a26-96847fad7597",
        "99254cd44de850b29a2696847fad7597",
        "99254cd4-4de8-50b2-9a26-96847fad759",
        "99254cd4-4de8-50b2-9a26-96847fad75977",
        "99254cd4-4de8-50b2-9a26-96847fad7597\n",
        "99254cd4-4de8-50b2-9a26-96847fad759g",
        "",
        uuid.UUID("99254cd4-4de8-50b2-9a26-96847fad7597"),  # VARCHAR: text, not a UUID object
    ],
    ids=repr,
)
def test_flag_id_rejects_other_forms(value: object) -> None:
    flag_error("flag_id", flag_data(flag_id=value))


# ---------------------------------------------------------------------------
# flags.rule_version: VARCHAR(32), a computed identifier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["1.0.0+demo.c2fb9a07", "1", "v" * 32, "1.0.0-rc.1+prod_x"])
def test_rule_version_accepts_identifiers(value: str) -> None:
    assert Flag.model_validate(flag_data(rule_version=value)).rule_version == value


@pytest.mark.parametrize(
    "value",
    ["", "v" * 33, "1.0 demo", " 1.0", "1.0\n", "1.0\t", "версия-1", "１.0"],
    ids=repr,
)
def test_rule_version_rejects_empty_long_and_non_ascii(value: str) -> None:
    flag_error("rule_version", flag_data(rule_version=value))


# ---------------------------------------------------------------------------
# flags.evidence: exact JSON object (D-42), INNs only under *_inn / *_inns and
# thresholds only under top-level `params` (D-46), weak-signal match_basis
# ---------------------------------------------------------------------------


def evidence_error(evidence: object) -> ValidationError:
    error = flag_error("evidence", flag_data(evidence=evidence))
    assert [e["type"] for e in error.errors()] == ["value_error"]
    return error


def with_facts(**facts: Any) -> dict[str, Any]:
    """The sample evidence with extra entries in ``facts``."""
    evidence = evidence_data()
    evidence["facts"] = {**evidence["facts"], **facts}
    return evidence


def nested(depth: int, leaf: Any = None, *, container: str = "dict") -> Any:
    """A JSON value of the given depth (the top-level object has depth 1)."""
    value = leaf
    for _ in range(depth):
        value = {"x": value} if container == "dict" else [value]
    return value


def test_sample_evidence_is_kept_exactly() -> None:
    flag = Flag.model_validate(flag_data())
    assert flag.evidence == evidence_data()


@pytest.mark.parametrize(
    "value",
    [{}, [], [{"flag_code": "LOW_DISCOUNT"}], '{"flag_code": "LOW_DISCOUNT"}', 1, True, "x"],
    ids=repr,
)
def test_evidence_must_be_a_non_empty_json_object(value: object) -> None:
    # A JSON column read from DuckDB comes back as text: the reader parses it
    # (json.loads) before building the row -- no silent coercion here.
    evidence_error(value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "Тест",
        0,
        -1,
        123456789012345678901234567890,  # Python int is exact
        True,
        False,
        None,
        [],
        {},
        [1, "a", None, [True], {"k": "v"}],
    ],
    ids=repr,
)
def test_evidence_accepts_exact_json_values(value: object) -> None:
    flag = Flag.model_validate(flag_data(evidence=with_facts(value=value)))
    assert flag.evidence["facts"]["value"] == value


class _Text(str):
    __slots__ = ()


class _Number(enum.IntEnum):
    ONE = 1


NOT_JSON = [
    0.5,
    1.0,  # D-42: no floats at all -- money as a float loses precision
    float("nan"),
    float("inf"),
    Decimal("1.00"),  # Python mode takes the JSON form: money is "1.00"
    (1, 2),
    {1, 2},
    frozenset(),
    b"bytes",
    date(2026, 5, 14),
    datetime(2026, 5, 14, tzinfo=UTC),
    uuid.UUID(int=1),
    _Text("subclass of str"),
    _Number.ONE,
    1j,
]


@pytest.mark.parametrize("value", NOT_JSON, ids=repr)
@pytest.mark.parametrize("place", ["top", "facts", "list", "list_of_objects"])
def test_evidence_rejects_values_that_are_not_exact_json(value: object, place: str) -> None:
    evidence: dict[str, Any] = evidence_data()
    if place == "top":
        evidence["value"] = value
    elif place == "facts":
        evidence = with_facts(value=value)
    elif place == "list":
        evidence["lot_ids"] = ["100001", value]
    else:
        evidence = with_facts(bids=[{"bid_price": "1.00"}, {"bid_price": value}])
    evidence_error(evidence)


@pytest.mark.parametrize("key", [1, None, True, ("a",), _Text("key")], ids=repr)
def test_evidence_keys_are_strings(key: object) -> None:
    evidence_error(with_facts(market={key: "x"}))
    evidence_error({**evidence_data(), key: "x"})


def flag_json_with(raw: str) -> str:
    """The sample flag as JSON text, with ``evidence.facts.deal_cost`` = raw token."""
    data = Flag.model_validate(flag_data()).model_dump(mode="json")
    data["evidence"]["facts"]["deal_cost"] = _RAW
    return json.dumps(data, ensure_ascii=False).replace(json.dumps(_RAW), raw)


@pytest.mark.parametrize(
    "raw",
    [
        "196510000.00",  # D-42: money as a JSON number is never accepted
        "123456789012345678.99",  # read as 123456789012345680.00 through float
        "1e-400",  # read as 0.0
        "0.5",
        "1.0",
        "1e5",
        "-0.0",
    ],
)
def test_evidence_json_number_with_fraction_or_exponent_is_rejected(raw: str) -> None:
    with pytest.raises(ValidationError) as exc:
        Flag.model_validate_json(flag_json_with(raw))
    assert [(e["type"], e["loc"]) for e in exc.value.errors()] == [("value_error", ("evidence",))]


@pytest.mark.parametrize("raw", ["0", "60", "-1", "123456789012345678901234567890"])
def test_evidence_json_integers_are_accepted(raw: str) -> None:
    # Counts are integers. An amount written as an integer ("196510000") cannot
    # be told from a count at this level: D-42 for evidence is the writer's
    # duty (03-screens writes money as "196510000.00").
    flag = Flag.model_validate_json(flag_json_with(raw))
    assert flag.evidence["facts"]["deal_cost"] == int(raw)


def test_evidence_money_string_is_kept_exactly_through_json() -> None:
    flag = Flag.model_validate_json(flag_json_with('"123456789012345678.99"'))
    assert flag.evidence["facts"]["deal_cost"] == "123456789012345678.99"
    assert '"deal_cost":"123456789012345678.99"' in flag.model_dump_json()


@pytest.mark.parametrize(
    "evidence",
    [
        {"winner_inn": "000000001"},
        {"winner_inn": None},
        {"group_inns": ["000000001", "000000002"]},
        {"group_inns": []},
        {"facts": {"scope": {"customer_inn": "000000003"}}},
        {"losses": [{"trade_id": "100001", "winner_inn": "000000004"}]},
        {"sequence": [{"winner_inn": None}, {"firm_inns": ["000000005"]}]},
    ],
    ids=repr,
)
def test_inns_under_inn_keys_are_accepted(evidence: dict[str, Any]) -> None:
    assert Flag.model_validate(flag_data(evidence=evidence)).evidence == evidence


@pytest.mark.parametrize(
    "value",
    [
        "00000001",
        "0000000001",
        "00000000X",
        "000000001 ",
        "000000001\n",
        "٠٠٠٠٠٠٠٠١",
        "",
        123456789,
        True,
        ["000000001"],
        {"inn": "000000001"},
        "000000001:000000002",
    ],
    ids=repr,
)
@pytest.mark.parametrize("place", ["top", "nested", "list_of_objects"])
def test_inn_key_holds_one_inn_or_null(value: object, place: str) -> None:
    # 07-backend masks evidence by these key suffixes (D-46): what is under
    # them must be exactly what the masking expects.
    entry = {"winner_inn": value}
    evidence = {
        "top": entry,
        "nested": {"facts": {"scope": entry}},
        "list_of_objects": {"losses": [{"winner_inn": "000000001"}, entry]},
    }[place]
    evidence_error(evidence)


@pytest.mark.parametrize(
    "value",
    [
        "000000001",
        None,
        ["00000001"],
        ["000000001", "00000000X"],
        [123456789],
        [None],
        [["000000001"]],
        {"a": "000000001"},
        ("000000001",),
    ],
    ids=repr,
)
def test_inns_key_holds_a_list_of_inns(value: object) -> None:
    evidence_error({"group_inns": value})
    evidence_error(with_facts(firm_inns=value))


@pytest.mark.parametrize(
    "key",
    ["inn", "inns", "INN", "Inn", "winnerInn", "Winner_INN", "firm_INNS", "customerinn", "x_Inns"],
)
def test_inn_like_key_without_the_suffix_is_rejected(key: str) -> None:
    # An INN under such a key would not be masked by 07 (D-46: suffix _inn /
    # _inns). The value is irrelevant: the key itself names an INN.
    evidence_error({key: "000000001"})
    evidence_error(with_facts(**{key: None}))


def test_inn_outside_inn_keys_cannot_be_detected() -> None:
    # Pinned limitation: a 9-digit trade_id is also a valid INN string, so the
    # model cannot tell an INN under another key. 03-screens must follow D-46.
    evidence = {"lot_ids": ["000000001"], "facts": {"value": "000000002"}}
    assert Flag.model_validate(flag_data(evidence=evidence)).evidence == evidence


def test_params_is_a_top_level_object() -> None:
    evidence = evidence_data(params={"min_market_lots": 10, "bands": {"low": "1"}})
    assert Flag.model_validate(flag_data(evidence=evidence)).evidence == evidence
    without = evidence_data()
    del without["params"]
    assert "params" not in Flag.model_validate(flag_data(evidence=without)).evidence


@pytest.mark.parametrize("value", ["0.5", 10, None, [], ["0.5"], True], ids=repr)
def test_params_that_is_not_an_object_is_rejected(value: object) -> None:
    evidence_error(evidence_data(params=value))


@pytest.mark.parametrize(
    "evidence",
    [
        {"facts": {"params": {"min_market_lots": 10}}},
        {"facts": {"markets": [{"params": {}}]}},
        {"metrics": {"params": "0.5"}},
        {"lot_ids": [{"params": {}}]},
    ],
    ids=repr,
)
def test_params_below_the_top_level_is_rejected(evidence: dict[str, Any]) -> None:
    # D-46: thresholds only under `params`, which 07 never returns. A nested
    # `params` would be a second place to strip.
    evidence_error({**evidence_data(), **evidence})


@pytest.mark.parametrize("value", ["name_hash_only", "via_intermediary", None])
@pytest.mark.parametrize("place", ["top", "nested"])
def test_match_basis_accepts_the_spec_values(value: str | None, place: str) -> None:
    entry = {"match_basis": value}
    evidence = evidence_data(**entry) if place == "top" else with_facts(links=[entry])
    assert Flag.model_validate(flag_data(evidence=evidence)).evidence == evidence


@pytest.mark.parametrize(
    "value",
    ["exact", "NAME_HASH_ONLY", "name_hash", "via intermediary", "", 1, True, ["name_hash_only"]],
    ids=repr,
)
@pytest.mark.parametrize("place", ["top", "nested"])
def test_match_basis_rejects_other_values(value: object, place: str) -> None:
    # A misspelt weak basis would not be weakened by 05 (rule of weak signals).
    entry = {"match_basis": value}
    evidence_error(evidence_data(**entry) if place == "top" else with_facts(links=[entry]))


FULL_HASH = "3f2a" * 16  # 64 hex: a whole person_id / address_hash / phone_hash


@pytest.mark.parametrize(
    "evidence",
    [
        {"person": FULL_HASH},
        {"facts": {"address": FULL_HASH.upper()}},
        {"links": ["P-3f2a", FULL_HASH]},
        {"links": [{"ref": "P-" + FULL_HASH}]},
        {"facts": {FULL_HASH: True}},
        {"note": "hash " + FULL_HASH + " in text"},
    ],
    ids=["value", "upper_case", "list_item", "prefixed", "key", "inside_text"],
)
def test_full_hashes_are_rejected(evidence: dict[str, Any]) -> None:
    # specs/agents/03-screens.md: no full hashes in evidence; the API returns
    # only short prefixes of hashes and person_id (P-3f2a).
    error = evidence_error({**evidence_data(), **evidence})
    assert_no_echo(error, FULL_HASH[:16])
    assert_no_echo(error, FULL_HASH.upper()[:16])


@pytest.mark.parametrize("value", ["P-3f2a", FULL_HASH[:63], "c2fb9a07", "1.0.0+demo.c2fb9a07"])
def test_short_hash_prefixes_are_accepted(value: str) -> None:
    evidence = with_facts(ref=value)
    assert Flag.model_validate(flag_data(evidence=evidence)).evidence == evidence


@pytest.mark.parametrize("container", ["dict", "list"])
def test_evidence_depth_is_limited(container: str) -> None:
    # The top-level object is depth 1; 03-screens' deepest evidence has depth 4.
    deepest = {"value": nested(EVIDENCE_MAX_DEPTH - 1, "leaf", container=container)}
    assert Flag.model_validate(flag_data(evidence=deepest)).evidence == deepest
    evidence_error({"value": nested(EVIDENCE_MAX_DEPTH, "leaf", container=container)})


def test_very_deep_json_evidence_is_a_validation_error() -> None:
    # Deeper than the JSON parser's own limit: still a ValidationError, never a
    # RecursionError that would abort a whole batch.
    shallow = Flag.model_validate(flag_data(evidence={"x": None})).model_dump_json()
    assert Flag.model_validate_json(shallow).evidence == {"x": None}
    raw = shallow.replace('{"x":null}', '{"x":' * 5000 + "null" + "}" * 5000)
    assert raw != shallow
    with pytest.raises(ValidationError):
        Flag.model_validate_json(raw)


@pytest.mark.parametrize(
    ("evidence", "secret"),
    [
        ({"inn": "000000077"}, "000000077"),
        ({"winner_inn": "00000077X"}, "00000077X"),
        ({"group_inns": ["000000077", "Тестов Тест Тестович-1"]}, "Тестов Тест Тестович-1"),
        ({"match_basis": "Тестов Тест Тестович-1"}, "Тестов Тест Тестович-1"),
        ({"facts": {"deal_cost": 196510000.25}}, "196510000.25"),
        ({"facts": {"Тестов Тест Тестович-1": 1.5}}, "Тестов Тест Тестович-1"),
    ],
    ids=["inn_key", "bad_inn", "name_in_inns", "match_basis", "float", "key"],
)
def test_evidence_error_does_not_echo_input(evidence: dict[str, Any], secret: str) -> None:
    # One error at the column: no key or index from inside the evidence in `loc`.
    error = evidence_error(evidence)
    assert_no_echo(error, secret)


def test_evidence_is_copied_from_the_input() -> None:
    source = evidence_data()
    flag = Flag.model_validate(flag_data(evidence=source))
    source["facts"]["deal_cost"] = "1.00"
    source["lot_ids"].append("100002")
    source["new"] = 1
    assert flag.evidence == evidence_data()
    assert flag.evidence is not source


def test_evidence_survives_the_json_column() -> None:
    # What the pipeline writes into the JSON column and a reader parses back.
    flag = Flag.model_validate(flag_data())
    text = json.dumps(flag.evidence, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    restored = Flag.model_validate(flag_data(evidence=json.loads(text)))
    assert restored == flag
