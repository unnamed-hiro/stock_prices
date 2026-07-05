"""準リアルタイム売買エンジン

yfinance の 1分足を5分間隔でポーリングし、AI(テクニカル)が判断 → 仮想売買 → 状態保存。
データは Yahoo Finance の仕様により約15分遅延します。
"""
from __future__ import annotations
import json
import time
import signal as _signal
from dataclasses import dataclass, field
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
import yfinance as yf

from .portfolio import Portfolio, Position, Trade
from .config import AppConfig

JST = ZoneInfo("Asia/Tokyo")
STATE_PATH = Path("data/state/realtime_portfolio.json")
SNAPSHOT_DIR = Path("results/realtime")


def now_jst() -> datetime:
    return datetime.now(JST)


def is_market_open(t: datetime) -> bool:
    """東証営業時間判定 (祝日は考慮しない簡易版)"""
    if t.weekday() >= 5:
        return False
    hm = t.time()
    morning = dtime(9, 0) <= hm < dtime(11, 30)
    afternoon = dtime(12, 30) <= hm < dtime(15, 0)
    return morning or afternoon


def next_open(t: datetime) -> datetime:
    """次回オープン時刻を返す"""
    candidate = t
    while True:
        if candidate.weekday() < 5 and candidate.time() < dtime(9, 0):
            return candidate.replace(hour=9, minute=0, second=0, microsecond=0)
        if candidate.weekday() < 5 and dtime(11, 30) <= candidate.time() < dtime(12, 30):
            return candidate.replace(hour=12, minute=30, second=0, microsecond=0)
        candidate = candidate + timedelta(days=1)
        candidate = candidate.replace(hour=0, minute=0, second=0, microsecond=0)


def fetch_intraday(tickers: list[str]) -> dict[str, pd.DataFrame]:
    """全銘柄の本日1分足を取得 (Yahoo Finance 約15分遅延)"""
    out: dict[str, pd.DataFrame] = {}
    for t in tickers:
        try:
            df = yf.download(
                t, period="1d", interval="1m",
                progress=False, auto_adjust=True, prepost=False,
            )
            if df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            out[t] = df
        except Exception as e:
            print(f"  [warn] {t}: {e}")
    return out


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    g = d.clip(lower=0).rolling(n).mean()
    l = (-d.clip(upper=0)).rolling(n).mean()
    rs = g / l.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))


@dataclass
class IntradaySignal:
    ticker: str
    action: str  # buy / sell / hold
    price: float
    confidence: float
    reason: str


def _recent_cross(short: pd.Series, long: pd.Series, lookback: int = 5) -> str | None:
    """直近 lookback バー以内のクロスを検出。'golden' | 'dead' | None"""
    end = len(short) - 1
    for k in range(1, min(lookback, end) + 1):
        sp, sn = short.iloc[end - k], short.iloc[end - k + 1]
        lp, ln = long.iloc[end - k], long.iloc[end - k + 1]
        if sp <= lp and sn > ln:
            return "golden"
        if sp >= lp and sn < ln:
            return "dead"
    return None


def generate_intraday_signals(
    bars: dict[str, pd.DataFrame],
    held: set[str],
    short_ema: int = 5,
    long_ema: int = 20,
    rsi_period: int = 14,
    vol_spike: float = 1.5,
    cross_lookback: int = 5,
) -> list[IntradaySignal]:
    """1分足テクニカル: 短期EMAクロス + RSI + 出来高スパイク"""
    sigs: list[IntradaySignal] = []
    warmup = max(long_ema, rsi_period) + 2
    for t, df in bars.items():
        if len(df) < warmup:
            continue
        c = df["Close"]
        v = df["Volume"]
        s = _ema(c, short_ema)
        l = _ema(c, long_ema)
        r = _rsi(c, rsi_period)
        v_avg = v.rolling(20).mean().iloc[-1]
        v_ratio = (v.iloc[-1] / v_avg) if v_avg and v_avg > 0 else 0
        r_now = r.iloc[-1]
        px = float(c.iloc[-1])
        cross = _recent_cross(s, l, cross_lookback)
        if t in held:
            if cross == "dead" or r_now > 75:
                sigs.append(IntradaySignal(
                    t, "sell", px, 0.7,
                    f"dead_cross={cross == 'dead'}, rsi={r_now:.0f}",
                ))
        else:
            if cross == "golden" and r_now < 70 and v_ratio >= vol_spike:
                conf = min(1.0, (70 - r_now) / 40 + 0.3)
                sigs.append(IntradaySignal(
                    t, "buy", px, conf,
                    f"EMA{short_ema}>EMA{long_ema}, rsi={r_now:.0f}, vol×{v_ratio:.1f}",
                ))
    return sigs


