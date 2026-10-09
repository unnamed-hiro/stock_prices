"""月次成績レポート — 毎月の運用成績を自動集計する

「観察フェーズ」で見るべき数字 (月次リターン・α・勝率・損益レシオ・
リスク管理の発動実績) を毎月自動で成績表にする。入金(積立)がある月は
入金分を利益と混同しないよう補正する。
"""
from __future__ import annotations
import json
from pathlib import Path

import pandas as pd

MONTHLY_DIR = Path("results/monthly")


def _month_bounds(month: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(month + "-01")
    end = start + pd.offsets.MonthEnd(1)
    return start, end


def build_monthly_report(state: dict, daily_reports: list[dict], month: str,
                         benchmark_pct: float | None = None) -> dict:
    """portfolio.json の state と日次レポート群から month (YYYY-MM) の成績を集計"""
    mstart, mend = _month_bounds(month)
    ec = [(pd.Timestamp(d), v) for d, v in state.get("equity_curve", [])]
    ec.sort(key=lambda x: x[0])

    before = [v for d, v in ec if d < mstart]
    within = [(d, v) for d, v in ec if mstart <= d <= mend]
    if not within:
        raise ValueError(f"{month} の運用データがありません")
    eq_start = before[-1] if before else state.get("initial_capital", within[0][1])
    eq_end = within[-1][1]

    deposits = [(pd.Timestamp(d), a) for d, a in state.get("deposit_log", [])]
    dep_month = sum(a for d, a in deposits if mstart <= d <= mend)

    profit = eq_end - eq_start - dep_month
    month_ret = profit / eq_start * 100 if eq_start > 0 else 0.0

    invested = state.get("initial_capital", 0) + state.get("total_deposits", 0.0)
    cum_ret = (eq_end - invested) / invested * 100 if invested > 0 else 0.0

    # 当月に決済した取引
    sells = [t for t in state.get("trades", []) if t.get("side") == "sell"
             and mstart <= pd.Timestamp(t["date"]) <= mend]
    wins = [t for t in sells if t.get("pnl", 0) > 0]
    losses = [t for t in sells if t.get("pnl", 0) <= 0]
    win_rate = len(wins) / len(sells) * 100 if sells else None
    avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0.0
    avg_loss = sum(t["pnl"] for t in losses) / len(losses) if losses else 0.0
    payoff = (avg_win / -avg_loss) if losses and avg_loss < 0 and wins else None

    # 日次レポートからリスク管理の発動実績
    month_dailies = [r for r in daily_reports if r.get("date", "").startswith(month)]
    risk_off_days = sum(1 for r in month_dailies if r.get("regime") == "risk_off")
    earnings_skips = sum(1 for r in month_dailies
                         for s in r.get("skipped", []) if "決算" in s.get("reason", ""))
    n_buys = sum(len(r.get("executed_buys", [])) for r in month_dailies)
    n_sells_exec = sum(len(r.get("executed_sells", [])) + len(r.get("exits", []))
                       for r in month_dailies)

    rep = {
        "month": month,
        "equity_start": eq_start,
        "equity_end": eq_end,
        "deposits_in_month": dep_month,
        "profit": profit,
        "month_return_pct": month_ret,
        "cumulative_return_pct": cum_ret,
        "invested_capital": invested,
        "benchmark_pct": benchmark_pct,
        "alpha_pct": (month_ret - benchmark_pct) if benchmark_pct is not None else None,
        "n_closed": len(sells),
        "win_rate_pct": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff_ratio": payoff,
        "n_buys": n_buys,
        "n_sell_execs": n_sells_exec,
        "risk_off_days": risk_off_days,
        "earnings_skips": earnings_skips,
        "trading_days": len(month_dailies),
    }
    return rep


def format_monthly_report(r: dict) -> str:
    """Markdown 成績表"""
    def yen(v): return f"{v:+,.0f}円" if v is not None else "—"
    def pct(v): return f"{v:+.2f}%" if v is not None else "—"
    lines = [
        f"# 月次運用レポート {r['month']}",
        "",
        "## 成績",
        "| 項目 | 値 |",
        "|---|---|",
        f"| 月初評価額 | {r['equity_start']:,.0f}円 |",
        f"| 月末評価額 | {r['equity_end']:,.0f}円 |",
    ]
    if r["deposits_in_month"]:
        lines.append(f"| 当月積立入金 | {r['deposits_in_month']:,.0f}円 (利益計算から除外済み) |")
    payoff_s = f"{r['payoff_ratio']:.2f}" if r['payoff_ratio'] else "—"
    win_s = pct(r['win_rate_pct']) if r['win_rate_pct'] is not None else "—"
    lines += [
        f"| **当月損益** | **{yen(r['profit'])} ({pct(r['month_return_pct'])})** |",
        f"| 市場 (全銘柄等ウェイト) | {pct(r['benchmark_pct'])} |",
        f"| **α (市場超過)** | **{pct(r['alpha_pct'])}** |",
        f"| 累計リターン (対投下資本 {r['invested_capital']:,.0f}円) | {pct(r['cumulative_return_pct'])} |",
        "",
        "## 取引",
        "| 項目 | 値 |",
        "|---|---|",
        f"| 当月決済 | {r['n_closed']}回 (勝率 {win_s}) |",
        f"| 平均利益 / 平均損失 | {yen(r['avg_win'])} / {yen(r['avg_loss'])} |",
        f"| 損益レシオ | {payoff_s} |",
        f"| 新規買い / 決済実行 | {r['n_buys']}回 / {r['n_sell_execs']}回 |",
        "",
        "## リスク管理の発動",
        "| 項目 | 値 |",
        "|---|---|",
        f"| リスクオフ日数 (新規買い停止) | {r['risk_off_days']} / {r['trading_days']}営業日 |",
        f"| 決算またぎ回避の見送り | {r['earnings_skips']}回 |",
        "",
        "---",
        "_αがプラス = 市場に勝った月。数ヶ月連続でマイナスなら戦略の見直しを検討。_",
    ]
    return "\n".join(lines)


def load_daily_reports(daily_dir: Path = Path("results/daily")) -> list[dict]:
    out = []
    if daily_dir.exists():
        for p in sorted(daily_dir.glob("*.json")):
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                continue
    return out
