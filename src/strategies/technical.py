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
        # entry_mode:
        #   "trend" (デフォルト) = 上昇トレンド中(短期MA>長期MA)ならエントリー → 資金稼働率が上がる
        #   "cross"            = 厳密なゴールデンクロスの瞬間のみ(旧来の挙動・取引が極端に少ない)
        self.entry_mode = self.params.get("entry_mode", "trend")

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
            uptrend = s_now > l_now  # 短期MAが長期MAの上 = 上昇トレンド継続

            if ticker in held_tickers:
                if dead_cross or rsi_now > self.rsi_overbought:
                    signals.append(Signal(ticker, "sell", confidence=0.7,
                                           reason=f"dead_cross={dead_cross}, rsi={rsi_now:.1f}"))
            else:
                if self.entry_mode == "cross":
                    # 旧来: ゴールデンクロスの瞬間 + 出来高急増のみ (発火が稀 → 資金稼働率が低い)
                    if golden_cross and rsi_now < self.rsi_overbought and vol_ratio >= self.volume_ratio_min:
                        conf = min(1.0, (self.rsi_overbought - rsi_now) / 40 + 0.3)
                        signals.append(Signal(ticker, "buy", confidence=conf,
                                               reason=f"golden_cross, rsi={rsi_now:.1f}, vol×{vol_ratio:.1f}"))
                else:
                    # trend: 上昇トレンド中で買われすぎでなければ参加。
                    # クロス直後や出来高を伴う日は信頼度を上乗せして優先的に選ばれるようにする。
                    if uptrend and rsi_now < self.rsi_overbought:
                        conf = min(1.0, (self.rsi_overbought - rsi_now) / 50 + 0.25)
                        if golden_cross:
                            conf = min(1.0, conf + 0.2)
                        if vol_ratio >= self.volume_ratio_min:
                            conf = min(1.0, conf + 0.1)
                        signals.append(Signal(ticker, "buy", confidence=conf,
                                               reason=f"uptrend(5MA>25MA), rsi={rsi_now:.1f}, vol×{vol_ratio:.1f}"))
        return signals
