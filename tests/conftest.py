"""テスト共通設定 — 外部ネットワークへの依存を遮断する"""
import pytest


@pytest.fixture(autouse=True)
def _no_network_earnings(monkeypatch, tmp_path):
    """決算日取得 (yfinance) をテスト中は常に「不明」にし、
    キャッシュ書き込みも一時ディレクトリに逃がす。
    決算ロジック自体のテストは next_earnings_date を個別にモックする。"""
    import src.earnings as earnings
    monkeypatch.setattr(earnings, "_fetch_next_earnings", lambda ticker: None)
    monkeypatch.setattr(earnings, "CACHE_PATH", tmp_path / "earnings_cache.json")
