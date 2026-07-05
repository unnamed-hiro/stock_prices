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
        }


def run_one_day(
    config: AppConfig,
    strategy: Strategy,
    date: pd.Timestamp,
    price_data: dict[str, pd.DataFrame],
    dry_run: bool = False,
) -> tuple[Portfolio, DailyReport]:
    """指定日について AI に判断させ、ペーパー口座を更新する"""
    pf = load_or_init(config)

    prices = {t: _close_on(df, date) for t, df in price_data.items()}
    prices = {t: p for t, p in prices.items() if p is not None}

    starting_eq = pf.total_equity(prices)
    report = DailyReport(
        date=str(date.date()),
        strategy=strategy.name,
        starting_equity=starting_eq,
        ending_equity=0,
        cash=pf.cash,
        n_positions=len(pf.positions),
    )

    risk = config.risk
    trailing = getattr(risk, "trailing_stop_pct", 0.0)
    for ticker, pos in list(pf.positions.items()):
        px = prices.get(ticker)
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
            entry_px = pos.entry_price
            entry_dt = str(pos.entry_date.date())
            if not dry_run and pf.sell(ticker, px, date):
                report.exits.append({
                    "ticker": ticker, "reason": reason,
                    "entry_price": entry_px, "exit_price": px,
                    "entry_date": entry_dt, "return_pct": ret * 100,
                })

    held = set(pf.positions.keys())
    signals = strategy.generate_signals(date, price_data, held)
    report.ai_signals = [
        {"ticker": s.ticker, "action": s.action,
         "confidence": s.confidence, "reason": s.reason}
        for s in signals
    ]

    # honor_strategy_sell=False の場合、戦略の売りは無視しリスク決済(トレーリング等)に委ねる
    # (バックテストで検証したポリシーと本番運用を一致させる)
    if getattr(risk, "honor_strategy_sell", True):
        sells = [s for s in signals if s.action == "sell" and s.ticker in held]
    else:
        sells = []
    for s in sells:
        px = prices.get(s.ticker)
        if px is None:
            continue
        pos = pf.positions[s.ticker]
        ret = (px - pos.entry_price) / pos.entry_price
        if not dry_run and pf.sell(s.ticker, px, date):
            report.executed_sells.append({
                "ticker": s.ticker, "price": px,
                "return_pct": ret * 100, "reason": s.reason,
            })

    buys = sorted(
        [s for s in signals if s.action == "buy" and s.ticker not in pf.positions],
        key=lambda x: -x.confidence,
    )
    base_equity = pf.total_equity(prices) if getattr(risk, "size_on_equity", True) else None
    for s in buys:
        if len(pf.positions) >= config.universe.max_positions:
            report.skipped.append({"ticker": s.ticker, "reason": "max_positions上限"})
            continue
        px = prices.get(s.ticker)
        if px is None:
            report.skipped.append({"ticker": s.ticker, "reason": "価格データなし"})
            continue
        shares = _size_position(pf, px, risk.position_size_pct,
                                risk.min_cash_reserve_pct, base_equity)
        if shares <= 0:
            report.skipped.append({"ticker": s.ticker, "reason": "資金不足/最小単元"})
            continue
        if not dry_run and pf.buy(s.ticker, px, shares, date):
            report.executed_buys.append({
                "ticker": s.ticker, "price": px, "shares": shares,
                "cost": px * shares, "reason": s.reason,
                "confidence": s.confidence,
            })

    if not dry_run:
        pf.record_equity(date, prices)

    report.ending_equity = pf.total_equity(prices)
    report.cash = pf.cash
    report.n_positions = len(pf.positions)
    return pf, report


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
    lines.append("=" * 66)
    return "\n".join(lines)
