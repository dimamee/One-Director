"""Thresholds and severity bands of the screens -- configuration only, never code.

Format (D-47): TOML read with ``tomllib``, shared by 03-screens, 04-graph and
05-model. Only the top-level ``mode`` (``"demo"`` / ``"production"``),
``price_screens_enabled`` (D-6) and the ``[screens]`` table are read; the other
tables (``[graph]``, ``[model]``) are ignored.

* Production values: a file outside the repository. The pipeline takes its path
  from ``RISK_CONFIG_PATH`` (``security.settings``) and passes it to
  :func:`load_config`; this module does not read the environment.
  ``load_config`` has no default and no fallback: without a path it raises
  :class:`ConfigError`, so a production run without ``RISK_CONFIG_PATH`` does
  not start (D-47).
* Demo values: ``demo_config.toml`` in this package, marked
  "DEMO — не для продакшна" (``docs/model-card.md`` §8). They are used only
  when the caller asks for them by name, :func:`load_demo_config`.

Every flag records the configuration it was decided with: ``rule_version`` is
``<code version>+<mode>.<digest prefix>`` -- the digest of the part of the file
this module reads (so edits of ``[graph]`` / ``[model]`` or of comments do not
change the screens' flags) -- and the applied values are in ``evidence.params``.
"""

from __future__ import annotations

import hashlib
import tomllib
from decimal import Decimal
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, model_validator

from one_director.screens.results import canonical_json

DIGEST_PREFIX_LEN: Final = 8
RULE_VERSION_MAX_LEN: Final = 32  # flags.rule_version is VARCHAR(32)

DEMO_CONFIG_RESOURCE: Final = "demo_config.toml"
_OWN_KEYS: Final = ("mode", "price_screens_enabled", "screens")

ProcedureType = Literal["best_offer", "tender", "auction", "other"]
LotStatus = Literal["completed", "cancelled", "failed", "other"]

Finite = Annotated[Decimal, Field(allow_inf_nan=False)]
NonNegative = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
Ratio = Annotated[Decimal, Field(ge=0, le=1, allow_inf_nan=False)]
PositiveInt = Annotated[int, Field(ge=1)]


class ConfigError(ValueError):
    """The configuration file is unreadable or invalid (values are not echoed)."""


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AtMostBands(_Section):
    """Severity grows as the value gets smaller: ``value <= high`` -> ``high``."""

    low: Finite
    medium: Finite
    high: Finite

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not self.low >= self.medium >= self.high:
            raise ValueError("bands must satisfy low >= medium >= high")
        return self


class AtLeastBands(_Section):
    """Severity grows as the value gets larger: ``value >= high`` -> ``high``."""

    low: Finite
    medium: Finite
    high: Finite

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not self.low <= self.medium <= self.high:
            raise ValueError("bands must satisfy low <= medium <= high")
        return self


class ScopeConfig(_Section):
    """Which lots are screened at all, and the minimum market size for normalisation."""

    procedure_types: tuple[ProcedureType, ...] = Field(min_length=1)
    statuses: tuple[LotStatus, ...] = Field(min_length=1)
    min_market_lots: PositiveInt


class LowDiscountConfig(_Section):
    min_gap_to_market_median: NonNegative
    max_discount: AtMostBands


class SingleBidderConfig(_Section):
    min_gap_to_market_median: AtLeastBands


class FewBiddersConfig(_Section):
    max_participants: int = Field(ge=2)
    min_gap_to_market_median: AtLeastBands


class CoBiddingConfig(_Section):
    min_joint_lots: int = Field(ge=2)
    min_overlap_share: Ratio
    min_lift: AtLeastBands


class WinnerRotationConfig(_Section):
    min_scope_lots: int = Field(ge=2)
    min_wins_per_member: PositiveInt
    max_group_size: int = Field(ge=2)
    min_balance: Ratio
    min_switch_rate: Ratio
    min_lift_to_market_share: NonNegative
    min_group_win_share: AtLeastBands


class PerpetualRunnerUpConfig(_Section):
    min_participations: PositiveInt
    max_win_rate: Ratio
    min_top_winner_share: Ratio
    max_ratio_to_expected_wins: AtMostBands


class CoverBidPatternConfig(_Section):
    min_losers: int = Field(ge=2)
    min_markup: NonNegative
    min_gap_to_market_median: NonNegative
    max_gap_cv: AtMostBands


class ScreensSection(_Section):
    scope: ScopeConfig
    low_discount: LowDiscountConfig
    single_bidder: SingleBidderConfig
    few_bidders: FewBiddersConfig
    co_bidding: CoBiddingConfig
    winner_rotation: WinnerRotationConfig
    perpetual_runner_up: PerpetualRunnerUpConfig
    cover_bid_pattern: CoverBidPatternConfig


class ScreensConfig(_Section):
    """The part of the risk configuration that belongs to the screens."""

    mode: Literal["demo", "production"]
    price_screens_enabled: StrictBool
    screens: ScreensSection

    def digest(self) -> str:
        """SHA-256 of the canonical JSON of this configuration."""
        payload = canonical_json(self.model_dump(mode="json"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def rule_version(self, code_version: str) -> str:
        """``flags.rule_version``: code version + mode + configuration digest prefix."""
        version = f"{code_version}+{self.mode}.{self.digest()[:DIGEST_PREFIX_LEN]}"
        if len(version) > RULE_VERSION_MAX_LEN:
            raise ValueError("rule_version does not fit flags.rule_version")
        return version


def load_config(path: Path) -> ScreensConfig:
    """Read the risk configuration at ``path`` (``RISK_CONFIG_PATH``).

    There is no silent fallback to the demo values (D-47): ``path=None`` raises
    :class:`ConfigError`; a demo run calls :func:`load_demo_config` explicitly.
    """
    if path is None:
        raise ConfigError(
            "RISK_CONFIG_PATH is not set: no risk configuration to run with "
            "(a demo run loads the demo file explicitly)"
        )
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # The location of the production file is not echoed either.
        raise ConfigError("risk configuration file cannot be read") from None
    return _parse(text)


def load_demo_config() -> ScreensConfig:
    """The demo configuration of this package ("DEMO — не для продакшна")."""
    resource = files("one_director.screens").joinpath(DEMO_CONFIG_RESOURCE)
    return _parse(resource.read_text(encoding="utf-8"))


def _parse(text: str) -> ScreensConfig:
    try:
        data = tomllib.loads(text, parse_float=Decimal)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError("risk configuration is not valid TOML") from exc
    try:
        return ScreensConfig.model_validate({key: data[key] for key in _OWN_KEYS if key in data})
    except ValidationError as exc:
        # Report where and what kind of error, never the (possibly production) values.
        problems = sorted(
            {
                ".".join(str(part) for part in error["loc"]) + f" ({error['type']})"
                for error in exc.errors()
            }
        )
        raise ConfigError("invalid screens configuration: " + ", ".join(problems)) from None
