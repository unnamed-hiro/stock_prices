"""小資金モード (単元未満株+積立) と月次レポートのテスト"""
import json
import numpy as np
import pandas as pd
import pytest

from src.config import load_config
from src.portfolio import Portfolio
from src.risk_engine import size_position
from src.metrics import compute_metrics
from src.monthly_report import build_monthly_report, format_monthly_report
from src.strategies.base import Strategy, Signal


def _risk(**over):
    r = load_config().risk
    r.sizing_mode = "fixed"
    for k, v in over.items():
        setattr(r, k, v)
    return r


# ---------------- 単元未満株 (lot_size) ----------------

def test_lot_size_1_enables_small_capital():
    """50万円×10%=5万円の予算でも lot_size=1 なら株価6,000円の銘柄を買える"""
    r = _risk(position_size_pct=0.10, min_cash_reserve_pct=0.0)
    lot100 = size_position(6000.0, 500_000, 500_000, r, base_equity=500_000, lot_size=100)
    lot1 = size_position(6000.0, 500_000, 500_000, r, base_equity=500_000, lot_size=1)
    assert lot100 == 0          # 単元株では1株も買えない (60万円必要)
    assert lot1 == 8            # 5万円予算 // 6,000円 = 8株


def test_lot_size_100_unchanged():
    """既定 lot_size=100 は従来と同じ挙動 (後方互換)"""
    r = _risk(position_size_pct=0.10, min_cash_reserve_pct=0.0)
    shares = size_position(1000.0, 10_000_000, 10_000_000, r,
                           base_equity=10_000_000, lot_size=100)
    assert shares == 1000 and shares % 100 == 0


def test_backtest_small_capital_with_lot1_trades():
    """バックテスト統合: 50万円でも lot_size=1 なら取引が成立する"""
    from src.backtester import run_backtest

    class AlwaysBuy(Strategy):
        name = "ab"
        def warmup_days(self): return 0
        def generate_signals(self, date, ph, held):
            return [Signal(t, "buy", 0.9, "t") for t in ph if t not in held]

    idx = pd.date_range("2024-01-01", periods=60, freq="B")
    px = np.linspace(6000, 6600, 60)
    ph = {"X.T": pd.DataFrame({"Open": px, "High": px * 1.01, "Low": px * 0.99,
                               "Close": px, "Volume": [10_000] * 60}, index=idx)}
    cfg = load_config()
    cfg.simulation.initial_capital = 500_000
    cfg.simulation.start_date = "2024-01-01"
    cfg.simulation.end_date = str(idx[-1].date())
    cfg.risk.regime_filter = False

    cfg.simulation.lot_size = 100
    pf100 = run_backtest(cfg, AlwaysBuy(), ph, verbose=False)
    cfg.simulation.lot_size = 1
    pf1 = run_backtest(cfg, AlwaysBuy(), ph, verbose=False)
    assert len(pf100.trades) == 0
    assert len(pf1.trades) > 0


# ---------------- 積立入金 ----------------

def test_deposit_not_counted_as_profit():
    """入金で残高が増えてもリターンは0%のまま"""
    pf = Portfolio(initial_capital=300_000)
    d1, d2 = pd.Timestamp("2024-01-31"), pd.Timestamp("2024-02-29")
    pf.record_equity(d1, {})
    pf.deposit(30_000, d2)
    pf.record_equity(d2, {})
    m = compute_metrics(pf)
    assert m.total_return_pct == pytest.approx(0.0, abs=0.01)
    # 入金日のジャンプ(+10%)がシャープに乗っていないこと
    assert abs(m.sharpe) < 0.01


def test_backtester_monthly_deposit_once_per_month():
    from src.backtester import run_backtest

    class Noop(Strategy):
        name = "noop"
        def warmup_days(self): return 0
        def generate_signals(self, d, ph, h): return []

    idx = pd.date_range("2024-01-01", "2024-03-29", freq="B")  # 3ヶ月
    px = np.full(len(idx), 1000.0)
    ph = {"X.T": pd.DataFrame({"Open": px, "High": px, "Low": px,
                               "Close": px, "Volume": [1_000] * len(idx)}, index=idx)}
    cfg = load_config()
    cfg.simulation.initial_capital = 300_000
    cfg.simulation.monthly_deposit = 30_000
    cfg.simulation.start_date = "2024-01-01"
    cfg.simulation.end_date = "2024-03-29"
    pf = run_backtest(cfg, Noop(), ph, verbose=False)
    # 初月スキップ → 2月・3月の2回入金
    assert pf.total_deposits == 60_000
    assert pf.cash == 360_000


