"""マルチAI合議制 + ファンダメンタルズ戦略のテスト"""
import numpy as np
import pandas as pd
import pytest

from src.strategies import build_strategy
from src.strategies.base import Strategy, Signal
from src.strategies.fundamental import FundamentalStrategy
from src.strategies.ensemble import EnsembleStrategy


def _bars(prices, volumes=None):
    idx = pd.date_range("2024-01-01", periods=len(prices), freq="D")
    return pd.DataFrame({
        "Open": prices, "High": prices, "Low": prices, "Close": prices,
        "Volume": volumes or [10_000] * len(prices),
    }, index=idx)


class StubStrategy(Strategy):
    """テスト用: 指定したシグナルを必ず返す"""
    def __init__(self, signals: list[Signal], warmup: int = 10):
        super().__init__({})
        self._signals = signals
        self._warmup = warmup

    def warmup_days(self) -> int:
        return self._warmup

    def generate_signals(self, date, price_history, held_tickers):
        return list(self._signals)


def _make_ensemble(members: dict, **ens_params) -> EnsembleStrategy:
    """メンバーを直接差し込んだ EnsembleStrategy を作る"""
    ens = EnsembleStrategy({"ensemble": {"members": [], **ens_params}})
    ens.members = members
    return ens


# ---- Fundamental ----

def test_fundamental_score_undervalued_high():
    s = FundamentalStrategy({"fundamentals": {}})
    cheap = {"trailingPE": 8, "priceToBook": 0.8, "returnOnEquity": 0.20,
             "dividendYield": 0.03}
    expensive = {"trailingPE": 60, "priceToBook": 8, "returnOnEquity": 0.01,
                 "dividendYield": 0.0}
    assert s.score(cheap) > s.score(expensive)
    assert s.score(cheap) > 0.6


def test_fundamental_score_none_when_no_data():
    s = FundamentalStrategy({"fundamentals": {}})
    assert s.score({}) is None


def test_fundamental_buy_signal_for_cheap_stock():
    funds = {"7203.T": {"trailingPE": 9, "priceToBook": 0.9,
                        "returnOnEquity": 0.18, "dividendYield": 0.035}}
    s = FundamentalStrategy({"fundamentals": funds, "buy_score": 0.6})
    ph = {"7203.T": _bars(list(np.linspace(1000, 1100, 30)))}
    sigs = s.generate_signals(pd.Timestamp("2024-01-30"), ph, set())
    assert any(x.action == "buy" and x.ticker == "7203.T" for x in sigs)


def test_fundamental_sell_signal_for_overvalued_held():
    funds = {"7203.T": {"trailingPE": 80, "priceToBook": 10,
                        "returnOnEquity": 0.0, "dividendYield": 0.0}}
    s = FundamentalStrategy({"fundamentals": funds, "sell_score": 0.3})
    ph = {"7203.T": _bars(list(np.linspace(1000, 1100, 30)))}
    sigs = s.generate_signals(pd.Timestamp("2024-01-30"), ph, {"7203.T"})
    assert any(x.action == "sell" for x in sigs)


# ---- Ensemble ----

def test_ensemble_builds_members_via_factory():
    params = {
        "technical": {},
        "fundamental": {"fundamentals": {}},
        "ensemble": {"members": ["technical", "fundamental"],
                     "min_agreement": 2, "buy_threshold": 1.0},
    }
    ens = build_strategy("ensemble", params)
    assert isinstance(ens, EnsembleStrategy)
    assert set(ens.members.keys()) == {"technical", "fundamental"}


def test_ensemble_buys_on_consensus():
    # 2人とも買い → 合議buy成立
    ph = {"X.T": _bars(list(np.linspace(1000, 1100, 30)))}
    ens = _make_ensemble(
        {"a": StubStrategy([Signal("X.T", "buy", 0.8, "a-buy")]),
         "b": StubStrategy([Signal("X.T", "buy", 0.7, "b-buy")])},
        min_agreement=2, buy_threshold=1.0,
        weights={"a": 1.0, "b": 1.0},
    )
    sigs = ens.generate_signals(pd.Timestamp("2024-01-30"), ph, set())
    buys = [s for s in sigs if s.action == "buy"]
    assert len(buys) == 1
    assert "合議buy" in buys[0].reason
    assert buys[0].ticker == "X.T"


