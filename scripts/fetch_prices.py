#!/usr/bin/env python3
"""価格データを事前ダウンロードしてキャッシュに保存"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load_config
from src.universe import get_tickers
from src.data_fetcher import fetch_many


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    cfg = load_config(args.config)
    tickers = get_tickers(cfg.universe.file)
    if args.limit:
        tickers = tickers[:args.limit]
    print(f"取得対象: {len(tickers)} 銘柄  期間: {cfg.simulation.start_date} 〜 {cfg.simulation.end_date}")
    out = fetch_many(tickers, cfg.simulation.start_date, cfg.simulation.end_date, use_cache=True)
    print(f"取得成功: {len(out)} 銘柄  (キャッシュ: data/cache/)")


if __name__ == "__main__":
    main()
