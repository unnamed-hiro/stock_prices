from dataclasses import dataclass, asdict
import numpy as np
import pandas as pd
from .portfolio import Portfolio
from .config import SuccessCriteria


@dataclass
class Metrics:
    initial_capital: float
    final_equity: float
    total_return_pct: float
    annual_return_pct: float
    sharpe: float
    max_drawdown_pct: float
    n_trades: int
    n_buys: int
    n_sells: int
    win_rate: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    avg_holding_days: float


def _equity_series(pf: Portfolio) -> pd.Series:
    if not pf.equity_curve:
        return pd.Series(dtype=float)
    s = pd.Series({d: v for d, v in pf.equity_curve}).sort_index()
    return s


def compute_metrics(pf: Portfolio) -> Metrics:
    eq = _equity_series(pf)
    if eq.empty:
        return Metrics(pf.initial_capital, pf.initial_capital, 0, 0, 0, 0, 0, 0, 0, 0, 1.0, 0, 0, 0)

    final = float(eq.iloc[-1])
    total_ret = final / pf.initial_capital - 1
    days = max((eq.index[-1] - eq.index[0]).days, 1)
    annual_ret = (final / pf.initial_capital) ** (365 / days) - 1

    daily_ret = eq.pct_change().dropna()
    sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else 0.0

    cummax = eq.cummax()
    dd = (eq / cummax - 1).min()

    sells = [t for t in pf.trades if t.side == "sell"]
    buys = [t for t in pf.trades if t.side == "buy"]
    wins = [t.pnl for t in sells if t.pnl > 0]
    losses = [t.pnl for t in sells if t.pnl <= 0]
    win_rate = len(wins) / len(sells) if sells else 0.0
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    pf_ratio = gross_win / gross_loss if gross_loss > 0 else (float("inf") if gross_win > 0 else 1.0)
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0
    avg_hold = float(np.mean([t.holding_days for t in sells])) if sells else 0.0

    return Metrics(
        initial_capital=pf.initial_capital,
        final_equity=final,
        total_return_pct=total_ret * 100,
        annual_return_pct=annual_ret * 100,
        sharpe=sharpe,
        max_drawdown_pct=float(dd) * 100,
        n_trades=len(pf.trades),
        n_buys=len(buys),
        n_sells=len(sells),
        win_rate=win_rate * 100,
        profit_factor=pf_ratio,
        avg_win=avg_win,
        avg_loss=avg_loss,
        avg_holding_days=avg_hold,
    )


def evaluate_success(m: Metrics, c: SuccessCriteria) -> dict[str, tuple[bool, str]]:
    return {
        "勝率":         (m.win_rate / 100 >= c.min_win_rate,
                        f"{m.win_rate:.1f}% (基準 {c.min_win_rate*100:.0f}%)"),
        "損益比":       (m.profit_factor >= c.min_profit_factor,
                        f"{m.profit_factor:.2f} (基準 {c.min_profit_factor:.2f})"),
        "シャープ":     (m.sharpe >= c.min_sharpe,
                        f"{m.sharpe:.2f} (基準 {c.min_sharpe:.2f})"),
        "最大DD":       (abs(m.max_drawdown_pct / 100) <= c.max_drawdown,
                        f"{m.max_drawdown_pct:.1f}% (基準 -{c.max_drawdown*100:.0f}%以内)"),
        "年率リターン": (m.annual_return_pct / 100 >= c.min_annual_return,
                        f"{m.annual_return_pct:.1f}% (基準 {c.min_annual_return*100:.0f}%)"),
        "取引数":       (m.n_sells >= c.min_trades,
                        f"{m.n_sells} (基準 {c.min_trades})"),
    }


def format_report(m: Metrics, success: dict[str, tuple[bool, str]] | None = None) -> str:
    lines = [
        "=" * 60,
        "  シミュレーション結果",
        "=" * 60,
        f"  初期資金     : {m.initial_capital:>15,.0f} 円",
        f"  最終評価額   : {m.final_equity:>15,.0f} 円",
        f"  累積リターン : {m.total_return_pct:>14.2f} %",
        f"  年率リターン : {m.annual_return_pct:>14.2f} %",
        f"  シャープ比   : {m.sharpe:>14.2f}",
        f"  最大DD       : {m.max_drawdown_pct:>14.2f} %",
        "-" * 60,
        f"  総取引数     : {m.n_trades} (買 {m.n_buys} / 売 {m.n_sells})",
        f"  勝率         : {m.win_rate:>14.2f} %",
        f"  損益比       : {m.profit_factor:>14.2f}",
        f"  平均利益     : {m.avg_win:>15,.0f} 円",
        f"  平均損失     : {m.avg_loss:>15,.0f} 円",
        f"  平均保有日数 : {m.avg_holding_days:>14.1f} 日",
    ]
    if success:
        lines.append("-" * 60)
        lines.append("  成功基準チェック")
        for name, (ok, msg) in success.items():
            mark = "[OK]" if ok else "[NG]"
            lines.append(f"  {mark} {name:<8} {msg}")
        all_ok = all(v[0] for v in success.values())
        lines.append("-" * 60)
        lines.append(f"  総合判定: {'★ 成功 (この戦略は採用候補) ★' if all_ok else '× 未達 (パラメータ再調整を推奨)'}")
    lines.append("=" * 60)
    return "\n".join(lines)
