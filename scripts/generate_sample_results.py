#!/usr/bin/env python3
"""ダッシュボード動作確認用のサンプル結果を生成 (ネットワーク不要)

通常はバックテスト実行で results/last_run.json が作られるが、
yfinance に繋がらない環境でもダッシュボードを確認できるように
ダミー結果をここで生成する。
"""
import json
import random
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd


def main(out_path: str = "results/sample_run.json", seed: int = 42):
    random.seed(seed)

    tickers = ["7203.T", "6758.T", "9984.T", "6861.T", "8306.T",
               "7974.T", "9433.T", "4063.T", "6098.T", "8035.T"]

    initial = 1_000_000
    dates = pd.date_range("2023-01-04", "2024-12-30", freq="B")

    trades = []
    equity = initial
    equity_curve = []

    for i, d in enumerate(dates):
        drift = random.gauss(0.0005, 0.012)
        equity *= (1 + drift)
        equity_curve.append([d.strftime("%Y-%m-%d"), round(equity, 2)])

        if i % 7 == 0 and random.random() < 0.7:
            t = random.choice(tickers)
            price = random.uniform(1000, 5000)
            shares = random.choice([100, 200, 300])
            trades.append({
                "ticker": t, "side": "buy", "shares": shares,
                "price": round(price, 2), "date": d.strftime("%Y-%m-%d"),
                "pnl": 0.0, "holding_days": 0,
            })

        if i % 11 == 0 and random.random() < 0.6:
            t = random.choice(tickers)
            price = random.uniform(1000, 5000)
            shares = 100
            pnl = random.gauss(15000, 40000)
            trades.append({
                "ticker": t, "side": "sell", "shares": shares,
                "price": round(price, 2), "date": d.strftime("%Y-%m-%d"),
                "pnl": round(pnl, 2),
                "holding_days": random.randint(3, 45),
            })

    sells = [t for t in trades if t["side"] == "sell"]
    wins = [t["pnl"] for t in sells if t["pnl"] > 0]
    losses = [t["pnl"] for t in sells if t["pnl"] <= 0]
    win_rate = len(wins) / len(sells) * 100 if sells else 0.0
    pf_ratio = sum(wins) / -sum(losses) if losses and sum(losses) < 0 else 1.5

    final = equity_curve[-1][1]
    total_ret = final / initial - 1
    days = (pd.Timestamp(equity_curve[-1][0]) - pd.Timestamp(equity_curve[0][0])).days
    annual = (final / initial) ** (365 / days) - 1

    eq_series = pd.Series([v for _, v in equity_curve])
    cummax = eq_series.cummax()
    dd = (eq_series / cummax - 1).min()

    daily_ret = eq_series.pct_change().dropna()
    sharpe = float(daily_ret.mean() / daily_ret.std() * (252 ** 0.5))

    metrics = {
        "initial_capital": initial,
        "final_equity": final,
        "total_return_pct": total_ret * 100,
        "annual_return_pct": annual * 100,
        "sharpe": sharpe,
        "max_drawdown_pct": float(dd) * 100,
        "n_trades": len(trades),
        "n_buys": len([t for t in trades if t["side"] == "buy"]),
        "n_sells": len(sells),
        "win_rate": win_rate,
        "profit_factor": pf_ratio,
        "avg_win": float(sum(wins) / len(wins)) if wins else 0.0,
        "avg_loss": float(sum(losses) / len(losses)) if losses else 0.0,
        "avg_holding_days": float(sum(t["holding_days"] for t in sells) / len(sells)) if sells else 0.0,
    }

    success = {
        "勝率": {"pass": bool(win_rate >= 55), "detail": f"{win_rate:.1f}% (基準 55%)"},
        "損益比": {"pass": bool(pf_ratio >= 1.5), "detail": f"{pf_ratio:.2f} (基準 1.50)"},
        "シャープ": {"pass": bool(sharpe >= 1.0), "detail": f"{sharpe:.2f} (基準 1.00)"},
        "最大DD": {"pass": bool(abs(dd) <= 0.20), "detail": f"{dd*100:.1f}% (基準 -20%以内)"},
        "年率リターン": {"pass": bool(annual >= 0.10), "detail": f"{annual*100:.1f}% (基準 10%)"},
        "取引数": {"pass": bool(len(sells) >= 20), "detail": f"{len(sells)} (基準 20)"},
    }

    out = {
        "strategy": "sample (random walk)",
        "metrics": metrics,
        "success": success,
        "equity_curve": equity_curve,
        "trades": trades,
    }

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"サンプル結果を生成: {out_path}")
    print(f"  取引数: {len(trades)} (買 {metrics['n_buys']} / 売 {metrics['n_sells']})")
    print(f"  最終評価額: {final:,.0f} 円 ({total_ret*100:+.1f}%)")


if __name__ == "__main__":
    main()