def load_portfolio(config: AppConfig) -> Portfolio:
    pf = Portfolio(
        initial_capital=config.simulation.initial_capital,
        commission_rate=config.simulation.commission_rate,
        slippage_rate=config.simulation.slippage_rate,
    )
    if not STATE_PATH.exists():
        return pf
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    pf.cash = data["cash"]
    pf.positions = {
        t: Position(
            ticker=p["ticker"], shares=p["shares"],
            entry_price=p["entry_price"],
            entry_date=pd.Timestamp(p["entry_date"]),
            peak_price=p.get("peak_price", p["entry_price"]),
        )
        for t, p in data["positions"].items()
    }
    pf.trades = [
        Trade(
            ticker=tr["ticker"], side=tr["side"], shares=tr["shares"],
            price=tr["price"], date=pd.Timestamp(tr["date"]),
            pnl=tr["pnl"], holding_days=tr["holding_days"],
        )
        for tr in data["trades"]
    ]
    return pf


def save_portfolio(pf: Portfolio):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "initial_capital": pf.initial_capital,
        "commission_rate": pf.commission_rate,
        "slippage_rate": pf.slippage_rate,
        "cash": pf.cash,
        "positions": {
            t: {"ticker": p.ticker, "shares": p.shares,
                "entry_price": p.entry_price,
                "entry_date": str(p.entry_date),
                "peak_price": p.peak_price}
            for t, p in pf.positions.items()
        },
        "trades": [
            {"ticker": tr.ticker, "side": tr.side, "shares": tr.shares,
             "price": tr.price, "date": str(tr.date),
             "pnl": tr.pnl, "holding_days": tr.holding_days}
            for tr in pf.trades
        ],
    }
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def reset_portfolio():
    if STATE_PATH.exists():
        STATE_PATH.unlink()


