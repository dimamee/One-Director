"""Tests for the ``lots`` / ``bids`` row models (``one_director.data.schema``).

Two layers:

* contract tests read the column tables straight from ``specs/schema.md`` and
  check that the models have exactly those columns (plus the technical
  ``collected_at`` / ``source``), the same nullability and the same type limits
  -- a model cannot silently drift from the spec or grow invented fields;
* domain tests pin the value rules: identifier patterns, white lists, money as
  ``Decimal`` (never float) with the column scale of 2, UTC timestamps (and a
  ``ValidationError``, not a crash, for values outside the UTC range),
  strictness and which error renderings do and do not echo input values.

All data is synthetic (``tests/fixtures/README.md``): INNs start with ``000``,
URLs point to ``example.invalid``. No network.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any, Literal, get_args, overload

import pytest
from pydantic import ValidationError

from one_director.data.schema import Bid, Lot, LotStatus, ProcedureType, Region, Source

SCHEMA_MD = Path(__file__).resolve().parents[2] / "specs" / "schema.md"

# specs/schema.md, "Общие правила": every table filled from a source carries
# `collected_at TIMESTAMPTZ` and `source`; they are not repeated in the tables.
TECHNICAL_COLUMNS = ("collected_at", "source")

MODELS: dict[str, type[Lot] | type[Bid]] = {"lots": Lot, "bids": Bid}

COLLECTED_AT = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


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


VALID: dict[str, Any] = {"lots": lot_data, "bids": bid_data}


@overload
def build(table: Literal["lots"], **overrides: Any) -> Lot: ...
@overload
def build(table: Literal["bids"], **overrides: Any) -> Bid: ...
@overload
def build(table: str, **overrides: Any) -> Lot | Bid: ...
def build(table: str, **overrides: Any) -> Lot | Bid:
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

    @property
    def varchar_length(self) -> int | None:
        match = re.fullmatch(r"VARCHAR\((\d+)\)", self.sql_type)
        return int(match.group(1)) if match else None


# "| `name` | TYPE(n) | nullable | ..." -- one column row of a spec table.
_ROW = re.compile(
    r"^\| `(?P<name>[a-z_]+)` "
    r"\| (?P<type>[A-Z]+(?:\([0-9, ]+\))?(?:\[\])?) "
    r"\| (?P<null>[^|]+) \|"
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
            columns.append(SpecColumn(table, row["name"], row["type"], nullable))
    assert columns, f"no columns parsed for `{table}`"
    return columns


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
    assert len(spec_columns("lots")) == 15
    assert len(spec_columns("bids")) == 7


@pytest.mark.parametrize("table", MODELS)
def test_model_columns_are_exactly_the_spec_columns(table: str) -> None:
    expected = [column.name for column in spec_columns(table)] + list(TECHNICAL_COLUMNS)
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


@pytest.mark.parametrize("table", MODELS)
@pytest.mark.parametrize("name", TECHNICAL_COLUMNS)
def test_technical_columns_are_required(table: str, name: str) -> None:
    data = VALID[table]()
    del data[name]
    with pytest.raises(ValidationError):
        MODELS[table].model_validate(data)


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


def test_json_number_is_parsed_as_exact_decimal() -> None:
    data = Lot.model_validate(lot_data()).model_dump(mode="json")
    data["start_cost"] = 0.1
    lot = Lot.model_validate_json(json.dumps(data))
    assert lot.start_cost == Decimal("0.1")


# ---------------------------------------------------------------------------
# Time: TIMESTAMPTZ in UTC, DATE as date
# ---------------------------------------------------------------------------

TIMESTAMP_COLUMNS = [
    *columns_of_type("TIMESTAMPTZ"),
    *(SpecColumn(table, "collected_at", "TIMESTAMPTZ", nullable=False) for table in MODELS),
]


@pytest.mark.parametrize("column", TIMESTAMP_COLUMNS, ids=column_id)
def test_timestamps_reject_naive_datetime(column: SpecColumn) -> None:
    with pytest.raises(ValidationError):
        naive = datetime(2026, 5, 10, 9, 30)  # noqa: DTZ001 -- naive on purpose: must be rejected
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


def test_deal_date_is_a_date_not_a_datetime() -> None:
    assert columns_of_type("DATE") == [SpecColumn("lots", "deal_date", "DATE", nullable=True)]
    with pytest.raises(ValidationError):
        Lot.model_validate(lot_data(deal_date=datetime(2026, 5, 14, tzinfo=UTC)))
    with pytest.raises(ValidationError):
        Lot.model_validate(lot_data(deal_date="2026-05-14"))


def test_json_round_trip_keeps_dates_and_times() -> None:
    lot = Lot.model_validate(lot_data())
    bid = Bid.model_validate(bid_data())
    assert Lot.model_validate_json(lot.model_dump_json()) == lot
    assert Bid.model_validate_json(bid.model_dump_json()) == bid


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
