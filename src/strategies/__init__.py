from .base import Strategy, Signal
from .technical import TechnicalStrategy
from .ml import MLStrategy
from .llm import LLMStrategy
from .fundamental import FundamentalStrategy


def build_strategy(name: str, params: dict) -> Strategy:
    """設定ファイルの strategy.name から戦略インスタンスを生成。

    params は strategy セクション全体 (name を除く) の辞書。
    通常戦略には params.get(name, {}) を渡す。
    ensemble はメンバー戦略を内部生成するため params 全体を受け取る。
    """
    from .ensemble import EnsembleStrategy

    registry = {
        "technical": TechnicalStrategy,
        "ml": MLStrategy,
        "llm": LLMStrategy,
        "fundamental": FundamentalStrategy,
    }
    if name == "ensemble":
        return EnsembleStrategy(params)
    if name not in registry:
        raise ValueError(
            f"unknown strategy: {name} "
            f"(choose from {list(registry) + ['ensemble']})")
    return registry[name](params.get(name, {}))
