import random
from decimal import Decimal

import pytest

from portfolio_manager import Action, compute_rebalance
from portfolio_manager.portfolio import FRACTIONAL_STEP, WHOLE_SHARE_STEP
from tests.helpers import build_portfolio, orders_by_ticker

PRICES = {"META": 500, "AAPL": 200}
TARGET = {"META": "0.4", "AAPL": "0.6"}


# --- Fractional mode (default) ---------------------------------------------


def test_reference_example():
    # 10 META x $500 = $5000 (71%), 10 AAPL x $200 = $2000 (29%). Total $7000.
    # Target: META 40% = $2800 -> 5.6 shares; AAPL 60% = $4200 -> 21 shares.
    plan = build_portfolio(PRICES, {"META": 10, "AAPL": 10}, TARGET).rebalance()

    assert orders_by_ticker(plan) == {"META": ("SELL", Decimal("4.4")), "AAPL": ("BUY", 11)}
    assert plan.cash_after == 0
    assert plan.weights_after == {"META": Decimal("0.4"), "AAPL": Decimal("0.6")}


def test_sells_come_before_buys():
    plan = build_portfolio(PRICES, {"META": 10, "AAPL": 10}, TARGET).rebalance()
    assert [o.action for o in plan.orders] == [Action.SELL, Action.BUY]


def test_balanced_portfolio_needs_no_orders():
    plan = build_portfolio(PRICES, {"META": 4, "AAPL": 15}, TARGET).rebalance()
    assert plan.is_empty


def test_stock_outside_allocation_is_sold_entirely():
    plan = build_portfolio(PRICES, {"META": 10, "AAPL": 10}, {"AAPL": 1}).rebalance()
    assert orders_by_ticker(plan) == {"META": ("SELL", 10), "AAPL": ("BUY", 25)}


def test_allocated_stock_not_held_is_bought():
    plan = build_portfolio(PRICES, {"META": 10}, TARGET).rebalance()
    assert orders_by_ticker(plan) == {"META": ("SELL", 6), "AAPL": ("BUY", 15)}


def test_available_cash_is_invested():
    plan = build_portfolio(PRICES, allocation=TARGET, cash=1000).rebalance()
    assert orders_by_ticker(plan) == {"META": ("BUY", Decimal("0.8")), "AAPL": ("BUY", 3)}
    assert plan.cash_after == 0


def test_empty_portfolio_produces_empty_plan():
    plan = build_portfolio(PRICES, allocation=TARGET).rebalance()
    assert plan.is_empty
    assert plan.total_value == 0


# --- Whole-share mode ------------------------------------------------------


def test_whole_shares_leave_the_remainder_as_cash():
    # Target META $2800 -> 5.6 shares, rounded down to 5 ($2500). AAPL $4200 -> 21.
    # $300 remain, less than one META share, so they stay in cash (~4.3%).
    plan = build_portfolio(PRICES, {"META": 10, "AAPL": 10}, TARGET).rebalance(whole_shares=True)

    assert orders_by_ticker(plan) == {"META": ("SELL", 5), "AAPL": ("BUY", 11)}
    assert plan.cash_after == 300
    assert all(o.quantity == o.quantity.to_integral_value() for o in plan.orders)


def test_greedy_spends_leftover_on_most_underweight_stock():
    # $1000 cash, three stocks at $250. Ideal: A $450, B $350, C $200.
    # Rounding down: A 1, B 1, C 0 -> $500 spent, $500 left.
    # Shortfalls: A 200, B 100, C 200. Greedy buys A (tie with C, alphabetical),
    # then C. B's shortfall is smaller, so it gets nothing extra.
    plan = build_portfolio(
        {"A": 250, "B": 250, "C": 250},
        allocation={"A": "0.45", "B": "0.35", "C": "0.20"},
        cash=1000,
    ).rebalance(whole_shares=True)

    assert orders_by_ticker(plan) == {"A": ("BUY", 2), "B": ("BUY", 1), "C": ("BUY", 1)}
    assert plan.cash_after == 0


