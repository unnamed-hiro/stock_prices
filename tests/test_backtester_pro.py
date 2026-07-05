"""プロ目線の改善(先読み排除・トレーリングストップ・ベンチマーク)のテスト"""
import pandas as pd
import pytest

from src.config import load_config
from src.portfolio import Portfolio
from src.strategies.base import Strategy, Signal
from src.backtester import run_backtest, compute_benchmark, _plan_exits


def _ohlc(rows):
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="D")
    o = [r[0] for r in rows]; h = [r[1] for r in rows]
    l = [r[2] for r in rows]; c = [r[3] for r in rows]
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c,
                         "Volume": [10_000] * len(rows)}, index=idx)


class BuyOnceStrategy(Strategy):
    """2本目の終値で1回だけ買いシグナルを出す(約定タイミング検証用)"""
    name = "buyonce"
    def __init__(s): super().__init__({}); s.done = False
    def warmup_days(s): return 0
    def generate_signals(s, date, ph, held):
        df = ph["X.T"]
        if date == df.index[1] and "X.T" not in held:
            return [Signal("X.T", "buy", 1.0, "test")]
        return []


def _cfg(**risk_over):
    cfg = load_config()
    cfg.simulation.start_date = "2024-01-01"
    cfg.simulation.end_date = "2024-12-31"
    for k, v in risk_over.items():
        setattr(cfg.risk, k, v)
    return cfg


def test_next_open_execution_fills_at_next_open_not_signal_close():
    """シグナルは2本目の終値で出るが、約定は3本目の始値であるべき(先読み排除)"""
    # bar2 close=100 (signal), bar3 open=110 (fill)
    df = _ohlc([(90, 91, 89, 90), (99, 101, 98, 100), (110, 112, 109, 111),
                (111, 113, 110, 112)])
    ph = {"X.T": df}
    cfg = _cfg(stop_loss_pct=0.5, take_profit_pct=0.0, trailing_stop_pct=0.0,
              position_size_pct=0.5, min_cash_reserve_pct=0.0)
    cfg.simulation.execution = "next_open"
    pf = run_backtest(cfg, BuyOnceStrategy(), ph, verbose=False)
    buys = [t for t in pf.trades if t.side == "buy"]
    assert len(buys) == 1
    # 約定価格は3本目の始値110ベース(スリッページ込み) — シグナル日の終値100ではない
    assert buys[0].price > 105, f"約定が始値110でなく終値100付近: {buys[0].price}"


def test_close_execution_fills_at_signal_close():
    """旧来モードでは当日終値で約定(先読みあり) — 後方互換の確認"""
    df = _ohlc([(90, 91, 89, 90), (99, 101, 98, 100), (110, 112, 109, 111)])
    ph = {"X.T": df}
    cfg = _cfg(stop_loss_pct=0.5, take_profit_pct=0.0, trailing_stop_pct=0.0,
              position_size_pct=0.5, min_cash_reserve_pct=0.0)
    cfg.simulation.execution = "close"
    pf = run_backtest(cfg, BuyOnceStrategy(), ph, verbose=False)
    buys = [t for t in pf.trades if t.side == "buy"]
    assert len(buys) == 1
    assert buys[0].price < 105, f"当日終値100付近で約定すべき: {buys[0].price}"


def test_trailing_stop_exits_after_peak_drop():
    pf = Portfolio(initial_capital=1_000_000)
    pf.buy("X.T", 100.0, 100, pd.Timestamp("2024-01-01"))
    # 価格が150まで上がってから130へ (peak150から-13%)
    _plan_exits(pf, pd.Timestamp("2024-01-05"), {"X.T": 150.0}, 0.08, 0.0, 250, 0.15)
    assert pf.positions["X.T"].peak_price == 150.0
    # 150から-15%=127.5未満で作動。130ではまだ(-13%)作動しない
    o1 = _plan_exits(pf, pd.Timestamp("2024-01-06"), {"X.T": 130.0}, 0.08, 0.0, 250, 0.15)
    assert not o1
    # 125なら-16.7%で作動
    o2 = _plan_exits(pf, pd.Timestamp("2024-01-07"), {"X.T": 125.0}, 0.08, 0.0, 250, 0.15)
    assert any(o["reason"] == "trailing_stop" for o in o2)


def test_trailing_stop_not_triggered_when_underwater():
    """含み損の状態ではトレーリングは作動せず、損切りに委ねる"""
    pf = Portfolio(initial_capital=1_000_000)
    pf.buy("X.T", 100.0, 100, pd.Timestamp("2024-01-01"))
    # 一度も上がらず95へ (peak=entry=100)。trailingは ret>0 条件で作動しない
    o = _plan_exits(pf, pd.Timestamp("2024-01-02"), {"X.T": 95.0}, 0.08, 0.0, 250, 0.15)
    assert not any(x["reason"] == "trailing_stop" for x in o)


def test_honor_strategy_sell_false_ignores_strategy_sells():
    class SellHeld(Strategy):
        name = "sellheld"
        def warmup_days(s): return 0
        def generate_signals(s, date, ph, held):
            return [Signal(t, "sell", 0.7, "x") for t in held]
    df = _ohlc([(100, 101, 99, 100)] * 5)
    ph = {"X.T": df}
    pf = Portfolio(initial_capital=1_000_000)
    pf.buy("X.T", 100.0, 100, pd.Timestamp("2024-01-01"))
    # honor_strategy_sell=False, かつリスク決済も発生しない設定 → 保有継続
    cfg = _cfg(stop_loss_pct=0.9, take_profit_pct=0.0, trailing_stop_pct=0.0,
              max_holding_days=9999, honor_strategy_sell=False)
    cfg.simulation.execution = "close"
    pf2 = run_backtest(cfg, SellHeld(), ph, verbose=False)
    # 戦略の売りは無視されるので売買が発生しない
    assert len([t for t in pf2.trades if t.side == "sell"]) == 0


def test_compute_benchmark_buy_and_hold():
    df = _ohlc([(100, 100, 100, 100), (100, 100, 100, 100), (100, 100, 100, 200)])
    ph = {"X.T": df}
    b = compute_benchmark(ph, pd.Timestamp("2024-01-01"),
                          pd.Timestamp("2024-12-31"), 1_000_000)
    # 100→200 で +100%
    assert abs(b["total_return_pct"] - 100.0) < 0.01
