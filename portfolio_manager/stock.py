"""Stock domain object and the price source it depends on.

A Stock does not know *where* its price comes from: it delegates to a
PriceProvider. That provider is the integration point for a real market-data
API. Tests and demos use InMemoryPriceProvider; production would plug in an
HTTP client exposing the same single method, with no change to Stock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

# Money and quantities use Decimal, never float: 0.1 + 0.2 != 0.3 in binary
# floating point, and rounding errors in a trading app end up as real money.
Number = Decimal | int | str


def as_decimal(value: Number) -> Decimal:
    """Convert user input to Decimal. Floats go through str() to avoid
    inheriting their binary representation (Decimal(0.1) != Decimal("0.1"))."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


class PriceProvider(Protocol):
    """Anything able to return the last available price for a ticker."""

    def get_last_price(self, ticker: str) -> Decimal: ...


class InMemoryPriceProvider:
    """Fixed prices held in memory. Meant for tests and demos."""

    def __init__(self, prices: dict[str, Number]) -> None:
        self._prices = {ticker: as_decimal(price) for ticker, price in prices.items()}

    def get_last_price(self, ticker: str) -> Decimal:
        try:
            return self._prices[ticker]
        except KeyError:
            raise LookupError(f"No price available for {ticker}") from None


@dataclass(frozen=True)
class Stock:
    """A tradable stock, identified by its ticker.

    The provider is excluded from equality: two Stock objects with the same
    ticker are the same stock regardless of where they get prices from.
    """

    ticker: str
    price_provider: PriceProvider = field(compare=False, repr=False)

    def current_price(self) -> Decimal:
        """Return the last available price. Invalid prices fail here, at the
        boundary, so the rebalance math can trust every price it receives."""
        price = self.price_provider.get_last_price(self.ticker)
        if price <= 0:
            raise ValueError(f"Invalid price for {self.ticker}: {price}")
        return price