def test_whole_shares_never_exceed_available_value():
    plan = build_portfolio({"X": 300}, allocation={"X": 1}, cash=1000).rebalance(whole_shares=True)
    assert orders_by_ticker(plan) == {"X": ("BUY", 3)}
    assert plan.cash_after == 100


# --- Minimum trade value ---------------------------------------------------


def test_orders_below_minimum_are_skipped():
    # META is off by 0.1 shares ($50); AAPL by 0.25 shares ($50). Both are noise.
    plan = build_portfolio(PRICES, {"META": "4.1", "AAPL": "14.75"}, TARGET).rebalance(
        min_trade_value=100
    )
    assert plan.is_empty


def test_skipped_sell_does_not_leave_buys_unfunded():
    # A sells $10 (skipped), B sells $1000, C buys $1010. Without A's $10,
    # C's buy is trimmed to what B's sale actually funds.
    plan = compute_rebalance(
        quantities={"A": Decimal(10), "B": Decimal(10)},
        weights={"A": Decimal("0.495"), "C": Decimal("0.505")},
        prices={"A": Decimal(100), "B": Decimal(100), "C": Decimal(100)},
        min_trade_value=Decimal(50),
    )
    assert orders_by_ticker(plan) == {"B": ("SELL", 10), "C": ("BUY", 10)}
    assert plan.cash_after == 0


# --- Output ----------------------------------------------------------------


def test_plan_serializes_decimals_as_plain_strings():
    plan = build_portfolio(PRICES, {"META": 10, "AAPL": 10}, TARGET).rebalance()
    assert plan.to_dict() == {
        "total_value": "7000",
        "cash_before": "0",
        "cash_after": "0",
        "orders": [
            {"ticker": "META", "action": "SELL", "quantity": "4.4", "price": "500", "estimated_value": "2200"},
            {"ticker": "AAPL", "action": "BUY", "quantity": "11", "price": "200", "estimated_value": "2200"},
        ],
        "weights_after": {"AAPL": "0.6", "META": "0.4"},
        "cash_weight_after": "0",
    }


# --- Invariants over random portfolios ------------------------------------


def _random_case(rng):
    tickers = [f"T{i}" for i in range(rng.randint(1, 6))]
    prices = {t: Decimal(rng.randint(100, 500_000)) / 100 for t in tickers}
    quantities = {t: Decimal(rng.randint(0, 100)) for t in tickers if rng.random() < 0.7}
    raw = [rng.randint(0, 100) for _ in tickers]
    raw[0] += 1  # at least one non-zero weight
    weights = {t: Decimal(r) / sum(raw) for t, r in zip(tickers[:-1], raw)}
    weights[tickers[-1]] = 1 - sum(weights.values(), Decimal(0))
    cash = Decimal(rng.randint(0, 100_000))
    return quantities, weights, prices, cash


@pytest.mark.parametrize("step", [FRACTIONAL_STEP, WHOLE_SHARE_STEP])
def test_invariants_hold_for_random_portfolios(step):
    rng = random.Random(42)
    for _ in range(500):
        quantities, weights, prices, cash = _random_case(rng)
        plan = compute_rebalance(quantities, weights, prices, cash, step)

        final = {t: quantities.get(t, Decimal(0)) for t in prices}
        for o in plan.orders:
            final[o.ticker] += o.quantity if o.action is Action.BUY else -o.quantity
        invested = sum((final[t] * prices[t] for t in final), Decimal(0))

        # Never spend money we don't have, and no money appears or vanishes.
        assert plan.cash_after >= 0
        assert invested + plan.cash_after == plan.total_value
        # Idle cash is always less than one lot of the most expensive stock:
        # otherwise the greedy step would have bought something with it.
        assert plan.cash_after < max(prices.values()) * step
        for t in final:
            assert final[t] >= 0
            # No stock ends more than one lot above its ideal value.
            ideal = plan.total_value * weights.get(t, Decimal(0))
            assert final[t] * prices[t] < ideal + prices[t] * step
