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

    print(f"[3/4] 戦略: {cfg.strategy_name}")
    strategy = build_strategy(cfg.strategy_name, cfg.strategy_params)

    print("[4/4] バックテスト実行...")
    pf = run_backtest(cfg, strategy, price_data)

    m = compute_metrics(pf)
    success = evaluate_success(m, cfg.success_criteria)
    print(format_report(m, success))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    from dataclasses import asdict
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "strategy": cfg.strategy_name,
            "metrics": asdict(m),
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
