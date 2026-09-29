"""Portfolio: what we hold, what we aim for, and how to get from one to the other.

The rebalance math lives in `compute_rebalance`, a pure function over plain
mappings (no I/O, no Stock objects). `Portfolio.rebalance` is a thin wrapper
that takes a single price snapshot and delegates to it, which keeps the core
algorithm easy to test and reason about.

Fractional and whole-share modes share one algorithm; only the quantity
`step` changes (0.000001 vs 1). See `compute_rebalance` for the steps.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from .orders import Action, RebalancePlan, TradeOrder
from .stock import Number, Stock, as_decimal

ZERO = Decimal(0)
ONE = Decimal(1)

# Smallest tradable quantity in fractional mode. Brokers usually support 6 to 9
# decimals; 6 is a conservative default.
FRACTIONAL_STEP = Decimal("0.000001")
WHOLE_SHARE_STEP = ONE

# Allocation weights must add up to 100% within this tolerance.
WEIGHT_TOLERANCE = Decimal("0.000001")


@dataclass(frozen=True)
class Holding:
    """A position we currently own."""

    stock: Stock
    quantity: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantity", as_decimal(self.quantity))
        if self.quantity < 0:
            raise ValueError(f"Negative quantity for {self.stock.ticker}: {self.quantity}")


@dataclass(frozen=True)
class Allocation:
    """Target share of the portfolio's total value for one stock (0.4 == 40%)."""

    stock: Stock
    weight: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "weight", as_decimal(self.weight))
        if not ZERO <= self.weight <= ONE:
            raise ValueError(f"Weight for {self.stock.ticker} must be in [0, 1]: {self.weight}")


class Portfolio:
    def __init__(
        self,
        holdings: Iterable[Holding] = (),
        allocations: Iterable[Allocation] = (),
        cash: Number = ZERO,
    ) -> None:
        self.holdings = _index_by_ticker(holdings, "holding")
        self.allocations = _index_by_ticker(allocations, "allocation")
        self.cash = as_decimal(cash)
        if self.cash < 0:
            raise ValueError(f"Cash cannot be negative: {self.cash}")

        # Fail fast: an allocation that doesn't add up to 100% is a bug upstream,
        # not something to silently normalize.
        total_weight = sum((a.weight for a in self.allocations.values()), ZERO)
        if abs(total_weight - ONE) > WEIGHT_TOLERANCE:
            raise ValueError(f"Allocation weights must sum to 1, got {total_weight}")

    @property
    def stocks(self) -> dict[str, Stock]:
        """Every stock the portfolio holds or targets, by ticker."""
        stocks = {ticker: a.stock for ticker, a in self.allocations.items()}
        stocks.update({ticker: h.stock for ticker, h in self.holdings.items()})
        return stocks

    def price_snapshot(self) -> dict[str, Decimal]:
        """Query each stock's price exactly once.

        Every calculation in a rebalance must use the same prices. Asking the
        provider again halfway through could mix prices from different moments
        and produce an inconsistent plan.
        """
        return {ticker: stock.current_price() for ticker, stock in self.stocks.items()}

    def total_value(self, prices: Mapping[str, Decimal] | None = None) -> Decimal:
        prices = self.price_snapshot() if prices is None else prices
        return self.cash + sum(
            (h.quantity * prices[ticker] for ticker, h in self.holdings.items()), ZERO
        )

    def current_weights(self, prices: Mapping[str, Decimal] | None = None) -> dict[str, Decimal]:
        prices = self.price_snapshot() if prices is None else prices
        total = self.total_value(prices)
        return {
            ticker: (h.quantity * prices[ticker] / total) if total else ZERO
            for ticker, h in self.holdings.items()
        }

    def rebalance(self, *, whole_shares: bool = False, min_trade_value: Number = ZERO) -> RebalancePlan:
        """Compute which stocks to sell and buy to match the allocation.

        whole_shares: trade integer quantities only. Whatever can't be invested
            stays as cash (reported in the plan).
        min_trade_value: skip orders smaller than this amount, to avoid trades
            whose fees would outweigh their benefit.
        """
        return compute_rebalance(
            quantities={ticker: h.quantity for ticker, h in self.holdings.items()},
            weights={ticker: a.weight for ticker, a in self.allocations.items()},
            prices=self.price_snapshot(),
            cash=self.cash,
            step=WHOLE_SHARE_STEP if whole_shares else FRACTIONAL_STEP,
            min_trade_value=as_decimal(min_trade_value),
        )


