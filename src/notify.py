"""ntfy.sh プッシュ通知 — 毎日アプリを開かなくても結果が届く

ntfy.sh は無料・登録不要のプッシュ通知サービス。iPhoneに ntfy アプリを入れて
トピックを購読し、こちらから同じトピックに POST するだけで通知が届く。
トピック名は事実上のパスワードなので、推測されにくい文字列にして
GitHub Secrets (NTFY_TOPIC) で管理する。

設計: 通知は「あると便利」であって運用の生命線ではない。送信失敗で
日次実行を落とさないよう、全て fail-open (例外を握りつぶしてFalseを返す)。
"""
from __future__ import annotations
import json
import os
import urllib.request


def send_ntfy(message: str, title: str = "", priority: str = "default",
              tags: str = "", topic: str | None = None,
              server: str = "https://ntfy.sh") -> bool:
    """ntfy に通知を送る。topic 未指定時は環境変数 NTFY_TOPIC を使う。
    トピック未設定・送信失敗は False (運用を止めない)。
    日本語タイトルを安全に送るため JSON publish 方式を使う。"""
    topic = topic or os.environ.get("NTFY_TOPIC", "")
    if not topic:
        return False
    try:
        payload: dict = {"topic": topic, "message": message, "markdown": True}
        if title:
            payload["title"] = title
        if priority != "default":
            payload["priority"] = {"min": 1, "low": 2, "default": 3,
                                   "high": 4, "max": 5}.get(priority, 3)
        if tags:
            payload["tags"] = tags.split(",")
        req = urllib.request.Request(
            server.rstrip("/"),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return 200 <= resp.status < 300
    except Exception as e:
        print(f"[notify] 送信失敗 (運用は継続): {e}")
        return False


def build_daily_message(report: dict, prev_report: dict | None = None) -> tuple[str, str, str]:
    """日次レポートから通知 (title, message, tags) を組み立てる"""
    pnl = report["ending_equity"] - report["starting_equity"]
    pct = pnl / report["starting_equity"] * 100 if report["starting_equity"] else 0
    n_buy = len(report.get("executed_buys", []))
    n_sell = len(report.get("exits", [])) + len(report.get("executed_sells", []))
    n_plan = len(report.get("planned_orders", []))
    regime = report.get("regime", "risk_on")

    title = f"AI運用 {report['date']}  {pnl:+,.0f}円 ({pct:+.2f}%)"
    lines = [
        f"評価額 {report['ending_equity']:,.0f}円 / 保有{report['n_positions']}銘柄",
        f"約定: 買{n_buy} 売{n_sell} / 翌日注文{n_plan}件",
    ]
    tags = "chart_with_upwards_trend" if pnl >= 0 else "chart_with_downwards_trend"

    if regime == "risk_off":
        lines.append("⚠️ リスクオフ: 市場が長期MA割れ — 新規買い停止中")
        tags = "warning"
    if prev_report is not None and prev_report.get("regime") != regime:
        arrow = "リスクオフへ転換 (防御モード)" if regime == "risk_off" else "リスクオンへ復帰"
        lines.append(f"🔄 レジーム転換: {arrow}")
        tags = "rotating_light"
    return title, "\n".join(lines), tags


def should_notify(report: dict, prev_report: dict | None, mode: str) -> bool:
    """mode="daily": 毎営業日 / mode="events": 売買・レジーム転換・リスクオフ時のみ"""
    if mode == "daily":
        return True
    if mode != "events":
        return False
    had_trades = bool(report.get("executed_buys") or report.get("executed_sells")
                      or report.get("exits"))
    regime_changed = (prev_report is not None
                      and prev_report.get("regime") != report.get("regime"))
    return had_trades or regime_changed or report.get("regime") == "risk_off"
