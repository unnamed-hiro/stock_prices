"""ライブ・ペーパートレード: AIに毎日売買判断させて仮想口座を更新する

状態は data/state/portfolio.json に永続化され、複数日にわたって継続できる。
"""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
import pandas as pd

from .portfolio import Portfolio, Position, Trade
from .strategies.base import Strategy, Signal
from .config import AppConfig

STATE_DIR = Path("data/state")
DAILY_LOG_DIR = Path("results/daily")


def _state_path() -> Path:
    return STATE_DIR / "portfolio.json"


def init_portfolio(config: AppConfig) -> Portfolio:
    return Portfolio(
        initial_capital=config.simulation.initial_capital,
        commission_rate=config.simulation.commission_rate,
        slippage_rate=config.simulation.slippage_rate,
    )


def load_or_init(config: AppConfig) -> Portfolio:
    path = _state_path()
    if not path.exists():
        return init_portfolio(config)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    pf = Portfolio(
        initial_capital=data["initial_capital"],
        commission_rate=data["commission_rate"],
        slippage_rate=data["slippage_rate"],
    )
    pf.cash = data["cash"]
    pf.positions = {
        t: Position(
            ticker=p["ticker"],
            shares=p["shares"],
            entry_price=p["entry_price"],
            entry_date=pd.Timestamp(p["entry_date"]),
            peak_price=p.get("peak_price", p["entry_price"]),
        )
        for t, p in data["positions"].items()
    }
    pf.trades = [
        Trade(
            ticker=t["ticker"], side=t["side"], shares=t["shares"],
            price=t["price"], date=pd.Timestamp(t["date"]),
            pnl=t["pnl"], holding_days=t["holding_days"],
        )
        for t in data["trades"]
    ]
    pf.equity_curve = [(pd.Timestamp(d), v) for d, v in data["equity_curve"]]
    return pf


