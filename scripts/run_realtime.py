"""準リアルタイム売買エンジンの起動スクリプト

使い方:
  python scripts/run_realtime.py                      # config.yaml の watchlist を5分間隔で実行
  python scripts/run_realtime.py --interval 1         # 1分間隔 (Rate limit注意)
  python scripts/run_realtime.py --dry-run            # 仮想口座を変更せず判断のみ
  python scripts/run_realtime.py --force-run          # 営業時間外でも実行 (テスト用)
  python scripts/run_realtime.py --iterations 3       # 3ティック実行して終了
  python scripts/run_realtime.py --reset              # リアルタイム用仮想口座をリセット
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load_config
from src.realtime import (
    run_loop, reset_portfolio, fetch_intraday,
    execute_tick, load_portfolio, save_portfolio,
    save_snapshot, format_tick, now_jst,
)


def main():
    parser = argparse.ArgumentParser(description="準リアルタイム AI 売買エンジン")
    parser.add_argument("--interval", type=int, default=None,
                        help="ポーリング間隔(分) (デフォルト: config.yaml の値)")
    parser.add_argument("--iterations", type=int, default=None,
                        help="最大反復回数 (デフォルト: 無制限)")
    parser.add_argument("--dry-run", action="store_true",
                        help="仮想口座を変更せず判断のみ表示")
    parser.add_argument("--force-run", action="store_true",
                        help="営業時間外でも実行 (テスト用)")
    parser.add_argument("--reset", action="store_true",
                        help="リアルタイム用仮想口座をリセットして終了")
    parser.add_argument("--once", action="store_true",
                        help="1回だけ判断して終了 (=--iterations 1 と等価)")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    if args.reset:
        reset_portfolio()
        print("リアルタイム用仮想口座をリセットしました")
        return

    config = load_config(args.config)
    rt = config.raw.get("realtime", {})
    if not rt:
        print("[エラー] config.yaml に realtime: セクションがありません")
        sys.exit(1)

    watchlist = rt.get("watchlist", [])
    if not watchlist:
        print("[エラー] config.yaml の realtime.watchlist が空です")
        sys.exit(1)

    interval = args.interval if args.interval else rt.get("poll_interval_minutes", 5)
    params = {
        "short_ema": rt.get("short_ema", 5),
        "long_ema": rt.get("long_ema", 20),
        "rsi_period": rt.get("rsi_period", 14),
        "vol_spike": rt.get("vol_spike", 1.5),
    }

    iterations = 1 if args.once else args.iterations

    run_loop(
        config=config,
        watchlist=watchlist,
        interval_min=interval,
        max_iterations=iterations,
        dry_run=args.dry_run,
        force_run=args.force_run,
        params=params,
    )


if __name__ == "__main__":
    main()
