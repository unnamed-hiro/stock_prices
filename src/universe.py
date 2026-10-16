from pathlib import Path
import pandas as pd


def load_universe(path: str | Path) -> pd.DataFrame:
    """銘柄一覧 (ticker, name, sector) を読み込む。重複は除去"""
    df = pd.read_csv(path)
    df = df.drop_duplicates(subset=["ticker"]).reset_index(drop=True)
    return df


def get_tickers(path: str | Path, apply_health: bool = True) -> list[str]:
    """銘柄コード一覧。apply_health=True (既定) なら、連続取得失敗で
    自動除外された銘柄 (上場廃止等) を取り除く (src/universe_health.py)。"""
    tickers = load_universe(path)["ticker"].tolist()
    if apply_health:
        from .universe_health import filter_excluded
        n = len(tickers)
        tickers = filter_excluded(tickers)
        if len(tickers) < n:
            print(f"[universe] 取得不能銘柄 {n - len(tickers)}件を除外 "
                  f"(上場廃止等 — data/state/ticker_health.json)")
    return tickers