def _size(pf: Portfolio, price: float, pct: float, reserve_pct: float,
          base_equity: float | None = None) -> int:
    base = base_equity if base_equity is not None else pf.initial_capital
    target = base * pct
    available = pf.cash - pf.initial_capital * reserve_pct
    budget = min(target, available)
    if budget <= 0 or price * 100 > budget:
        return 0
    return int(budget // (price * 100)) * 100


@dataclass
class Tick:
    timestamp: str
    equity: float
    cash: float
    n_positions: int
    prices: dict[str, float] = field(default_factory=dict)
    executed: list[dict] = field(default_factory=list)
    signals: list[dict] = field(default_factory=list)


def execute_tick(
    config: AppConfig,
    pf: Portfolio,
    bars: dict[str, pd.DataFrame],
    now: datetime,
    dry_run: bool = False,
    params: dict | None = None,
) -> Tick:
    """1ティック分の AI 判断と仮想売買を実行"""
    params = params or {}
    prices = {t: float(df["Close"].iloc[-1]) for t, df in bars.items() if len(df)}
    # tz-naive に統一 (Portfolio は tz-naive Timestamp 前提)
    ts = pd.Timestamp(now).tz_localize(None) if pd.Timestamp(now).tz else pd.Timestamp(now)

    tick = Tick(
        timestamp=now.strftime("%Y-%m-%d %H:%M:%S"),
        equity=pf.total_equity(prices),
        cash=pf.cash,
        n_positions=len(pf.positions),
        prices=prices,
    )

    risk = config.risk
    trailing = getattr(risk, "trailing_stop_pct", 0.0)
    for t, pos in list(pf.positions.items()):
        px = prices.get(t)
        if px is None:
            continue
        if px > pos.peak_price:
            pos.peak_price = px
        ret = (px - pos.entry_price) / pos.entry_price
        peak = pos.peak_price if pos.peak_price > 0 else pos.entry_price
        drop_from_peak = (px - peak) / peak
        reason = None
        if ret <= -risk.stop_loss_pct:
            reason = f"stop_loss ({ret*100:+.1f}%)"
        elif trailing > 0 and ret > 0 and drop_from_peak <= -trailing:
            reason = f"trailing_stop (peak比{drop_from_peak*100:+.1f}%)"
        elif risk.take_profit_pct > 0 and ret >= risk.take_profit_pct:
            # take_profit_pct=0 は「固定利確なし」— ret>=0 で即売却しないようガード必須
            reason = f"take_profit ({ret*100:+.1f}%)"
        if reason:
            entry_px = pos.entry_price
            if not dry_run and pf.sell(t, px, ts):
                tick.executed.append({
                    "side": "sell-risk", "ticker": t,
                    "price": px, "shares": pos.shares,
                    "return_pct": ret * 100, "reason": reason,
                    "entry_price": entry_px,
                })

    held = set(pf.positions.keys())
    sigs = generate_intraday_signals(
        bars, held,
        short_ema=params.get("short_ema", 5),
        long_ema=params.get("long_ema", 20),
        rsi_period=params.get("rsi_period", 14),
        vol_spike=params.get("vol_spike", 1.5),
        cross_lookback=params.get("cross_lookback", 5),
    )
    tick.signals = [
        {"ticker": s.ticker, "action": s.action,
         "price": s.price, "confidence": s.confidence, "reason": s.reason}
        for s in sigs
    ]

    # honor_strategy_sell=False の場合、戦略売りは無視しリスク決済(トレーリング等)に委ねる
    honor_sell = getattr(risk, "honor_strategy_sell", True)
    ai_sells = [x for x in sigs if x.action == "sell" and x.ticker in pf.positions] if honor_sell else []
    for s in ai_sells:
        pos = pf.positions[s.ticker]
        ret = (s.price - pos.entry_price) / pos.entry_price
        shares_before = pos.shares
        if not dry_run and pf.sell(s.ticker, s.price, ts):
            tick.executed.append({
                "side": "sell-ai", "ticker": s.ticker,
                "price": s.price, "shares": shares_before,
                "return_pct": ret * 100, "reason": s.reason,
            })

    buys = sorted(
        [x for x in sigs if x.action == "buy" and x.ticker not in pf.positions],
        key=lambda x: -x.confidence,
    )
    base_equity = pf.total_equity(prices) if getattr(risk, "size_on_equity", True) else None
    for s in buys:
        if len(pf.positions) >= config.universe.max_positions:
            break
        shares = _size(pf, s.price, risk.position_size_pct,
                       risk.min_cash_reserve_pct, base_equity)
        if shares <= 0:
            continue
        if not dry_run and pf.buy(s.ticker, s.price, shares, ts):
            tick.executed.append({
                "side": "buy-ai", "ticker": s.ticker,
                "price": s.price, "shares": shares,
                "cost": s.price * shares,
                "confidence": s.confidence, "reason": s.reason,
            })

    tick.equity = pf.total_equity(prices)
    tick.cash = pf.cash
    tick.n_positions = len(pf.positions)
    return tick


def save_snapshot(tick: Tick):
    today = tick.timestamp[:10]
    d = SNAPSHOT_DIR / today
    d.mkdir(parents=True, exist_ok=True)
    fname = tick.timestamp.replace(":", "").replace(" ", "_").replace("-", "")
    path = d / f"{fname}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": tick.timestamp,
            "equity": tick.equity,
            "cash": tick.cash,
            "n_positions": tick.n_positions,
            "prices": tick.prices,
            "signals": tick.signals,
            "executed": tick.executed,
        }, f, ensure_ascii=False, indent=2)


