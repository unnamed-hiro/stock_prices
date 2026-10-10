"""銘柄リストのヘルス管理 — 上場廃止銘柄の自動検出と除外

背景: 銘柄リストは作成時点の現存銘柄で固定されており、時間が経つと
上場廃止・コード変更で取得不能な銘柄が増える (実測: 405銘柄中34銘柄が
"possibly delisted" で毎回失敗)。これらは取得時間とログを浪費するだけでなく、
「死んだ銘柄がリストに残り続ける」= 生存者バイアスの進行をログで示す症状でもある。

仕組み:
- 毎営業日の実行後、取得に失敗した銘柄の連続失敗回数を記録
  (data/state/ticker_health.json — CIがコミットして引き継ぐ)
- 連続 EXCLUDE_AFTER 回 (既定5営業日) 失敗した銘柄を自動除外
- 一度でも成功すればカウンタはリセット (一時的なAPI不調では除外しない)
- 除外は universe の読み込み時に適用され、全経路 (ライブ/バックテスト/WF) に効く
- 復帰: 除外は手動解除 (ticker_health.json から該当銘柄を消す)。
  上場廃止銘柄が復活することは基本無いため、自動再試行はしない
"""
from __future__ import annotations
import json
from pathlib import Path

HEALTH_PATH = Path("data/state/ticker_health.json")
EXCLUDE_AFTER = 5  # 連続この回数失敗したら除外


def load_health(path: Path | None = None) -> dict:
    path = path if path is not None else HEALTH_PATH
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_health(health: dict, path: Path | None = None):
    path = path if path is not None else HEALTH_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(health, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    except Exception as e:
        print(f"[universe_health] 保存失敗 (運用は継続): {e}")


def excluded_tickers(health: dict | None = None) -> set[str]:
    """除外中 (連続失敗が閾値以上) の銘柄集合"""
    if health is None:
        health = load_health()
    return {t for t, h in health.items()
            if h.get("consecutive_failures", 0) >= EXCLUDE_AFTER}


def record_fetch_results(requested: list[str], succeeded: set[str],
                         date: str = "", path: Path | None = None) -> list[str]:
    """取得結果を記録し、今回新たに除外された銘柄のリストを返す"""
    path = path if path is not None else HEALTH_PATH
    health = load_health(path)
    before = excluded_tickers(health)
    for t in requested:
        h = health.get(t, {"consecutive_failures": 0})
        if t in succeeded:
            if h.get("consecutive_failures", 0) == 0 and t not in health:
                continue  # 健康な銘柄はエントリを作らない (ファイル肥大防止)
            h["consecutive_failures"] = 0
            h["last_ok"] = date
        else:
            h["consecutive_failures"] = h.get("consecutive_failures", 0) + 1
            h["last_failed"] = date
        health[t] = h
    # 完全回復した銘柄のエントリは掃除
    health = {t: h for t, h in health.items()
              if h.get("consecutive_failures", 0) > 0 or t in before}
    save_health(health, path)
    newly = sorted(excluded_tickers(health) - before)
    return newly


def filter_excluded(tickers: list[str], path: Path | None = None) -> list[str]:
    """除外中の銘柄をリストから取り除く"""
    path = path if path is not None else HEALTH_PATH
    exc = excluded_tickers(load_health(path))
    if not exc:
        return tickers
    return [t for t in tickers if t not in exc]
