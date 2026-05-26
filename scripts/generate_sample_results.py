#!/usr/bin/env python3
"""ダッシュボード動作確認用のサンプル結果を生成 (ネットワーク不要)

使い方:
    python scripts/generate_sample_results.py           # デフォルト1件
    python scripts/generate_sample_results.py --all     # 好成績/不振/平均の3パターン

通常はバックテスト実行で results/last_run.json が作られるが、
yfinance に繋がらない環境でもダッシュボードを確認できるように
ダミー結果をここで生成する。
"""
import argparse
import json
import random
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd


SCENARIOS = {
    "good": {
        "label": "好成績戦略 (採用候補)",
        "drift_mean": 0.0010,
        "drift_std": 0.010,
        "pnl_mean": 25000,
        "pnl_std": 30000,
        "buy_prob": 0.75,
        "sell_prob": 0.65,
    },
    "average": {
        "label": "平均的戦略 (一部未達)",
        "drift_mean": 0.0005,
        "drift_std": 0.012,
        "pnl_mean": 15000,
        "pnl_std": 40000,
        "buy_prob": 0.70,
        "sell_prob": 0.60,
    },
    "poor": {
        "label": "不振戦略 (採用見送り)",
        "drift_mean": -0.0003,
        "drift_std": 0.018,
        "pnl_mean": -5000,
        "pnl_std": 35000,
        "buy_prob": 0.65,
        "sell_prob": 0.70,
    },
}


def generate(scenario_key: str, out_path: str, seed: int = 42):
    sc = SCENARIOS[scenario_key]
    random.seed(seed)

    tickers = ["7203.T", "6758.T", "9984.T", "6861.T", "8306.T",
               "7974.T", "9433.T", "4063.T", "6098.T", "8035.T",
               "6594.T", "8035.T", "4502.T", "9020.T", "8001.T"]

    initial = 1_000_000
    dates = pd.date_range("2023-01-04", "2024-12-30", freq="B")

    trades = []
    equity = initial
    equity_curve = []

    for i, d in enumerate(dates):
        drift = random.gauss(sc["drift_mean"], sc["drift_std"])
        equity *= (1 + drift)
        equity_curve.append([d.strftime("%Y-%m-%d"), round(equity, 2)])

        if i % 7 == 0 and random.random() < sc["buy_prob"]:
            t = random.choice(tickers)
            price = random.uniform(1000, 5000)
            shares = random.choice([100, 200, 300])
            trades.append({
                "ticker": t, "side": "buy", "shares": shares,
                "price": round(price, 2), "date": d.strftime("%Y-%m-%d"),
                "pnl": 0.0, "holding_days": 0,
            })

        if i % 11 == 0 and random.random() < sc["sell_prob"]:
            t = random.choice(tickers)
            price = random.uniform(1000, 5000)
            shares = 100
            pnl = random.gauss(sc["pnl_mean"], sc["pnl_std"])
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
    if losses and sum(losses) < 0:
        pf_ratio = sum(wins) / -sum(losses)
    else:
        pf_ratio = 1.5

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
        "strategy": f"{sc['label']} ({scenario_key})",
        "metrics": metrics,
        "success": success,
        "equity_curve": equity_curve,
        "trades": trades,
    }

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    passed = sum(1 for v in success.values() if v["pass"])
    print(f"  → {out_path}")
    print(f"    {sc['label']}")
    print(f"    最終評価額: {final:,.0f} 円 ({total_ret*100:+.1f}%) | "
          f"勝率 {win_rate:.1f}% | シャープ {sharpe:.2f} | 基準クリア {passed}/6")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="3パターンすべて生成")
    parser.add_argument("--scenario", choices=list(SCENARIOS.keys()), default="average")
    args = parser.parse_args()

    print("サンプル結果を生成中...")
    if args.all:
        for i, key in enumerate(SCENARIOS.keys()):
            generate(key, f"results/sample_{key}.json", seed=42 + i)
    else:
        generate(args.scenario, f"results/sample_run.json", seed=42)


if __name__ == "__main__":
    main()
