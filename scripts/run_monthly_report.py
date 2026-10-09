#!/usr/bin/env python3
"""月次成績レポート生成 — 毎月1日に前月分を自動生成 (GitHub Actions から呼ばれる)

使い方:
    python scripts/run_monthly_report.py            # 前月分
    python scripts/run_monthly_report.py --month 2026-10
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load_config
from src.monthly_report import (
    build_monthly_report, format_monthly_report, load_daily_reports,
    _month_bounds, MONTHLY_DIR,
)

STATE_PATH = Path("data/state/portfolio.json")


def _benchmark_for_month(cfg, month: str) -> float | None:
    """ユニバース等ウェイトの当月リターン% (取得失敗は None = レポートに'—')"""
    try:
        from src.universe import get_tickers
        from src.data_fetcher import fetch_many
        from src.backtester import compute_benchmark
        mstart, mend = _month_bounds(month)
        tickers = get_tickers(cfg.universe.file)
        ph = fetch_many(tickers, str((mstart - pd.Timedelta(days=10)).date()),
                        str(mend.date()), use_cache=True)
        if not ph:
            return None
        b = compute_benchmark(ph, mstart, mend, 1_000_000)
        return b["total_return_pct"]
    except Exception as e:
        print(f"[warn] ベンチマーク取得失敗: {e}")
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", default=None, help="YYYY-MM (省略時は前月)")
    parser.add_argument("--force", action="store_true", help="既存レポートを上書き")
    args = parser.parse_args()

    month = args.month or (pd.Timestamp.now().normalize().replace(day=1)
                           - pd.Timedelta(days=1)).strftime("%Y-%m")
    out_md = MONTHLY_DIR / f"{month}.md"
    if out_md.exists() and not args.force:
        print(f"[skip] {out_md} は生成済み")
        return

    if not STATE_PATH.exists():
        print("[error] data/state/portfolio.json がありません (運用未開始)")
        sys.exit(1)
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    dailies = load_daily_reports()

    cfg = load_config()
    bench = _benchmark_for_month(cfg, month)

    try:
        rep = build_monthly_report(state, dailies, month, benchmark_pct=bench)
    except ValueError as e:
        print(f"[skip] {e}")
        return

    MONTHLY_DIR.mkdir(parents=True, exist_ok=True)
    out_md.write_text(format_monthly_report(rep), encoding="utf-8")
    (MONTHLY_DIR / f"{month}.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(format_monthly_report(rep))
    print(f"\n保存: {out_md}")


if __name__ == "__main__":
    main()
