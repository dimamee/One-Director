"""``PERPETUAL_RUNNER_UP`` -- bids often, almost never wins, loses to the same firm (firm level).

Normalised by market: the firm's wins are compared with
``expected_wins = sum over markets of firm_lots,m * lots_m / bids_m`` -- the
wins of an average bidder with the same activity in the same markets
(region x category). The flag needs a low win rate, a low ratio to the
expected wins *and* a dominant winner among the firm's losses.

Only lots with a single winner and bid records that agree with
``participants_count`` are used (R2).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from decimal import Decimal
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
    lot_ids,
    q,
    require,
    severity_at_most,
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

FLAG_CODE: Final[FlagCode] = "PERPETUAL_RUNNER_UP"
RULE_VERSION: Final = "1.0.0"


def _inputs(view: LotView) -> NotComputedReason | tuple[Market, str]:
    reason = scope_reason(view)
    if reason is not None or view.market is None:
        return reason or "market_undefined"
    if not view.consistent:
        return "participants_mismatch"
    winner = single_winner(view)
    if winner is None:
        return "winner_ambiguous"
    return view.market, winner


def evaluate(evidence: Mapping[str, JsonValue]) -> Evaluation:
    with exact():
        params = get_map(evidence, "params")
        min_participations = get_int(params, "min_participations")
        max_win_rate = get_dec(params, "max_win_rate")
        min_top_share = get_dec(params, "min_top_winner_share")
        bands = get_bands(params, "max_ratio_to_expected_wins")
        facts = get_map(evidence, "facts")
        firm = get_str(facts, "firm_inn")

        participations = wins = 0
        expected = Decimal(0)
        for market in get_maps(facts, "markets"):
            get_str(market, "region")
            get_str(market, "category")
            lots_m, bids_m = get_market_lots(market, params), get_int(market, "bids")
            firm_lots_m, firm_wins_m = get_int(market, "firm_lots"), get_int(market, "firm_wins")
            require(
                0 <= firm_wins_m <= firm_lots_m <= lots_m <= bids_m and firm_lots_m >= 1,
                "market counts are inconsistent",
            )
            participations, wins = participations + firm_lots_m, wins + firm_wins_m
            expected += Decimal(firm_lots_m * lots_m) / bids_m
        require(len(lot_ids(evidence)) == participations, "lot_ids must list every participation")

        losers_to = Counter[str]()
        losses = get_maps(facts, "losses")
        for loss in losses:
            get_str(loss, "trade_id")
            winner = get_str(loss, "winner_inn")
            require(winner != firm, "a loss cannot be won by the firm itself")
            losers_to[winner] += 1
        require(len(losses) == participations - wins, "losses must list every lost lot")

        win_rate = q(Decimal(wins) / participations)
        ratio = q(wins / expected)  # exact expected; only the stored values are rounded
        expected = q(expected)
        top_inn: str | None = None
        top_losses = 0
        if losers_to:
            # Most frequent winner; ties broken by INN for determinism.
            top_inn, top_losses = min(losers_to.items(), key=lambda item: (-item[1], item[0]))
        top_share = q(Decimal(top_losses) / len(losses)) if losses else Decimal(0)
        metrics: Evidence = {
            "participations": participations,
            "wins": wins,
            "win_rate": dec(win_rate),
            "expected_wins": dec(expected),
            "ratio_to_expected_wins": dec(ratio),
            "losses": len(losses),
            "top_winner_inn": top_inn,
            "top_winner_losses": top_losses,
            "top_winner_share": dec(top_share),
        }
        if participations < min_participations or win_rate > max_win_rate or not losses:
            return Evaluation(None, metrics)
        if top_share < min_top_share:
            return Evaluation(None, metrics)
        return Evaluation(severity_at_most(ratio, bands), metrics)


def screen(views: tuple[LotView, ...], config: ScreensConfig) -> ScreenOutput:
    settings = config.screens.perpetual_runner_up
    params = screen_params(settings, config)
    rule_version = config.rule_version(RULE_VERSION)
    not_computed: list[NotComputed] = []
    by_market: dict[Market, list[tuple[LotView, str]]] = {}
    for view in views:
        inputs = _inputs(view)
        if isinstance(inputs, str):
            not_computed.append(NotComputed(FLAG_CODE, view.trade_id, inputs, rule_version))
            continue
        market, winner = inputs
        by_market.setdefault(market, []).append((view, winner))

    market_size: dict[Market, tuple[int, int]] = {}
    firm_lots: defaultdict[str, Counter[Market]] = defaultdict(Counter)
    firm_wins: defaultdict[str, Counter[Market]] = defaultdict(Counter)
    participated: defaultdict[str, list[str]] = defaultdict(list)
    losses: defaultdict[str, list[tuple[str, str]]] = defaultdict(list)
    for market, items in by_market.items():
        if len(items) < config.screens.scope.min_market_lots:
            not_computed += [
                NotComputed(FLAG_CODE, v.trade_id, "market_too_small", rule_version)
                for v, _ in items
            ]
            continue
        market_size[market] = (len(items), sum(len(view.bids) for view, _ in items))
        for view, winner in items:
            for bid in view.bids:
                inn = bid.participant_inn
                firm_lots[inn][market] += 1
                participated[inn].append(view.trade_id)
                if inn == winner:
                    firm_wins[inn][market] += 1
                else:
                    losses[inn].append((view.trade_id, winner))

    flags: list[ScreenFlag] = []
    for firm in sorted(firm_lots):
        if sum(firm_lots[firm].values()) < settings.min_participations:
            continue
        markets: list[JsonValue] = [
            {
                **market.as_json(),
                "lots": market_size[market][0],
                "bids": market_size[market][1],
                "firm_lots": firm_lots[firm][market],
                "firm_wins": firm_wins[firm][market],
            }
            for market in sorted(firm_lots[firm])
        ]
        lost: list[JsonValue] = [
            {"trade_id": trade_id, "winner_inn": winner}
            for trade_id, winner in sorted(losses[firm], key=lambda item: trade_sort_key(item[0]))
        ]
        ids: list[str] = sorted(participated[firm], key=trade_sort_key)
        evidence: Evidence = {
            "flag_code": FLAG_CODE,
            "rule_version": rule_version,
            "lot_ids": list[JsonValue](ids),
            "facts": {"firm_inn": firm, "markets": markets, "losses": lost},
            "params": params,
        }
        flag = make_flag(FLAG_CODE, "firm", firm, evidence, evaluate(evidence))
        if flag is not None:
            flags.append(flag)
    return flags, not_computed