def test_ensemble_requires_min_agreement():
    # 1人だけ買い、min_agreement=2 → 見送り
    ph = {"X.T": _bars(list(np.linspace(1000, 1100, 30)))}
    ens = _make_ensemble(
        {"a": StubStrategy([Signal("X.T", "buy", 0.9, "a-buy")]),
         "b": StubStrategy([])},
        min_agreement=2, buy_threshold=0.5,
    )
    sigs = ens.generate_signals(pd.Timestamp("2024-01-30"), ph, set())
    assert not any(s.action == "buy" for s in sigs)


def test_ensemble_respects_buy_threshold():
    # 2人買いだが加重スコアが閾値未満 → 見送り
    ph = {"X.T": _bars(list(np.linspace(1000, 1100, 30)))}
    ens = _make_ensemble(
        {"a": StubStrategy([Signal("X.T", "buy", 0.3, "a")]),
         "b": StubStrategy([Signal("X.T", "buy", 0.3, "b")])},
        min_agreement=2, buy_threshold=1.0,  # 0.3+0.3=0.6 < 1.0
        weights={"a": 1.0, "b": 1.0},
    )
    sigs = ens.generate_signals(pd.Timestamp("2024-01-30"), ph, set())
    assert not any(s.action == "buy" for s in sigs)


def test_ensemble_weights_affect_score():
    # fundamentalの重みを上げれば閾値クリア
    ph = {"X.T": _bars(list(np.linspace(1000, 1100, 30)))}
    ens = _make_ensemble(
        {"a": StubStrategy([Signal("X.T", "buy", 0.5, "a")]),
         "b": StubStrategy([Signal("X.T", "buy", 0.5, "b")])},
        min_agreement=2, buy_threshold=1.2,
        weights={"a": 2.0, "b": 1.0},  # 0.5*2 + 0.5*1 = 1.5 >= 1.2
    )
    sigs = ens.generate_signals(pd.Timestamp("2024-01-30"), ph, set())
    assert any(s.action == "buy" for s in sigs)


def test_ensemble_sells_held_on_consensus():
    ph = {"X.T": _bars(list(np.linspace(1100, 1000, 30)))}
    ens = _make_ensemble(
        {"a": StubStrategy([Signal("X.T", "sell", 0.6, "a-sell")]),
         "b": StubStrategy([Signal("X.T", "sell", 0.5, "b-sell")])},
        min_agreement=2, sell_threshold=0.8,
    )
    sigs = ens.generate_signals(pd.Timestamp("2024-01-30"), ph, {"X.T"})
    assert any(s.action == "sell" for s in sigs)


def test_ensemble_member_failure_is_isolated():
    # 1メンバーが例外を投げても他メンバーで判断継続
    class Boom(Strategy):
        def warmup_days(self): return 10
        def generate_signals(self, *a): raise RuntimeError("boom")
    ph = {"X.T": _bars(list(np.linspace(1000, 1100, 30)))}
    ens = _make_ensemble(
        {"boom": Boom({}),
         "a": StubStrategy([Signal("X.T", "buy", 0.9, "a")]),
         "b": StubStrategy([Signal("X.T", "buy", 0.9, "b")])},
        min_agreement=2, buy_threshold=1.0,
    )
    sigs = ens.generate_signals(pd.Timestamp("2024-01-30"), ph, set())
    assert any(s.action == "buy" for s in sigs)


def test_ensemble_warmup_is_max_of_members():
    params = {
        "technical": {},
        "fundamental": {"fundamentals": {}},
        "ensemble": {"members": ["technical", "fundamental"]},
    }
    ens = build_strategy("ensemble", params)
    tech = build_strategy("technical", params)
    fund = build_strategy("fundamental", params)
    assert ens.warmup_days() == max(tech.warmup_days(), fund.warmup_days())


def test_ensemble_ignores_self_reference():
    params = {"technical": {}, "ensemble": {"members": ["technical", "ensemble"]}}
    ens = build_strategy("ensemble", params)
    assert "ensemble" not in ens.members
