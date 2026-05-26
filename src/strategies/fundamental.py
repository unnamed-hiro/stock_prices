"""ファンダメンタルズ戦略

yfinanceから財務指標 (PER, PBR, ROE, 配当利回り) を取得し、
「割安かつ質が高い」銘柄を高スコアと判定する。

【重要な制約 — 先読みバイアス】
yfinanceで取得できる財務指標は「現在の値」のみで、過去時点の財務は取れない。
そのためバックテスト(過去日付)では現在のファンダを過去に適用することになり、
厳密には先読みバイアス(look-ahead bias)が入る。
ライブ運用・本日判断では現在のファンダで現在判断するため問題ない。
"""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from .base import Strategy, Signal

FUND_CACHE = Path("data/cache/fundamentals.json")


def _load_cache() -> dict:
    if FUND_CACHE.exists():
        try:
            return json.loads(FUND_CACHE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict):
    FUND_CACHE.parent.mkdir(parents=True, exist_ok=True)
    FUND_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2),
                          encoding="utf-8")


def _fetch_one(ticker: str) -> dict | None:
    """yfinanceから1銘柄の財務指標を取得。失敗時はNone。"""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        return {
            "trailingPE": info.get("trailingPE"),
            "priceToBook": info.get("priceToBook"),
            "returnOnEquity": info.get("returnOnEquity"),
            "dividendYield": info.get("dividendYield"),
            "marketCap": info.get("marketCap"),
        }
    except Exception:
        return None


class FundamentalStrategy(Strategy):
    """割安(PER/PBR低) かつ 質が高い(ROE高) 銘柄を選好する"""

    name = "fundamental"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self.max_per = self.params.get("max_per", 25.0)
        self.max_pbr = self.params.get("max_pbr", 3.0)
        self.min_roe = self.params.get("min_roe", 0.08)
        self.buy_score = self.params.get("buy_score", 0.6)
        self.sell_score = self.params.get("sell_score", 0.3)
        # テスト/オフライン用に財務データを直接注入できる
        self._injected = self.params.get("fundamentals")
        self._cache = None

    def warmup_days(self) -> int:
        return 20

    def _get_fundamentals(self, tickers: list[str]) -> dict:
        if self._injected is not None:
            return self._injected
        if self._cache is None:
            self._cache = _load_cache()
        missing = [t for t in tickers if t not in self._cache]
        if missing:
            updated = False
            for t in missing:
                data = _fetch_one(t)
                if data is not None:
                    self._cache[t] = data
                    updated = True
            if updated:
                _save_cache(self._cache)
        return self._cache

    def score(self, f: dict) -> float | None:
        """財務指標から 0〜1 のスコアを算出。判定不能なら None。"""
        parts: list[float] = []
        per = f.get("trailingPE")
        if per is not None and per > 0:
            parts.append(max(0.0, min(1.0, (self.max_per - per) / self.max_per)))
        pbr = f.get("priceToBook")
        if pbr is not None and pbr > 0:
            parts.append(max(0.0, min(1.0, (self.max_pbr - pbr) / self.max_pbr)))
        roe = f.get("returnOnEquity")
        if roe is not None:
            parts.append(max(0.0, min(1.0, roe / (self.min_roe * 2))))
        dy = f.get("dividendYield")
        if dy is not None and dy > 0:
            parts.append(min(1.0, dy / 0.04))  # 配当利回り4%で満点
        if not parts:
            return None
        return sum(parts) / len(parts)

    def generate_signals(
        self,
        date: pd.Timestamp,
        price_history: dict[str, pd.DataFrame],
        held_tickers: set[str],
    ) -> list[Signal]:
        tickers = list(price_history.keys())
        funds = self._get_fundamentals(tickers)
        signals: list[Signal] = []
        for t in tickers:
            f = funds.get(t)
            if not f:
                continue
            sc = self.score(f)
            if sc is None:
                continue
            per = f.get("trailingPE")
            pbr = f.get("priceToBook")
            roe = f.get("returnOnEquity")
            detail = (f"score={sc:.2f} PER={per if per else '-'} "
                      f"PBR={pbr if pbr else '-'} "
                      f"ROE={roe*100:.0f}%" if roe is not None else f"score={sc:.2f}")
            if t in held_tickers:
                if sc <= self.sell_score:
                    signals.append(Signal(t, "sell", confidence=1 - sc,
                                          reason=f"割高/低質 {detail}"))
            else:
                if sc >= self.buy_score:
                    signals.append(Signal(t, "buy", confidence=sc,
                                          reason=f"割安/高質 {detail}"))
        return signals
