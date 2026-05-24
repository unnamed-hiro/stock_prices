from .base import Strategy, Signal
from .technical import TechnicalStrategy
from .ml import MLStrategy
from .llm import LLMStrategy


def build_strategy(name: str, params: dict) -> Strategy:
    """設定ファイルの strategy.name から戦略インスタンスを生成"""
    registry = {
        "technical": TechnicalStrategy,
        "ml": MLStrategy,
        "llm": LLMStrategy,
    }
    if name not in registry:
        raise ValueError(f"unknown strategy: {name} (choose from {list(registry)})")
    return registry[name](params.get(name, {}))
