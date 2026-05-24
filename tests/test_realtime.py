"""準リアルタイム売買エンジンの単体テスト"""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import pytest

from src.config import load_config
from src.realtime import (
    is_market_open, next_open, generate_intraday_signals,
    execute_tick, load_portfolio, save_portfolio, reset_portfolio,
    STATE_PATH, _rsi, _ema,
)

JST = ZoneInfo("Asia/Tokyo")


def test_market_open_weekday_morning():
    t = datetime(2026, 5, 25, 10, 0, tzinfo=JST)  # 月 10:00
    assert is_market_open(t)


def test_market_open_weekday_lunch():
    t = datetime(2026, 5, 25, 12, 0, tzinfo=JST)  # 月 12:00
    assert not is_market_open(t)


def test_market_open_weekday_afternoon():
    t = datetime(2026, 5, 25, 13, 30, tzinfo=JST)  # 月 13:30
    assert is_market_open(t)


def test_market_closed_weekend():
    t = datetime(2026, 5, 24, 10, 0, tzinfo=JST)  # 日
    assert not is_market_open(t)


def test_market_closed_after_hours():
    t = datetime(2026, 5, 25, 16, 0, tzinfo=JST)  # 月 16:00
    assert not is_market_open(t)


def test_next_open_from_weekend():
    sun = datetime(2026, 5, 24, 10, 0, tzinfo=JST)
    nx = next_open(sun)
    assert nx.weekday() == 0
    assert nx.hour == 9 and nx.minute == 0


def test_next_open_from_lunch():
    noon = datetime(2026, 5, 25, 12, 0, tzinfo=JST)
    nx = next_open(noon)
    assert nx.hour == 12 and nx.minute == 30


def _make_bars(prices: list[float], volumes: list[int] | None = None) -> pd.DataFrame:
    idx = pd.date_range("2026-05-25 09:00", periods=len(prices), freq="1min")
    df = pd.DataFrame({
        "Open": prices, "High": prices, "Low": prices, "Close": prices,
        "Volume": volumes or [10_000] * len(prices),
    }, index=idx)
    return df


def test_signal_golden_cross_buy():
    # 下落→急上昇 (ゴールデンクロス成立)
    down = list(np.linspace(1000, 940, 30))
    up = list(np.linspace(940, 970, 6))
    vols = [10_000] * 30 + [50_000] * 6
    bars = {"TEST.T": _make_bars(down + up, vols)}
    sigs = generate_intraday_signals(bars, held=set(), short_ema=5, long_ema=20)
    buys = [s for s in sigs if s.action == "buy"]
    assert len(buys) == 1
    assert "EMA" in buys[0].reason


def test_signal_no_buy_without_volume():
    # ゴールデンクロスはあるが出来高スパイクなし → 買わない
    down = list(np.linspace(1000, 940, 30))
    up = list(np.linspace(940, 970, 6))
    bars = {"TEST.T": _make_bars(down + up, [10_000] * 36)}
    sigs = generate_intraday_signals(bars, held=set(), vol_spike=1.5)
    assert not any(s.action == "buy" for s in sigs)


def test_signal_dead_cross_sell():
    up = list(np.linspace(900, 1100, 28))
    down = list(np.linspace(1100, 1000, 8))
    bars = {"TEST.T": _make_bars(up + down)}
    sigs = generate_intraday_signals(bars, held={"TEST.T"})
    sells = [s for s in sigs if s.action == "sell"]
    assert len(sells) == 1


def test_persistence_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("src.realtime.STATE_PATH", tmp_path / "rt.json")
    config = load_config()
    from src.realtime import load_portfolio as lp, save_portfolio as sp
    pf = lp(config)
    pf.buy("7203.T", 3000.0, 100, pd.Timestamp("2026-05-25 10:00"))
    sp(pf)
    pf2 = lp(config)
    assert "7203.T" in pf2.positions
    assert pf2.positions["7203.T"].shares == 100
    assert abs(pf2.cash - pf.cash) < 1


def test_execute_tick_buys_on_signal(tmp_path, monkeypatch):
    monkeypatch.setattr("src.realtime.STATE_PATH", tmp_path / "rt.json")
    config = load_config()
    pf = load_portfolio(config)
    # ゴールデンクロス + 出来高スパイクを起こす
    down = list(np.linspace(1000, 940, 30))
    up = list(np.linspace(940, 970, 6))
    vols = [10_000] * 30 + [50_000] * 6
    bars = {"7203.T": _make_bars(down + up, vols)}
    now = datetime(2026, 5, 25, 10, 0, tzinfo=JST)
    tick = execute_tick(config, pf, bars, now, dry_run=False)
    assert any(e["side"] == "buy-ai" for e in tick.executed)
    assert "7203.T" in pf.positions


def test_execute_tick_dry_run_does_not_mutate(tmp_path, monkeypatch):
    monkeypatch.setattr("src.realtime.STATE_PATH", tmp_path / "rt.json")
    config = load_config()
    pf = load_portfolio(config)
    down = list(np.linspace(1000, 940, 30))
    up = list(np.linspace(940, 970, 6))
    vols = [10_000] * 30 + [50_000] * 6
    bars = {"7203.T": _make_bars(down + up, vols)}
    cash_before = pf.cash
    now = datetime(2026, 5, 25, 10, 0, tzinfo=JST)
    execute_tick(config, pf, bars, now, dry_run=True)
    assert pf.cash == cash_before
    assert "7203.T" not in pf.positions


def test_run_loop_once_with_mock(tmp_path, monkeypatch):
    """yfinance を mock して run_loop の 1ティックが期待通り動作することを確認"""
    monkeypatch.setattr("src.realtime.STATE_PATH", tmp_path / "rt.json")
    monkeypatch.setattr("src.realtime.SNAPSHOT_DIR", tmp_path / "snap")

    def fake_fetch(tickers):
        down = list(np.linspace(1000, 940, 30))
        up = list(np.linspace(940, 970, 6))
        vols = [10_000] * 30 + [50_000] * 6
        return {tickers[0]: _make_bars(down + up, vols)}

    monkeypatch.setattr("src.realtime.fetch_intraday", fake_fetch)

    from src.realtime import run_loop
    config = load_config()
    run_loop(
        config=config,
        watchlist=["7203.T"],
        interval_min=1,
        max_iterations=1,
        dry_run=False,
        force_run=True,
    )
    # 状態が永続化されていることを確認
    assert (tmp_path / "rt.json").exists()
    with open(tmp_path / "rt.json") as f:
        state = json.load(f)
    assert "7203.T" in state["positions"]
    # スナップショットが残ることを確認
    snap_files = list((tmp_path / "snap").rglob("*.json"))
    assert len(snap_files) == 1


def test_stop_loss_triggers_sell(tmp_path, monkeypatch):
    monkeypatch.setattr("src.realtime.STATE_PATH", tmp_path / "rt.json")
    config = load_config()
    pf = load_portfolio(config)
    pf.buy("7203.T", 3000.0, 100, pd.Timestamp("2026-05-25 09:00"))
    # -10% 下落 (stop_loss = 5%)
    prices = [2700.0] * 45
    bars = {"7203.T": _make_bars(prices)}
    now = datetime(2026, 5, 25, 10, 0, tzinfo=JST)
    tick = execute_tick(config, pf, bars, now)
    assert any(e["side"] == "sell-risk" for e in tick.executed)
    assert "7203.T" not in pf.positions
