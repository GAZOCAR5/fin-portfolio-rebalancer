from decimal import Decimal

import pytest

from tests.helpers import CountingPriceProvider, build_portfolio

PRICES = {"META": 500, "AAPL": 200}


@pytest.mark.parametrize(
    "allocation",
    [
        {"META": "0.4", "AAPL": "0.5"},  # sums to 0.9
        {"META": "0.4", "AAPL": "0.7"},  # sums to 1.1
        {},  # sums to 0
    ],
)
def test_allocation_must_sum_to_one(allocation):
    with pytest.raises(ValueError, match="sum to 1"):
        build_portfolio(PRICES, allocation=allocation)


@pytest.mark.parametrize("weight", ["-0.1", "1.1"])
def test_weight_must_be_between_zero_and_one(weight):
    with pytest.raises(ValueError):
        build_portfolio(PRICES, allocation={"META": weight})


def test_negative_quantity_is_rejected():
    with pytest.raises(ValueError):
        build_portfolio(PRICES, holdings={"META": -1}, allocation={"META": 1})


def test_negative_cash_is_rejected():
    with pytest.raises(ValueError):
        build_portfolio(PRICES, allocation={"META": 1}, cash=-1)


def test_total_value_includes_cash():
    portfolio = build_portfolio(
        PRICES, holdings={"META": 10, "AAPL": 10}, allocation={"META": 1}, cash=100
    )
    assert portfolio.total_value() == Decimal(7100)


def test_current_weights():
    portfolio = build_portfolio(
        PRICES, holdings={"META": 2, "AAPL": 5}, allocation={"META": "0.5", "AAPL": "0.5"}
    )
    assert portfolio.current_weights() == {"META": Decimal("0.5"), "AAPL": Decimal("0.5")}


def test_rebalance_queries_each_price_exactly_once():
    provider = CountingPriceProvider(PRICES)
    portfolio = build_portfolio(
        PRICES,
        holdings={"META": 10},
        allocation={"META": "0.4", "AAPL": "0.6"},
        provider=provider,
    )
    portfolio.rebalance()
    assert provider.calls == {"META": 1, "AAPL": 1}
