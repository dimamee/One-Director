"""Row models of the ``lots``, ``bids`` and ``flags`` tables (owner: 01-data).

Source of truth: ``specs/schema.md`` (version 0.3). Change the spec first, then
this module; ``tests/data/test_schema.py`` reads the column tables from the spec
and fails if the models drift from it. Other agents import the models from here
(decision D-7) and do not describe these tables again.

Rules shared by every row model:

* columns are exactly the spec columns, plus the technical ``collected_at`` and
  ``source`` for a table filled from a source ("Общие правила": ``lots``,
  ``bids``; ``flags`` is computed and has none); any other key is rejected
  (``extra="forbid"``), so fields such as ``founder`` / ``beneficiary`` can
  never reach a table;
* strict types, no silent coercion: money is ``Decimal`` (never ``float``)
  kept with the column scale of exactly 2 places (``1.5`` -> ``1.50``), dates
  are ``date``, timestamps are timezone-aware ``datetime`` and are stored in
  UTC, identifiers are strings. Raw platform values are converted by the parser
  before a row is built (``model_validate`` takes Python objects only);
* JSON input (``model_validate_json``; ``model_validate_strings`` follows the
  same rules for the scalar columns) is our own JSON -- the form
  ``model_dump_json`` writes -- and is read without any lossy step:

  - money (D-42) is a string with exactly 2 places after the point, as DuckDB
    returns ``DECIMAL(20, 2)``: ``"196510000.00"``. ASCII digits, no sign, no
    exponent, no leading zeros, no spaces or underscores. A JSON number is
    rejected: it is read through ``float``, which silently changes the amount
    (``123456789012345678.99`` -> ``...680.00``, ``1e-400`` -> ``0.00``);
  - timestamps are RFC 3339 strings with seconds and an explicit offset:
    ``"2026-05-10T09:30:00Z"``, ``"2026-05-10T14:30:00+05:00"``, at most 6
    fractional digits. A string of digits (``"1700000000"``), which pydantic
    would read as unix time, and a JSON number are rejected;
  - dates are ``"YYYY-MM-DD"`` (pydantic's strict JSON rules);

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

Open gaps of ``lots`` / ``bids`` keep the current behaviour until the answers
(D-51): an empty ``title`` and placeholder dates (``0001-01-01``,
``9999-12-31``) pass, cross-field rules (``completed`` => ``deal_cost``,
``deal_cost <= start_cost``) are not checked.

``flags`` (a flag is an indicator for review, never a finding) adds:

* ``flag_code`` is a code of ``docs/model-card.md`` §3 and is written only for
  the level of that code (:data:`FLAG_OBJECT_TYPES`; a group-level screen is
  one ``firm`` flag per member, D-44). ``object_id`` has the format of its
  ``object_type``: ``trade_id``, ``inn`` or ``inn1:inn2`` with ``inn1 < inn2``;
* ``evidence`` is a non-empty JSON object of exact JSON values: strings,
  integers, booleans, null, lists, objects -- no floats anywhere, because
  money in evidence is a string with 2 places (D-42) and a number cannot be
  told from an amount here. INN keys follow D-46: under a key ending with
  ``_inn`` only an INN or null, under ``_inns`` only a list of INNs, no
  INN-like key without that suffix; applied thresholds are only under the
  top-level ``params`` object (07 never returns it); ``match_basis`` is a
  weak-signal value of the spec or null; no full 64-hex hashes (person_id,
  address / phone hashes). Nesting is limited to :data:`EVIDENCE_MAX_DEPTH`.
  Errors name the rule, never a key or a value of the evidence. Not
  detectable here: an INN under another key (a 9-digit ``trade_id`` looks the
  same), an amount written as an integer, names. The JSON column comes back
  from DuckDB as text: parse it (``json.loads``) before ``model_validate``;
* ``evidence`` is validated into a new dict (no container is shared with the
  input). The row cannot be reassigned, but the dict itself is mutable: do not
  change it.

Models of the other tables and of the raw platform responses are not part of
this module yet.
"""

import re
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from decimal import Context, Decimal
from types import MappingProxyType
from typing import Annotated, Final, Literal, get_args

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
)

__all__ = [
    "EVIDENCE_MAX_DEPTH",
    "FLAG_OBJECT_TYPES",
    "Bid",
    "CurrencyCode",
    "Evidence",
    "EvidenceValue",
    "Flag",
    "FlagCode",
    "FlagId",
    "FlagObjectType",
    "Inn",
    "Lot",
    "LotStatus",
    "MatchBasis",
    "Money",
    "ProcedureType",
    "Region",
    "RuleVersion",
    "Severity",
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


# RFC 3339 date-time with seconds and an explicit offset, ASCII digits only
# (`[0-9]`, not `\d`). Matched with fullmatch: `$` would let a trailing newline in.
_RFC3339 = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}"  # date
    r"T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?"  # time, at most microseconds
    r"(?:Z|[+-][0-9]{2}:[0-9]{2})"  # offset
)
_TIMESTAMP_TEXT_ERROR = "timestamp must be an RFC 3339 string with seconds and an offset"


