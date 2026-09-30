"""リスクエンジン — 市場レジームフィルターとボラティリティ・ポジションサイジング

全実行経路 (バックテスト / 日次ライブ) で共有する。ここに一本化することで
「検証したポリシーと運用するポリシーの乖離」(過去に踏んだ致命傷) を防ぐ。

■ 市場レジームフィルター
個別銘柄がどれだけ良いシグナルでも、市場全体が下落トレンドなら大半の銘柄は
連れ安する。ユニバース全銘柄の等ウェイト指数を内部で合成し、その指数が
長期移動平均 (既定200日) を下回っている間は新規買いを止める。
外部の指数データ (日経平均等) に依存しないため、バックテスト/ライブ/デモの
全てで同一に機能する。

■ ボラティリティ・サイジング (ATRベース)
「どの銘柄も 1ポジションの想定損失が資産の一定割合 (既定1%) になる」よう
投入額を調整する。値動きの荒い銘柄は少なく、穏やかな銘柄は多く持つ。
想定損失 = ATR × atr_stop_multiple を損切り幅の代理とする。
"""
from __future__ import annotations
import pandas as pd


# ---------------------------------------------------------------- ATR

def compute_atr(df: pd.DataFrame, date: pd.Timestamp, period: int = 14) -> float | None:
    """date 時点の ATR (Average True Range)。date までのデータのみ使用 (先読みなし)。"""
    sub = df.loc[:date]
    if len(sub) < period + 1:
        return None
    high, low, close = sub["High"], sub["Low"], sub["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean().iloc[-1]
    return float(atr) if pd.notna(atr) and atr > 0 else None


# ------------------------------------------------- 市場レジームフィルター

def build_market_index(price_data: dict[str, pd.DataFrame]) -> pd.Series:
    """ユニバース全銘柄の等ウェイト合成指数 (各銘柄の初値=1.0 に正規化して平均)。"""
    normed = []
    for df in price_data.values():
        c = df["Close"].dropna()
        if len(c) >= 2 and c.iloc[0] > 0:
            normed.append(c / c.iloc[0])
    if not normed:
        return pd.Series(dtype=float)
    idx = pd.concat(normed, axis=1).sort_index()
    # 上場前は NaN のまま平均から除外 (その時点で存在した銘柄だけの指数)
    return idx.mean(axis=1, skipna=True)


def build_regime_series(price_data: dict[str, pd.DataFrame],
                        ma_days: int = 200) -> pd.Series:
    """日付 → リスクオンか (bool)。指数が MA 以上なら True (新規買い可)。

    履歴が ma_days に満たない期間は判定不能なのでリスクオン扱い
    (フィルターは「明確な下落トレンドで止める」ための保守装置であり、
    データ不足で取引機会を奪わない)。
    """
    index = build_market_index(price_data)
    if index.empty:
        return pd.Series(dtype=bool)
    ma = index.rolling(ma_days, min_periods=ma_days).mean()
    regime = index >= ma
    regime[ma.isna()] = True
    return regime


def regime_on(regime: pd.Series, date: pd.Timestamp) -> bool:
    """date 時点のレジーム。系列が空/日付が範囲外なら True (安全側=取引可)。"""
    if regime is None or len(regime) == 0:
        return True
    sub = regime.loc[:date]
    return bool(sub.iloc[-1]) if len(sub) else True


# ------------------------------------------------- ポジションサイジング

def size_position(
    price: float,
    cash: float,
    initial_capital: float,
    risk,
    base_equity: float | None = None,
    atr_value: float | None = None,
) -> int:
    """1ポジションの株数を決める (100株単元)。

    sizing_mode="volatility": 想定損失 (ATR×倍率×株数) が資産の
    risk_per_trade_pct になる株数。position_size_pct は上限キャップとして残る。
    ATR が無い銘柄は fixed にフォールバック。
    sizing_mode="fixed" (旧来): 資産の position_size_pct を投入。
    """
    if price <= 0:
        return 0
    base = base_equity if base_equity is not None else initial_capital
    cap_yen = base * risk.position_size_pct  # 1銘柄への投入上限
    available = cash - initial_capital * risk.min_cash_reserve_pct

    mode = getattr(risk, "sizing_mode", "fixed")
    if mode == "volatility" and atr_value is not None and atr_value > 0:
        risk_amount = base * getattr(risk, "risk_per_trade_pct", 0.01)
        stop_dist = atr_value * getattr(risk, "atr_stop_multiple", 2.0)
        target_yen = (risk_amount / stop_dist) * price if stop_dist > 0 else cap_yen
        target_yen = min(target_yen, cap_yen)
    else:
        target_yen = cap_yen

    budget = min(target_yen, available)
    if budget <= 0 or price * 100 > budget:
        return 0
    return int(budget // (price * 100)) * 100
