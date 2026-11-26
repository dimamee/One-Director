"""Shared helpers for ``tests/screens/``: test configuration and synthetic worlds.

``TEST_CONFIG`` is a *test* configuration (values tuned on the synthetic
generator), not the demo file and not production thresholds.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from tests.screens.synthetic import MarketBuilder, MarketRef, SyntheticData

from one_director.screens import ScreenFlag, ScreenResult, ScreensConfig, run_structural_screens

TEST_CONFIG: dict[str, Any] = {
    "mode": "demo",
    "price_screens_enabled": True,
    "screens": {
        "scope": {
            "procedure_types": ["best_offer", "tender", "auction"],
            "statuses": ["completed"],
            "min_market_lots": 10,
        },
        "low_discount": {
            "min_gap_to_market_median": "0.03",
            "max_discount": {"low": "0.02", "medium": "0.01", "high": "0.005"},
        },
        "single_bidder": {
            "min_gap_to_market_median": {"low": "1", "medium": "2", "high": "3"},
        },
        "few_bidders": {
            "max_participants": 2,
            "min_gap_to_market_median": {"low": "2", "medium": "3", "high": "4"},
        },
        "co_bidding": {
            "min_joint_lots": 5,
            "min_overlap_share": "0.6",
            "min_lift": {"low": "2", "medium": "3", "high": "4"},
        },
        "winner_rotation": {
            "min_scope_lots": 6,
            "min_wins_per_member": 3,
            "max_group_size": 4,
            "min_balance": "0.5",
            "min_switch_rate": "0.6",
            "min_lift_to_market_share": "3",
            "min_group_win_share": {"low": "0.7", "medium": "0.8", "high": "0.9"},
        },
        "perpetual_runner_up": {
            "min_participations": 8,
            "max_win_rate": "0.1",
            "min_top_winner_share": "0.6",
            "max_ratio_to_expected_wins": {"low": "0.3", "medium": "0.15", "high": "0.05"},
        },
        "cover_bid_pattern": {
            "min_losers": 3,
            "min_markup": "0.01",
            "min_gap_to_market_median": "0.2",
            "max_gap_cv": {"low": "0.03", "medium": "0.01", "high": "0.005"},
        },
    },
}

MARKETS = (
    ("tashkent_city", "construction"),
    ("samarkand", "food"),
    ("fergana", "it_services"),
)


def config_with(*changes: tuple[str, Any]) -> ScreensConfig:
    """``TEST_CONFIG`` with dotted-path overrides, e.g. ``("screens.scope.min_market_lots", 3)``."""
    data = copy.deepcopy(TEST_CONFIG)
    for path, value in changes:
        node = data
        *parents, leaf = path.split(".")
        for key in parents:
            node = node[key]
        node[leaf] = value
    return ScreensConfig.model_validate(data)


def base_config() -> ScreensConfig:
    return ScreensConfig.model_validate(TEST_CONFIG)


def clean_world(seed: int) -> tuple[MarketBuilder, list[MarketRef]]:
    builder = MarketBuilder(seed)
    markets = [builder.clean_market(region, category) for region, category in MARKETS]
    return builder, markets


def injected_world(seed: int = 7, *, with_bid_prices: bool = True) -> SyntheticData:
    """Three clean markets plus every structural scheme, spread over the markets."""
    builder, (first, second, third) = clean_world(seed)
    builder.inject_low_discount(first)
    builder.inject_single_bidder(first)
    builder.inject_few_bidders(first)
    builder.inject_co_bidding_pair(second)
    builder.inject_winner_rotation(second)
    builder.inject_perpetual_runner_up(third)
    builder.inject_cover_bids(third)
    return builder.build(with_bid_prices=with_bid_prices)


def run(data: SyntheticData, config: ScreensConfig | None = None) -> ScreenResult:
    return run_structural_screens(data.lots, data.bids, config or base_config())


def flagged(result: ScreenResult, flag_code: str) -> set[str]:
    return {flag.object_id for flag in result.flags if flag.flag_code == flag_code}


def by_code(result: ScreenResult, flag_code: str) -> list[ScreenFlag]:
    return [flag for flag in result.flags if flag.flag_code == flag_code]


def json_round_trip(value: Any) -> Any:
    """What a consumer reads back from the ``flags.evidence`` JSON column."""
    return json.loads(json.dumps(value, ensure_ascii=False))
