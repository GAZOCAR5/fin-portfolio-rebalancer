"""Run with: python -m examples.demo"""

import json

from portfolio_manager import Allocation, Holding, InMemoryPriceProvider, Portfolio, Stock

provider = InMemoryPriceProvider({"META": "500", "AAPL": "200", "GOOG": "1000"})
meta = Stock("META", provider)
aapl = Stock("AAPL", provider)
goog = Stock("GOOG", provider)

portfolio = Portfolio(
    holdings=[Holding(meta, 10), Holding(aapl, 10), Holding(goog, 10)],
    allocations=[Allocation(meta, "0.4"), Allocation(aapl, "0.6"), Allocation(goog, "0.0")],
)

print("Current weights:", {t: f"{w:.2%}" for t, w in portfolio.current_weights().items()})

print("\nRebalance with fractional shares (default):")
print(json.dumps(portfolio.rebalance().to_dict(), indent=2))

print("\nRebalance with whole shares (remainder stays in cash):")
print(json.dumps(portfolio.rebalance(whole_shares=True).to_dict(), indent=2))