def _timestamp_from_json(value: object, info: ValidationInfo) -> object:
    # Python input goes on to the strict check (datetime instances only). JSON
    # input is parsed here: after a before-validator pydantic validates the
    # result as a Python object, so the string must already be a datetime.
    if info.mode == "python":
        return value
    if not isinstance(value, str) or _RFC3339.fullmatch(value) is None:
        raise ValueError(_TIMESTAMP_TEXT_ERROR)
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        # E.g. 2026-02-30: the stdlib message would echo the value.
        raise ValueError(_TIMESTAMP_TEXT_ERROR) from None


# DECIMAL(20, 2): 20 significant digits. Fixed here so that the result does not
# depend on the caller's thread-local decimal context.
_DECIMAL_20 = Context(prec=20)
_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")


def _to_column_scale(value: Decimal) -> Decimal:
    # The column has a fixed scale, so 1.5, 1.500, 0E-10 and 1E+5 come back from
    # DuckDB as 1.50, 1.50, 0.00 and 100000.00. Rows use the same form, so the
    # canonical JSON (facts_hash, evidence) does not change after a round trip.
    # Nothing is rounded: more than 2 places were already rejected.
    scaled = value.quantize(_CENT, context=_DECIMAL_20)
    # -0 passes ge=0 but must not keep its sign ("-0.00"). Only zero is
    # replaced, so the sign of any other amount never depends on ge=0.
    return _ZERO if scaled.is_zero() else scaled


# Money in JSON (D-42): exactly what DuckDB writes for DECIMAL(20, 2) >= 0.
# The number of digits is left to max_digits.
_MONEY_TEXT = re.compile(r"(?:0|[1-9][0-9]*)\.[0-9]{2}")
_MONEY_TEXT_ERROR = "money must be a JSON string with exactly 2 decimal places, e.g. 0.50"


def _money_from_json(value: object, info: ValidationInfo) -> object:
    # Python input goes on to the strict check (Decimal instances only). In JSON
    # a number has already been read as float (precision lost), so only the
    # canonical string is accepted; it is converted to Decimal exactly.
    if info.mode == "python":
        return value
    if not isinstance(value, str) or _MONEY_TEXT.fullmatch(value) is None:
        raise ValueError(_MONEY_TEXT_ERROR)
    return Decimal(value)


# Identifier patterns. pydantic matches them as given; Python code uses
# re.fullmatch with the same text, so a trailing newline never passes `$`.
_TRADE_ID_PATTERN = r"^[0-9]{1,12}$"
_INN_PATTERN = r"^[0-9]{9}$"

# Platform trade id: an integer kept as VARCHAR(32) (D-9).
TradeId = Annotated[str, StringConstraints(pattern=_TRADE_ID_PATTERN)]
# INN (STIR): VARCHAR(9), ASCII digits only.
Inn = Annotated[str, StringConstraints(pattern=_INN_PATTERN)]
# DECIMAL(20, 2) in the row's `currency`, >= 0 (specs/schema.md, "Общие правила").
# Validators run outside-in: the JSON check first, then the Decimal constraints,
# then the column scale.
Money = Annotated[
    Decimal,
    Field(ge=0, max_digits=20, decimal_places=2, allow_inf_nan=False),
    AfterValidator(_to_column_scale),
    BeforeValidator(_money_from_json),
]
# ISO 4217 alphabetic code, VARCHAR(3).
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
# Computed link to the lot page, VARCHAR(500); documents are never downloaded.
SourceUrl = Annotated[str, StringConstraints(max_length=500, pattern=r"^https://\S+$")]
# TIMESTAMPTZ: timezone-aware, normalised to UTC; no UTC value -> ValidationError.
# In JSON: RFC 3339 only, never unix time.
UtcDatetime = Annotated[
    AwareDatetime,
    AfterValidator(_to_utc),
    BeforeValidator(_timestamp_from_json),
]

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


# --------------------------------------------------------------------------- flags

