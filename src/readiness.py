"""実弾移行判定 — 「いつ実際のお金を入れてよいか」を感情でなく基準で判定する

ペーパー運用の実績が以下の基準を全て満たしたとき、少額の実弾
(例: 30万円+積立プラン) への移行を「検討してよい」と判定する。
これは移行を推奨するものではなく、検討の前提条件が揃ったことを示すだけ。
"""
from __future__ import annotations
import json
from pathlib import Path

import pandas as pd

READINESS_PATH = Path("results/readiness.json")

# 判定基準 (保守的に設定。緩めるのは簡単だが、緩い基準に意味はない)
MIN_TRADING_DAYS = 90        # 最低運用日数 (営業日)
MAX_DRAWDOWN_LIMIT = -15.0   # 最大DDがこれより浅いこと (%)
ALPHA_MONTHS_REQUIRED = 2    # 直近3ヶ月中、αがプラスの月がこれ以上
MIN_CLOSED_TRADES = 20       # 統計的に最低限の決済回数


def evaluate_readiness(state: dict, monthly_reports: list[dict]) -> dict:
    """口座状態と月次レポート群から移行判定を行う"""
    ec = [(pd.Timestamp(d), v) for d, v in state.get("equity_curve", [])]
    criteria = []

    # 1. 運用日数
    n_days = len(ec)
    criteria.append({
        "name": f"運用実績 {MIN_TRADING_DAYS}営業日以上",
        "status": "pass" if n_days >= MIN_TRADING_DAYS else "pending",
        "detail": f"現在 {n_days}営業日",
    })

    # 2. 最大ドローダウン
    if ec:
        peak, mdd = 0.0, 0.0
        for _, v in ec:
            peak = max(peak, v)
            if peak > 0:
                mdd = min(mdd, (v - peak) / peak * 100)
        dd_ok = mdd >= MAX_DRAWDOWN_LIMIT
        criteria.append({
            "name": f"最大ドローダウン {MAX_DRAWDOWN_LIMIT}%以内",
            "status": "pass" if dd_ok else "fail",
            "detail": f"実績 {mdd:.1f}%",
        })
    else:
        criteria.append({"name": f"最大ドローダウン {MAX_DRAWDOWN_LIMIT}%以内",
                         "status": "pending", "detail": "データなし"})

    # 3. α (市場超過) — 直近3ヶ月の月次レポートで判定
    recent = sorted(monthly_reports, key=lambda r: r.get("month", ""))[-3:]
    alphas = [(r["month"], r.get("alpha_pct")) for r in recent]
    known = [(m, a) for m, a in alphas if a is not None]
    n_pos = sum(1 for _, a in known if a > 0)
    if len(recent) >= 3 and len(known) == len(recent):
        status = "pass" if n_pos >= ALPHA_MONTHS_REQUIRED else "fail"
        detail = f"直近3ヶ月: α>0 が {n_pos}ヶ月 " + \
                 " ".join(f"{m}:{a:+.1f}%" for m, a in known)
    else:
        status = "pending"
        detail = (f"月次レポート {len(recent)}/3ヶ月分 — 毎月1日に自動蓄積されます"
                  if recent else "月次レポート待ち (毎月1日に自動生成)")
    criteria.append({
        "name": f"α(市場超過)が直近3ヶ月中{ALPHA_MONTHS_REQUIRED}ヶ月以上プラス",
        "status": status, "detail": detail,
    })

    # 4. 決済回数 (統計的最低ライン)
    n_sells = sum(1 for t in state.get("trades", []) if t.get("side") == "sell")
    criteria.append({
        "name": f"決済 {MIN_CLOSED_TRADES}回以上 (統計の最低ライン)",
        "status": "pass" if n_sells >= MIN_CLOSED_TRADES else "pending",
        "detail": f"現在 {n_sells}回",
    })

    # 5. 防御機構の実地経験 (リスクオフを一度でも通過したか)
    #    上昇相場しか知らないシステムに実弾は入れない
    risk_off_seen = state.get("risk_off_days_total", 0) > 0
    criteria.append({
        "name": "下落局面 (リスクオフ) の通過経験",
        "status": "pass" if risk_off_seen else "pending",
        "detail": (f"リスクオフ {state.get('risk_off_days_total', 0)}営業日を経験"
                   if risk_off_seen else "まだ本格的な下落局面を経験していません"),
    })

    ready = all(c["status"] == "pass" for c in criteria)
    return {
        "ready": ready,
        "criteria": criteria,
        "verdict": ("✅ 全基準クリア — 30万円+積立プランでの実弾移行を検討できます"
                    if ready else
                    "⏳ 観察継続 — 全基準が pass になるまで実弾は入れない"),
        "note": "移行しても最初は「失っても生活に影響しない額」から。基準は src/readiness.py で調整可",
    }


def count_risk_off_days(daily_reports: list[dict]) -> int:
    return sum(1 for r in daily_reports if r.get("regime") == "risk_off")


def generate_readiness_file(state: dict, daily_reports: list[dict],
                            monthly_reports: list[dict],
                            path: Path = READINESS_PATH) -> dict:
    """判定を実行して results/readiness.json に保存"""
    state = dict(state)
    state["risk_off_days_total"] = count_risk_off_days(daily_reports)
    result = evaluate_readiness(state, monthly_reports)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return result


def load_monthly_reports(monthly_dir: Path = Path("results/monthly")) -> list[dict]:
    out = []
    if monthly_dir.exists():
        for p in sorted(monthly_dir.glob("*.json")):
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                continue
    return out
