import pandas as pd
from .base import Strategy, Signal


def _rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))


class TechnicalStrategy(Strategy):
    """MAクロス + RSI + 出来高フィルタによるシグナル生成"""

    name = "technical"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self.short_ma = self.params.get("short_ma", 5)
        self.long_ma = self.params.get("long_ma", 25)
        self.rsi_period = self.params.get("rsi_period", 14)
        self.rsi_oversold = self.params.get("rsi_oversold", 30)
        self.rsi_overbought = self.params.get("rsi_overbought", 70)
        self.volume_ratio_min = self.params.get("volume_ratio_min", 1.2)

    def warmup_days(self) -> int:
        return max(self.long_ma, self.rsi_period) + 5

    def generate_signals(
        self,
        date: pd.Timestamp,
        price_history: dict[str, pd.DataFrame],
        held_tickers: set[str],
    ) -> list[Signal]:
        signals: list[Signal] = []
        for ticker, df in price_history.items():
            window = df.loc[:date]
            if len(window) < self.warmup_days():
                continue
            close = window["Close"]
            vol = window["Volume"]
            short = close.rolling(self.short_ma).mean()
            long = close.rolling(self.long_ma).mean()
            rsi = _rsi(close, self.rsi_period)
            vol_ratio = vol.iloc[-1] / vol.rolling(20).mean().iloc[-1] if vol.rolling(20).mean().iloc[-1] > 0 else 0

            s_now, s_prev = short.iloc[-1], short.iloc[-2]
            l_now, l_prev = long.iloc[-1], long.iloc[-2]
            rsi_now = rsi.iloc[-1]

            golden_cross = s_prev <= l_prev and s_now > l_now
            dead_cross = s_prev >= l_prev and s_now < l_now

            if ticker in held_tickers:
                if dead_cross or rsi_now > self.rsi_overbought:
                    signals.append(Signal(ticker, "sell", confidence=0.7,
                                           reason=f"dead_cross={dead_cross}, rsi={rsi_now:.1f}"))
            else:
                if golden_cross and rsi_now < self.rsi_overbought and vol_ratio >= self.volume_ratio_min:
                    conf = min(1.0, (self.rsi_overbought - rsi_now) / 40 + 0.3)
                    signals.append(Signal(ticker, "buy", confidence=conf,
                                           reason=f"golden_cross, rsi={rsi_now:.1f}, vol×{vol_ratio:.1f}"))
        return signals
