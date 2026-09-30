"""リスクエンジン (レジームフィルター+ATRサイジング) のテスト"""
import numpy as np
import pandas as pd
import pytest

from src.config import load_config
from src.portfolio import Portfolio
from src.risk_engine import (
    compute_atr, build_market_index, build_regime_series, regime_on, size_position,
)
from src.strategies.base import Strategy, Signal


def _risk(**over):
    r = load_config().risk
    for k, v in over.items():
        setattr(r, k, v)
    return r


def _bars(closes, spread=0.0):
    idx = pd.date_range("2023-01-01", periods=len(closes), freq="B")
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"Open": c, "High": c * (1 + spread), "Low": c * (1 - spread),
                         "Close": c, "Volume": [10_000] * len(c)})


# ---------------- ATR ----------------

def test_compute_atr_constant_range():
    """毎日値幅が一定なら ATR はその値幅に一致する"""
    df = _bars([100.0] * 40, spread=0.02)  # High=102, Low=98 → TR=4
    atr = compute_atr(df, df.index[-1], period=14)
    assert atr == pytest.approx(4.0, rel=0.01)


def test_compute_atr_insufficient_data():
    df = _bars([100.0] * 5, spread=0.02)
    assert compute_atr(df, df.index[-1], period=14) is None


def test_compute_atr_no_lookahead():
    """date より後のデータは ATR に影響しない"""
    quiet = _bars([100.0] * 60, spread=0.01)
    mid = quiet.index[39]
    wild = quiet.copy()
    wild.loc[wild.index[40]:, "High"] = 130.0  # 後半だけ荒れる
    assert compute_atr(quiet, mid) == pytest.approx(compute_atr(wild, mid))


# ---------------- レジームフィルター ----------------

def _crash_universe():
    """前半上昇→後半暴落のユニバース (2銘柄)"""
    up = list(np.linspace(100, 200, 150))
    down = list(np.linspace(200, 80, 100))
    return {"A.T": _bars(up + down), "B.T": _bars([x * 2 for x in up + down])}


def test_regime_turns_off_in_crash():
    ph = _crash_universe()
    regime = build_regime_series(ph, ma_days=50)
    dates = list(ph["A.T"].index)
    assert regime_on(regime, dates[140]) is True    # 上昇中はリスクオン
    assert regime_on(regime, dates[-1]) is False    # 暴落後はリスクオフ


def test_regime_defaults_on_when_history_short():
    """MA日数に満たない期間はリスクオン扱い (機会を奪わない)"""
    ph = {"A.T": _bars(list(np.linspace(100, 120, 60)))}
    regime = build_regime_series(ph, ma_days=200)
    assert regime_on(regime, ph["A.T"].index[-1]) is True


def test_regime_on_empty_series_is_safe():
    assert regime_on(pd.Series(dtype=bool), pd.Timestamp("2024-01-01")) is True


# ---------------- ボラティリティ・サイジング ----------------

def test_vol_sizing_math():
    """想定損失(株数×ATR×倍率)が資産×risk_per_trade に一致する株数"""
    r = _risk(sizing_mode="volatility", risk_per_trade_pct=0.01,
              atr_stop_multiple=2.0, position_size_pct=0.50,
              min_cash_reserve_pct=0.0)
    # 資産1000万, 許容損失10万, ATR=50 → 損切り幅100円/株 → 1000株
    shares = size_position(price=1000.0, cash=10_000_000, initial_capital=10_000_000,
                           risk=r, base_equity=10_000_000, atr_value=50.0)
    assert shares == 1000


def test_vol_sizing_smaller_for_wilder_stock():
    """ボラが2倍なら投入株数は半分になる"""
    r = _risk(sizing_mode="volatility", risk_per_trade_pct=0.01,
              atr_stop_multiple=2.0, position_size_pct=0.50,
              min_cash_reserve_pct=0.0)
    calm = size_position(1000.0, 10_000_000, 10_000_000, r,
                         base_equity=10_000_000, atr_value=25.0)
    wild = size_position(1000.0, 10_000_000, 10_000_000, r,
                         base_equity=10_000_000, atr_value=50.0)
    assert calm == 2 * wild


