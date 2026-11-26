"""Synthetic procurement markets with injected bid-rigging *indicator* schemes.

Test-only stub for the ``lots`` / ``bids`` tables until 01-data ships
``one_director.data.schema`` (D-7). Field names and types follow
``specs/schema.md`` exactly (``test_synthetic.py`` checks this against the
spec), including the technical fields ``collected_at`` and ``source``.

Everything here is fictional: INNs are ``000`` + 6 digits
(``tests/fixtures/README.md``), names are ``ООО Тест-N``, links point to
``example.invalid``. Category codes are placeholders until the category
whitelist is approved (D-8).

A "clean" market is a competitive market: 3..7 independent bidders per lot,
discounts of 5..25 % from the start cost, the lowest bid wins. Each
``inject_*`` method adds new lots that carry one scheme and records the
objects a screen is expected to flag in ``truth`` (``flag_code`` -> set of
``flags.object_id``).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

COLLECTED_AT = datetime(2026, 11, 1, tzinfo=UTC)
CENT = Decimal("0.01")
BASIS_POINTS = Decimal(10_000)
COMPETITIVE_PROCEDURES = ("tender", "best_offer", "auction")
FIRST_DAY = date(2025, 1, 1)


@dataclass(frozen=True, slots=True)
class SyntheticLot:
    """One row of ``lots`` (``specs/schema.md``)."""

    trade_id: str
    display_no: str | None
    title: str
    procedure_type: str | None
    category: str | None
    customer_inn: str
    customer_name: str | None
    start_cost: Decimal
    deal_cost: Decimal | None
    currency: str
    deal_date: date | None
    region: str | None
    participants_count: int | None
    status: str
    source_url: str
    collected_at: datetime
    source: str


@dataclass(frozen=True, slots=True)
class SyntheticBid:
    """One row of ``bids`` (``specs/schema.md``)."""

    trade_id: str
    participant_inn: str
    participant_name: str | None
    is_winner: bool
    bid_price: Decimal | None
    submitted_at: datetime | None
    participant_status: str | None
    collected_at: datetime
    source: str


@dataclass(frozen=True, slots=True)
class MarketRef:
    """A market (region x category) with its pool of firms and customers."""

    region: str
    category: str
    firms: tuple[str, ...]
    customers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SyntheticData:
    lots: tuple[SyntheticLot, ...]
    bids: tuple[SyntheticBid, ...]
    truth: dict[str, frozenset[str]]


def pair_id(first: str, second: str) -> str:
    """``flags.object_id`` of a pair: ``inn1:inn2``, sorted."""
    low, high = sorted((first, second))
    return f"{low}:{high}"


class MarketBuilder:
    """Deterministic builder of synthetic markets (same seed -> same data)."""

    def __init__(self, seed: int) -> None:
        # Synthetic test data, not a security context.
        self._rng = random.Random(seed)  # noqa: S311
        self._next_party = 1
        self._next_trade = 600_000
        self._lots: list[SyntheticLot] = []
        self._bids: list[SyntheticBid] = []
        self._truth: dict[str, set[str]] = {}

    # -- identifiers -----------------------------------------------------

    def new_inn(self) -> str:
        inn = f"000{self._next_party:06d}"
        self._next_party += 1
        return inn

    def _new_trade_id(self) -> str:
        trade_id = str(self._next_trade)
        self._next_trade += 1
        return trade_id

    def _expect(self, flag_code: str, object_ids: list[str]) -> None:
        self._truth.setdefault(flag_code, set()).update(object_ids)

    # -- prices ------------------------------------------------------------

    def _start_cost(self) -> Decimal:
        return Decimal(self._rng.randint(10_000, 500_000) * 1_000)

    @staticmethod
    def _price(start_cost: Decimal, discount_bp: int) -> Decimal:
        return (start_cost * (1 - Decimal(discount_bp) / BASIS_POINTS)).quantize(CENT)

    def _distinct_discounts(self, count: int, low_bp: int, high_bp: int) -> list[int]:
        """``count`` distinct discounts in basis points, largest first (= lowest price)."""
        return sorted(self._rng.sample(range(low_bp, high_bp + 1), count), reverse=True)

    def _random_date(self) -> date:
        return FIRST_DAY + timedelta(days=self._rng.randint(0, 539))

    # -- low-level lot writer ----------------------------------------------

    def add_lot(
        self,
        market: MarketRef,
        *,
        customer: str,
        start_cost: Decimal,
        bids: list[tuple[str, Decimal | None]],
        winner: str | None,
        deal_date: date | None,
        participants_count: int | None = None,
        procedure_type: str | None = None,
        status: str = "completed",
        deal_cost: Decimal | None = None,
        region: str | None = None,
        category: str | None = None,
    ) -> str:
        """Append one lot and its bids; returns ``trade_id``.

        ``participants_count`` defaults to the number of bids, ``deal_cost`` to
        the winner's price, ``region``/``category`` to the market's.
        """
        trade_id = self._new_trade_id()
        prices = dict(bids)
        if deal_cost is None and winner is not None:
            deal_cost = prices[winner]
        self._lots.append(
            SyntheticLot(
                trade_id=trade_id,
                display_no=f"T-{trade_id}",
                title=f"Тестовый лот {trade_id}",
                procedure_type=(
                    procedure_type
                    if procedure_type is not None
                    else self._rng.choice(COMPETITIVE_PROCEDURES)
                ),
                category=category if category is not None else market.category,
                customer_inn=customer,
                customer_name=f"Заказчик Тест-{customer[-3:]}",
                start_cost=start_cost,
                deal_cost=deal_cost,
                currency="UZS",
                deal_date=deal_date,
                region=region if region is not None else market.region,
                participants_count=len(bids) if participants_count is None else participants_count,
                status=status,
                source_url=f"https://example.invalid/lot/{trade_id}",
                collected_at=COLLECTED_AT,
                source="etender",
            )
        )
        for inn, price in bids:
            self._bids.append(
                SyntheticBid(
                    trade_id=trade_id,
                    participant_inn=inn,
                    participant_name=f"ООО Тест-{inn[-4:]}",
                    is_winner=inn == winner,
                    bid_price=price,
                    submitted_at=None,
                    participant_status=None,
                    collected_at=COLLECTED_AT,
                    source="etender",
                )
            )
        return trade_id

    def _competitive_lot(
        self,
        market: MarketRef,
        participants: list[str],
        *,
        customer: str | None = None,
        deal_date: date | None = None,
        discount_bp: tuple[int, int] = (500, 2_500),
    ) -> str:
        """Independent bids; the lowest price wins."""
        start_cost = self._start_cost()
        discounts = self._distinct_discounts(len(participants), *discount_bp)
        shuffled = self._rng.sample(participants, len(participants))
        bids = [
            (inn, self._price(start_cost, bp)) for inn, bp in zip(shuffled, discounts, strict=True)
        ]
        return self.add_lot(
            market,
            customer=customer if customer is not None else self._rng.choice(market.customers),
            start_cost=start_cost,
            bids=bids,
            winner=bids[0][0],
            deal_date=deal_date if deal_date is not None else self._random_date(),
        )

    # -- markets -------------------------------------------------------------

    def clean_market(
        self,
        region: str,
        category: str,
        *,
        lots: int = 60,
        firms: int = 12,
        customers: int = 4,
        participants: tuple[int, int] = (3, 7),
        discount_bp: tuple[int, int] = (500, 2_500),
    ) -> MarketRef:
        """A competitive market without injected schemes."""
        market = MarketRef(
            region=region,
            category=category,
            firms=tuple(self.new_inn() for _ in range(firms)),
            customers=tuple(self.new_inn() for _ in range(customers)),
        )
        for _ in range(lots):
            count = self._rng.randint(*participants)
            self._competitive_lot(
                market, self._rng.sample(market.firms, count), discount_bp=discount_bp
            )
        return market

    # -- injected schemes ----------------------------------------------------

    def inject_low_discount(self, market: MarketRef, count: int = 3) -> list[str]:
        """Deal price within 0.1..0.4 % of the start cost; losers even closer to it."""
        trade_ids = []
        for _ in range(count):
            start_cost = self._start_cost()
            participants = self._rng.sample(market.firms, self._rng.randint(3, 5))
            winner_bp = self._rng.randint(10, 40)
            loser_bps = self._rng.sample(range(winner_bp), len(participants) - 1)
            bids = [(participants[0], self._price(start_cost, winner_bp))]
            bids += [
                (inn, self._price(start_cost, bp))
                for inn, bp in zip(participants[1:], loser_bps, strict=True)
            ]
            trade_ids.append(
                self.add_lot(
                    market,
                    customer=self._rng.choice(market.customers),
                    start_cost=start_cost,
                    bids=bids,
                    winner=participants[0],
                    deal_date=self._random_date(),
                )
            )
        self._expect("LOW_DISCOUNT", trade_ids)
        return trade_ids

    def inject_single_bidder(self, market: MarketRef, count: int = 3) -> list[str]:
        trade_ids = [
            self._competitive_lot(market, self._rng.sample(market.firms, 1)) for _ in range(count)
        ]
        self._expect("SINGLE_BIDDER", trade_ids)
        return trade_ids

    def inject_few_bidders(self, market: MarketRef, count: int = 3) -> list[str]:
        trade_ids = [
            self._competitive_lot(market, self._rng.sample(market.firms, 2)) for _ in range(count)
        ]
        self._expect("FEW_BIDDERS", trade_ids)
        return trade_ids

    def inject_co_bidding_pair(self, market: MarketRef, joint_lots: int = 12) -> str:
        """Two new firms that always bid together, with 2..4 ordinary bidders."""
        first, second = self.new_inn(), self.new_inn()
        for _ in range(joint_lots):
            fillers = self._rng.sample(market.firms, self._rng.randint(2, 4))
            self._competitive_lot(market, [first, second, *fillers])
        pair = pair_id(first, second)
        self._expect("CO_BIDDING", [pair])
        return pair

    def inject_winner_rotation(
        self, market: MarketRef, group_size: int = 3, lots: int = 12
    ) -> list[str]:
        """A new customer whose lots are won in turn by a group of new firms."""
        group = [self.new_inn() for _ in range(group_size)]
        customer = self.new_inn()
        first_day = self._random_date()
        for index in range(lots):
            fillers = self._rng.sample(market.firms, self._rng.randint(2, 4))
            start_cost = self._start_cost()
            discounts = self._distinct_discounts(1 + len(fillers), 500, 2_500)
            participants = [group[index % group_size], *fillers]
            bids = [
                (inn, self._price(start_cost, bp))
                for inn, bp in zip(participants, discounts, strict=True)
            ]
            self.add_lot(
                market,
                customer=customer,
                start_cost=start_cost,
                bids=bids,
                winner=participants[0],
                deal_date=first_day + timedelta(days=20 * index),
            )
        self._expect("WINNER_ROTATION", group)
        return group

    def inject_perpetual_runner_up(self, market: MarketRef, lots: int = 15) -> str:
        """A new firm that always bids and always loses to the same new firm.

        Bidding together in every lot is also co-bidding, so the pair is
        expected in ``CO_BIDDING`` as well.
        """
        runner_up, winner = self.new_inn(), self.new_inn()
        for _ in range(lots):
            fillers = self._rng.sample(market.firms, self._rng.randint(1, 3))
            start_cost = self._start_cost()
            participants = [winner, runner_up, *fillers]
            discounts = self._distinct_discounts(len(participants), 500, 2_500)
            bids = [
                (inn, self._price(start_cost, bp))
                for inn, bp in zip(participants, discounts, strict=True)
            ]
            self.add_lot(
                market,
                customer=self._rng.choice(market.customers),
                start_cost=start_cost,
                bids=bids,
                winner=winner,
                deal_date=self._random_date(),
            )
        self._expect("PERPETUAL_RUNNER_UP", [runner_up])
        self._expect("CO_BIDDING", [pair_id(runner_up, winner)])
        return runner_up

    def inject_cover_bids(
        self, market: MarketRef, count: int = 4, losers: int = 3, step_bp: int = 400
    ) -> list[str]:
        """Losing bids evenly spaced above the winner: +step, +2*step, ..."""
        trade_ids = []
        step = Decimal(step_bp) / BASIS_POINTS
        for _ in range(count):
            start_cost = self._start_cost()
            participants = self._rng.sample(market.firms, losers + 1)
            winner_price = self._price(start_cost, self._rng.randint(500, 2_000))
            bids = [(participants[0], winner_price)]
            bids += [
                (inn, (winner_price * (1 + step * rank)).quantize(CENT))
                for rank, inn in enumerate(participants[1:], start=1)
            ]
            trade_ids.append(
                self.add_lot(
                    market,
                    customer=self._rng.choice(market.customers),
                    start_cost=start_cost,
                    bids=bids,
                    winner=participants[0],
                    deal_date=self._random_date(),
                )
            )
        self._expect("COVER_BID_PATTERN", trade_ids)
        return trade_ids

    # -- output ----------------------------------------------------------------

    def build(self, *, with_bid_prices: bool = True) -> SyntheticData:
        """Freeze the data; ``with_bid_prices=False`` models scenario B (no bid prices)."""
        bids = tuple(
            bid
            if with_bid_prices
            else SyntheticBid(
                trade_id=bid.trade_id,
                participant_inn=bid.participant_inn,
                participant_name=bid.participant_name,
                is_winner=bid.is_winner,
                bid_price=None,
                submitted_at=bid.submitted_at,
                participant_status=bid.participant_status,
                collected_at=bid.collected_at,
                source=bid.source,
            )
            for bid in self._bids
        )
        return SyntheticData(
            lots=tuple(self._lots),
            bids=bids,
            truth={code: frozenset(ids) for code, ids in self._truth.items()},
        )
