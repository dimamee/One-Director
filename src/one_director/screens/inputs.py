"""Read-only views of the ``lots`` and ``bids`` rows the screens read.

The shared pydantic models ``Lot`` / ``Bid`` belong to 01-data
(``one_director.data.schema``, D-7). The screens accept any object with these
attributes (structural typing), so those models -- built from
``specs/schema.md`` -- fit without adapters and the tables are not redefined
here. Only the fields the screens actually read are listed.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Protocol


class LotLike(Protocol):
    """Fields of ``lots`` used by the screens."""

    @property
    def trade_id(self) -> str: ...
    @property
    def procedure_type(self) -> str | None: ...
    @property
    def category(self) -> str | None: ...
    @property
    def customer_inn(self) -> str: ...
    @property
    def start_cost(self) -> Decimal: ...
    @property
    def deal_cost(self) -> Decimal | None: ...
    @property
    def currency(self) -> str: ...
    @property
    def deal_date(self) -> date | None: ...
    @property
    def region(self) -> str | None: ...
    @property
    def participants_count(self) -> int | None: ...
    @property
    def status(self) -> str: ...


class BidLike(Protocol):
    """Fields of ``bids`` used by the screens (``participant_name`` is never read)."""

    @property
    def trade_id(self) -> str: ...
    @property
    def participant_inn(self) -> str: ...
    @property
    def is_winner(self) -> bool: ...
    @property
    def bid_price(self) -> Decimal | None: ...