def test_vol_sizing_capped_by_position_size_pct():
    """ATRが極端に小さくても position_size_pct を超えない"""
    r = _risk(sizing_mode="volatility", risk_per_trade_pct=0.01,
              atr_stop_multiple=2.0, position_size_pct=0.10,
              min_cash_reserve_pct=0.0)
    shares = size_position(1000.0, 10_000_000, 10_000_000, r,
                           base_equity=10_000_000, atr_value=0.5)
    assert shares * 1000.0 <= 10_000_000 * 0.10


def test_vol_sizing_falls_back_to_fixed_without_atr():
    r = _risk(sizing_mode="volatility", position_size_pct=0.10,
              min_cash_reserve_pct=0.0)
    with_none = size_position(1000.0, 10_000_000, 10_000_000, r,
                              base_equity=10_000_000, atr_value=None)
    r2 = _risk(sizing_mode="fixed", position_size_pct=0.10, min_cash_reserve_pct=0.0)
    fixed = size_position(1000.0, 10_000_000, 10_000_000, r2, base_equity=10_000_000)
    assert with_none == fixed > 0


# ---------------- バックテスター統合 ----------------

class AlwaysBuyStrategy(Strategy):
    name = "alwaysbuy"
    def warmup_days(self): return 0
    def generate_signals(self, date, ph, held):
        return [Signal(t, "buy", 0.9, "test") for t in ph if t not in held]


def test_backtester_regime_filter_blocks_buys_in_crash():
    from src.backtester import run_backtest
    cfg = load_config()
    ph = _crash_universe()
    dates = ph["A.T"].index
    # 暴落後期のみをテスト期間に (レジームは全履歴から判定される)
    cfg.simulation.start_date = str(dates[200].date())
    cfg.simulation.end_date = str(dates[-1].date())
    cfg.risk.regime_filter = True
    cfg.risk.regime_ma_days = 50
    pf = run_backtest(cfg, AlwaysBuyStrategy(), ph, verbose=False)
    assert len(pf.trades) == 0, "リスクオフ期間に買ってはいけない"

    cfg2 = load_config()
    cfg2.simulation.start_date = str(dates[200].date())
    cfg2.simulation.end_date = str(dates[-1].date())
    cfg2.risk.regime_filter = False
    pf2 = run_backtest(cfg2, AlwaysBuyStrategy(), ph, verbose=False)
    assert len(pf2.trades) > 0, "フィルター無効なら買うはず"


# ---------------- 日次ライブ統合 ----------------

def test_live_regime_off_skips_buys_and_reports(tmp_path, monkeypatch):
    from src import live_paper
    monkeypatch.setattr(live_paper, "_state_path", lambda: tmp_path / "pf.json")
    monkeypatch.setattr(live_paper, "_pending_path", lambda: tmp_path / "pend.json")
    cfg = load_config()
    cfg.risk.regime_filter = True
    cfg.risk.regime_ma_days = 50
    ph = _crash_universe()
    date = ph["A.T"].index[-1]  # 暴落後 = リスクオフ
    _, report = live_paper.run_one_day(cfg, AlwaysBuyStrategy(), date, ph)
    assert report.regime == "risk_off"
    assert not any(o["side"] == "buy" for o in report.planned_orders)
    assert any("レジームオフ" in s["reason"] for s in report.skipped)


def test_live_buy_order_carries_atr(tmp_path, monkeypatch):
    """volatilityモードでは買い注文にATRが添付され持ち越される"""
    from src import live_paper
    monkeypatch.setattr(live_paper, "_state_path", lambda: tmp_path / "pf.json")
    monkeypatch.setattr(live_paper, "_pending_path", lambda: tmp_path / "pend.json")
    cfg = load_config()
    cfg.risk.regime_filter = False
    cfg.risk.sizing_mode = "volatility"
    ph = {"A.T": _bars(list(np.linspace(100, 150, 80)), spread=0.02)}
    date = ph["A.T"].index[-1]
    _, report = live_paper.run_one_day(cfg, AlwaysBuyStrategy(), date, ph)
    buys = [o for o in report.planned_orders if o["side"] == "buy"]
    assert buys and buys[0].get("atr") is not None and buys[0]["atr"] > 0
    # 保存された注文にも ATR が乗っている (翌日約定時に使われる)
    assert live_paper.load_pending()["orders"][0].get("atr") == buys[0]["atr"]
