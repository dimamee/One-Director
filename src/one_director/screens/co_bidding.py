"""``CO_BIDDING`` -- the same two firms keep bidding together (pair level).

For a pair (a, b): ``joint`` lots with both, ``overlap = joint / min(lots_a, lots_b)``
and ``lift = joint / expected``, where ``expected = sum over markets of
lots_a,m * lots_b,m / lots_m`` is the co-occurrence of two independent bidders
with the same activity in the same markets (region x category). In a small
market where everybody bids on everything the lift is ~1 and nothing is
flagged.

Only lots whose bid records agree with ``participants_count`` are used (R2).
This is a structure-of-bidding signal: it is never weakened by the
intermediary rule (``CLAUDE.md``, weak signals).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from decimal import Decimal
from itertools import combinations
from typing import Final

from one_director.screens._evidence import (
    Evaluation,
    dec,
    exact,
    get_bands,
    get_dec,
    get_int,
    get_map,
    get_maps,
    get_str,
    get_strs,
    lot_ids,
    q,
    require,
    severity_at_least,
)
from one_director.screens._prepare import (
    LotView,
    Market,
    ScreenOutput,
    make_flag,
    scope_reason,
    trade_sort_key,
)
from one_director.screens.config import ScreensConfig
from one_director.screens.results import (
    Evidence,
    FlagCode,
    JsonValue,
    NotComputed,
    NotComputedReason,
    ScreenFlag,
)

FLAG_CODE: Final[FlagCode] = "CO_BIDDING"
RULE_VERSION: Final = "1.0.0"


def _inputs(view: LotView) -> NotComputedReason | Market:
    reason = scope_reason(view)
    if reason is not None or view.market is None:
        return reason or "market_undefined"
    if not view.consistent:
        return "participants_mismatch"
    return view.market


def evaluate(evidence: Mapping[str, JsonValue]) -> Evaluation:
    with exact():
        params = get_map(evidence, "params")
        min_joint = get_int(params, "min_joint_lots")
        min_overlap = get_dec(params, "min_overlap_share")
        bands = get_bands(params, "min_lift")
        facts = get_map(evidence, "facts")
        firms = get_strs(facts, "firm_inns")
        require(len(firms) == 2 and firms[0] < firms[1], "firm_inns must be a sorted pair")

        joint = lots_a = lots_b = 0
        expected = Decimal(0)
        for market in get_maps(facts, "markets"):
            get_str(market, "region")
            get_str(market, "category")
            lots_m = get_int(market, "lots")
            a_m, b_m, joint_m = (get_int(market, key) for key in ("lots_a", "lots_b", "joint_lots"))
            require(
                0 <= joint_m <= min(a_m, b_m) and max(a_m, b_m) <= lots_m and lots_m >= 1,
                "market counts are inconsistent",
            )
            joint, lots_a, lots_b = joint + joint_m, lots_a + a_m, lots_b + b_m
            expected += Decimal(a_m * b_m) / lots_m
        require(len(lot_ids(evidence)) == joint, "lot_ids must list the joint lots")

        overlap = q(Decimal(joint) / min(lots_a, lots_b))
        lift = q(joint / expected)  # exact expected; only the stored values are rounded
        expected = q(expected)
        metrics: Evidence = {
            "joint_lots": joint,
            "lots_a": lots_a,
            "lots_b": lots_b,
            "overlap_share": dec(overlap),
            "expected_joint_lots": dec(expected),
            "lift": dec(lift),
        }
        if joint < min_joint or overlap < min_overlap:
            return Evaluation(None, metrics)
        return Evaluation(severity_at_least(lift, bands), metrics)


def screen(views: tuple[LotView, ...], config: ScreensConfig) -> ScreenOutput:
    settings = config.screens.co_bidding
    params: Evidence = settings.model_dump(mode="json")
    rule_version = config.rule_version(RULE_VERSION)
    not_computed: list[NotComputed] = []
    by_market: dict[Market, list[LotView]] = {}
    for view in views:
        inputs = _inputs(view)
        if isinstance(inputs, str):
            not_computed.append(NotComputed(FLAG_CODE, view.trade_id, inputs))
            continue
        by_market.setdefault(inputs, []).append(view)

    market_lots: dict[Market, int] = {}
    firm_lots: defaultdict[Market, Counter[str]] = defaultdict(Counter)
    joint_lots: defaultdict[tuple[str, str], defaultdict[Market, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for market, items in by_market.items():
        if len(items) < config.screens.scope.min_market_lots:
            not_computed += [NotComputed(FLAG_CODE, v.trade_id, "market_too_small") for v in items]
            continue
        market_lots[market] = len(items)
        for view in items:
            inns = [bid.participant_inn for bid in view.bids]
            firm_lots[market].update(inns)
            for pair in combinations(inns, 2):
                joint_lots[pair][market].append(view.trade_id)

    flags: list[ScreenFlag] = []
    for (first, second), per_market in sorted(joint_lots.items()):
        if sum(len(ids) for ids in per_market.values()) < settings.min_joint_lots:
            continue
        markets: list[JsonValue] = [
            {
                **market.as_json(),
                "lots": market_lots[market],
                "lots_a": firm_lots[market][first],
                "lots_b": firm_lots[market][second],
                "joint_lots": len(per_market.get(market, ())),
            }
            for market in sorted(market_lots)
            if firm_lots[market][first] or firm_lots[market][second]
        ]
        ids = sorted((i for group in per_market.values() for i in group), key=trade_sort_key)
        evidence: Evidence = {
            "flag_code": FLAG_CODE,
            "rule_version": rule_version,
            "lot_ids": list[JsonValue](ids),
            "facts": {"firm_inns": [first, second], "markets": markets},
            "params": params,
        }
        flag = make_flag(FLAG_CODE, "pair", f"{first}:{second}", evidence, evaluate(evidence))
        if flag is not None:
            flags.append(flag)
    return flags, not_computed
