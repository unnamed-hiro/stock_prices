from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal
import pandas as pd


@dataclass
class Signal:
    ticker: str
    action: Literal["buy", "sell", "hold"]
    confidence: float = 1.0
    reason: str = ""


class Strategy(ABC):
    """全戦略の共通インターフェース"""

    name: str = "base"

    def __init__(self, params: dict | None = None):
        self.params = params or {}

    @abstractmethod
    def generate_signals(
        self,
        date: pd.Timestamp,
        price_history: dict[str, pd.DataFrame],
        held_tickers: set[str],
    ) -> list[Signal]:
        """指定日における各銘柄の売買シグナルを返す"""
        ...

    def warmup_days(self) -> int:
        """戦略が必要とする最小過去日数"""
        return 60
