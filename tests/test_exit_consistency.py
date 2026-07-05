"""全実行経路(バックテスト/日次ライブ/リアルタイム)の決済ロジック整合性テスト

背景: config を take_profit_pct=0 (固定利確なし) に変更した際、バックテスターだけ
ガードを入れ、日次ライブ・リアルタイムには入れ忘れた。その結果、自動運用が
「含み益0%以上を即日利確」する重大バグが発生した。本テストはその再発を防ぐ。
"""
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import pytest

from src.config import load_config
from src.portfolio import Portfolio
from src.strategies.base import Strategy, Signal

JST = ZoneInfo("Asia/Tokyo")


def _cfg(**risk_over):
    cfg = load_config()
    for k, v in risk_over.items():
        setattr(cfg.risk, k, v)
    return cfg


def _daily_bars(prices):
    idx = pd.date_range("2024-01-01", periods=len(prices), freq="D")
    return pd.DataFrame({"Open": prices, "High": prices, "Low": prices,
                         "Close": prices, "Volume": [10_000] * len(prices)}, index=idx)


def _minute_bars(prices):
    idx = pd.date_range("2026-05-25 09:00", periods=len(prices), freq="1min")
    return pd.DataFrame({"Open": prices, "High": prices, "Low": prices,
                         "Close": prices, "Volume": [10_000] * len(prices)}, index=idx)


class NoopStrategy(Strategy):
    name = "noop"
    def warmup_days(self): return 0
    def generate_signals(self, date, ph, held): return []


class SellAllStrategy(Strategy):
    name = "sellall"
    def warmup_days(self): return 0
    def generate_signals(self, date, ph, held):
        return [Signal(t, "sell", 0.9, "ai-sell") for t in held]


# ---- 日次ライブ (live_paper) : 自動運用が使う本番経路 ----

def test_live_tp_zero_does_not_liquidate_winners(tmp_path, monkeypatch):
    """take_profit_pct=0 のとき、含み益ポジションを即日利確してはいけない"""
    monkeypatch.setattr("src.live_paper.STATE_DIR", tmp_path)
    from src import live_paper
    monkeypatch.setattr(live_paper, "_state_path", lambda: tmp_path / "pf.json")

    cfg = _cfg(take_profit_pct=0.0, trailing_stop_pct=0.15,
               stop_loss_pct=0.08, max_holding_days=250)
    pf = live_paper.init_portfolio(cfg)
    pf.buy("X.T", 100.0, 100, pd.Timestamp("2024-01-01"))
    live_paper.save_state(pf)

    # +5% の含み益 (トレーリングにも損切りにも該当しない)
    ph = {"X.T": _daily_bars([100.0, 105.0])}
    _, report = live_paper.run_one_day(cfg, NoopStrategy(), pd.Timestamp("2024-01-02"), ph)
    assert report.exits == [], f"tp=0で勝ちポジションを即決済した: {report.exits}"


def test_live_trailing_stop_fires(tmp_path, monkeypatch):
    """日次ライブでもトレーリングストップが機能する"""
    from src import live_paper
    monkeypatch.setattr(live_paper, "_state_path", lambda: tmp_path / "pf.json")

    cfg = _cfg(take_profit_pct=0.0, trailing_stop_pct=0.15,
               stop_loss_pct=0.5, max_holding_days=999)
    pf = live_paper.init_portfolio(cfg)
    pf.buy("X.T", 100.0, 100, pd.Timestamp("2024-01-01"))
    pf.positions["X.T"].peak_price = 150.0  # 150まで上昇済み
    live_paper.save_state(pf)

    # 150 → 120 (peak比 -20%、取得比 +20%) → トレーリング作動
    ph = {"X.T": _daily_bars([100.0, 120.0])}
    _, report = live_paper.run_one_day(cfg, NoopStrategy(), pd.Timestamp("2024-01-02"), ph)
    assert any("trailing_stop" in e["reason"] for e in report.exits)


def test_live_honor_strategy_sell_false_ignores_ai_sells(tmp_path, monkeypatch):
    """honor_strategy_sell=False なら戦略の売りシグナルを実行しない"""
    from src import live_paper
    monkeypatch.setattr(live_paper, "_state_path", lambda: tmp_path / "pf.json")

    cfg = _cfg(take_profit_pct=0.0, trailing_stop_pct=0.15,
               stop_loss_pct=0.5, max_holding_days=999, honor_strategy_sell=False)
    pf = live_paper.init_portfolio(cfg)
    pf.buy("X.T", 100.0, 100, pd.Timestamp("2024-01-01"))
    live_paper.save_state(pf)

    ph = {"X.T": _daily_bars([100.0, 105.0])}
    _, report = live_paper.run_one_day(cfg, SellAllStrategy(), pd.Timestamp("2024-01-02"), ph)
    assert report.executed_sells == []
    assert "X.T" in _reload_positions(tmp_path, cfg, monkeypatch)


def _reload_positions(tmp_path, cfg, monkeypatch):
    from src import live_paper
    return live_paper.load_or_init(cfg).positions


# ---- リアルタイム (realtime.execute_tick) : 準リアルタイム/本日シミュ共用 ----

def test_realtime_tp_zero_does_not_liquidate_winners(tmp_path, monkeypatch):
    monkeypatch.setattr("src.realtime.STATE_PATH", tmp_path / "rt.json")
    from src.realtime import execute_tick
    cfg = _cfg(take_profit_pct=0.0, trailing_stop_pct=0.15,
               stop_loss_pct=0.08, max_holding_days=250)
    pf = Portfolio(initial_capital=5_000_000)
    pf.buy("X.T", 100.0, 100, pd.Timestamp("2026-05-25 09:00"))

    bars = {"X.T": _minute_bars([100.0] * 30 + [105.0] * 10)}  # +5%
    now = datetime(2026, 5, 25, 10, 0, tzinfo=JST)
    tick = execute_tick(cfg, pf, bars, now)
    assert not any(e["side"] == "sell-risk" for e in tick.executed), \
        f"tp=0で勝ちポジションを即決済した: {tick.executed}"


def test_realtime_trailing_stop_fires(tmp_path, monkeypatch):
    monkeypatch.setattr("src.realtime.STATE_PATH", tmp_path / "rt.json")
    from src.realtime import execute_tick
    cfg = _cfg(take_profit_pct=0.0, trailing_stop_pct=0.15,
               stop_loss_pct=0.5, max_holding_days=999)
    pf = Portfolio(initial_capital=5_000_000)
    pf.buy("X.T", 100.0, 100, pd.Timestamp("2026-05-25 09:00"))
    pf.positions["X.T"].peak_price = 150.0

    bars = {"X.T": _minute_bars([100.0] * 30 + [120.0] * 10)}  # peak比-20%, 取得比+20%
    now = datetime(2026, 5, 25, 10, 0, tzinfo=JST)
    tick = execute_tick(cfg, pf, bars, now)
    assert any(e["side"] == "sell-risk" and "trailing" in e["reason"]
               for e in tick.executed)


def test_config_yaml_exit_policy_is_consistent():
    """config.yaml の決済ポリシーが全経路で成立する形になっているか"""
    cfg = load_config()
    # tp=0 なら trailing か max_holding のどちらかは有効でなければ出口がない
    if cfg.risk.take_profit_pct == 0:
        assert cfg.risk.trailing_stop_pct > 0 or cfg.risk.max_holding_days < 9999, \
            "固定利確なしなのに代替出口(トレーリング/最大保有)が無い"
