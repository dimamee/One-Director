"""``evidence`` alone is enough to recompute a flag (specs/agents/03-screens.md)."""

from __future__ import annotations

import copy
import json
import re
from decimal import Decimal
from typing import Any

import pytest
from tests.screens.helpers import base_config, injected_world, json_round_trip, run

from one_director.screens import EvidenceError, recompute
from one_director.screens.synthetic import MarketBuilder

# Band parameter of each screen and a value that no real observation can reach.
UNREACHABLE_BANDS = {
    "LOW_DISCOUNT": ("max_discount", "-1"),
    "SINGLE_BIDDER": ("min_gap_to_market_median", "1000000"),
    "FEW_BIDDERS": ("min_gap_to_market_median", "1000000"),
    "CO_BIDDING": ("min_lift", "1000000"),
    "WINNER_ROTATION": ("min_group_win_share", "2"),
    "PERPETUAL_RUNNER_UP": ("max_ratio_to_expected_wins", "-1"),
    "COVER_BID_PATTERN": ("max_gap_cv", "-1"),
}


@pytest.fixture(scope="module")
def all_flags() -> list[Any]:
    result = run(injected_world())
    assert result.flags
    return list(result.flags)


def walk(value: Any) -> list[Any]:
    """Every scalar inside a JSON tree."""
    if isinstance(value, dict):
        return [leaf for item in value.values() for leaf in walk(item)]
    if isinstance(value, list):
        return [leaf for item in value for leaf in walk(item)]
    return [value]


def test_every_flag_is_recomputed_from_its_evidence(all_flags: list[Any]) -> None:
    for flag in all_flags:
        evidence = json_round_trip(flag.evidence)
        evaluation = recompute(evidence)
        assert evaluation.severity == flag.severity, flag.flag_code
        assert evaluation.metrics == evidence["metrics"], flag.flag_code


def test_evidence_envelope(all_flags: list[Any]) -> None:
    lot_ids = {lot.trade_id for lot in injected_world().lots}
    for flag in all_flags:
        evidence = flag.evidence
        assert evidence["flag_code"] == flag.flag_code
        assert evidence["rule_version"] == flag.rule_version
        assert evidence["lot_ids"]
        assert set(evidence["lot_ids"]) <= lot_ids
        assert {"facts", "params", "metrics"} <= set(evidence)


def test_evidence_is_exact_json_without_floats(all_flags: list[Any]) -> None:
    for flag in all_flags:
        leaves = walk(flag.evidence)
        assert not any(isinstance(leaf, float) for leaf in leaves)
        json.dumps(flag.evidence)


@pytest.mark.parametrize("flag_code", sorted(UNREACHABLE_BANDS))
def test_recompute_follows_the_params_in_evidence(all_flags: list[Any], flag_code: str) -> None:
    key, extreme = UNREACHABLE_BANDS[flag_code]
    flag = next(flag for flag in all_flags if flag.flag_code == flag_code)
    evidence = json_round_trip(flag.evidence)
    evidence["params"][key] = {"low": extreme, "medium": extreme, "high": extreme}
    assert recompute(evidence).severity is None


def test_recompute_follows_the_facts_in_evidence(all_flags: list[Any]) -> None:
    low_discount = next(flag for flag in all_flags if flag.flag_code == "LOW_DISCOUNT")
    evidence = json_round_trip(low_discount.evidence)
    start = Decimal(evidence["facts"]["start_cost"])
    evidence["facts"]["deal_cost"] = str(start / 2)
    assert recompute(evidence).severity is None

    cover = next(flag for flag in all_flags if flag.flag_code == "COVER_BID_PATTERN")
    evidence = json_round_trip(cover.evidence)
    last = evidence["facts"]["bids"][-1]
    last["bid_price"] = str(Decimal(last["bid_price"]) * 3)
    assert recompute(evidence).severity is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda e: e.pop("facts"),
        lambda e: e.pop("flag_code"),
        lambda e: e.__setitem__("flag_code", "NOT_A_SCREEN"),
        lambda e: e["params"].__setitem__(next(iter(e["params"])), 0.5),
        lambda e: e["lot_ids"].append("999999999"),
    ],
)
def test_malformed_evidence_is_rejected(all_flags: list[Any], mutate: Any) -> None:
    for flag in all_flags:
        evidence = copy.deepcopy(json_round_trip(flag.evidence))
        mutate(evidence)
        with pytest.raises(EvidenceError):
            recompute(evidence)


