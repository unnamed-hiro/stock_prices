"""利益改善(エントリー緩和・複利化)のリグレッションテスト"""
import numpy as np
import pandas as pd
import pytest

from src.strategies.technical import TechnicalStrategy
from src.backtester import _size_position
from src.live_paper import _size_position as live_size
from src.portfolio import Portfolio


def _bars(prices, volumes=None):
    idx = pd.date_range("2024-01-01", periods=len(prices), freq="D")
    return pd.DataFrame({
        "Open": prices, "High": prices, "Low": prices, "Close": prices,
        "Volume": volumes or [10_000] * len(prices),
    }, index=idx)


def _uptrend_history():
    # 押し目を挟む緩やかな上昇トレンド (5MA>25MA は継続、RSIは過熱しない)
    base = np.linspace(1000, 1300, 80)
    wobble = 40 * np.sin(np.linspace(0, 8 * np.pi, 80))
    prices = list(base + wobble)
    return {"X.T": _bars(prices)}


def test_trend_mode_fires_more_than_cross_mode():
    """trendモードはcrossモードより多くの買いシグナルを出す(資金稼働率↑)"""
    ph = _uptrend_history()
    date = ph["X.T"].index[-1]

    trend = TechnicalStrategy({"entry_mode": "trend"})
    cross = TechnicalStrategy({"entry_mode": "cross"})

    # 上昇トレンド継続中の日: trendは買い、crossはクロス瞬間でないので無反応
    t_sigs = trend.generate_signals(date, ph, set())
    c_sigs = cross.generate_signals(date, ph, set())

    assert any(s.action == "buy" for s in t_sigs)
    assert not any(s.action == "buy" for s in c_sigs)


def test_trend_mode_is_default():
    s = TechnicalStrategy({})
    assert s.entry_mode == "trend"


def test_trend_mode_no_buy_when_overbought():
    # RSIが過熱しているときは上昇トレンドでも買わない
    prices = list(np.linspace(1000, 3000, 60))  # 急騰でRSI高
    ph = {"X.T": _bars(prices)}
    s = TechnicalStrategy({"entry_mode": "trend", "rsi_overbought": 70})
    sigs = s.generate_signals(ph["X.T"].index[-1], ph, set())
    # 過熱で買いが出ない(または控えめ)ことを確認
    buys = [x for x in sigs if x.action == "buy"]
    assert len(buys) == 0


def test_size_on_equity_compounds():
    """現在資産が大きいほど建玉サイズが大きくなる(複利)"""
    pf = Portfolio(initial_capital=5_000_000)
    pf.cash = 10_000_000  # 利益が乗って資産倍増した想定

    # 初期資金基準 (base_equity=None)
    shares_fixed = _size_position(pf, 1000.0, 0.10, 0.10, base_equity=None)
    # 現在資産基準 (複利)
    shares_compound = _size_position(pf, 1000.0, 0.10, 0.10, base_equity=10_000_000)

    assert shares_compound > shares_fixed


def test_live_size_on_equity_compounds():
    pf = Portfolio(initial_capital=5_000_000)
    pf.cash = 10_000_000
    fixed = live_size(pf, 1000.0, 0.10, 0.10, base_equity=None)
    compound = live_size(pf, 1000.0, 0.10, 0.10, base_equity=10_000_000)
    assert compound > fixed


def test_size_respects_cash_reserve():
    """現金が乏しいときは複利基準でも現金準備率を割らない"""
    pf = Portfolio(initial_capital=5_000_000)
    pf.cash = 400_000  # ほぼ現金なし (準備率10%=50万を下回る)
    shares = _size_position(pf, 1000.0, 0.10, 0.10, base_equity=20_000_000)
    assert shares == 0