def format_tick(tick: Tick, starting_eq: float) -> str:
    pnl = tick.equity - starting_eq
    pct = pnl / starting_eq * 100 if starting_eq else 0
    lines = [
        "─" * 66,
        f"  {tick.timestamp}  評価額 {tick.equity:>12,.0f}円  "
        f"({pnl:+,.0f} / {pct:+.2f}%)  現金 {tick.cash:>11,.0f}円  保有 {tick.n_positions}",
    ]
    if tick.executed:
        for e in tick.executed:
            mark = {"buy-ai": "[BUY]", "sell-ai": "[SELL]", "sell-risk": "[RISK]"}.get(e["side"], "[?]")
            base = f"    {mark} {e['ticker']} {e.get('shares','')}株 @ {e['price']:,.0f}円"
            if e["side"] == "buy-ai":
                base += f"  conf {e['confidence']:.2f}"
            else:
                base += f"  リターン {e['return_pct']:+.2f}%"
            lines.append(base)
            lines.append(f"      根拠: {e['reason']}")
    elif tick.signals:
        n_buy = sum(1 for s in tick.signals if s["action"] == "buy")
        n_sell = sum(1 for s in tick.signals if s["action"] == "sell")
        lines.append(f"    シグナル発火 (buy={n_buy}, sell={n_sell}) ※他制約により未約定")
    return "\n".join(lines)


def run_loop(
    config: AppConfig,
    watchlist: list[str],
    interval_min: int = 5,
    max_iterations: int | None = None,
    dry_run: bool = False,
    force_run: bool = False,
    params: dict | None = None,
):
    """準リアルタイムループ本体。Ctrl+C で停止、状態は自動保存される。"""
    print(f"監視銘柄: {len(watchlist)}  ポーリング間隔: {interval_min}分")
    print(f"営業時間: 9:00〜11:30, 12:30〜15:00 (JST)  ※Yahooデータは約15分遅延")
    if dry_run:
        print("【dry-run】 仮想口座は変更されません")
    if force_run:
        print("【force-run】 営業時間外でも実行")
    print()

    pf = load_portfolio(config)
    starting_eq = pf.cash + sum(p.entry_price * p.shares for p in pf.positions.values())
    print(f"初期評価額: {starting_eq:,.0f}円  現金 {pf.cash:,.0f}円  保有 {len(pf.positions)}銘柄")

    stop = {"flag": False}
    def handler(*_):
        print("\n[Ctrl+C] 停止します...")
        stop["flag"] = True
    _signal.signal(_signal.SIGINT, handler)

    iteration = 0
    while not stop["flag"]:
        now = now_jst()
        if not is_market_open(now) and not force_run:
            nxt = next_open(now)
            wait = (nxt - now).total_seconds()
            print(f"  [{now.strftime('%H:%M:%S')}] 営業時間外。次回オープン {nxt.strftime('%Y-%m-%d %H:%M')} まで待機")
            slept = 0
            while slept < wait and not stop["flag"]:
                time.sleep(min(30, wait - slept))
                slept += 30
            continue

        iteration += 1
        print(f"\n[{now.strftime('%H:%M:%S')}] tick #{iteration}  価格取得中 ({len(watchlist)}銘柄)...")
        bars = fetch_intraday(watchlist)
        print(f"  取得成功: {len(bars)}/{len(watchlist)}")
        if not bars:
            print("  データ取得失敗。次のティックまで待機。")
        else:
            tick = execute_tick(config, pf, bars, now, dry_run=dry_run, params=params)
            print(format_tick(tick, starting_eq))
            save_snapshot(tick)
            if not dry_run:
                save_portfolio(pf)

        if max_iterations and iteration >= max_iterations:
            print(f"\n最大反復数 {max_iterations} に到達、終了します")
            break

        wait = interval_min * 60
        slept = 0
        while slept < wait and not stop["flag"]:
            time.sleep(min(5, wait - slept))
            slept += 5

    print("\n最終状態を保存しました")
