from decimal import Decimal

import pytest

from portfolio_manager import InMemoryPriceProvider, Stock
from portfolio_manager.stock import as_decimal


def test_current_price_comes_from_provider():
    stock = Stock("META", InMemoryPriceProvider({"META": "512.30"}))
    assert stock.current_price() == Decimal("512.30")


@pytest.mark.parametrize("bad_price", [0, -1])
def test_non_positive_price_is_rejected(bad_price):
    stock = Stock("META", InMemoryPriceProvider({"META": bad_price}))
    with pytest.raises(ValueError):
        stock.current_price()


def test_missing_price_raises_lookup_error():
    with pytest.raises(LookupError):
        Stock("META", InMemoryPriceProvider({})).current_price()


def test_stocks_are_equal_by_ticker_regardless_of_provider():
    assert Stock("META", InMemoryPriceProvider({})) == Stock("META", InMemoryPriceProvider({}))


def test_floats_are_converted_through_their_string_form():
    assert as_decimal(0.1) == Decimal("0.1")
