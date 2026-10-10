"""銘柄ヘルス管理 (上場廃止銘柄の自動除外) のテスト"""
import json
import pytest

from src.universe_health import (
    record_fetch_results, excluded_tickers, filter_excluded, load_health,
    EXCLUDE_AFTER,
)


def test_exclusion_after_consecutive_failures(tmp_path):
    p = tmp_path / "health.json"
    # 閾値未満の失敗では除外されない
    for i in range(EXCLUDE_AFTER - 1):
        newly = record_fetch_results(["DEAD.T", "OK.T"], {"OK.T"},
                                     date=f"2026-10-0{i+1}", path=p)
        assert newly == []
    assert excluded_tickers(load_health(p)) == set()
    # 閾値到達で除外
    newly = record_fetch_results(["DEAD.T", "OK.T"], {"OK.T"},
                                 date="2026-10-09", path=p)
    assert newly == ["DEAD.T"]
    assert excluded_tickers(load_health(p)) == {"DEAD.T"}


def test_success_resets_counter(tmp_path):
    p = tmp_path / "health.json"
    for i in range(EXCLUDE_AFTER - 1):
        record_fetch_results(["FLAKY.T"], set(), date=f"d{i}", path=p)
    # 1回成功 → カウンタリセット (一時的なAPI不調では除外しない)
    record_fetch_results(["FLAKY.T"], {"FLAKY.T"}, date="ok", path=p)
    record_fetch_results(["FLAKY.T"], set(), date="d9", path=p)
    assert excluded_tickers(load_health(p)) == set()


def test_filter_excluded(tmp_path):
    p = tmp_path / "health.json"
    for i in range(EXCLUDE_AFTER):
        record_fetch_results(["DEAD.T"], set(), date=f"d{i}", path=p)
    out = filter_excluded(["DEAD.T", "A.T", "B.T"], path=p)
    assert out == ["A.T", "B.T"]


def test_healthy_tickers_not_bloating_file(tmp_path):
    """常に成功している銘柄はファイルにエントリを作らない (肥大防止)"""
    p = tmp_path / "health.json"
    record_fetch_results(["A.T", "B.T"], {"A.T", "B.T"}, date="d1", path=p)
    assert load_health(p) == {}


def test_get_tickers_applies_health(tmp_path, monkeypatch):
    import src.universe_health as uh
    import src.universe as uni
    hp = tmp_path / "health.json"
    monkeypatch.setattr(uh, "HEALTH_PATH", hp)
    csv = tmp_path / "u.csv"
    csv.write_text("ticker,name,sector\nDEAD.T,死に株,X\nOK.T,元気,Y\n",
                   encoding="utf-8")
    for i in range(EXCLUDE_AFTER):
        record_fetch_results(["DEAD.T"], set(), date=f"d{i}", path=hp)
    assert uni.get_tickers(csv) == ["OK.T"]
    assert uni.get_tickers(csv, apply_health=False) == ["DEAD.T", "OK.T"]
