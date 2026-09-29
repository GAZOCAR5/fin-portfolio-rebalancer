"""Structured output of a rebalance: which orders to place and the expected result.

Pure data, no business logic. The plan is what a downstream system (an order
executor, an API response, a confirmation screen) would consume, so it is
immutable and serializable via to_dict().
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

WEIGHT_DISPLAY = Decimal("0.0001")


class Action(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class TradeOrder:
    ticker: str
    action: Action
    quantity: Decimal
    # Price the order was computed with. Kept for traceability: when executing,
    # it lets you tell how far the market moved since the plan was made.
    price: Decimal

    @property
    def value(self) -> Decimal:
        """Estimated amount traded, at the plan's price."""
        return self.quantity * self.price

    @property
    def cash_flow(self) -> Decimal:
        """Effect on cash: sales bring money in, purchases take it out."""
        return self.value if self.action is Action.SELL else -self.value

    def to_dict(self) -> dict[str, str]:
        return {
            "ticker": self.ticker,
            "action": self.action.value,
            "quantity": _fmt(self.quantity),
            "price": _fmt(self.price),
            "estimated_value": _fmt(self.value),
        }


@dataclass(frozen=True)
class RebalancePlan:
    total_value: Decimal
    # Sells first, then buys: in execution, sale proceeds fund the purchases.
    orders: tuple[TradeOrder, ...]
    cash_before: Decimal
    cash_after: Decimal
    # Weight of each stock over total value once every order is filled.
    weights_after: Mapping[str, Decimal]

    @property
    def sells(self) -> tuple[TradeOrder, ...]:
        return tuple(o for o in self.orders if o.action is Action.SELL)

    @property
    def buys(self) -> tuple[TradeOrder, ...]:
        return tuple(o for o in self.orders if o.action is Action.BUY)

    @property
    def is_empty(self) -> bool:
        return not self.orders

    @property
    def cash_weight_after(self) -> Decimal:
        """Share of the portfolio left in cash (e.g. 0.03 == 3%)."""
        return self.cash_after / self.total_value if self.total_value else Decimal(0)

    def to_dict(self) -> dict:
        # Decimals are serialized as strings so JSON consumers don't lose precision.
        return {
            "total_value": _fmt(self.total_value),
            "cash_before": _fmt(self.cash_before),
            "cash_after": _fmt(self.cash_after),
            "orders": [o.to_dict() for o in self.orders],
            "weights_after": {
                ticker: _fmt(weight.quantize(WEIGHT_DISPLAY))
                for ticker, weight in self.weights_after.items()
            },
            "cash_weight_after": _fmt(self.cash_weight_after.quantize(WEIGHT_DISPLAY)),
        }


def _fmt(value: Decimal) -> str:
    """Plain notation without trailing zeros: 4.400000 -> '4.4', 1E+1 -> '10'."""
    return format(value.normalize(), "f")