def test_live_monthly_deposit_and_persistence(tmp_path, monkeypatch):
    from src import live_paper

    class Noop(Strategy):
        name = "noop"
        def warmup_days(self): return 0
        def generate_signals(self, d, ph, h): return []

    monkeypatch.setattr(live_paper, "_state_path", lambda: tmp_path / "pf.json")
    monkeypatch.setattr(live_paper, "_pending_path", lambda: tmp_path / "pend.json")
    cfg = load_config()
    cfg.simulation.initial_capital = 300_000
    cfg.simulation.monthly_deposit = 30_000
    cfg.risk.regime_filter = False

    idx = pd.date_range("2024-01-25", periods=10, freq="B")
    px = np.full(10, 1000.0)
    ph = {"X.T": pd.DataFrame({"Open": px, "High": px, "Low": px,
                               "Close": px, "Volume": [1_000] * 10}, index=idx)}
    # 1月の実行 → 入金なし (開始月)
    pf, _ = live_paper.run_one_day(cfg, Noop(), pd.Timestamp("2024-01-26"), ph)
    live_paper.save_state(pf)
    assert pf.total_deposits == 0
    # 2月最初の実行 → 1回入金
    pf, _ = live_paper.run_one_day(cfg, Noop(), pd.Timestamp("2024-02-01"), ph)
    live_paper.save_state(pf)
    assert pf.total_deposits == 30_000
    # 同月2回目 → 入金されない
    pf, _ = live_paper.run_one_day(cfg, Noop(), pd.Timestamp("2024-02-02"), ph)
    live_paper.save_state(pf)
    assert pf.total_deposits == 30_000
    # 永続化の往復
    pf2 = live_paper.load_or_init(cfg)
    assert pf2.total_deposits == 30_000 and len(pf2.deposit_log) == 1


# ---------------- 月次レポート ----------------

def _fake_state():
    return {
        "initial_capital": 300_000,
        "total_deposits": 30_000,
        "deposit_log": [["2024-02-01", 30_000]],
        "equity_curve": [["2024-01-31", 310_000],
                         ["2024-02-15", 345_000],
                         ["2024-02-29", 352_000]],
        "trades": [
            {"ticker": "A.T", "side": "sell", "shares": 10, "price": 1100,
             "date": "2024-02-10", "pnl": 5_000, "holding_days": 20},
            {"ticker": "B.T", "side": "sell", "shares": 5, "price": 900,
             "date": "2024-02-20", "pnl": -2_000, "holding_days": 10},
        ],
    }


def test_monthly_report_corrects_for_deposit():
    dailies = [
        {"date": "2024-02-05", "regime": "risk_off", "skipped": [], "executed_buys": [],
         "executed_sells": [], "exits": []},
        {"date": "2024-02-06", "regime": "risk_on",
         "skipped": [{"ticker": "C.T", "reason": "決算発表が3日以内のため見送り"}],
         "executed_buys": [{"ticker": "A.T"}], "executed_sells": [], "exits": []},
    ]
    r = build_monthly_report(_fake_state(), dailies, "2024-02")
    # 利益 = 352,000 - 310,000 - 30,000(入金) = +12,000円
    assert r["profit"] == pytest.approx(12_000)
    assert r["month_return_pct"] == pytest.approx(12_000 / 310_000 * 100)
    assert r["n_closed"] == 2 and r["win_rate_pct"] == pytest.approx(50.0)
    assert r["risk_off_days"] == 1
    assert r["earnings_skips"] == 1
    md = format_monthly_report(r)
    assert "月次運用レポート 2024-02" in md and "+12,000円" in md


def test_monthly_report_no_data_month():
    with pytest.raises(ValueError):
        build_monthly_report(_fake_state(), [], "2023-01")