# Codes of docs/model-card.md §3 (a new code -- e.g. the price screens of D-5 --
# needs a PR there and in the glossary first; tests/data reads the table).
FlagCode = Literal[
    "LOW_DISCOUNT",
    "SINGLE_BIDDER",
    "FEW_BIDDERS",
    "CO_BIDDING",
    "WINNER_ROTATION",
    "PERPETUAL_RUNNER_UP",
    "SHARED_FOUNDER",
    "SHARED_DIRECTOR",
    "SHARED_ADDRESS",
    "SHARED_PHONE",
    "COVER_BID_PATTERN",
]
FlagObjectType = Literal["lot", "firm", "pair"]
Severity = Literal["low", "medium", "high"]
# Values of evidence.match_basis for weak matches (specs/schema.md -> flags).
MatchBasis = Literal["name_hash_only", "via_intermediary"]

# The object_type each code is written for: the level in docs/model-card.md §3.
# A group-level screen (WINNER_ROTATION) is one `firm` flag per member of the
# group, with the same evidence and `group_inns` (D-44).
FLAG_OBJECT_TYPES: Final[Mapping[FlagCode, FlagObjectType]] = MappingProxyType(
    {
        "LOW_DISCOUNT": "lot",
        "SINGLE_BIDDER": "lot",
        "FEW_BIDDERS": "lot",
        "CO_BIDDING": "pair",
        "WINNER_ROTATION": "firm",
        "PERPETUAL_RUNNER_UP": "firm",
        "SHARED_FOUNDER": "pair",
        "SHARED_DIRECTOR": "pair",
        "SHARED_ADDRESS": "pair",
        "SHARED_PHONE": "pair",
        "COVER_BID_PATTERN": "lot",
    }
)

# UUID as text, VARCHAR(36): the canonical lower-case form `str(uuid.UUID)`
# writes. Another case or layout of the same UUID would be another primary key.
FlagId = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
]
# VARCHAR(32), a computed identifier: printable ASCII without spaces
# ("1.0.0+demo.c2fb9a07"), never empty.
RuleVersion = Annotated[str, StringConstraints(min_length=1, max_length=32, pattern=r"^[!-~]+$")]

type EvidenceValue = str | int | bool | list[EvidenceValue] | dict[str, EvidenceValue] | None
"""A value inside ``flags.evidence``: exact JSON, no floats (D-42)."""

type Evidence = dict[str, EvidenceValue]
"""``flags.evidence``: a JSON object."""

# The top-level object has depth 1; 03-screens' deepest evidence has depth 4.
# The limit keeps errors as one ValidationError at `evidence` (pydantic's own
# recursion limit would report a location built from the evidence keys).
EVIDENCE_MAX_DEPTH: Final = 16

_INN_KEY_SUFFIX = "_inn"
_INNS_KEY_SUFFIX = "_inns"
_PARAMS_KEY = "params"
_MATCH_BASIS_KEY = "match_basis"
_MATCH_BASIS_VALUES: Final = frozenset(get_args(MatchBasis))
_SCALAR_TYPES: Final = (str, int, bool, type(None))
# 64 hex digits: a whole HMAC-SHA256 pseudonym (person_id, address / phone hash).
_FULL_HASH = re.compile(r"[0-9a-fA-F]{64}")

_EVIDENCE_OBJECT_ERROR = "evidence must be a non-empty JSON object"
_EVIDENCE_JSON_ERROR = (
    "evidence values must be exact JSON: string, integer, boolean, null, list or object "
    "with string keys; no floats (money is a string with 2 decimal places, D-42)"
)
_EVIDENCE_DEPTH_ERROR = f"evidence is nested deeper than {EVIDENCE_MAX_DEPTH} levels"
_INN_VALUE_ERROR = "evidence: a key ending with _inn holds one INN (9 digits) or null (D-46)"
_INNS_VALUE_ERROR = "evidence: a key ending with _inns holds a list of INNs (9 digits) (D-46)"
_INN_KEY_ERROR = "evidence: INNs only under keys ending with _inn or _inns, lower case (D-46)"
_PARAMS_ERROR = "evidence: applied thresholds only under a top-level 'params' object (D-46)"
_MATCH_BASIS_ERROR = "evidence: match_basis is name_hash_only, via_intermediary or null"
_FULL_HASH_ERROR = "evidence must not contain a full 64-hex hash (person_id, address/phone hash)"


def _is_inn(value: object) -> bool:
    return type(value) is str and re.fullmatch(_INN_PATTERN, value) is not None


def _is_match_basis(value: object) -> bool:
    # `in` on a frozenset hashes the value: only a str gets that far.
    return type(value) is str and value in _MATCH_BASIS_VALUES


def _check_evidence_key(key: object, depth: int) -> str:
    if type(key) is not str:
        raise ValueError(_EVIDENCE_JSON_ERROR)
    if _FULL_HASH.search(key):
        raise ValueError(_FULL_HASH_ERROR)
    if key == _PARAMS_KEY and depth > 1:
        raise ValueError(_PARAMS_ERROR)
    if key.lower().endswith(("inn", "inns")) and not key.endswith(
        (_INN_KEY_SUFFIX, _INNS_KEY_SUFFIX)
    ):
        raise ValueError(_INN_KEY_ERROR)
    return key


