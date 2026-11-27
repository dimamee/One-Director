"""``WINNER_ROTATION`` -- a small group of firms wins a customer's lots in turn.

Scope: one customer (``customer_inn``) inside one market (region x category).
Lots are ordered by ``deal_date`` then ``trade_id``. The group is every firm
with at least ``min_wins_per_member`` wins in the scope. The flag needs a group
of 2..``max_group_size`` firms that

* takes a large share of the scope's lots (severity bands),
* splits the wins evenly (``balance`` = fewest / most wins of a member),
* alternates (``switch_rate`` = winner changes between consecutive group wins),
* and wins at this customer much more than in its market: ``lift`` =
  share at the customer / share of all lots of the market won by the group
  (normalisation by region x category; a group that wins everywhere in a
  market where few firms compete has lift ~1 and is not flagged).

The ``flags`` table has no ``group`` object type (``specs/schema.md``), so the
group is reported as one ``firm`` flag per member with the same evidence, the
group being ``facts.group_inns`` (sorted INNs) -- D-44.
Winners are reliable even when bid records disagree with
``participants_count`` (R2), so this screen does not need consistent lots.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from itertools import pairwise
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
    get_market_lots,
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
    screen_params,
    single_winner,
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

FLAG_CODE: Final[FlagCode] = "WINNER_ROTATION"
RULE_VERSION: Final = "1.0.0"

type _Win = tuple[date, str, str]  # deal_date, trade_id, winner_inn


def _inputs(view: LotView) -> NotComputedReason | tuple[Market, _Win]:
    reason = scope_reason(view)
    if reason is not None or view.market is None:
        return reason or "market_undefined"
    winner = single_winner(view)
    if winner is None:
        return "winner_ambiguous"
    if view.lot.deal_date is None:
        return "deal_date_missing"
    return view.market, (view.lot.deal_date, view.trade_id, winner)


def evaluate(evidence: Mapping[str, JsonValue]) -> Evaluation:
    with exact():
        params = get_map(evidence, "params")
        min_wins = get_int(params, "min_wins_per_member")
        max_group = get_int(params, "max_group_size")
        min_balance = get_dec(params, "min_balance")
        min_switch = get_dec(params, "min_switch_rate")
        min_lift = get_dec(params, "min_lift_to_market_share")
        bands = get_bands(params, "min_group_win_share")
        min_scope_lots = get_int(params, "min_scope_lots")
        facts = get_map(evidence, "facts")
        scope = get_map(facts, "scope")
        for key in ("customer_inn", "region", "category"):
            get_str(scope, key)
        scope_lots = get_int(facts, "scope_lots")
        group = get_strs(facts, "group_inns")
        require(bool(group) and group == sorted(set(group)), "group_inns must be sorted and unique")
        market = get_map(facts, "market")
        market_lots = get_market_lots(market, params)
        market_group_wins = get_int(market, "group_wins")

        sequence = get_maps(facts, "sequence")
        winners = [get_str(item, "winner_inn") for item in sequence]
        ordered = [(get_str(item, "deal_date"), get_str(item, "trade_id")) for item in sequence]
        require(
            [trade_id for _, trade_id in ordered] == lot_ids(evidence),
            "lot_ids must list the sequence",
        )
        require(
            ordered == sorted(ordered, key=lambda item: (item[0], trade_sort_key(item[1]))),
            "sequence must be ordered by deal_date, trade_id",
        )
        require(set(winners) <= set(group), "sequence winners must belong to the group")
        require(len(sequence) <= scope_lots, "sequence is longer than the scope")
        require(
            len(sequence) <= market_group_wins <= market_lots and scope_lots <= market_lots,
            "market counts are inconsistent",
        )

        wins = Counter(winners)
        switches = sum(1 for before, after in pairwise(winners) if before != after)
        group_wins = len(winners)
        fewest, most = min(wins[inn] for inn in group), max(wins[inn] for inn in group)
        share = q(Decimal(group_wins) / scope_lots)
        balance = q(Decimal(fewest) / most) if most else Decimal(0)
        switch_rate = q(Decimal(switches) / (group_wins - 1)) if group_wins > 1 else Decimal(0)
        market_share = q(Decimal(market_group_wins) / market_lots)
        # From exact counts, not from the rounded shares.
        lift = q(Decimal(group_wins * market_lots) / (scope_lots * market_group_wins))
        metrics: Evidence = {
            "group_size": len(group),
            "group_wins": group_wins,
            "group_win_share": dec(share),
            "member_wins": [{"winner_inn": inn, "wins": wins[inn]} for inn in group],
            "balance": dec(balance),
            "switch_rate": dec(switch_rate),
            "market_group_share": dec(market_share),
            "lift_to_market_share": dec(lift),
        }
        if scope_lots < min_scope_lots or not 2 <= len(group) <= max_group or fewest < min_wins:
            return Evaluation(None, metrics)
        if balance < min_balance or switch_rate < min_switch or lift < min_lift:
            return Evaluation(None, metrics)
        return Evaluation(severity_at_least(share, bands), metrics)


def screen(views: tuple[LotView, ...], config: ScreensConfig) -> ScreenOutput:
    settings = config.screens.winner_rotation
    params = screen_params(settings, config)
    rule_version = config.rule_version(RULE_VERSION)
    not_computed: list[NotComputed] = []
    by_market: dict[Market, list[tuple[LotView, _Win]]] = {}
    for view in views:
        inputs = _inputs(view)
        if isinstance(inputs, str):
            not_computed.append(NotComputed(FLAG_CODE, view.trade_id, inputs, rule_version))
            continue
        market, win = inputs
        by_market.setdefault(market, []).append((view, win))

    flags: list[ScreenFlag] = []
    for market in sorted(by_market):
        items = by_market[market]
        if len(items) < config.screens.scope.min_market_lots:
            not_computed += [
                NotComputed(FLAG_CODE, v.trade_id, "market_too_small", rule_version)
                for v, _ in items
            ]
            continue
        market_wins = Counter(winner for _, (_, _, winner) in items)
        scopes: defaultdict[str, list[_Win]] = defaultdict(list)
        for view, win in items:
            scopes[view.lot.customer_inn].append(win)
        for customer in sorted(scopes):
            wins = sorted(scopes[customer], key=lambda w: (w[0], trade_sort_key(w[1])))
            if len(wins) < settings.min_scope_lots:
                continue
            counts = Counter(winner for _, _, winner in wins)
            group = sorted(inn for inn, n in counts.items() if n >= settings.min_wins_per_member)
            if not 2 <= len(group) <= settings.max_group_size:
                continue
            members = set(group)
            sequence = [w for w in wins if w[2] in members]
            evidence: Evidence = {
                "flag_code": FLAG_CODE,
                "rule_version": rule_version,
                "lot_ids": [trade_id for _, trade_id, _ in sequence],
                "facts": {
                    "scope": {"customer_inn": customer, **market.as_json()},
                    "scope_lots": len(wins),
                    "group_inns": list[JsonValue](group),
                    "sequence": [
                        {"trade_id": trade_id, "deal_date": day.isoformat(), "winner_inn": inn}
                        for day, trade_id, inn in sequence
                    ],
                    "market": {
                        **market.as_json(),
                        "lots": len(items),
                        "group_wins": sum(market_wins[inn] for inn in group),
                    },
                },
                "params": params,
            }
            evaluation = evaluate(evidence)
            for inn in group:
                flag = make_flag(FLAG_CODE, "firm", inn, evidence, evaluation)
                if flag is not None:
                    flags.append(flag)
    return flags, not_computed
