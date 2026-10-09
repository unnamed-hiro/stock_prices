"""NaN汚染防止のテスト — 状態JSONの不正化 (iPhoneアプリが読めなくなる事故) の再発防止

実際に起きた事故: yfinance が特定銘柄の終値を NaN で返した日、評価額が
現金+NaN=NaN となり portfolio.json に JSON仕様違反の `NaN` が書き込まれ、
厳格なデコーダ (Swift の JSONDecoder 等) が読めなくなった。
"""
import json
import math
import numpy as np
import pandas as pd
import pytest

from src.config import load_config
from src.portfolio import Portfolio
from src.strategies.base import Strategy


class NoopStrategy(Strategy):
    name = "noop"
    def warmup_days(self): return 0
    def generate_signals(self, d, ph, h): return []


def _bars_with_nan_tail():
    """最終日の終値が NaN (データ欠損) の価格データ"""
    idx = pd.date_range("2024-01-01", periods=10, freq="B")
    close = [100.0] * 9 + [np.nan]
    return pd.DataFrame({"Open": close, "High": close, "Low": close,
                         "Close": close, "Volume": [1_000] * 10}, index=idx)


def test_close_on_skips_nan():
    """_close_on は NaN を返さず、直近の有効な終値にフォールバックする"""
    from src.live_paper import _close_on
    df = _bars_with_nan_tail()
    v = _close_on(df, df.index[-1])
    assert v == 100.0  # 前日の有効値


def test_record_equity_never_records_nonfinite():
    pf = Portfolio(initial_capital=1_000_000)
    pf.record_equity(pd.Timestamp("2024-01-01"), {})
    pf.cash = float("nan")
    pf.record_equity(pd.Timestamp("2024-01-02"), {})  # 記録されない
    assert len(pf.equity_curve) == 1
    assert all(math.isfinite(v) for _, v in pf.equity_curve)


def test_live_state_json_is_strict_parseable_with_nan_prices(tmp_path, monkeypatch):
    """終値NaNの銘柄を保有していても、保存される状態JSONは仕様違反にならない"""
    from src import live_paper
    monkeypatch.setattr(live_paper, "_state_path", lambda: tmp_path / "pf.json")
    monkeypatch.setattr(live_paper, "_pending_path", lambda: tmp_path / "pend.json")

    cfg = load_config()
    cfg.risk.regime_filter = False
    pf = live_paper.init_portfolio(cfg)
    pf.buy("X.T", 100.0, 100, pd.Timestamp("2024-01-01"))
    live_paper.save_state(pf)

    ph = {"X.T": _bars_with_nan_tail()}
    pf, report = live_paper.run_one_day(cfg, NoopStrategy(), ph["X.T"].index[-1], ph)
    live_paper.save_state(pf)

    raw = (tmp_path / "pf.json").read_text(encoding="utf-8")
    assert "NaN" not in raw and "Infinity" not in raw
    # 厳格パーサ相当: NaN/Infinity を拒否して読めること
    def reject(x): raise ValueError(f"invalid JSON constant: {x}")
    data = json.loads(raw, parse_constant=reject)
    assert all(math.isfinite(v) for _, v in data["equity_curve"])
    # レポートの評価額も有限
    assert math.isfinite(report.ending_equity)


def test_committed_state_files_have_no_nan():
    """リポジトリにコミット済みの状態/結果JSONに NaN が残っていないこと"""
    import glob, re
    from pathlib import Path
    for f in ["data/state/portfolio.json"] + glob.glob("results/daily/*.json"):
        if Path(f).exists():
            raw = Path(f).read_text(encoding="utf-8")
            assert not re.search(r"\bNaN\b|\bInfinity\b", raw), f"{f} にNaN残存"
