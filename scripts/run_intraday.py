"""本日(または指定日)のイントラデイ・トレードシミュレーション

使い方:
  python scripts/run_intraday.py                 # 本日の1分足で実行
  python scripts/run_intraday.py --date 2026-05-22  # 指定日 (7日以内)
  python scripts/run_intraday.py --hold          # 引けで手仕舞いせず持ち越し
  python scripts/run_intraday.py --step 5        # 5分ごとに判断 (高速化)
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load_config
from src.intraday_sim import (
    fetch_intraday_day, simulate_day, save_result, format_result,
)

JST = ZoneInfo("Asia/Tokyo")


def main():
    parser = argparse.ArgumentParser(description="本日トレードシミュレーション")
    parser.add_argument("--date", default=None,
                        help="YYYY-MM-DD (省略時は本日, 1分足は直近7日まで)")
    parser.add_argument("--hold", action="store_true",
                        help="引けで手仕舞いせずポジションを持ち越す")
    parser.add_argument("--step", type=int, default=1,
                        help="何分ごとに判断するか (デフォルト1分)")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    config = load_config(args.config)
    rt = config.raw.get("realtime", {})
    watchlist = rt.get("watchlist", [])
    if not watchlist:
        print("[エラー] config.yaml の realtime.watchlist が空です")
        sys.exit(1)
    params = {
        "short_ema": rt.get("short_ema", 5),
        "long_ema": rt.get("long_ema", 20),
        "rsi_period": rt.get("rsi_period", 14),
        "vol_spike": rt.get("vol_spike", 1.5),
    }

    date_label = args.date or datetime.now(JST).strftime("%Y-%m-%d")
    print(f"対象日: {date_label}  銘柄数: {len(watchlist)}  1分足を取得中...")
    bars = fetch_intraday_day(watchlist, args.date)
    print(f"取得成功: {len(bars)}/{len(watchlist)} 銘柄")
    if not bars:
        print("[エラー] 1分足データを取得できませんでした。")
        print("  - 本日が休場でないか / 場が始まっているか")
        print("  - 指定日が直近7日以内か (yfinanceの1分足制約) を確認してください")
        sys.exit(1)

    result = simulate_day(config, bars, date_label, params=params,
                          eod_close=not args.hold, step=args.step)
    print(format_result(result))
    path = save_result(result)
    print(f"\n結果を保存: {path}")
    print("ダッシュボードの「📅 本日シミュレーション」タブでも確認できます")


if __name__ == "__main__":
    main()
