#!/usr/bin/env python3
"""バックテスト実行スクリプト

使い方:
    python scripts/run_backtest.py                       # config.yaml の戦略で実行
    python scripts/run_backtest.py --strategy technical  # 戦略を上書き
    python scripts/run_backtest.py --limit 50            # 銘柄数を絞ってテスト

実行前に:
    pip install -r requirements.txt
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load_config
from src.universe import get_tickers
from src.data_fetcher import fetch_many
from src.strategies import build_strategy
from src.backtester import run_backtest
from src.metrics import compute_metrics, evaluate_success, format_report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--strategy", default=None,
                        help="ensemble / technical / ml / fundamental / llm")
    parser.add_argument("--limit", type=int, default=None, help="銘柄数を制限 (動作確認用)")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--out", default="results/last_run.json")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.strategy:
        cfg.strategy_name = args.strategy

    tickers = get_tickers(cfg.universe.file)
    if args.limit:
        tickers = tickers[:args.limit]
    print(f"[1/4] 銘柄数: {len(tickers)}")

    print(f"[2/4] 価格データ取得中... ({cfg.simulation.start_date} 〜 {cfg.simulation.end_date})")
    price_data = fetch_many(tickers, cfg.simulation.start_date, cfg.simulation.end_date,
                            use_cache=not args.no_cache)
    print(f"      取得成功: {len(price_data)} / {len(tickers)}")

    # データ品質レポート (生存者バイアスの定量化)
    import pandas as pd
    _start = pd.Timestamp(cfg.simulation.start_date)
    _end = pd.Timestamp(cfg.simulation.end_date)
    span = (_end - _start).days
    partial = [t for t, df in price_data.items()
               if (df.index.min() - _start).days > 30 or (_end - df.index.max()).days > 30]
    print("      --- データ品質 ---")
    print(f"      期間全体をカバーしない銘柄: {len(partial)} / {len(price_data)}")
    print("      ⚠ 生存者バイアス: 銘柄リストは現存銘柄のみで構成されており、")
    print("        期間中に上場廃止・破綻した銘柄(敗者)が含まれていません。")
    print("        実際の成績はこのバックテストより悪くなる可能性が高いです。")

    print(f"[3/4] 戦略: {cfg.strategy_name}")
    strategy = build_strategy(cfg.strategy_name, cfg.strategy_params)

    print("[4/4] バックテスト実行...")
    pf = run_backtest(cfg, strategy, price_data)

    m = compute_metrics(pf)
    success = evaluate_success(m, cfg.success_criteria)
    print(format_report(m, success))

    # ベンチマーク(全銘柄バイ&ホールド)との比較 = α (市場に勝ったか)
    import pandas as pd
    from src.backtester import compute_benchmark
    bench = compute_benchmark(price_data, pd.Timestamp(cfg.simulation.start_date),
                              pd.Timestamp(cfg.simulation.end_date),
                              cfg.simulation.initial_capital)
    alpha = m.total_return_pct - bench["total_return_pct"]
    print("-" * 60)
    print("  市場比較 (α = 戦略が市場をどれだけ上回ったか)")
    print(f"  戦略リターン       : {m.total_return_pct:>8.2f} %")
    print(f"  市場(バイ&ホールド): {bench['total_return_pct']:>8.2f} %  ({bench.get('n_tickers',0)}銘柄等金額)")
    print(f"  超過リターン (α)   : {alpha:>8.2f} %  "
          f"{'★市場に勝利' if alpha > 0 else '×市場に負け (単純保有の方が良い)'}")
    print("=" * 60)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    from dataclasses import asdict
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "strategy": cfg.strategy_name,
            "metrics": asdict(m),
            "benchmark": {"total_return_pct": bench["total_return_pct"], "alpha_pct": alpha},
            "data_quality": {
                "n_tickers": len(price_data),
                "n_partial_coverage": len(partial),
                "survivorship_bias": "銘柄リストは現存銘柄のみ。上場廃止銘柄が除外されており成績は過大評価の可能性",
            },
            "success": {k: {"pass": v[0], "detail": v[1]} for k, v in success.items()},
            "equity_curve": [(str(d), v) for d, v in pf.equity_curve],
            "trades": [
                {"ticker": t.ticker, "side": t.side, "shares": t.shares,
                 "price": t.price, "date": str(t.date), "pnl": t.pnl,
                 "holding_days": t.holding_days}
                for t in pf.trades
            ],
        }, f, ensure_ascii=False, indent=2)
    print(f"\n結果を保存: {out_path}")


if __name__ == "__main__":
    main()
