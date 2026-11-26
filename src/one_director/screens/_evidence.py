"""Exact arithmetic and strict reading of ``evidence`` (shared by all screens).

Screens decide a flag *only* through ``evaluate(evidence)`` of their module, so
the decision is reproducible from the stored evidence by construction
(``recompute`` in ``run.py``). Numbers in evidence are decimal strings or
integers; floats are rejected.
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
    """Fixed Decimal context, independent of any global changes."""
    with localcontext(_CONTEXT):
        yield


def q(value: Decimal) -> Decimal:
    """Round a derived ratio to the stored precision."""
    return value.quantize(QUANTUM)


def dec(value: Decimal) -> str:
    """Decimal -> exact string for evidence (fixed-point, no exponent)."""
    return format(value, "f")


def median(values: Sequence[Decimal]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
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