def test_evidence_contains_no_names_or_free_text() -> None:
    """Names of participants (an ИП or an entity of unknown type is a person),
    customer names and lot titles never reach evidence; firms are referenced
    by INN only and the API masks them (specs/api-contract.md)."""
    builder = MarketBuilder(5)
    market = builder.clean_market("andijan", "construction")
    builder.inject_single_bidder(market)
    builder.inject_cover_bids(market)
    data = builder.build()
    renamed = [
        type(bid)(**{**_fields(bid), "participant_name": "ИП Тестов Тест Тестович-1"})
        for bid in data.bids
    ]
    result = run(type(data)(lots=data.lots, bids=tuple(renamed), truth=data.truth))
    assert result.flags
    text = json.dumps([flag.evidence for flag in result.flags], ensure_ascii=False)
    assert "Тест" not in text
    assert "example.invalid" not in text


def _fields(obj: Any) -> dict[str, Any]:
    return {name: getattr(obj, name) for name in obj.__dataclass_fields__}


# -- D-46: INNs only under *_inn / *_inns, thresholds only under params ----------

ENVELOPE = {"flag_code", "rule_version", "lot_ids", "facts", "params", "metrics"}
INN = re.compile(r"[0-9]{9}")
SECTIONS = {
    "LOW_DISCOUNT": "low_discount",
    "SINGLE_BIDDER": "single_bidder",
    "FEW_BIDDERS": "few_bidders",
    "CO_BIDDING": "co_bidding",
    "WINNER_ROTATION": "winner_rotation",
    "PERPETUAL_RUNNER_UP": "perpetual_runner_up",
    "COVER_BID_PATTERN": "cover_bid_pattern",
}


def keyed_leaves(value: Any, key: str = "") -> list[tuple[str, Any]]:
    """(nearest key, scalar) for every scalar of a JSON tree; list items keep the list's key."""
    if isinstance(value, dict):
        return [leaf for k, item in value.items() for leaf in keyed_leaves(item, k)]
    if isinstance(value, list):
        return [leaf for item in value for leaf in keyed_leaves(item, key)]
    return [(key, value)]


def test_inns_appear_only_under_inn_keys(all_flags: list[Any]) -> None:
    data = injected_world()
    inns = {lot.customer_inn for lot in data.lots} | {bid.participant_inn for bid in data.bids}
    seen_keys = set()
    for flag in all_flags:
        for key, leaf in keyed_leaves(flag.evidence):
            if key.endswith(("_inn", "_inns")):
                seen_keys.add(key)
                assert leaf is None or (isinstance(leaf, str) and INN.fullmatch(leaf)), key
            else:
                assert leaf not in inns, (flag.flag_code, key)
    assert seen_keys >= {
        "firm_inn",
        "firm_inns",
        "group_inns",
        "customer_inn",
        "winner_inn",
        "participant_inn",
    }


def test_thresholds_are_only_under_params(all_flags: list[Any]) -> None:
    config = base_config()
    sections = config.screens.model_dump(mode="json")
    for flag in all_flags:
        evidence = flag.evidence
        assert set(evidence) == ENVELOPE, flag.flag_code
        expected = {
            **sections[SECTIONS[flag.flag_code]],
            "min_market_lots": config.screens.scope.min_market_lots,
        }
        assert evidence["params"] == expected, flag.flag_code


def test_market_size_gate_is_recomputed_from_params(all_flags: list[Any]) -> None:
    for flag in all_flags:
        evidence = json_round_trip(flag.evidence)
        evidence["params"]["min_market_lots"] = 1_000_000
        with pytest.raises(EvidenceError, match="min_market_lots"):
            recompute(evidence)


# -- 09 review R2: out-of-range arithmetic is malformed evidence -----------------


def _set(path: str, value: Any) -> Any:
    def mutate(evidence: dict[str, Any]) -> None:
        *parents, leaf = path.split(".")
        node: Any = evidence
        for key in parents:
            node = node[int(key)] if isinstance(node, list) else node[key]
        node[leaf] = value

    return mutate


@pytest.mark.parametrize(
    ("flag_code", "mutations"),
    [
        # The example of the review: no InvalidOperation may escape.
        ("LOW_DISCOUNT", [_set("facts.start_cost", "1e-28"), _set("facts.deal_cost", "1e20")]),
        ("LOW_DISCOUNT", [_set("facts.market.median_discount", "1e30")]),
        ("SINGLE_BIDDER", [_set("facts.market.median_participants", "1e30")]),
        ("CO_BIDDING", [_set("facts.markets.0.lots", 10**30)]),
        ("WINNER_ROTATION", [_set("facts.market.lots", 10**40)]),
        ("COVER_BID_PATTERN", [_set("facts.market.median_gap_cv", "1e30")]),
    ],
)
def test_out_of_range_values_raise_evidence_error(
    all_flags: list[Any], flag_code: str, mutations: list[Any]
) -> None:
    flag = next(flag for flag in all_flags if flag.flag_code == flag_code)
    evidence = json_round_trip(flag.evidence)
    for mutate in mutations:
        mutate(evidence)
    with pytest.raises(EvidenceError):
        recompute(evidence)
