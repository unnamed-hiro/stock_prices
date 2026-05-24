from pathlib import Path
import pandas as pd


def load_universe(path: str | Path) -> pd.DataFrame:
    """銘柄一覧 (ticker, name, sector) を読み込む。重複は除去"""
    df = pd.read_csv(path)
    df = df.drop_duplicates(subset=["ticker"]).reset_index(drop=True)
    return df


def get_tickers(path: str | Path) -> list[str]:
    return load_universe(path)["ticker"].tolist()