def compute_rebalance(
    quantities: Mapping[str, Decimal],
    weights: Mapping[str, Decimal],
    prices: Mapping[str, Decimal],
    cash: Decimal = ZERO,
    step: Decimal = FRACTIONAL_STEP,
    min_trade_value: Decimal = ZERO,
) -> RebalancePlan:
    """Pure rebalance calculation.

    1. Total value = cash + market value of every holding.
    2. Ideal value per stock = total value x target weight. A stock we hold but
       don't target has weight 0, so it gets sold entirely.
    3. Round every ideal quantity DOWN to a multiple of `step`. This guarantees
       we never allocate more than 100% of the portfolio.
    4. Rounding down leaves idle cash. Spend it greedily (see `_greedy_fill`).
    5. Order = target quantity - current quantity. Drop orders below
       `min_trade_value`, then make sure buys are still funded (`_fund_buys`).

    In fractional mode the leftover of step 3 is negligible, so the result is
    essentially exact. In whole-share mode the leftover is real and ends up as
    cash in the plan.
    """
    tickers = sorted(set(quantities) | set(weights))
    held = {t: quantities.get(t, ZERO) for t in tickers}
    total_value = cash + sum((held[t] * prices[t] for t in tickers), ZERO)

    ideal_values = {t: total_value * weights.get(t, ZERO) for t in tickers}
    targets = {t: _floor_to_step(ideal_values[t] / prices[t], step) for t in tickers}

    leftover = total_value - sum((targets[t] * prices[t] for t in tickers), ZERO)
    targets = _greedy_fill(targets, ideal_values, prices, leftover, step)

    orders = []
    for t in tickers:
        delta = targets[t] - held[t]
        if delta:
            action = Action.BUY if delta > 0 else Action.SELL
            orders.append(TradeOrder(t, action, abs(delta), prices[t]))
    orders = [o for o in orders if o.value >= min_trade_value]
    orders = _fund_buys(orders, cash, step)
    orders.sort(key=lambda o: (o.action is not Action.SELL, o.ticker))

    final = dict(held)
    for o in orders:
        final[o.ticker] += o.quantity if o.action is Action.BUY else -o.quantity

    return RebalancePlan(
        total_value=total_value,
        orders=tuple(orders),
        cash_before=cash,
        cash_after=cash + sum((o.cash_flow for o in orders), ZERO),
        weights_after={
            t: (final[t] * prices[t] / total_value) if total_value else ZERO for t in tickers
        },
    )


def _greedy_fill(
    targets: dict[str, Decimal],
    ideal_values: Mapping[str, Decimal],
    prices: Mapping[str, Decimal],
    cash: Decimal,
    step: Decimal,
) -> dict[str, Decimal]:
    """Invest the cash left over by rounding down, one lot (`step`) at a time.

    On each iteration, buy one more lot of the stock furthest below its ideal
    value, among those whose lot still fits in the remaining cash. Ties go
    to alphabetical order so the result is deterministic.

    Why this is good enough: rounding down leaves each stock less than one lot
    below its ideal, so buying a single extra lot always pushes it over. Each
    stock therefore gets at most one extra lot (at most N iterations), and
    every purchase moves idle cash into a stock that was underweight, which
    reduces the total deviation from the allocation. An optimal fit would be
    a knapsack problem, far more complex for a marginal gain.
    """
    targets = dict(targets)

    def shortfall(t: str) -> Decimal:
        return ideal_values[t] - targets[t] * prices[t]

    while True:
        candidates = [t for t in targets if shortfall(t) > 0 and prices[t] * step <= cash]
        if not candidates:
            return targets
        best = min(candidates, key=lambda t: (-shortfall(t), t))
        targets[best] += step
        cash -= prices[best] * step


def _fund_buys(orders: list[TradeOrder], cash: Decimal, step: Decimal) -> list[TradeOrder]:
    """Guarantee that buys never spend more than cash + sale proceeds.

    Since targets are rounded down, this only kicks in when `min_trade_value`
    dropped a small *sell* whose proceeds some buy relied on. In that case,
    buys are trimmed starting with the largest until they are funded.
    """
    missing = -(cash + sum((o.cash_flow for o in orders), ZERO))
    if missing <= 0:
        return orders

    funded = [o for o in orders if o.action is Action.SELL]
    buys = sorted((o for o in orders if o.action is Action.BUY), key=lambda o: o.value, reverse=True)
    for buy in buys:
        if missing > 0:
            cut = min(buy.quantity, _ceil_to_step(missing / buy.price, step))
            missing -= cut * buy.price
            buy = replace(buy, quantity=buy.quantity - cut)
        if buy.quantity > 0:
            funded.append(buy)
    return funded


def _floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def _ceil_to_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_CEILING) * step


def _index_by_ticker(items: Iterable[Holding] | Iterable[Allocation], kind: str) -> dict:
    indexed = {}
    for item in items:
        ticker = item.stock.ticker
        if ticker in indexed:
            raise ValueError(f"Duplicate {kind} for {ticker}")
        indexed[ticker] = item
    return indexed
