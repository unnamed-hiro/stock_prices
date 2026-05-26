import numpy as np
import pandas as pd
from .base import Strategy, Signal


def _features(close: pd.Series, volume: pd.Series) -> pd.DataFrame:
    ret1 = close.pct_change()
    feat = pd.DataFrame({
        "ret_1": ret1,
        "ret_5": close.pct_change(5),
        "ret_10": close.pct_change(10),
        "ret_20": close.pct_change(20),
        "vol_5": ret1.rolling(5).std(),
        "vol_20": ret1.rolling(20).std(),
        "ma_ratio_5_25": close.rolling(5).mean() / close.rolling(25).mean() - 1,
        "ma_ratio_10_50": close.rolling(10).mean() / close.rolling(50).mean() - 1,
        "volume_z": (volume - volume.rolling(20).mean()) / volume.rolling(20).std(),
    })
    return feat


class MLStrategy(Strategy):
    """LightGBM/ロジスティック回帰で翌N日後の上昇確率を予測"""

    name = "ml"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self.model_type = self.params.get("model_type", "lightgbm")
        self.train_window = self.params.get("train_window_days", 252)
        self.retrain_freq = self.params.get("retrain_freq_days", 21)
        self.horizon = self.params.get("prediction_horizon_days", 5)
        self.buy_threshold = self.params.get("buy_threshold", 0.55)
        self.sell_threshold = self.params.get("sell_threshold", 0.45)
        self._models: dict[str, object] = {}
        self._last_train: dict[str, pd.Timestamp] = {}

    def warmup_days(self) -> int:
        return self.train_window + 60

    def _train(self, df: pd.DataFrame):
        feat = _features(df["Close"], df["Volume"])
        target = (df["Close"].shift(-self.horizon) / df["Close"] - 1 > 0).astype(int)
        data = feat.join(target.rename("y")).dropna()
        if len(data) < 50:
            return None
        X, y = data.drop(columns=["y"]).values, data["y"].values
        try:
            import lightgbm as lgb
            model = lgb.LGBMClassifier(n_estimators=200, max_depth=4, learning_rate=0.05, verbose=-1)
        except ImportError:
            from sklearn.linear_model import LogisticRegression
            model = LogisticRegression(max_iter=500)
        model.fit(X, y)
        return model

    def _predict(self, model, df: pd.DataFrame) -> float:
        feat = _features(df["Close"], df["Volume"]).iloc[-1:].dropna()
        if feat.empty:
            return 0.5
        return float(model.predict_proba(feat.values)[0, 1])

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
            last_train = self._last_train.get(ticker)
            if last_train is None or (date - last_train).days >= self.retrain_freq:
                train_df = window.iloc[-self.train_window:]
                model = self._train(train_df)
                if model is None:
                    continue
                self._models[ticker] = model
                self._last_train[ticker] = date
            model = self._models.get(ticker)
            if model is None:
                continue
            prob = self._predict(model, window)
            if ticker in held_tickers:
                if prob < self.sell_threshold:
                    signals.append(Signal(ticker, "sell", confidence=1 - prob, reason=f"p_up={prob:.2f}"))
            else:
                if prob > self.buy_threshold:
                    signals.append(Signal(ticker, "buy", confidence=prob, reason=f"p_up={prob:.2f}"))
        return signals
