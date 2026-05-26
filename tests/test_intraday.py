"""イントラデイ・トレードシミュレーションの単体テスト"""
import numpy as np
import pandas as pd
import pytest

from src.config import load_config
from src.intraday_sim import simulate_day, format_result, IntradayResult


def _day_bars(prices: list[float], volumes: list[int] | None = None) -> pd.DataFrame:
    idx = pd.date_range("2026-05-22 09:00", periods=len(prices), freq="1min")
    return pd.DataFrame({
        "Open": prices, "High": prices, "Low": prices, "Close": prices,
        "Volume": volumes or [10_000] * len(prices),
    }, index=idx)


def test_simulate_day_runs_and_returns_result():
    config = load_config()
    # 下落→ゴールデンクロス→上昇 で買いが出る形
    down = list(np.linspace(1000, 940, 30))
    up = list(np.linspace(940, 1010, 40))
    vols = [10_000] * 30 + [50_000] * 40
    bars = {"7203.T": _day_bars(down + up, vols)}
    r = simulate_day(config, bars, "2026-05-22", eod_close=True)
    assert isinstance(r, IntradayResult)
    assert r.n_bars == 70
    assert r.n_tickers == 1
    assert r.starting_equity == config.simulation.initial_capital
    assert len(r.equity_curve) > 0


def test_eod_close_flattens_positions():
    config = load_config()
    down = list(np.linspace(1000, 940, 30))
    up = list(np.linspace(940, 1020, 40))
    vols = [10_000] * 30 + [50_000] * 40
    bars = {"7203.T": _day_bars(down + up, vols)}
    r = simulate_day(config, bars, "2026-05-22", eod_close=True)
    # 引け手仕舞いありなら最終ポジションは無いはず
    assert r.final_positions == []


def test_hold_keeps_positions_possible():
    config = load_config()
    down = list(np.linspace(1000, 940, 30))
    up = list(np.linspace(940, 1020, 40))
    vols = [10_000] * 30 + [50_000] * 40
    bars = {"7203.T": _day_bars(down + up, vols)}
    r_hold = simulate_day(config, bars, "2026-05-22", eod_close=False)
    r_close = simulate_day(config, bars, "2026-05-22", eod_close=True)
    # 持ち越しモードでは手仕舞いしない分、最終ポジションが残りうる
    assert len(r_hold.final_positions) >= len(r_close.final_positions)


def test_does_not_touch_realtime_state(tmp_path, monkeypatch):
    """シミュレーションが本番リアルタイム口座ファイルに触れないこと"""
    monkeypatch.setattr("src.realtime.STATE_PATH", tmp_path / "rt.json")
    config = load_config()
    bars = {"7203.T": _day_bars(list(np.linspace(1000, 1010, 60)))}
    simulate_day(config, bars, "2026-05-22")
    assert not (tmp_path / "rt.json").exists()


def test_step_reduces_decision_points():
    config = load_config()
    prices = list(np.linspace(1000, 1050, 120))
    bars = {"7203.T": _day_bars(prices)}
    r1 = simulate_day(config, bars, "2026-05-22", step=1)
    r5 = simulate_day(config, bars, "2026-05-22", step=5)
    # step=5 の方が判断点(エクイティカーブ点)が少ない
    assert len(r5.equity_curve) < len(r1.equity_curve)


def test_format_result_renders():
    r = IntradayResult(
        date="2026-05-22", n_tickers=2, n_bars=300,
        starting_equity=5_000_000, ending_equity=5_050_000,
        eod_close=True,
        trades=[{"ticker": "7203.T", "side": "buy", "shares": 100,
                 "price": 3000, "time": "2026-05-22 10:00:00", "pnl": 0},
                {"ticker": "7203.T", "side": "sell", "shares": 100,
                 "price": 3050, "time": "2026-05-22 14:00:00", "pnl": 5000}],
    )
    out = format_result(r)
    assert "本日トレードシミュレーション" in out
    assert "+50,000" in out or "+1.00%" in out