def _check_evidence_entry(key: str, value: object) -> None:
    if key.endswith(_INN_KEY_SUFFIX):
        if value is not None and not _is_inn(value):
            raise ValueError(_INN_VALUE_ERROR)
    elif key.endswith(_INNS_KEY_SUFFIX):
        if type(value) is not list or not all(_is_inn(item) for item in value):
            raise ValueError(_INNS_VALUE_ERROR)
    elif key == _MATCH_BASIS_KEY and not (value is None or _is_match_basis(value)):
        raise ValueError(_MATCH_BASIS_ERROR)


def _check_evidence(value: object) -> object:
    """Shape and conventions of ``flags.evidence`` (Python and JSON input alike).

    Runs before pydantic's own validation of :data:`Evidence`, so a bad value
    gives one error at ``evidence`` with a fixed message. Exact built-in types
    only: a ``float``, ``Decimal``, tuple or ``str`` / ``int`` subclass (an enum)
    would not come back the same from the JSON column. The walk is iterative.
    """
    if type(value) is not dict or not value:
        raise ValueError(_EVIDENCE_OBJECT_ERROR)
    if _PARAMS_KEY in value and type(value[_PARAMS_KEY]) is not dict:
        raise ValueError(_PARAMS_ERROR)
    stack: list[tuple[object, int]] = [(value, 1)]
    while stack:
        node, depth = stack.pop()
        if type(node) is dict:
            if depth > EVIDENCE_MAX_DEPTH:
                raise ValueError(_EVIDENCE_DEPTH_ERROR)
            for raw_key, item in node.items():
                key = _check_evidence_key(raw_key, depth)
                _check_evidence_entry(key, item)
                stack.append((item, depth + 1))
        elif type(node) is list:
            if depth > EVIDENCE_MAX_DEPTH:
                raise ValueError(_EVIDENCE_DEPTH_ERROR)
            stack.extend((item, depth + 1) for item in node)
        elif type(node) not in _SCALAR_TYPES:
            raise ValueError(_EVIDENCE_JSON_ERROR)
        elif type(node) is str and _FULL_HASH.search(node):
            raise ValueError(_FULL_HASH_ERROR)
    return value


def _is_trade_id(value: str) -> bool:
    return re.fullmatch(_TRADE_ID_PATTERN, value) is not None


def _is_pair(value: str) -> bool:
    # "inn1:inn2", sorted (specs/schema.md); a firm is not a pair with itself.
    first, separator, second = value.partition(":")
    return bool(separator) and _is_inn(first) and _is_inn(second) and first < second


# object_type -> (check of object_id, fixed error message).
_OBJECT_ID_RULES: Final[Mapping[str, tuple[Callable[[str], bool], str]]] = MappingProxyType(
    {
        "lot": (_is_trade_id, "object_id of a lot must be a trade_id (1-12 digits)"),
        "firm": (_is_inn, "object_id of a firm must be an INN (9 digits)"),
        "pair": (_is_pair, "object_id of a pair must be 'inn1:inn2' with inn1 < inn2"),
    }
)


class Flag(_Row):
    """One row of ``flags``: an indicator for review (PK ``flag_id``).

    Computed by 03-screens; a flag is never a finding. ``evidence`` rules are in
    the module docstring.
    """

    flag_id: FlagId
    object_type: FlagObjectType
    # VARCHAR(64); trade_id, inn or "inn1:inn2" by object_type (checked below).
    object_id: Annotated[str, StringConstraints(max_length=64)]
    flag_code: FlagCode
    severity: Severity
    evidence: Annotated[Evidence, BeforeValidator(_check_evidence)]
    rule_version: RuleVersion
    created_at: UtcDatetime

    # Fields are validated in order, so `object_type` is in `info.data` here
    # unless it was itself invalid (then that is the only error reported).
    @field_validator("object_id")
    @classmethod
    def _object_id_has_the_format_of_object_type(cls, value: str, info: ValidationInfo) -> str:
        object_type = info.data.get("object_type")
        if object_type is None:
            return value
        is_valid, message = _OBJECT_ID_RULES[object_type]
        if not is_valid(value):
            raise ValueError(message)
        return value

    @field_validator("flag_code")
    @classmethod
    def _flag_code_is_written_for_object_type(
        cls, value: FlagCode, info: ValidationInfo
    ) -> FlagCode:
        object_type = info.data.get("object_type")
        if object_type is not None and FLAG_OBJECT_TYPES[value] != object_type:
            raise ValueError(
                "flag_code is not written for this object_type (docs/model-card.md §3, D-44)"
            )
        return value
