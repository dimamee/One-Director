"""Exact arithmetic and strict reading of ``evidence`` (shared by all screens).

Screens decide a flag *only* through ``evaluate(evidence)`` of their module, so
the decision is reproducible from the stored evidence by construction
(``recompute`` in ``run.py``). Numbers in evidence are decimal strings or
integers; floats are rejected. Two string formats, both independent of the
scale of the input ``Decimal``:

* money (:func:`money`) -- exactly two decimals, as DuckDB returns
  ``DECIMAL(20, 2)``: ``"196510000.00"`` (D-42);
* derived values -- ratios, medians, metrics (:func:`dec`) -- exactly six
  decimals: ``"0.002595"``.

Arithmetic that leaves the exact range while evaluating evidence (for example,
an absurd market median in tampered evidence) raises :class:`EvidenceError`,
never a bare ``decimal`` signal.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from typing import Final, NamedTuple

from one_director.screens.results import Evidence, JsonValue, Severity

DECIMAL_PRECISION: Final = 28
QUANTUM: Final = Decimal("0.000001")
# Money columns are DECIMAL(20, 2) (specs/schema.md); outside the database an
# amount is a string with exactly MONEY_SCALE decimals (D-42).
MONEY_PRECISION: Final = 20
MONEY_SCALE: Final = 2
MONEY_QUANTUM: Final = Decimal(1).scaleb(-MONEY_SCALE)
MONEY_LIMIT: Final = Decimal(10) ** (MONEY_PRECISION - MONEY_SCALE)

_CONTEXT: Final = Context(
    prec=DECIMAL_PRECISION,
    rounding=ROUND_HALF_EVEN,
    traps=[InvalidOperation, DivisionByZero, Overflow],
)


class EvidenceError(ValueError):
    """Evidence is malformed or internally inconsistent (field names only, no values)."""


@dataclass(frozen=True, slots=True)
class Evaluation:
    """Outcome of a screen on one piece of evidence."""

    severity: Severity | None
    metrics: Evidence = field(default_factory=dict)


class Bands(NamedTuple):
    low: Decimal
    medium: Decimal
    high: Decimal


@contextmanager
def exact() -> Iterator[None]:
    """Fixed Decimal context, independent of any global changes.

    Inputs of the screens are validated before they reach this context (money
    by :func:`as_money`), so an arithmetic signal here can only come from
    evidence values out of range; it is reported as :class:`EvidenceError`.
    """
    with localcontext(_CONTEXT):
        try:
            yield
        except ArithmeticError:  # decimal.InvalidOperation, DivisionByZero, Overflow
            raise EvidenceError("evidence values are outside the exact arithmetic range") from None


def q(value: Decimal) -> Decimal:
    """Round a derived ratio to the stored precision."""
    return value.quantize(QUANTUM)


def dec(value: Decimal) -> str:
    """Derived value -> evidence string: fixed point, exactly six decimals."""
    return format(q(value), "f")


def as_money(value: Decimal) -> Decimal | None:
    """``value`` with scale 2 if ``DECIMAL(20, 2)`` can hold it exactly, else ``None``.

    ``Decimal("196510000")``, ``Decimal("1.9651E+8")`` and
    ``Decimal("196510000.00")`` all give ``Decimal("196510000.00")``. Negative,
    non-finite, too large and sub-cent amounts give ``None``.
    """
    if not value.is_finite() or value < 0 or value >= MONEY_LIMIT:
        return None
    with localcontext(_CONTEXT):
        amount = value.quantize(MONEY_QUANTUM)
    if amount != value:
        return None
    return amount.copy_abs()  # -0.00 -> 0.00


def money(value: Decimal) -> str:
    """Amount -> evidence string with exactly two decimals (D-42)."""
    amount = as_money(value)
    if amount is None:
        raise ValueError("amount does not fit DECIMAL(20, 2)")
    return format(amount, "f")


def median(values: Sequence[Decimal]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return q(ordered[middle])
    return q((ordered[middle - 1] + ordered[middle]) / 2)


def severity_at_most(value: Decimal, bands: Bands) -> Severity | None:
    if value <= bands.high:
        return "high"
    if value <= bands.medium:
        return "medium"
    if value <= bands.low:
        return "low"
    return None


def severity_at_least(value: Decimal, bands: Bands) -> Severity | None:
    if value >= bands.high:
        return "high"
    if value >= bands.medium:
        return "medium"
    if value >= bands.low:
        return "low"
    return None


# -- strict readers ------------------------------------------------------------


def get_map(data: Mapping[str, JsonValue], key: str) -> dict[str, JsonValue]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise EvidenceError(f"evidence field {key!r} must be an object")
    return value


def get_list(data: Mapping[str, JsonValue], key: str) -> list[JsonValue]:
    value = data.get(key)
    if not isinstance(value, list):
        raise EvidenceError(f"evidence field {key!r} must be a list")
    return value


def get_str(data: Mapping[str, JsonValue], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise EvidenceError(f"evidence field {key!r} must be a string")
    return value


def get_bool(data: Mapping[str, JsonValue], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise EvidenceError(f"evidence field {key!r} must be a boolean")
    return value


def get_int(data: Mapping[str, JsonValue], key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise EvidenceError(f"evidence field {key!r} must be an integer")
    return value


def get_dec(data: Mapping[str, JsonValue], key: str) -> Decimal:
    value = data.get(key)
    if not isinstance(value, str):
        raise EvidenceError(f"evidence field {key!r} must be a decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise EvidenceError(f"evidence field {key!r} must be a decimal string") from None
    if not number.is_finite():
        raise EvidenceError(f"evidence field {key!r} must be finite")
    return number


def get_money(data: Mapping[str, JsonValue], key: str) -> Decimal:
    """An amount in its canonical form only: ``"196510000.00"`` (D-42).

    ``"196510000"``, ``"1.9651E+8"``, ``"196510000.000"``, negative amounts and
    JSON numbers are rejected: they are not what the screens write.
    """
    value = data.get(key)
    if isinstance(value, str):
        try:
            amount = as_money(Decimal(value))
        except InvalidOperation:
            amount = None
        if amount is not None and format(amount, "f") == value:
            return amount
    raise EvidenceError(f"evidence field {key!r} must be an amount with two decimals")


def get_market_lots(market: Mapping[str, JsonValue], params: Mapping[str, JsonValue]) -> int:
    """``market.lots``, checked against the market-size gate in ``params``."""
    lots = get_int(market, "lots")
    require(lots >= get_int(params, "min_market_lots"), "market is below params.min_market_lots")
    return lots


def get_bands(data: Mapping[str, JsonValue], key: str) -> Bands:
    bands = get_map(data, key)
    return Bands(get_dec(bands, "low"), get_dec(bands, "medium"), get_dec(bands, "high"))


def get_maps(data: Mapping[str, JsonValue], key: str) -> list[dict[str, JsonValue]]:
    items = get_list(data, key)
    if not all(isinstance(item, dict) for item in items):
        raise EvidenceError(f"evidence field {key!r} must be a list of objects")
    return [item for item in items if isinstance(item, dict)]


def get_strs(data: Mapping[str, JsonValue], key: str) -> list[str]:
    items = get_list(data, key)
    if not all(isinstance(item, str) for item in items):
        raise EvidenceError(f"evidence field {key!r} must be a list of strings")
    return [item for item in items if isinstance(item, str)]


def lot_ids(evidence: Mapping[str, JsonValue]) -> list[str]:
    """``evidence.lot_ids``: non-empty, without duplicates."""
    ids = get_strs(evidence, "lot_ids")
    if not ids or len(set(ids)) != len(ids):
        raise EvidenceError("evidence field 'lot_ids' must be non-empty and unique")
    return ids


def require(condition: bool, message: str) -> None:
    """Consistency check of evidence (raise instead of guessing)."""
    if not condition:
        raise EvidenceError(message)
