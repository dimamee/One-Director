"""Every structural screen fires on its injected scheme and stays silent on clean markets."""

from __future__ import annotations

import pytest
from tests.screens.helpers import by_code, clean_world, flagged, injected_world, run

from one_director.screens import STRUCTURAL_FLAG_CODES

OBJECT_TYPES = {
    "LOW_DISCOUNT": "lot",
    "SINGLE_BIDDER": "lot",
    "FEW_BIDDERS": "lot",
    "COVER_BID_PATTERN": "lot",
    "CO_BIDDING": "pair",
    "WINNER_ROTATION": "firm",
    "PERPETUAL_RUNNER_UP": "firm",
}


def test_structural_codes_are_the_pass_one_screens() -> None:
    assert set(STRUCTURAL_FLAG_CODES) == set(OBJECT_TYPES)


@pytest.mark.parametrize("seed", [7, 11, 23])
@pytest.mark.parametrize("flag_code", sorted(OBJECT_TYPES))
def test_screen_finds_exactly_the_injected_objects(seed: int, flag_code: str) -> None:
    data = injected_world(seed)
    assert flagged(run(data), flag_code) == data.truth[flag_code]


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_clean_markets_raise_no_flags(seed: int) -> None:
    builder, _ = clean_world(seed)
    result = run(builder.build())
    assert result.flags == ()
    # Clean data is computable; the only gap is lots with too few losing bids to
    # judge their spacing (3-bidder lots under min_losers = 3).
    reasons = {(item.flag_code, item.reason) for item in result.not_computed}
    assert reasons <= {("COVER_BID_PATTERN", "too_few_bids")}


@pytest.mark.parametrize("flag_code", sorted(OBJECT_TYPES))
def test_object_type_and_id_format(flag_code: str) -> None:
    flags = by_code(run(injected_world()), flag_code)
    assert flags
    for flag in flags:
        assert flag.object_type == OBJECT_TYPES[flag_code]
        assert flag.severity in {"low", "medium", "high"}
        assert len(flag.object_id) <= 64
        if flag.object_type == "pair":
            first, second = flag.object_id.split(":")
            assert first < second


def test_rotation_flags_every_member_with_the_same_group_evidence() -> None:
    """D-44: a group-level screen writes one ``firm`` flag per member, same evidence."""
    data = injected_world()
    flags = by_code(run(data), "WINNER_ROTATION")
    group = sorted(data.truth["WINNER_ROTATION"])
    assert sorted(flag.object_id for flag in flags) == group
    assert {flag.object_type for flag in flags} == {"firm"}
    for flag in flags:
        assert flag.evidence["facts"]["group_inns"] == group
        assert flag.evidence == flags[0].evidence
        assert flag.severity == flags[0].severity
    assert len({flag.flag_id for flag in flags}) == len(flags)


def test_unambiguous_schemes_get_high_severity() -> None:
    result = run(injected_world())
    # Evenly spaced cover bids (gap CV ~ 0) and a runner-up that never wins.
    assert {flag.severity for flag in by_code(result, "COVER_BID_PATTERN")} == {"high"}
    assert {flag.severity for flag in by_code(result, "PERPETUAL_RUNNER_UP")} == {"high"}
    # A strict 3-firm rotation: all lots of the customer, perfectly balanced.
    assert {flag.severity for flag in by_code(result, "WINNER_ROTATION")} == {"high"}
