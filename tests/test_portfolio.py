import pandas as pd
import pytest
from src.portfolio import Portfolio


@pytest.fixture
def pf():
    return Portfolio(initial_capital=1_000_000, commission_rate=0.001, slippage_rate=0.0)


def test_initial_state(pf):
    assert pf.cash == 1_000_000
    assert pf.positions == {}
    assert pf.trades == []


def test_buy_reduces_cash(pf):
    date = pd.Timestamp("2024-01-04")
    assert pf.buy("7203.T", price=2000, shares=100, date=date)
    assert pf.cash == pytest.approx(1_000_000 - 2000 * 100 * 1.001)
    assert "7203.T" in pf.positions
    assert pf.positions["7203.T"].shares == 100


def test_buy_rejects_oversize(pf):
    date = pd.Timestamp("2024-01-04")
    assert not pf.buy("7203.T", price=2000, shares=10_000, date=date)
    assert pf.cash == 1_000_000


def test_sell_realizes_pnl(pf):
    d1 = pd.Timestamp("2024-01-04")
    d2 = pd.Timestamp("2024-02-04")
    pf.buy("7203.T", price=2000, shares=100, date=d1)
    pf.sell("7203.T", price=2200, date=d2)
    sells = [t for t in pf.trades if t.side == "sell"]
    assert len(sells) == 1
    assert sells[0].pnl > 0
    assert sells[0].holding_days == 31
    assert "7203.T" not in pf.positions


def test_total_equity(pf):
    d = pd.Timestamp("2024-01-04")
    pf.buy("7203.T", price=2000, shares=100, date=d)
    eq = pf.total_equity({"7203.T": 2100})
    assert eq == pytest.approx(pf.cash + 2100 * 100)


def test_average_entry_on_repeated_buys(pf):
    d1 = pd.Timestamp("2024-01-04")
    d2 = pd.Timestamp("2024-01-10")
    pf.buy("7203.T", price=2000, shares=100, date=d1)
    pf.buy("7203.T", price=2200, shares=100, date=d2)
    pos = pf.positions["7203.T"]
    assert pos.shares == 200
    assert pos.entry_price == pytest.approx(2100.0)
