"""Row models of the ``lots`` and ``bids`` tables (owner: 01-data).

Source of truth: ``specs/schema.md`` (version 0.2). Change the spec first, then
this module; ``tests/data/test_schema.py`` reads the column tables from the spec
and fails if the models drift from it. Other agents import the models from here
(decision D-7) and do not describe these tables again.

Rules shared by every row model:

* columns are exactly the spec columns plus the technical ``collected_at`` and
  ``source`` ("Общие правила"); any other key is rejected (``extra="forbid"``),
  so fields such as ``founder`` / ``beneficiary`` can never reach a table;
* strict types, no silent coercion: money is ``Decimal`` (never ``float``)
  kept with the column scale of exactly 2 places (``1.5`` -> ``1.50``), dates
  are ``date``, timestamps are timezone-aware ``datetime`` and are stored in
  UTC, identifiers are strings. Raw platform values are converted by the parser
  before a row is built; JSON input goes through ``model_validate_json``;
* every bad value, including a timestamp with no UTC equivalent, fails as a
  ``ValidationError``, so one bad record can be quarantined without aborting
  the parse;
* ``str(ValidationError)`` does not echo input values (``hide_input_in_errors``).
  ``errors()`` and ``json()`` still include the raw ``input`` (an INN, a name)
  by default: anything that logs or stores an error must call
  ``errors(include_input=False, include_url=False)`` or
  ``json(include_input=False)`` and keep field names and error types only;
* rows are immutable;
* source texts (``title``, ``*_name``, ``display_no``) are untrusted input: they
  are stored as is and escaped on output, never treated as instructions.

Models of the other tables and of the raw platform responses are not part of
this module yet.
"""

from datetime import UTC, date, datetime
from decimal import Context, Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

__all__ = [
    "Bid",
    "CurrencyCode",
    "Inn",
    "Lot",
    "LotStatus",
    "Money",
    "ProcedureType",
    "Region",
    "Source",
    "SourceUrl",
    "TradeId",
    "UtcDatetime",
]


def _to_utc(value: datetime) -> datetime:
    try:
        return value.astimezone(UTC)
    except OverflowError:
        # E.g. 0001-01-01T01:00:00+05:00 (a DateTime.MinValue placeholder) or
        # 9999-12-31T23:00:00-05:00 has no UTC value in `datetime`. A ValueError
        # becomes a ValidationError; the message never contains the value.
        raise ValueError("timestamp is out of range after conversion to UTC") from None


# DECIMAL(20, 2): 20 significant digits. Fixed here so that the result does not
# depend on the caller's thread-local decimal context.
_DECIMAL_20 = Context(prec=20)
_CENT = Decimal("0.01")


def _to_column_scale(value: Decimal) -> Decimal:
    # The column has a fixed scale, so 1.5, 1.500, 0E-10 and 1E+5 come back from
    # DuckDB as 1.50, 1.50, 0.00 and 100000.00. Rows use the same form, so the
    # canonical JSON (facts_hash, evidence) does not change after a round trip.
    # Nothing is rounded: more than 2 places were already rejected. copy_abs()
    # only turns -0 (allowed by ge=0) into 0.
    return value.quantize(_CENT, context=_DECIMAL_20).copy_abs()


# Platform trade id: an integer kept as VARCHAR(32) (D-9).
TradeId = Annotated[str, StringConstraints(pattern=r"^[0-9]{1,12}$")]
# INN (STIR): VARCHAR(9), ASCII digits only.
Inn = Annotated[str, StringConstraints(pattern=r"^[0-9]{9}$")]
# DECIMAL(20, 2) in the row's `currency`; prices are >= 0 (specs/agents/01-data.md).
Money = Annotated[
    Decimal,
    Field(ge=0, max_digits=20, decimal_places=2, allow_inf_nan=False),
    AfterValidator(_to_column_scale),
]
# ISO 4217 alphabetic code, VARCHAR(3).
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
# Computed link to the lot page, VARCHAR(500); documents are never downloaded.
SourceUrl = Annotated[str, StringConstraints(max_length=500, pattern=r"^https://\S+$")]
# TIMESTAMPTZ: timezone-aware, normalised to UTC; no UTC value -> ValidationError.
UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]

Source = Literal["etender", "registry", "committee"]
ProcedureType = Literal["best_offer", "tender", "auction", "other"]
LotStatus = Literal["completed", "cancelled", "failed", "other"]
# Region codes, fixed white list (D-8).
Region = Literal[
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
]


class _Row(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )


class Lot(_Row):
    """One row of ``lots``: a lot / deal on the platform (PK ``trade_id``)."""

    trade_id: TradeId
    display_no: Annotated[str, StringConstraints(max_length=64)] | None = None
    title: Annotated[str, StringConstraints(max_length=1000)]
    procedure_type: ProcedureType | None = None
    # White list of category codes is pending (D-8); only the length is checked.
    category: Annotated[str, StringConstraints(max_length=64)] | None = None
    customer_inn: Inn
    customer_name: Annotated[str, StringConstraints(max_length=500)] | None = None
    start_cost: Money
    deal_cost: Money | None = None
    currency: CurrencyCode
    deal_date: date | None = None
    region: Region | None = None
    # As reported by the platform; never recomputed from `bids` (R2).
    participants_count: Annotated[int, Field(ge=0, le=32767)] | None = None
    status: LotStatus
    source_url: SourceUrl
    collected_at: UtcDatetime
    source: Source


class Bid(_Row):
    """One row of ``bids``: a participant of a lot (PK ``trade_id``, ``participant_inn``)."""

    trade_id: TradeId
    participant_inn: Inn
    participant_name: Annotated[str, StringConstraints(max_length=500)] | None = None
    is_winner: bool
    bid_price: Money | None = None
    submitted_at: UtcDatetime | None = None
    # VARCHAR(32) in the spec, but its values are unknown until UZEX/RTAM answer
    # (D-10, D-11): until a schema PR adds the white list the column is always null.
    participant_status: None = None
    collected_at: UtcDatetime
    source: Source
