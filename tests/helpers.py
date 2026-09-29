from collections import Counter

from portfolio_manager import Allocation, Holding, InMemoryPriceProvider, Portfolio, Stock


class CountingPriceProvider(InMemoryPriceProvider):
    """Records how many times each ticker's price was requested."""

    def __init__(self, prices):
        super().__init__(prices)
        self.calls = Counter()

    def get_last_price(self, ticker):
        self.calls[ticker] += 1
        return super().get_last_price(ticker)


def build_portfolio(prices, holdings=None, allocation=None, cash=0, provider=None):
    provider = provider or InMemoryPriceProvider(prices)
    return Portfolio(
        holdings=[Holding(Stock(t, provider), q) for t, q in (holdings or {}).items()],
        allocations=[Allocation(Stock(t, provider), w) for t, w in (allocation or {}).items()],
        cash=cash,
    )


def orders_by_ticker(plan):
    """{ticker: (action, quantity)} for compact assertions."""
    return {o.ticker: (o.action.value, o.quantity) for o in plan.orders}
