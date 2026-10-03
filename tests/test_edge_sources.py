"""優先度3 (エッジの源泉) のテスト — 決算またぎ回避 / LLMニュース解析"""
import numpy as np
import pandas as pd
import pytest

from src.config import load_config
from src import earnings
from src.strategies.base import Strategy, Signal


def _bars(closes):
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="B")
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99,
                         "Close": c, "Volume": [10_000] * len(c)})


class AlwaysBuyStrategy(Strategy):
    name = "alwaysbuy"
    def warmup_days(self): return 0
    def generate_signals(self, date, ph, held):
        return [Signal(t, "buy", 0.9, "test") for t in ph if t not in held]


# ---------------- 決算またぎ回避 ----------------

def test_blackout_boundaries(monkeypatch):
    monkeypatch.setattr(earnings, "next_earnings_date",
                        lambda t: pd.Timestamp("2024-06-10"))
    # 3日前〜翌日は True、それ以外は False
    assert earnings.in_earnings_blackout("X.T", pd.Timestamp("2024-06-07"), 3) is True
    assert earnings.in_earnings_blackout("X.T", pd.Timestamp("2024-06-10"), 3) is True
    assert earnings.in_earnings_blackout("X.T", pd.Timestamp("2024-06-11"), 3) is True   # 発表翌日
    assert earnings.in_earnings_blackout("X.T", pd.Timestamp("2024-06-06"), 3) is False  # 4日前
    assert earnings.in_earnings_blackout("X.T", pd.Timestamp("2024-06-12"), 3) is False  # 発表2日後


def test_blackout_fail_open_when_unknown(monkeypatch):
    """決算日が取得できない銘柄は制限なし (データ障害で取引を止めない)"""
    monkeypatch.setattr(earnings, "next_earnings_date", lambda t: None)
    assert earnings.in_earnings_blackout("X.T", pd.Timestamp("2024-06-09"), 3) is False


def test_blackout_disabled_with_zero():
    assert earnings.in_earnings_blackout("X.T", pd.Timestamp("2024-06-09"), 0) is False


def test_earnings_cache_roundtrip(tmp_path, monkeypatch):
    """取得結果は7日キャッシュされ、2回目はネットワークに行かない"""
    monkeypatch.setattr(earnings, "CACHE_PATH", tmp_path / "e.json")
    calls = []
    monkeypatch.setattr(earnings, "_fetch_next_earnings",
                        lambda t: calls.append(t) or "2024-06-10")
    d1 = earnings.next_earnings_date("X.T", now=1000.0)
    d2 = earnings.next_earnings_date("X.T", now=2000.0)  # TTL内
    assert d1 == d2 == pd.Timestamp("2024-06-10")
    assert calls == ["X.T"]
    # TTL切れで再取得
    earnings.next_earnings_date("X.T", now=1000.0 + 8 * 86400)
    assert calls == ["X.T", "X.T"]


def test_live_skips_buy_in_blackout(tmp_path, monkeypatch):
    """日次ライブ: 決算直前の銘柄は買い注文を出さず、見送り理由を記録する"""
    from src import live_paper
    monkeypatch.setattr(live_paper, "_state_path", lambda: tmp_path / "pf.json")
    monkeypatch.setattr(live_paper, "_pending_path", lambda: tmp_path / "pend.json")
    ph = {"NEAR.T": _bars([100.0] * 40), "FAR.T": _bars([100.0] * 40)}
    date = ph["NEAR.T"].index[-1]
    monkeypatch.setattr(
        earnings, "next_earnings_date",
        lambda t: date + pd.Timedelta(days=2) if t == "NEAR.T" else None)

    cfg = load_config()
    cfg.risk.regime_filter = False
    cfg.risk.earnings_blackout_days = 3
    _, report = live_paper.run_one_day(cfg, AlwaysBuyStrategy(), date, ph)
    planned_buy_tickers = {o["ticker"] for o in report.planned_orders if o["side"] == "buy"}
    assert "FAR.T" in planned_buy_tickers
    assert "NEAR.T" not in planned_buy_tickers
    assert any("決算" in s["reason"] for s in report.skipped)


# ---------------- LLMニュース解析 ----------------

def test_summarize_includes_news():
    from src.strategies.llm import _summarize
    df = _bars([100.0] * 40)
    news = [{"title": "上方修正を発表", "published": "2024-02-20"}]
    d = _summarize("X.T", df, news)
    assert d["news"] == news
    d2 = _summarize("X.T", df, None)
    assert "news" not in d2


def test_llm_news_only_in_live_mode(monkeypatch):
    """ニュースは判断日が現在±3日以内のときだけ取得 (過去日付=バックテストでは先読み防止)"""
    from src.strategies import llm as llm_mod
    fetched = []
    monkeypatch.setattr(llm_mod, "_fetch_news",
                        lambda t, n: fetched.append(t) or [])
    captured = {}

    strat = llm_mod.LLMStrategy({"use_news": True})
    monkeypatch.setattr(strat, "_ask",
                        lambda date, batch: captured.setdefault("batch", batch) and [] or [])

    n = 40
    today = pd.Timestamp.now().normalize()
    idx = pd.bdate_range(end=today, periods=n)
    df = pd.DataFrame({"Open": [100.0]*n, "High": [101.0]*n, "Low": [99.0]*n,
                       "Close": [100.0]*n, "Volume": [10_000]*n}, index=idx)

    # ライブ (判断日=今日) → ニュース取得する
    strat.generate_signals(today, {"X.T": df}, set())
    assert fetched == ["X.T"]

    # バックテスト (判断日=過去) → ニュース取得しない
    fetched.clear()
    past = today - pd.Timedelta(days=400)
    idx2 = pd.bdate_range(end=past, periods=n)
    df2 = df.copy(); df2.index = idx2
    strat.generate_signals(past, {"X.T": df2}, set())
    assert fetched == []


def test_ensemble_skips_llm_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from src.strategies.ensemble import EnsembleStrategy
    e = EnsembleStrategy({"ensemble": {"members": ["technical", "llm"]}})
    assert "llm" not in e.members and "technical" in e.members


def test_ensemble_includes_llm_with_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-dummy")
    from src.strategies.ensemble import EnsembleStrategy
    e = EnsembleStrategy({"ensemble": {"members": ["technical", "llm"]}})
    assert "llm" in e.members
