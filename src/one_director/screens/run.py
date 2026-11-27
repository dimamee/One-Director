"""Pass 1 of 03-screens: structural screens over ``lots`` and ``bids``.

Pure functions, no I/O: the pipeline (D-21) reads the tables, calls
:func:`run_structural_screens` and writes :func:`to_flag_rows` into ``flags``
and :func:`to_coverage_rows` into ``screen_coverage`` (D-45) with parameterised
DuckDB queries.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timedelta
from typing import Final

from one_director.screens import (
    co_bidding,
    cover_bid_pattern,
    low_discount,
    participants,
    perpetual_runner_up,
    winner_rotation,
)
from one_director.screens._evidence import Evaluation, EvidenceError, get_str
from one_director.screens._prepare import Screen, prepare, trade_sort_key
from one_director.screens.config import ScreensConfig
from one_director.screens.inputs import BidLike, LotLike
from one_director.screens.results import (
    CoverageRow,
    FlagRow,
    JsonValue,
    NotComputed,
    ScreenFlag,
    ScreenResult,
)

STRUCTURAL_SCREENS: Final[tuple[Screen, ...]] = (
    low_discount.screen,
    participants.screen,
    co_bidding.screen,
    winner_rotation.screen,
    perpetual_runner_up.screen,
    cover_bid_pattern.screen,
)

_EVALUATORS: Final[dict[str, Callable[[Mapping[str, JsonValue]], Evaluation]]] = {
    "LOW_DISCOUNT": low_discount.evaluate,
    "SINGLE_BIDDER": participants.evaluate_single,
    "FEW_BIDDERS": participants.evaluate_few,
    "CO_BIDDING": co_bidding.evaluate,
    "WINNER_ROTATION": winner_rotation.evaluate,
    "PERPETUAL_RUNNER_UP": perpetual_runner_up.evaluate,
    "COVER_BID_PATTERN": cover_bid_pattern.evaluate,
}


def _flag_key(flag: ScreenFlag) -> tuple[str, str, str, str]:
    return (flag.flag_code, flag.object_type, flag.object_id, flag.flag_id)


def _not_computed_key(item: NotComputed) -> tuple[str, tuple[int, int, str]]:
    return (item.flag_code, trade_sort_key(item.trade_id))


def run_structural_screens(
    lots: Iterable[LotLike], bids: Iterable[BidLike], config: ScreensConfig
) -> ScreenResult:
    """Every pass-1 screen on the given rows; the result is deterministic and sorted."""
    views = prepare(lots, bids, config.screens.scope)
    flags: list[ScreenFlag] = []
    not_computed: list[NotComputed] = []
    for screen in STRUCTURAL_SCREENS:
        screen_flags, screen_not_computed = screen(views, config)
        flags += screen_flags
        not_computed += screen_not_computed
    return ScreenResult(
        flags=tuple(sorted(flags, key=_flag_key)),
        not_computed=tuple(sorted(not_computed, key=_not_computed_key)),
    )


def recompute(evidence: Mapping[str, JsonValue]) -> Evaluation:
    """Decide a flag again from its stored ``evidence`` alone (severity + metrics).

    Malformed, inconsistent or out-of-range evidence raises :class:`EvidenceError`.
    """
    flag_code = get_str(evidence, "flag_code")
    evaluator = _EVALUATORS.get(flag_code)
    if evaluator is None:
        raise EvidenceError("evidence names an unknown structural flag code")
    get_str(evidence, "rule_version")
    return evaluator(evidence)


def _require_utc(created_at: datetime) -> None:
    if created_at.tzinfo is None or created_at.utcoffset() != timedelta(0):
        raise ValueError("created_at must be a timezone-aware UTC timestamp")


def to_flag_rows(flags: Iterable[ScreenFlag], *, created_at: datetime) -> list[FlagRow]:
    """Rows for the ``flags`` table; ``created_at`` must be timezone-aware UTC."""
    _require_utc(created_at)
    return [
        FlagRow(
            flag_id=flag.flag_id,
            object_type=flag.object_type,
            object_id=flag.object_id,
            flag_code=flag.flag_code,
            severity=flag.severity,
            evidence=flag.evidence,
            rule_version=flag.rule_version,
            created_at=created_at,
        )
        for flag in flags
    ]


def to_coverage_rows(
    not_computed: Iterable[NotComputed], *, created_at: datetime
) -> list[CoverageRow]:
    """Rows for the ``screen_coverage`` table (D-45); ``created_at`` must be UTC."""
    _require_utc(created_at)
    return [
        CoverageRow(
            trade_id=item.trade_id,
            flag_code=item.flag_code,
            reason=item.reason,
            rule_version=item.rule_version,
            created_at=created_at,
        )
        for item in not_computed
    ]
