"""本日(または指定日)のイントラデイ・トレードシミュレーション

その日の1分足を時系列で先頭から再生し、各時点で「その時点までの情報だけ」で
AIに判断させて売買する。引け後に実行すれば1日分を即座に再現できる。

準リアルタイム(realtime.py)との違い:
  - realtime: 5分ごとに待ちながら最新足で判断 (ライブ運用)
  - intraday : 確定した1日分の1分足を一気にリプレイ (検証・実験)

本番のリアルタイム口座(realtime_portfolio.json)には一切触れない。
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
import yfinance as yf

from .portfolio import Portfolio
from .config import AppConfig
from .realtime import execute_tick, JST

INTRADAY_DIR = Path("results/intraday")


def fetch_intraday_day(tickers: list[str], date: str | None = None) -> dict[str, pd.DataFrame]:
    """指定日(YYYY-MM-DD)の1分足を取得。date=None なら本日。
    yfinanceの1分足は直近約7日のみ取得可能。"""
    out: dict[str, pd.DataFrame] = {}
    if date is None:
        dl_kwargs = dict(period="1d")
    else:
        d = pd.Timestamp(date)
        dl_kwargs = dict(start=d.strftime("%Y-%m-%d"),
                         end=(d + timedelta(days=1)).strftime("%Y-%m-%d"))
    for t in tickers:
        try:
            df = yf.download(t, interval="1m", progress=False,
                             auto_adjust=True, prepost=False, **dl_kwargs)
            if df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            out[t] = df
        except Exception as e:
            print(f"  [warn] {t}: {e}")
    return out


@dataclass
class IntradayResult:
    date: str
    n_tickers: int
    n_bars: int
    starting_equity: float
    ending_equity: float
    eod_close: bool
    equity_curve: list[tuple[str, float]] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)
    final_positions: list[dict] = field(default_factory=list)

    @property
    def pnl(self) -> float:
        return self.ending_equity - self.starting_equity

    @property
    def pnl_pct(self) -> float:
        return self.pnl / self.starting_equity * 100 if self.starting_equity else 0.0

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "n_tickers": self.n_tickers,
            "n_bars": self.n_bars,
            "starting_equity": self.starting_equity,
            "ending_equity": self.ending_equity,
            "pnl": self.pnl,
            "pnl_pct": self.pnl_pct,
            "eod_close": self.eod_close,
            "equity_curve": self.equity_curve,
            "trades": self.trades,
            "final_positions": self.final_positions,
        }


def simulate_day(
    config: AppConfig,
    bars_full: dict[str, pd.DataFrame],
    date: str,
    params: dict | None = None,
    eod_close: bool = True,
    step: int = 1,
) -> IntradayResult:
    """1日分の1分足(bars_full)を時系列リプレイしてAI売買をシミュレート。"""
    params = params or {}
    short_ema = params.get("short_ema", 5)
    long_ema = params.get("long_ema", 20)
    rsi_period = params.get("rsi_period", 14)
    warmup = max(long_ema, rsi_period) + 2

    # 全銘柄共通の時刻軸 (和集合・ソート)
    idx_union = sorted(set().union(*[set(df.index) for df in bars_full.values()]))

    pf = Portfolio(
        initial_capital=config.simulation.initial_capital,
        commission_rate=config.simulation.commission_rate,
        slippage_rate=config.simulation.slippage_rate,
    )
    starting_equity = pf.cash

    equity_curve: list[tuple[str, float]] = []
    for i in range(warmup, len(idx_union), max(1, step)):
        t = idx_union[i]
        bars_now = {}
        for tk, df in bars_full.items():
            sub = df.loc[:t]
            if len(sub) >= warmup:
                bars_now[tk] = sub
        if not bars_now:
            continue
        now_dt = t.to_pydatetime() if hasattr(t, "to_pydatetime") else t
        tick = execute_tick(config, pf, bars_now, now_dt, params=params)
        equity_curve.append((tick.timestamp, tick.equity))

    # 引け処理: 全ポジションを最終値で手仕舞い
    last_t = idx_union[-1]
    last_prices = {}
    for tk, df in bars_full.items():
        if len(df):
            last_prices[tk] = float(df["Close"].iloc[-1])
    if eod_close:
        ts = pd.Timestamp(last_t)
        for tk in list(pf.positions.keys()):
            px = last_prices.get(tk)
            if px is not None:
                pf.sell(tk, px, ts)
        equity_curve.append((str(last_t), pf.total_equity(last_prices)))

    ending_equity = pf.total_equity(last_prices)

    trades = [
        {"ticker": tr.ticker, "side": tr.side, "shares": tr.shares,
         "price": tr.price, "time": str(tr.date), "pnl": tr.pnl}
        for tr in pf.trades
    ]
    final_positions = [
        {"ticker": p.ticker, "shares": p.shares,
         "entry_price": p.entry_price,
         "last_price": last_prices.get(t, p.entry_price)}
        for t, p in pf.positions.items()
    ]

    return IntradayResult(
        date=date,
        n_tickers=len(bars_full),
        n_bars=len(idx_union),
        starting_equity=starting_equity,
        ending_equity=ending_equity,
        eod_close=eod_close,
        equity_curve=equity_curve,
        trades=trades,
        final_positions=final_positions,
    )


def save_result(result: IntradayResult) -> Path:
    INTRADAY_DIR.mkdir(parents=True, exist_ok=True)
    path = INTRADAY_DIR / f"{result.date}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
    return path


def format_result(r: IntradayResult) -> str:
    n_buys = sum(1 for t in r.trades if t["side"] == "buy")
    n_sells = sum(1 for t in r.trades if t["side"] == "sell")
    win = sum(1 for t in r.trades if t["side"] == "sell" and t["pnl"] > 0)
    lines = [
        "=" * 66,
        f"  本日トレードシミュレーション  {r.date}",
        "=" * 66,
        f"  対象銘柄     : {r.n_tickers}",
        f"  時間軸(1分足): {r.n_bars} 本",
        f"  開始評価額   : {r.starting_equity:>15,.0f} 円",
        f"  終了評価額   : {r.ending_equity:>15,.0f} 円  ({r.pnl:+,.0f} / {r.pnl_pct:+.2f}%)",
        f"  約定         : 買 {n_buys}件 / 売 {n_sells}件" +
        (f" (うち利益確定 {win}件)" if n_sells else ""),
        f"  引け手仕舞い : {'あり' if r.eod_close else 'なし(持ち越し)'}",
    ]
    if r.trades:
        lines.append("-" * 66)
        for t in r.trades[:20]:
            tm = t["time"][11:16] if len(t["time"]) >= 16 else t["time"]
            if t["side"] == "buy":
                lines.append(f"    {tm} [買] {t['ticker']} {t['shares']}株 @ {t['price']:,.0f}円")
            else:
                lines.append(f"    {tm} [売] {t['ticker']} {t['shares']}株 @ {t['price']:,.0f}円  "
                             f"損益 {t['pnl']:+,.0f}円")
        if len(r.trades) > 20:
            lines.append(f"    ...他 {len(r.trades) - 20}件")
    lines.append("=" * 66)
    return "\n".join(lines)
