#!/usr/bin/env python3
"""ライブモードのデモ用に合成価格データをキャッシュに生成

yfinance に繋がらない環境でも run_live.py の挙動を確認できる。
実運用では不要 (yfinance が直接価格を取得する)。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd


CACHE_DIR = Path("data/cache")

DEMO_TICKERS = [
    "7203.T", "7267.T", "7269.T", "7270.T", "7201.T",
    "6758.T", "6861.T", "6501.T", "6502.T", "6503.T",
    "6701.T", "6702.T", "6752.T", "6753.T", "6954.T",
]


def generate_one(ticker: str, start: str, end: str, seed: int, base_price: float):
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start, end, freq="B")
    n = len(dates)

    drift = rng.normal(0.001, 0.0008)
    vol = rng.uniform(0.014, 0.024)
    returns = rng.normal(drift, vol, n)

    cycle = 0.012 * np.sin(np.linspace(0, rng.uniform(3, 6) * np.pi, n))
    returns = returns + np.diff(np.concatenate([[0], cycle]))

    closes = base_price * np.exp(np.cumsum(returns))

    opens = closes * (1 + rng.normal(0, 0.003, n))
    highs = np.maximum(opens, closes) * (1 + np.abs(rng.normal(0, 0.005, n)))
    lows = np.minimum(opens, closes) * (1 - np.abs(rng.normal(0, 0.005, n)))

    abs_returns = np.abs(returns)
    vol_base = rng.integers(800_000, 3_000_000, n).astype(float)
    volumes = vol_base * (1 + 5 * abs_returns)

    df = pd.DataFrame({
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Volume": volumes,
    }, index=dates)
    df.index.name = "Date"
    return df


def main(start: str = "2023-06-01", end: str = "2024-12-31"):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    base_prices = {
        "7203.T": 2800, "7267.T": 1600, "7269.T": 1900, "7270.T": 2700,
        "7201.T": 600, "6758.T": 13000, "6861.T": 65000, "6501.T": 3500,
        "6502.T": 4500, "6503.T": 2300, "6701.T": 13000, "6702.T": 2400,
        "6752.T": 1700, "6753.T": 1100, "6954.T": 4200,
    }
    print(f"合成価格データを生成中: {start} 〜 {end}")
    for i, t in enumerate(DEMO_TICKERS):
        df = generate_one(t, start, end, seed=42 + i, base_price=base_prices.get(t, 3000))
        out = CACHE_DIR / f"{t.replace('.', '_')}.parquet"
        df.to_parquet(out)
        print(f"  ✓ {t}  {len(df)}日分  最新終値 {df['Close'].iloc[-1]:,.0f}円")
    print(f"完了: {len(DEMO_TICKERS)}銘柄 → {CACHE_DIR}/")


if __name__ == "__main__":
    main()
