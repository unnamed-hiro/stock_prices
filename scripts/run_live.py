#!/usr/bin/env python3
"""AIライブ・ペーパートレード

毎営業日にこのスクリプトを叩くと、AIが当日の売買判断を行い、
仮想口座に反映する。状態は data/state/portfolio.json に永続化される。

使い方:
    python scripts/run_live.py                       # 当日 (最新営業日) を判断
    python scripts/run_live.py --date 2024-12-20     # 任意日付を判断
    python scripts/run_live.py --strategy llm        # 戦略を切替
    python scripts/run_live.py --dry-run             # 判断のみ、口座は変更しない
    python scripts/run_live.py --reset               # 仮想口座をリセット

cron で毎営業日18:00に実行する例:
    0 18 * * 1-5 cd /path/to/stock_prices && python scripts/run_live.py --strategy technical
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.config import load_config
from src.universe import get_tickers
from src.data_fetcher import fetch_many
from src.strategies import build_strategy
from src.live_paper import (
    run_one_day, save_state, save_daily_report,
    reset_state, format_report, load_or_init,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--strategy", default=None)
    parser.add_argument("--date", default=None, help="YYYY-MM-DD (省略時は最新)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reset", action="store_true", help="仮想口座をリセット")
    parser.add_argument("--lookback-days", type=int, default=365,
                        help="戦略のwarmupに必要な過去データ取得日数")
    parser.add_argument("--skip-if-done", action="store_true",
                        help="最新営業日が処理済みならスキップ (自動運用向け・冪等)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.strategy:
        cfg.strategy_name = args.strategy

    if args.reset:
        reset_state()
        print("仮想口座をリセットしました")
        return

    target = pd.Timestamp(args.date) if args.date else pd.Timestamp.today().normalize()
    start = (target - pd.Timedelta(days=args.lookback_days)).strftime("%Y-%m-%d")
    end = (target + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    tickers = get_tickers(cfg.universe.file)
    if args.limit:
        tickers = tickers[:args.limit]

    print(f"判断日付: {target.date()}  戦略: {cfg.strategy_name}  対象: {len(tickers)}銘柄")
    print(f"価格データ取得中 ({start} 〜 {end})...")
    price_data = fetch_many(tickers, start, end, use_cache=True)
    print(f"取得成功: {len(price_data)} / {len(tickers)}")

    if not price_data:
        print("[error] 価格データが1件も取得できませんでした (ネットワーク/銘柄リスト要確認)")
        sys.exit(1)

    # 冪等性ガード: 実データの最終営業日を判断日にし、処理済みならスキップ
    if args.skip_if_done:
        from src.live_paper import DAILY_LOG_DIR
        latest = max(df.index.max() for df in price_data.values())
        target = pd.Timestamp(latest).normalize()
        done_path = DAILY_LOG_DIR / f"{target.date()}.json"
        if done_path.exists():
            print(f"[skip] {target.date()} は既に処理済みのためスキップします")
            return
        print(f"[auto] 最新営業日 {target.date()} を判断対象にします")

    strategy = build_strategy(cfg.strategy_name, cfg.strategy_params)

    pf_before = load_or_init(cfg)
    print(f"[現状] 現金 {pf_before.cash:,.0f}円  保有 {len(pf_before.positions)}銘柄")

    pf, report = run_one_day(cfg, strategy, target, price_data, dry_run=args.dry_run)

    print()
    print(format_report(report))

    if not args.dry_run:
        save_state(pf)
        path = save_daily_report(report)
        print(f"\n状態を保存: data/state/portfolio.json")
        print(f"日次ログ : {path}")

        # 実弾移行判定を更新 (results/readiness.json)
        try:
            import json as _json
            from src.readiness import generate_readiness_file, load_monthly_reports
            from src.monthly_report import load_daily_reports
            state = _json.loads(Path("data/state/portfolio.json").read_text(encoding="utf-8"))
            res = generate_readiness_file(state, load_daily_reports(), load_monthly_reports())
            print(f"移行判定 : {res['verdict']}")
        except Exception as e:
            print(f"[warn] 移行判定の生成に失敗 (運用は継続): {e}")

        # プッシュ通知 (NTFY_TOPIC 設定時のみ)
        try:
            import json as _json
            from src.notify import send_ntfy, build_daily_message, should_notify
            from src.live_paper import DAILY_LOG_DIR
            rep = report.to_dict()
            prevs = sorted(DAILY_LOG_DIR.glob("*.json"))
            prevs = [p for p in prevs if p.stem < rep["date"]]
            prev = _json.loads(prevs[-1].read_text(encoding="utf-8")) if prevs else None
            mode = getattr(cfg, "notify_mode", "daily")
            if should_notify(rep, prev, mode):
                title, msg, tags = build_daily_message(rep, prev)
                if send_ntfy(msg, title=title, tags=tags):
                    print("通知送信 : ntfy ✓")
        except Exception as e:
            print(f"[warn] 通知に失敗 (運用は継続): {e}")
    else:
        print("\n[dry-run] 実行はスキップしました (口座変更なし)")


if __name__ == "__main__":
    main()
