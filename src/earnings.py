"""決算またぎ回避 — 決算発表直前の新規買いを見送る

決算発表をまたぐ保有は、一晩で±10%動き得る「博打」になる。本モジュールは
買い候補の銘柄について次回決算日を調べ、発表が近い場合のエントリーを見送る。

設計方針:
- データ源: yfinance の決算カレンダー。銘柄ごとに 7日間ローカルキャッシュ
  (data/cache/earnings_dates.json) し、買い候補の銘柄だけを遅延取得する
  (全400銘柄の一括取得はAPI負荷と実行時間の点で現実的でないため)。
- fail-open: 決算日が取得できない銘柄は「制限なし」として扱う。
  データ障害でシステム全体の取引が止まる事態を避ける。日本株の決算日は
  yfinance でのカバレッジが不完全なため、これは「わかる範囲で避ける」保険。
- バックテストには適用しない: 過去の決算日履歴は無料データでは数四半期分
  しか得られず、部分適用すると「古い期間ほど制限なし」の歪みが入るため。
"""
from __future__ import annotations
import json
import time
from pathlib import Path

import pandas as pd

CACHE_PATH = Path("data/cache/earnings_dates.json")
CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7日


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict):
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass  # キャッシュ保存失敗は致命的でない


def _fetch_next_earnings(ticker: str) -> str | None:
    """yfinance から次回決算日 (ISO文字列) を取得。失敗/不明は None。"""
    try:
        import yfinance as yf
        cal = yf.Ticker(ticker).calendar
        # yfinance>=0.2 は dict を返す: {"Earnings Date": [date, ...], ...}
        if isinstance(cal, dict):
            dates = cal.get("Earnings Date") or []
            if dates:
                return str(pd.Timestamp(dates[0]).date())
        elif cal is not None and len(cal) > 0:  # 旧API (DataFrame)
            v = cal.loc["Earnings Date"].iloc[0]
            return str(pd.Timestamp(v).date())
    except Exception:
        return None
    return None


def next_earnings_date(ticker: str, now: float | None = None) -> pd.Timestamp | None:
    """次回決算日を返す (7日キャッシュ付き)。不明なら None。"""
    now = now if now is not None else time.time()
    cache = _load_cache()
    ent = cache.get(ticker)
    if ent and now - ent.get("fetched_at", 0) < CACHE_TTL_SECONDS:
        raw = ent.get("date")
        return pd.Timestamp(raw) if raw else None
    date = _fetch_next_earnings(ticker)
    cache[ticker] = {"date": date, "fetched_at": now}
    _save_cache(cache)
    return pd.Timestamp(date) if date else None


def in_earnings_blackout(ticker: str, date: pd.Timestamp,
                         blackout_days: int) -> bool:
    """date 時点で「決算発表まで blackout_days 日以内」なら True (買い見送り)。

    決算日が不明なら False (fail-open)。発表当日と翌日も True とし、
    発表直後のギャップ変動が落ち着くまで待つ。
    """
    if blackout_days <= 0:
        return False
    edate = next_earnings_date(ticker)
    if edate is None:
        return False
    delta = (edate.normalize() - date.normalize()).days
    return -1 <= delta <= blackout_days
