"""通知 (ntfy) と実弾移行判定のテスト"""
import json
import pandas as pd
import pytest

from src import notify
from src.readiness import (
    evaluate_readiness, count_risk_off_days, generate_readiness_file,
    MIN_TRADING_DAYS, MIN_CLOSED_TRADES,
)


# ---------------- 通知 ----------------

def test_send_ntfy_no_topic_is_noop(monkeypatch):
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    assert notify.send_ntfy("msg") is False  # トピック未設定 → 送らない・落ちない


def test_send_ntfy_posts_json(monkeypatch):
    sent = {}
    class FakeResp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
    def fake_urlopen(req, timeout=0):
        sent["url"] = req.full_url
        sent["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResp()
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake_urlopen)
    ok = notify.send_ntfy("本文", title="日本語タイトル", tags="warning",
                          priority="high", topic="my-secret-topic")
    assert ok is True
    assert sent["body"]["topic"] == "my-secret-topic"
    assert sent["body"]["title"] == "日本語タイトル"
    assert sent["body"]["priority"] == 4
    assert sent["body"]["tags"] == ["warning"]


def test_send_ntfy_failure_is_swallowed(monkeypatch):
    def boom(req, timeout=0): raise OSError("network down")
    monkeypatch.setattr(notify.urllib.request, "urlopen", boom)
    assert notify.send_ntfy("msg", topic="t") is False  # 例外を漏らさない


def _report(regime="risk_on", buys=0, sells=0):
    return {
        "date": "2026-10-09", "starting_equity": 5_000_000,
        "ending_equity": 5_050_000, "n_positions": 10, "regime": regime,
        "executed_buys": [{}] * buys, "executed_sells": [{}] * sells,
        "exits": [], "planned_orders": [],
    }


def test_build_daily_message_regime_change():
    prev = _report(regime="risk_on")
    cur = _report(regime="risk_off")
    title, msg, tags = notify.build_daily_message(cur, prev)
    assert "レジーム転換" in msg and "リスクオフ" in msg
    assert "+50,000" in title


def test_should_notify_events_mode():
    quiet = _report()
    assert notify.should_notify(quiet, quiet, "events") is False     # 何もない日
    assert notify.should_notify(_report(buys=1), quiet, "events") is True   # 売買あり
    assert notify.should_notify(_report(regime="risk_off"), quiet, "events") is True
    assert notify.should_notify(quiet, quiet, "daily") is True
    assert notify.should_notify(quiet, quiet, "off") is False


# ---------------- 実弾移行判定 ----------------

def _state(days=100, sells=25, dd_crash=False):
    ec = []
    v = 1_000_000.0
    for i in range(days):
        v *= 1.001
        ec.append([str(pd.Timestamp("2026-01-01") + pd.Timedelta(days=i)), v])
    if dd_crash:
        ec.append([str(pd.Timestamp("2026-01-01") + pd.Timedelta(days=days)), v * 0.7])
    return {
        "initial_capital": 1_000_000,
        "equity_curve": ec,
        "trades": [{"side": "sell", "pnl": 1} for _ in range(sells)],
        "risk_off_days_total": 5,
    }


def _monthly(month, alpha):
    return {"month": month, "alpha_pct": alpha}


def test_readiness_all_pass():
    monthly = [_monthly("2026-07", 1.0), _monthly("2026-08", -0.5),
               _monthly("2026-09", 2.0)]
    r = evaluate_readiness(_state(), monthly)
    assert r["ready"] is True
    assert all(c["status"] == "pass" for c in r["criteria"])


def test_readiness_pending_without_monthly_reports():
    r = evaluate_readiness(_state(), [])
    alpha = [c for c in r["criteria"] if "α" in c["name"]][0]
    assert alpha["status"] == "pending"
    assert r["ready"] is False


def test_readiness_fails_on_deep_drawdown():
    r = evaluate_readiness(_state(dd_crash=True), [])
    dd = [c for c in r["criteria"] if "ドローダウン" in c["name"]][0]
    assert dd["status"] == "fail"


def test_readiness_fails_on_negative_alpha_months():
    monthly = [_monthly("2026-07", -1.0), _monthly("2026-08", -0.5),
               _monthly("2026-09", 2.0)]
    r = evaluate_readiness(_state(), monthly)
    alpha = [c for c in r["criteria"] if "α" in c["name"]][0]
    assert alpha["status"] == "fail"


def test_readiness_pending_short_history():
    r = evaluate_readiness(_state(days=MIN_TRADING_DAYS - 10,
                                  sells=MIN_CLOSED_TRADES - 5), [])
    names = {c["name"]: c["status"] for c in r["criteria"]}
    assert any(s == "pending" for s in names.values())
    assert r["ready"] is False


def test_generate_readiness_file(tmp_path):
    dailies = [{"regime": "risk_off"}, {"regime": "risk_on"}, {"regime": "risk_off"}]
    assert count_risk_off_days(dailies) == 2
    out = tmp_path / "readiness.json"
    r = generate_readiness_file(_state(), dailies, [], path=out)
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["ready"] == r["ready"]
    assert "criteria" in saved and len(saved["criteria"]) == 5
