"""Thresholds come from configuration: demo file in the module, production file by path."""

from __future__ import annotations

import re
from importlib.resources import files
from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.screens.helpers import (
    TEST_CONFIG,
    base_config,
    clean_world,
    config_with,
    flagged,
    injected_world,
    run,
)

from one_director.screens import ConfigError, ScreensConfig, load_config, load_demo_config

DEMO_FILE = files("one_director.screens").joinpath("demo_config.toml")

PRODUCTION_LIKE_FILE = """
# Shared risk configuration (RISK_CONFIG_PATH): other agents own other sections.
mode = "production"
price_screens_enabled = true

[graph]
intermediary_min_firms = 1

[model]
weights = { LOW_DISCOUNT = 1.0 }

[screens.scope]
procedure_types = ["tender"]
statuses = ["completed"]
min_market_lots = 10

[screens.low_discount]
min_gap_to_market_median = 0.03
max_discount = { low = 0.02, medium = 0.01, high = 0.005 }

[screens.single_bidder]
min_gap_to_market_median = { low = 1, medium = 2, high = 3 }

[screens.few_bidders]
max_participants = 2
min_gap_to_market_median = { low = 2, medium = 3, high = 4 }

[screens.co_bidding]
min_joint_lots = 5
min_overlap_share = 0.6
min_lift = { low = 2, medium = 3, high = 4 }

[screens.winner_rotation]
min_scope_lots = 6
min_wins_per_member = 3
max_group_size = 4
min_balance = 0.5
min_switch_rate = 0.6
min_lift_to_market_share = 3
min_group_win_share = { low = 0.7, medium = 0.8, high = 0.9 }

[screens.perpetual_runner_up]
min_participations = 8
max_win_rate = 0.1
min_top_winner_share = 0.6
max_ratio_to_expected_wins = { low = 0.3, medium = 0.15, high = 0.05 }

[screens.cover_bid_pattern]
min_losers = 3
min_markup = 0.01
min_gap_to_market_median = 0.2
max_gap_cv = { low = 0.03, medium = 0.01, high = 0.005 }
"""


def test_demo_config_is_marked_and_valid() -> None:
    text = DEMO_FILE.read_text(encoding="utf-8")
    assert "DEMO — не для продакшна" in text
    config = load_demo_config()
    assert config.mode == "demo"
    # D-6: the price block is off in the demo file (scenario B).
    assert config.price_screens_enabled is False


def test_rule_version_marks_demo_values() -> None:
    version = load_demo_config().rule_version("1.0.0")
    assert re.fullmatch(r"1\.0\.0\+demo\.[0-9a-f]{8}", version)
    assert len(version) <= 32  # flags.rule_version is VARCHAR(32)


def test_production_file_is_read_by_path_and_foreign_sections_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "risk.toml"
    path.write_text(PRODUCTION_LIKE_FILE, encoding="utf-8")
    config = load_config(path)
    assert config.mode == "production"
    assert config.price_screens_enabled is True
    assert config.screens.scope.procedure_types == ("tender",)
    version = config.rule_version("1.0.0")
    assert re.fullmatch(r"1\.0\.0\+production\.[0-9a-f]{8}", version)
    assert len(version) <= 32


def test_digest_depends_on_every_threshold() -> None:
    base = base_config()
    changed = config_with(("screens.co_bidding.min_joint_lots", 6))
    assert base.digest() != changed.digest()
    assert base.rule_version("1.0.0") != changed.rule_version("1.0.0")
    assert base.digest() == base_config().digest()


@pytest.mark.parametrize(
    "change",
    [
        ("screens.low_discount.unexpected", 1),
        ("screens.low_discount.max_discount", {"low": "0.01", "medium": "0.02", "high": "0.03"}),
        ("screens.co_bidding.min_lift", {"low": "4", "medium": "3", "high": "2"}),
        ("screens.co_bidding.min_overlap_share", "1.5"),
        ("screens.scope.min_market_lots", 0),
        ("screens.scope.procedure_types", []),
        ("screens.scope.procedure_types", ["direct_contract"]),
        ("screens.cover_bid_pattern.min_losers", 1),
        ("mode", "test"),
    ],
)
def test_invalid_config_is_rejected(change: tuple[str, object]) -> None:
    with pytest.raises(ValidationError):
        config_with(change)


def test_missing_section_is_rejected() -> None:
    data = {**TEST_CONFIG, "screens": dict(TEST_CONFIG["screens"])}
    del data["screens"]["winner_rotation"]
    with pytest.raises(ValidationError):
        ScreensConfig.model_validate(data)


def test_thresholds_are_read_from_config() -> None:
    data = injected_world()
    assert flagged(run(data), "LOW_DISCOUNT") == data.truth["LOW_DISCOUNT"]
    stricter = config_with(
        (
            "screens.low_discount.max_discount",
            {"low": "0.0001", "medium": "0.0001", "high": "0.0001"},
        )
    )
    assert flagged(run(data, stricter), "LOW_DISCOUNT") == set()
    looser = config_with(
        ("screens.low_discount.max_discount", {"low": "0.30", "medium": "0.20", "high": "0.10"}),
        ("screens.low_discount.min_gap_to_market_median", "0"),
    )
    assert flagged(run(data, looser), "LOW_DISCOUNT") > data.truth["LOW_DISCOUNT"]


def test_demo_config_finds_structural_schemes_on_synthetic_data() -> None:
    """Smoke test: the shipped demo values work on the synthetic markets."""
    data = injected_world()
    result = run(data, load_demo_config())
    for flag_code, expected in data.truth.items():
        if flag_code == "COVER_BID_PATTERN":
            continue  # price block is disabled in the demo file
        assert flagged(result, flag_code) == expected, flag_code
    builder, _ = clean_world(1)
    assert run(builder.build(), load_demo_config()).flags == ()


def test_invalid_file_is_reported_without_its_values(tmp_path: Path) -> None:
    path = tmp_path / "risk.toml"
    path.write_text(
        PRODUCTION_LIKE_FILE.replace("min_overlap_share = 0.6", "min_overlap_share = 7.654321"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as excinfo:
        load_config(path)
    message = str(excinfo.value)
    assert "screens.co_bidding.min_overlap_share" in message
    assert "7.654321" not in message
    assert excinfo.value.__cause__ is None

    path.write_text("mode = [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_no_silent_fallback_to_the_demo_file() -> None:
    """D-47: without RISK_CONFIG_PATH a run does not start; demo values are chosen explicitly."""
    with pytest.raises(ConfigError, match="RISK_CONFIG_PATH") as excinfo:
        load_config(None)  # type: ignore[arg-type]
    assert excinfo.value.__cause__ is None
    assert load_demo_config().mode == "demo"


def test_unreadable_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot be read") as excinfo:
        load_config(tmp_path / "absent.toml")
    assert str(tmp_path) not in str(excinfo.value)
    with pytest.raises(ConfigError, match="cannot be read"):
        load_config(tmp_path)  # a directory