def save_state(pf: Portfolio):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "initial_capital": pf.initial_capital,
        "commission_rate": pf.commission_rate,
        "slippage_rate": pf.slippage_rate,
        "cash": pf.cash,
        "positions": {
            t: {"ticker": p.ticker, "shares": p.shares,
                "entry_price": p.entry_price, "entry_date": str(p.entry_date),
                "peak_price": p.peak_price}
            for t, p in pf.positions.items()
        },
        "trades": [
            {"ticker": t.ticker, "side": t.side, "shares": t.shares,
             "price": t.price, "date": str(t.date),
             "pnl": t.pnl, "holding_days": t.holding_days}
            for t in pf.trades
        ],
        "equity_curve": [(str(d), v) for d, v in pf.equity_curve],
    }
    with open(_state_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def reset_state():
    p = _state_path()
    if p.exists():
        p.unlink()
    clear_pending()


def _size_position(pf: Portfolio, price: float, pct: float, reserve_pct: float,
                   base_equity: float | None = None) -> int:
    # base_equity を渡せば「現在の総資産」基準 (複利)、無ければ初期資金基準
    base = base_equity if base_equity is not None else pf.initial_capital
    target = base * pct
    available = pf.cash - pf.initial_capital * reserve_pct
    budget = min(target, available)
    if budget <= 0 or price * 100 > budget:
        return 0
    return int(budget // (price * 100)) * 100


def _close_on(df: pd.DataFrame, date: pd.Timestamp) -> float | None:
    sub = df.loc[:date]
    return float(sub["Close"].iloc[-1]) if len(sub) else None


def _open_on(df: pd.DataFrame, date: pd.Timestamp) -> float | None:
    """指定日ちょうどの始値。約定用なので当日バーが無ければ None (未約定)。"""
    if date in df.index:
        col = "Open" if "Open" in df.columns else "Close"
        v = df.loc[date, col]
        return float(v) if pd.notna(v) else None
    return None


def _pending_path() -> Path:
    return STATE_DIR / "pending_orders.json"


def load_pending() -> dict:
    """前回の判断で持ち越された注文 {decided_on, orders:[...]} を読む"""
    p = _pending_path()
    if not p.exists():
        return {"decided_on": None, "orders": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"decided_on": None, "orders": []}


def save_pending(decided_on: pd.Timestamp, orders: list[dict]):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _pending_path().write_text(
        json.dumps({"decided_on": str(decided_on.date()), "orders": orders},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")


def clear_pending():
    p = _pending_path()
    if p.exists():
        p.unlink()


@dataclass
class DailyReport:
    date: str
    strategy: str
    starting_equity: float
    ending_equity: float
    cash: float
    n_positions: int
    exits: list[dict] = field(default_factory=list)
    ai_signals: list[dict] = field(default_factory=list)
    executed_buys: list[dict] = field(default_factory=list)
    executed_sells: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    # next_open方式: 当日の判断で発行し翌営業日の始値で約定する予定の注文
    planned_orders: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "strategy": self.strategy,
            "starting_equity": self.starting_equity,
            "ending_equity": self.ending_equity,
            "cash": self.cash,
            "n_positions": self.n_positions,
            "exits": self.exits,
            "ai_signals": self.ai_signals,
            "executed_buys": self.executed_buys,
            "executed_sells": self.executed_sells,
            "skipped": self.skipped,
            "planned_orders": self.planned_orders,
        }


def _fill_pending_orders(
    pf: Portfolio,
    orders: list[dict],
    date: pd.Timestamp,
    price_data: dict[str, pd.DataFrame],
    config: AppConfig,
    report: "DailyReport",
    dry_run: bool,
):
    """前営業日に発行した注文を当日の始値で約定する (バックテスターと同じ挙動)"""
    risk = config.risk
    opens = {t: _open_on(df, date) for t, df in price_data.items()}
    opens = {t: p for t, p in opens.items() if p is not None}

    # 売り(決済)を先に処理して現金を確保
    for o in [x for x in orders if x["side"] == "sell"]:
        px = opens.get(o["ticker"])
        if px is None or o["ticker"] not in pf.positions:
            report.skipped.append({"ticker": o["ticker"],
                                   "reason": "売り注文: 当日始値なし/保有なし"})
            continue
        pos = pf.positions[o["ticker"]]
        ret = (px - pos.entry_price) / pos.entry_price
        entry_px = pos.entry_price
        entry_dt = str(pos.entry_date.date())
        if not dry_run and pf.sell(o["ticker"], px, date):
            rec = {"ticker": o["ticker"], "reason": o.get("reason", ""),
                   "entry_price": entry_px, "exit_price": px,
                   "entry_date": entry_dt, "return_pct": ret * 100}
            if o.get("kind") == "risk":
                report.exits.append(rec)
            else:
                report.executed_sells.append(
                    {"ticker": o["ticker"], "price": px,
                     "return_pct": ret * 100, "reason": o.get("reason", "")})

    # 買いは信頼度順、サイズは約定時の資産・現金で計算
    buys = sorted([x for x in orders if x["side"] == "buy"],
                  key=lambda x: -x.get("confidence", 0))
    base_equity = pf.total_equity(opens) if getattr(risk, "size_on_equity", True) else None
    for o in buys:
        if o["ticker"] in pf.positions:
            continue
        if len(pf.positions) >= config.universe.max_positions:
            report.skipped.append({"ticker": o["ticker"], "reason": "max_positions上限"})
            continue
        px = opens.get(o["ticker"])
        if px is None:
            report.skipped.append({"ticker": o["ticker"], "reason": "買い注文: 当日始値なし"})
            continue
        shares = _size_position(pf, px, risk.position_size_pct,
                                risk.min_cash_reserve_pct, base_equity)
        if shares <= 0:
            report.skipped.append({"ticker": o["ticker"], "reason": "資金不足/最小単元"})
            continue
        if not dry_run and pf.buy(o["ticker"], px, shares, date):
            report.executed_buys.append({
                "ticker": o["ticker"], "price": px, "shares": shares,
                "cost": px * shares, "reason": o.get("reason", ""),
                "confidence": o.get("confidence", 0),
            })


def _decide_orders(
    pf: Portfolio,
    date: pd.Timestamp,
    closes: dict[str, float],
    price_data: dict[str, pd.DataFrame],
    strategy: Strategy,
    config: AppConfig,
    report: "DailyReport",
) -> list[dict]:
    """当日終値までの情報でリスク決済+戦略シグナルを判断し、注文リストを返す"""
    risk = config.risk
    trailing = getattr(risk, "trailing_stop_pct", 0.0)
    orders: list[dict] = []

    for ticker, pos in list(pf.positions.items()):
        px = closes.get(ticker)
        if px is None:
            continue
        # 取得後最高値を更新 (トレーリングストップ用)
        if px > pos.peak_price:
            pos.peak_price = px
        ret = (px - pos.entry_price) / pos.entry_price
        days = (date - pos.entry_date).days
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
        elif days >= risk.max_holding_days:
            reason = f"max_holding ({days}日)"
        if reason:
            orders.append({"side": "sell", "ticker": ticker,
                           "kind": "risk", "reason": reason})

    exiting = {o["ticker"] for o in orders}
    held = set(pf.positions.keys())
    signals = strategy.generate_signals(date, price_data, held)
    report.ai_signals = [
        {"ticker": s.ticker, "action": s.action,
         "confidence": s.confidence, "reason": s.reason}
        for s in signals
    ]

    # honor_strategy_sell=False の場合、戦略の売りは無視しリスク決済(トレーリング等)に委ねる
    honor_sell = getattr(risk, "honor_strategy_sell", True)
    for s in signals:
        if s.action == "sell" and s.ticker in held and s.ticker not in exiting:
            if honor_sell:
                orders.append({"side": "sell", "ticker": s.ticker,
                               "kind": "ai", "reason": s.reason})
        elif s.action == "buy" and s.ticker not in held:
            orders.append({"side": "buy", "ticker": s.ticker,
                           "confidence": s.confidence, "reason": s.reason})
    return orders


def run_one_day(
    config: AppConfig,
    strategy: Strategy,
    date: pd.Timestamp,
    price_data: dict[str, pd.DataFrame],
    dry_run: bool = False,
) -> tuple[Portfolio, DailyReport]:
    """指定日について AI に判断させ、ペーパー口座を更新する。

    execution="next_open" (既定): 前回判断の注文を当日始値で約定 → 当日終値で
    新たに判断し注文を保存 (翌営業日の実行時に約定)。バックテスターと同じ、
    先読みのない現実的な約定タイミング。
    execution="close" (旧来): 当日終値で判断し同じ終値で即約定 (先読みあり)。
    """
    pf = load_or_init(config)
    execution = getattr(config.simulation, "execution", "next_open")

    closes = {t: _close_on(df, date) for t, df in price_data.items()}
    closes = {t: p for t, p in closes.items() if p is not None}

    starting_eq = pf.total_equity(closes)
    report = DailyReport(
        date=str(date.date()),
        strategy=strategy.name,
        starting_equity=starting_eq,
        ending_equity=0,
        cash=pf.cash,
        n_positions=len(pf.positions),
    )

    # 1) 前営業日に発行した注文を当日の始値で約定
    if execution == "next_open":
        pending = load_pending()
        decided_on = pending.get("decided_on")
        if pending["orders"] and decided_on and pd.Timestamp(decided_on) < date:
            _fill_pending_orders(pf, pending["orders"], date, price_data,
                                 config, report, dry_run)
            if not dry_run:
                clear_pending()

    # 2) 当日終値までの情報で判断
    orders = _decide_orders(pf, date, closes, price_data, strategy, config, report)

    if execution == "close":
        # 旧来: 当日終値で即約定
        _fill_orders_at_close(pf, orders, date, closes, config, report, dry_run)
    else:
        # 既定: 注文を保存し翌営業日の始値で約定
        report.planned_orders = orders
        if not dry_run:
            save_pending(date, orders)

    if not dry_run:
        pf.record_equity(date, closes)

    report.ending_equity = pf.total_equity(closes)
    report.cash = pf.cash
    report.n_positions = len(pf.positions)
    return pf, report


def _fill_orders_at_close(
    pf: Portfolio,
    orders: list[dict],
    date: pd.Timestamp,
    closes: dict[str, float],
    config: AppConfig,
    report: "DailyReport",
    dry_run: bool,
):
    """旧来モード: 当日終値で即約定 (先読みあり・後方互換用)"""
    risk = config.risk
    for o in [x for x in orders if x["side"] == "sell"]:
        px = closes.get(o["ticker"])
        if px is None or o["ticker"] not in pf.positions:
            continue
        pos = pf.positions[o["ticker"]]
        ret = (px - pos.entry_price) / pos.entry_price
        entry_px = pos.entry_price
        entry_dt = str(pos.entry_date.date())
        if not dry_run and pf.sell(o["ticker"], px, date):
            if o.get("kind") == "risk":
                report.exits.append({
                    "ticker": o["ticker"], "reason": o.get("reason", ""),
                    "entry_price": entry_px, "exit_price": px,
                    "entry_date": entry_dt, "return_pct": ret * 100})
            else:
                report.executed_sells.append(
                    {"ticker": o["ticker"], "price": px,
                     "return_pct": ret * 100, "reason": o.get("reason", "")})

    buys = sorted([x for x in orders if x["side"] == "buy"],
                  key=lambda x: -x.get("confidence", 0))
    base_equity = pf.total_equity(closes) if getattr(risk, "size_on_equity", True) else None
    for o in buys:
        if o["ticker"] in pf.positions:
            continue
        if len(pf.positions) >= config.universe.max_positions:
            report.skipped.append({"ticker": o["ticker"], "reason": "max_positions上限"})
            continue
        px = closes.get(o["ticker"])
        if px is None:
            report.skipped.append({"ticker": o["ticker"], "reason": "価格データなし"})
            continue
        shares = _size_position(pf, px, risk.position_size_pct,
                                risk.min_cash_reserve_pct, base_equity)
        if shares <= 0:
            report.skipped.append({"ticker": o["ticker"], "reason": "資金不足/最小単元"})
            continue
        if not dry_run and pf.buy(o["ticker"], px, shares, date):
            report.executed_buys.append({
                "ticker": o["ticker"], "price": px, "shares": shares,
                "cost": px * shares, "reason": o.get("reason", ""),
                "confidence": o.get("confidence", 0),
            })


def save_daily_report(report: DailyReport):
    DAILY_LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = DAILY_LOG_DIR / f"{report.date}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
    return path


def format_report(report: DailyReport) -> str:
    pnl = report.ending_equity - report.starting_equity
    pnl_pct = pnl / report.starting_equity * 100 if report.starting_equity else 0
    lines = [
        "=" * 66,
        f"  AIライブ判断レポート  {report.date}  戦略:{report.strategy}",
        "=" * 66,
        f"  開始評価額   : {report.starting_equity:>15,.0f} 円",
        f"  終了評価額   : {report.ending_equity:>15,.0f} 円  ({pnl:+,.0f} / {pnl_pct:+.2f}%)",
        f"  現金残       : {report.cash:>15,.0f} 円",
        f"  保有銘柄数   : {report.n_positions}",
    ]
    if report.exits:
        lines.append("-" * 66)
        lines.append(f"  リスク管理による決済 ({len(report.exits)}件)")
        for e in report.exits:
            lines.append(f"    {e['ticker']}: {e['reason']} → リターン {e['return_pct']:+.2f}%")
    if report.executed_sells:
        lines.append("-" * 66)
        lines.append(f"  AI判断による売却 ({len(report.executed_sells)}件)")
        for s in report.executed_sells:
            lines.append(f"    {s['ticker']} @ {s['price']:,.0f}円  リターン {s['return_pct']:+.2f}%")
            lines.append(f"      根拠: {s['reason']}")
    if report.executed_buys:
        lines.append("-" * 66)
        lines.append(f"  AI判断による買付 ({len(report.executed_buys)}件)")
        for b in report.executed_buys:
            lines.append(f"    {b['ticker']} {b['shares']}株 @ {b['price']:,.0f}円  "
                         f"= {b['cost']:,.0f}円  信頼度 {b['confidence']:.2f}")
            lines.append(f"      根拠: {b['reason']}")
    if report.skipped:
        lines.append("-" * 66)
        lines.append(f"  見送り ({len(report.skipped)}件)")
        for s in report.skipped[:5]:
            lines.append(f"    {s['ticker']}: {s['reason']}")
        if len(report.skipped) > 5:
            lines.append(f"    ...他 {len(report.skipped) - 5}件")
    if report.planned_orders:
        n_buy = sum(1 for o in report.planned_orders if o["side"] == "buy")
        n_sell = sum(1 for o in report.planned_orders if o["side"] == "sell")
        lines.append("-" * 66)
        lines.append(f"  翌営業日の始値で約定予定の注文 (買{n_buy} / 売{n_sell})")
        for o in report.planned_orders[:8]:
            mark = "[買]" if o["side"] == "buy" else "[売]"
            lines.append(f"    {mark} {o['ticker']}  {o.get('reason','')}")
        if len(report.planned_orders) > 8:
            lines.append(f"    ...他 {len(report.planned_orders) - 8}件")
    lines.append("=" * 66)
    return "\n".join(lines)
