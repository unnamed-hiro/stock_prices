"""ウォークフォワード検証のテスト"""
import numpy as np
import pandas as pd
import pytest

from src.config import load_config
from src.walkforward import split_windows, run_walkforward


def test_split_windows_covers_full_range_without_overlap():
    start = pd.Timestamp("2023-01-01")
    end = pd.Timestamp("2024-12-31")
    ws = split_windows(start, end, 4)
    assert len(ws) == 4
    assert ws[0][0] == start
    assert ws[-1][1] == end
    for i in range(1, 4):
        # 前ウィンドウの終わりの翌日から次が始まる (重複なし・隙間なし)
        assert ws[i][0] == ws[i - 1][1] + pd.Timedelta(days=1)
    for s, e in ws:
        assert s < e


def test_split_windows_single():
    ws = split_windows(pd.Timestamp("2023-01-01"), pd.Timestamp("2023-12-31"), 1)
    assert len(ws) == 1


def test_split_windows_invalid():
    with pytest.raises(ValueError):
        split_windows(pd.Timestamp("2023-01-01"), pd.Timestamp("2023-12-31"), 0)


def _uptrend_data():
    idx = pd.date_range("2023-01-01", "2024-12-31", freq="B")
    n = len(idx)
    rng = np.random.default_rng(7)
    prices = 1000 * np.cumprod(1 + rng.normal(0.0005, 0.01, n))
    return {"X.T": pd.DataFrame({
        "Open": prices, "High": prices * 1.01, "Low": prices * 0.99,
        "Close": prices, "Volume": rng.integers(5_000, 50_000, n),
    }, index=idx)}


def test_run_walkforward_returns_per_window_results():
    cfg = load_config()
    cfg.simulation.start_date = "2023-01-01"
    cfg.simulation.end_date = "2024-12-31"
    ph = _uptrend_data()
    s = run_walkforward(cfg, "technical", ph, n_windows=3)
    assert s["n_windows"] == 3
    assert len(s["windows"]) == 3
    for w in s["windows"]:
        assert "alpha_pct" in w and "return_pct" in w and "sharpe" in w
    # consistent は「全ウィンドウでα>0」と厳密に一致する
    assert s["consistent"] == (s["n_windows_alpha_positive"] == 3)


def test_run_walkforward_windows_are_independent():
    """ウィンドウ間で口座が引き継がれない (各回 初期資金からスタート)"""
    cfg = load_config()
    cfg.simulation.start_date = "2023-01-01"
    cfg.simulation.end_date = "2024-12-31"
    ph = _uptrend_data()
    s = run_walkforward(cfg, "technical", ph, n_windows=2)
    # 各ウィンドウのリターンは初期資金基準の% (口座継続なら複利で桁が変わる)
    for w in s["windows"]:
        assert -100 < w["return_pct"] < 500
