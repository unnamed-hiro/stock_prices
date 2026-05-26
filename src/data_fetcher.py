from pathlib import Path
import pandas as pd
import yfinance as yf

CACHE_DIR = Path("data/cache")


def _cache_path(ticker: str) -> Path:
    return CACHE_DIR / f"{ticker.replace('.', '_')}.parquet"


def fetch_one(ticker: str, start: str, end: str, use_cache: bool = True) -> pd.DataFrame:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = _cache_path(ticker)
    if use_cache and cache.exists():
        df = pd.read_parquet(cache)
        if df.index.min() <= pd.Timestamp(start) and df.index.max() >= pd.Timestamp(end):
            return df.loc[start:end]
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.to_parquet(cache)
    return df


def fetch_many(
    tickers: list[str], start: str, end: str, use_cache: bool = True,
    progress: bool = True,
) -> dict[str, pd.DataFrame]:
    """ticker → OHLCV DataFrame の辞書を返す。失敗銘柄は除外。
    銘柄数が多い場合に進捗を表示する。"""
    out: dict[str, pd.DataFrame] = {}
    total = len(tickers)
    for i, t in enumerate(tickers, 1):
        try:
            df = fetch_one(t, start, end, use_cache=use_cache)
            if not df.empty and len(df) > 30:
                out[t] = df
        except Exception as e:
            print(f"[warn] fetch failed for {t}: {e}")
        if progress and (i % 25 == 0 or i == total):
            print(f"      ...取得進捗 {i}/{total}  (成功 {len(out)})", flush=True)
    return out


def align_close_panel(price_dict: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """各銘柄のClose列を1つのDataFrameに整列 (index=日付, columns=ticker)"""
    closes = {t: df["Close"] for t, df in price_dict.items()}
    panel = pd.DataFrame(closes).sort_index()
    return panel
