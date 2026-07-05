#!/usr/bin/env python3
"""ウォークフォワード検証 — 戦略が「たまたま」でなく安定して勝てるかを確認

使い方:
    python scripts/run_walkforward.py                        # config戦略・4分割
    python scripts/run_walkforward.py --strategy technical --windows 6
    python scripts/run_walkforward.py --limit 20             # 銘柄を絞って高速確認
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load_config
from src.universe import get_tickers
from src.data_fetcher import fetch_many
from src.walkforward import run_walkforward, format_walkforward


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--strategy", default=None,
                        help="ensemble / technical / ml / fundamental / llm")
    parser.add_argument("--windows", type=int, default=4, help="分割ウィンドウ数")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    cfg = load_config(args.config)
    strategy_name = args.strategy or cfg.strategy_name

    tickers = get_tickers(cfg.universe.file)
    if args.limit:
        tickers = tickers[:args.limit]
    print(f"[1/3] 銘柄数: {len(tickers)}  戦略: {strategy_name}  ウィンドウ: {args.windows}")

    print(f"[2/3] 価格データ取得中... ({cfg.simulation.start_date} 〜 {cfg.simulation.end_date})")
    price_data = fetch_many(tickers, cfg.simulation.start_date, cfg.simulation.end_date,
                            use_cache=not args.no_cache)
    print(f"      取得成功: {len(price_data)} / {len(tickers)}")
    if not price_data:
        print("[error] 価格データが取得できませんでした")
        sys.exit(1)

    print(f"[3/3] ウォークフォワード実行...")
    summary = run_walkforward(cfg, strategy_name, price_data,
                              n_windows=args.windows, verbose=True)
    print()
    print(format_walkforward(summary))

    out = args.out or f"results/walkforward_{strategy_name}.json"
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n結果を保存: {out_path}")


if __name__ == "__main__":
    main()
